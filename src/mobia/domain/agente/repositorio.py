import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import column, delete, select, table, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.desambiguacao import intencao_efetiva
from mobia.domain.agente.models import ConversationIntent, Recomendacao
from mobia.domain.agente.recomendacao import DescartePorBairro, motivo_do_match
from mobia.domain.agente.schemas import (
    LIMIAR_DE_DESAMBIGUACAO,
    CategoriaDescarte,
    Intencao,
    ReacaoDoImovel,
    ReacaoLead,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IntencaoDaConversa:
    intencao: Intencao
    confianca: Decimal
    modelo: str
    desambiguado_em: datetime | None

    @property
    def efetiva(self) -> Intencao:
        """A intencao que se pode usar para rotear. **Leia por aqui.**

        `intencao` e o palpite cru, que abaixo do limiar nao sustenta decisao
        nenhuma. Ver `intencao_efetiva`.
        """
        return intencao_efetiva(self.intencao, self.confianca)


async def ler_intencao(
    session: AsyncSession, channel: str, conversation_key: str
) -> IntencaoDaConversa | None:
    linha = await session.get(ConversationIntent, (channel, conversation_key))
    if linha is None:
        return None
    return IntencaoDaConversa(
        intencao=Intencao(linha.intencao),
        confianca=linha.confianca,
        modelo=linha.modelo,
        desambiguado_em=linha.desambiguado_em,
    )


async def gravar_intencao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    confianca: Decimal,
    modelo: str,
) -> None:
    """Upsert. **Nao commita** -- o chamador e dono da transacao.

    Mesma fronteira que `gravar_resumo` da TEC-127 passou a respeitar depois de
    uma review: quem abre a sessao e quem a finaliza.
    """
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "intencao": str(intencao),
        "confianca": confianca,
        "modelo": modelo,
        # Linha nova comeca sem episodio em aberto: a primeira ambiguidade de
        # uma conversa tem de poder perguntar.
        "desambiguado_em": None,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationIntent).values(valores)

    atualizacoes: dict[str, Any] = {
        chave: statement.excluded[chave]
        for chave in ("intencao", "confianca", "modelo", "updated_at")
    }
    if confianca >= LIMIAR_DE_DESAMBIGUACAO:
        # Classificacao confiante encerra o episodio de ambiguidade: o proximo
        # trecho vago da conversa tem direito a uma pergunta nova.
        atualizacoes["desambiguado_em"] = None
    # Abaixo do limiar o marcador **nao** entra no set_: a ambiguidade e a
    # mesma, e a pergunta dela ja foi gasta.

    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_=atualizacoes,
        )
    )


async def marcar_desambiguacao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    quando: datetime | None = None,
) -> None:
    """Registra que a pergunta de desambiguacao ja foi feita. **Nao commita.**

    Chamada **depois** da entrega confirmada, nunca antes: o marcador afirma
    "eu ja perguntei", e isso so e verdade se a pergunta chegou. Escrito antes,
    um 5xx da Meta queimaria a unica chance de desambiguar -- o sweeper
    reprocessa, encontra o marcador, e o lead fica em INDEFINIDA sem ninguem
    ter perguntado nada.

    A linha sempre existe neste ponto: `gravar_intencao` rodou e commitou mais
    cedo no mesmo turno.
    """
    await session.execute(
        update(ConversationIntent)
        .where(
            ConversationIntent.channel == channel,
            ConversationIntent.conversation_key == conversation_key,
        )
        .values(desambiguado_em=quando or datetime.now(UTC))
    )


async def gravar_recomendacoes(
    session_factory: Any,
    *,
    channel: str,
    conversation_key: str,
    candidatos: Sequence[Mapping[str, Any]],
    scores: Mapping[uuid.UUID, float],
    criterios: Sequence[str],
    message_id: uuid.UUID,
    kinds: Sequence[str],
    relaxou_preco: bool,
    relaxou_bairro: bool,
    agora: datetime,
) -> None:
    """Uma linha por imovel apresentado. RN-10.3, e a L1 da TEC-162.

    **`ON CONFLICT DO NOTHING`, e nao um `raise`.** O UNIQUE existe para
    impedir DUPLICATA, nao para derrubar o turno: o lead pede "mostra de novo
    aquele do Campeche" e a reapresentacao e legitima. Deixar o IntegrityError
    subir mataria o turno por causa de um registro, e a D9 da TEC-265 ja
    escreveu a regra oposta para este caminho.

    A linha original sobrevive com a reacao que ja tiver -- que e o
    comportamento certo: a opiniao do lead sobre aquele imovel nao muda porque
    ele o viu de novo.

    **Gravada ANTES da entrega**, por quem chama. O docstring de `_apresentar`
    registra que uma falha parcial perde o conjunto escolhido e o turno
    seguinte pode reapresentar os mesmos imoveis; gravar depois manteria esse
    buraco aberto. Gravar antes tambem significa gravar linha para ficha que
    pode nao sair -- quem desfaz essas e `conciliar_apresentacao`, chamada
    depois do laco de entrega.

    **`relaxou_preco`/`relaxou_bairro` sao do RESULTADO, `criterios` e do
    PEDIDO.** Os dois entram na frase por `motivo_do_match`, e o porque esta
    la: sem eles, um candidato que so apareceu porque o teto cedeu ficaria
    gravado com o criterio que ele nao satisfaz.

    **`kinds` vem do chamador, e nao e derivado aqui.** O kind e posicional
    (`KINDS_DAS_FICHAS[posicao]`) e quem enumera as posicoes e o laco de
    entrega. Esta funcao recebe `candidatos` com a MESMA ordem e o MESMO
    filtro que aquele laco usa, entao o indice bate -- mas depender disso em
    silencio seria frageis: quem passa os kinds e quem sabe deles. Ver a D9
    do desenho da TEC-275 para por que reconstruir a posicao depois nao
    funciona.

    **Toda apresentacao vira linha, sem excecao (RN-10.3).** A regra nao tem
    clausula de excecao -- "toda apresentacao e registrada como
    `Recomendacao`" -- e uma linha faltando quebra tres coisas por quem le
    depois: o UNIQUE que e a garantia do cenario 4 do Gherkin (o proximo
    candidato deste imovel nesta conversa nao teria contra o que colidir), o
    gatilho `reacao_lead IS NULL` que a Task 5 usa para saber quem perguntar,
    e a propria medida de conversao que esta tabela existe para dar.

    **Um candidato sem entrada em `scores` AINDA vira linha, com
    `score_match = 0.0` e um `log.error`.** Isto e decisao de ruling, nao a
    original desta funcao -- a original recusava `0.0` como valor ROTINEIRO,
    e continua certa sobre isso: se este caminho fosse o normal, `0.0`
    tornaria a coluna decorativa e derrubaria o D4 (o que distingue os
    candidatos de uma recomendacao e o score). Mas o `0.0` daqui so e
    alcancado quando um invariante que deveria ser impossivel ja quebrou --
    por construcao (D17, `_PortaComScore` em `ferramenta_de_busca.py`), o
    turno monta `scores` chamando `score_de` para cada imovel de
    `candidatos` logo apos a MESMA busca que os gerou, entao a ausencia so
    acontece se as duas listas vieram de chamadas diferentes. Entre um numero
    errado que berra (`error` no log, `0.0` que salta aos olhos em qualquer
    consulta) e um fato que falta em silencio (a linha simplesmente nao
    existe, e ninguem que le a tabela depois sabe que o imovel foi
    apresentado), a regra escolhe o que berra: a linha existir e a Task 5 ter
    o que reagir importa mais que o numero dela estar certo neste caso que
    nunca deveria acontecer. **Nao filtre o candidato da ENTREGA por causa
    disto** -- o lead ja recebeu a ficha nesse ponto do turno, e transformar
    um defeito de contabilidade nosso numa apresentacao que ele nunca ve so
    troca nosso problema pelo dele.
    """
    if not candidatos:
        return

    motivo = motivo_do_match(criterios, relaxou_preco=relaxou_preco, relaxou_bairro=relaxou_bairro)
    linhas: list[dict[str, Any]] = []
    for posicao, candidato in enumerate(candidatos):
        imovel_id = uuid.UUID(str(candidato["imovel_id"]))
        score = scores.get(imovel_id)
        if score is None:
            # Nunca deveria acontecer (ver docstring) -- `error`, nao
            # `warning`, porque e sinal de invariante quebrado, e `0.0` fica
            # gravado de proposito para o numero errado saltar aos olhos em
            # vez de a linha faltar em silencio.
            log.error(
                "recomendacao.score_ausente",
                channel=channel,
                conversation_key=conversation_key,
                imovel_id=str(imovel_id),
            )
            score = 0.0
        linhas.append(
            {
                "id": uuid.uuid4(),
                "channel": channel,
                "conversation_key": conversation_key,
                "imovel_id": imovel_id,
                "score_match": Decimal(str(score)),
                "motivo_match": motivo,
                "apresentado_em": agora,
                "message_id": message_id,
                "preco_centavos": int(candidato["preco_centavos"]),
                "kind": kinds[posicao],
            }
        )

    async with session_factory() as session:
        await session.execute(pg_insert(Recomendacao).values(linhas).on_conflict_do_nothing())
        await session.commit()


async def apagar_recomendacao_nao_entregue(
    session_factory: Any,
    *,
    channel: str,
    conversation_key: str,
    imovel_id: uuid.UUID,
    apresentado_em: datetime,
) -> None:
    """A linha de uma ficha que NAO chegou ao lead, apagada na hora. TEC-275, D8.

    Mesmo recorte de `conciliar_apresentacao` no ramo `nao_entregues`, e pelas
    mesmas razoes: apaga em vez de fechar (o UNIQUE por conversa e para
    sempre, e linha fechada tornaria o imovel inalcancavel pelo resto da
    conversa), e exige `reacao_lead IS NULL` mais o carimbo deste lote, para
    nunca tocar a linha de uma apresentacao anterior em que o lead de fato viu
    o imovel.

    **Por que existe separada da conciliacao.** La a delecao roda DEPOIS do
    laco, junto com o fechamento -- que precisa de `houve_entrega`, e
    `houve_entrega` so se conhece no fim. A delecao nao precisa: ela depende
    so do que acabou de acontecer com esta ficha. Enquanto as duas andavam
    juntas, um turno que morria no meio do laco levava a limpeza junto, e a
    linha de um imovel que o lead nunca viu sobrevivia como pendente.

    Isso deixou de ser um detalhe quando a continuacao (D4) passou a ler as
    reservas de `outbound_dispatches` para saber o que ja saiu: falha
    permanente MANTEM a reserva de proposito, entao sem esta delecao a
    continuacao leria a recusa como entrega feita.
    """
    async with session_factory() as session:
        await session.execute(
            delete(Recomendacao).where(
                Recomendacao.channel == channel,
                Recomendacao.conversation_key == conversation_key,
                Recomendacao.imovel_id == imovel_id,
                Recomendacao.apresentado_em == apresentado_em,
                Recomendacao.reacao_lead.is_(None),
            )
        )
        await session.commit()


async def conciliar_apresentacao(
    session_factory: Any,
    *,
    channel: str,
    conversation_key: str,
    agora: datetime,
    nao_entregues: Sequence[uuid.UUID],
    houve_entrega: bool,
) -> None:
    """Faz `ler_pendentes` voltar a ser "o que o lead viu, na ordem em que viu".

    Chamada DEPOIS do laco de entrega de `_apresentar`, e a contraparte de
    `gravar_recomendacoes` ser chamada ANTES dele. Gravar antes e o que salva
    o conjunto escolhido de uma falha de rede no meio (a L1 da TEC-162), mas
    deixa duas classes de linha que o lead nunca viu na lista que o ordinal
    dele indexa -- e a posicao N daquela lista E o ordinal N (D7). Uma linha a
    mais nao e um registro a mais: e a opiniao do lead grudando no imovel
    errado, e, se for descarte por distancia, um bairro saindo da busca sem
    ele ter rejeitado nada ali.

    **(a) Pendente ANTIGA que a apresentacao de hoje supera -> `SEM_RESPOSTA`.**
    E o valor que o enum e a D8 descrevem ("uma apresentacao nova superou esta
    linha antes de o lead reagir") e que, ate aqui, nada escrevia -- a
    docstring de `gravar_reacoes` dizia que a marcacao era "de quem apresenta
    de novo (`turno.py`)", e `turno.py` nao a fazia. No caminho feliz nao
    sobra nenhuma: `gravar_reacoes` fecha tudo como NEUTRO no comeco do turno.
    Sobra quando `reagir` falhou (o `except Exception` amplo de `turno.py`,
    que esta certo em si) -- e ai o turno seguinte veria SEIS imoveis numa
    lista so, tres deles de uma apresentacao que o lead ja deixou para tras,
    com "o segundo" apontando para o segundo da lista VELHA.

    **`houve_entrega` e a condicao, e nao "esta funcao foi chamada".** So uma
    apresentacao que CHEGOU supera a anterior (D8, L5). Se nenhuma ficha saiu
    -- todas recusadas, ou nenhuma sobrou depois de `fichas_do_catalogo` --, o
    lead continua com a lista antiga na tela, e fecha-la o deixaria sem como
    reagir ao unico conjunto que ele tem.

    **(b) Linha desta apresentacao cuja ficha NAO saiu -> apagada, nao
    fechada.** Recusa permanente da Meta (`apresentacao.ficha_recusada`) ou
    reserva ja existente (`send` devolvendo False): nos dois casos nada chegou
    ao lead, e RN-10.3 registra o que foi APRESENTADO -- uma ficha que nao saiu
    nao e apresentacao, entao nao ha fato para guardar.

    Apagar, e nao fechar com `SEM_RESPOSTA`, porque o UNIQUE
    (`channel`, `conversation_key`, `imovel_id`) e por conversa e para sempre:
    uma linha fechada continuaria ocupando o lugar daquele imovel nesta
    conversa, e a proxima apresentacao dele -- a que de fato sair -- cairia no
    `ON CONFLICT DO NOTHING`, sem nunca gerar pendente. O imovel ficaria
    inalcancavel pela reacao do lead pelo resto da conversa, por causa de uma
    foto que a Meta recusou uma vez. Fechar tambem contaria uma apresentacao
    que nao houve na medida de conversao que a tabela existe para dar.

    O recorte e `apresentado_em == agora` E `reacao_lead IS NULL`, e ele e
    estreito de proposito: `gravar_recomendacoes` grava o lote inteiro com um
    unico `agora` (ver `ler_pendentes`), entao so as linhas que ESTA chamada
    inseriu batem. Uma reapresentacao cuja ficha foi recusada agora nao apaga
    nada -- a linha original guarda o `apresentado_em` da vez em que o lead de
    fato viu o imovel, junto com a reacao que ele deu. E o mesmo recorte que
    protege o caso da reserva suprimida: se `send` devolveu False, a tentativa
    anterior desta MESMA mensagem ja passou por aqui e gravou a linha com o
    `agora` dela.

    Commita ao final, como as outras escritas deste modulo.
    """
    async with session_factory() as session:
        if nao_entregues:
            await session.execute(
                delete(Recomendacao).where(
                    Recomendacao.channel == channel,
                    Recomendacao.conversation_key == conversation_key,
                    Recomendacao.imovel_id.in_(tuple(nao_entregues)),
                    Recomendacao.apresentado_em == agora,
                    Recomendacao.reacao_lead.is_(None),
                )
            )

        if houve_entrega:
            await session.execute(
                update(Recomendacao)
                .where(
                    Recomendacao.channel == channel,
                    Recomendacao.conversation_key == conversation_key,
                    Recomendacao.reacao_lead.is_(None),
                    # `< agora` e nao `!=`: o lote de hoje fica de fora por ser
                    # o mais novo, e as linhas que o `delete` acima ja tirou
                    # nao existem mais para serem fechadas.
                    Recomendacao.apresentado_em < agora,
                )
                .values(reacao_lead=str(ReacaoLead.SEM_RESPOSTA))
            )
        await session.commit()


# As quatro colunas que `ler_pendentes` e `ler_descartes_por_distancia` leem
# de `imoveis`, declaradas como Core table e nao importadas de
# `mobia.domain.catalogo.models.Imovel`. `ferramenta_de_busca.py` registra no
# proprio docstring ser "o unico arquivo em que domain/agente toca
# domain/catalogo" -- espalhar o import por aqui tambem tornaria essa
# fronteira invisivel. O join precisa do nome da tabela e das colunas, nao da
# classe ORM, entao a tabela Core basta e nao quebra a regra.
#
# `bairro_busca` (TEC-163) e nao `bairro`: e a forma dobrada que
# `FiltroDeBusca.bairros_excluidos` compara, e `ler_descartes_por_distancia`
# tem de devolver o bairro na MESMA forma que o filtro espera -- ver o
# docstring de `DescartePorBairro`.
_TABELA_IMOVEIS = table(
    "imoveis", column("id"), column("titulo"), column("bairro"), column("bairro_busca")
)


@dataclass(frozen=True)
class RecomendacaoPendente:
    """Um imovel apresentado que ainda espera a reacao do lead. TEC-163.

    **Sem preco, de proposito -- ruling do round de revisao.** `recomendacoes`
    nao guarda qual OPERACAO foi buscada, e `Imovel` carrega `preco_venda` e
    `preco_aluguel` ao mesmo tempo; reconstruir um preco aqui a partir so do
    `imovel_id` devolveria o de venda numa busca de aluguel, ou vice-versa.
    E o mesmo defeito que `Candidato.preco_centavos` (`catalogo/schemas.py`)
    existe para evitar -- o comentario de la e explicito: "numa busca de
    aluguel, devolver o preco de venda seria devolver o campo errado".
    Titulo e bairro bastam para desambiguar "o segundo" e "o do Campeche",
    que sao as duas formas que o criterio de aceite desta card nomeia.
    """

    imovel_id: uuid.UUID
    titulo: str
    bairro: str


async def ler_pendentes(
    session_factory: Any, *, channel: str, conversation_key: str
) -> tuple[RecomendacaoPendente, ...]:
    """As linhas desta conversa ainda sem reacao, na ordem em que foram apresentadas.

    **A ordem E o ordinal (D7).** "O segundo" na resposta do lead significa o
    segundo imovel apresentado, e quem le esta lista de volta (`turno.py`,
    junto com `resolver_ordinais`) casa o ordinal do modelo com a posicao
    aqui. Se a ordem mudar entre a apresentacao e a leitura da reacao, a
    opiniao do lead gruda no imovel errado.

    **`apresentado_em` sozinho empata, e nao e caso raro.**
    `gravar_recomendacoes` grava toda apresentacao com o MESMO `agora` para
    todas as linhas do lote -- sempre que mais de um imovel sai numa mesma
    apresentacao, essas linhas empatam em `apresentado_em` por construcao.
    O desempate e `score_match DESC, imovel_id ASC`, e essa escolha nao e
    arbitraria: e a MESMA ordem que `buscar` (`catalogo/busca.py`) usa no
    proprio `ORDER BY` (score decrescente, id como desempate), e nem
    `turno.py` nem `gravar_recomendacoes` reordenam os candidatos entre a
    busca e a gravacao. Reproduzir aquela ordem aqui reconstroi a ordem de
    apresentacao real -- nao serve so para tornar o teste deterministico.

    Ver `RecomendacaoPendente` para o porque de nao ter preco.
    """
    consulta = (
        select(Recomendacao.imovel_id, _TABELA_IMOVEIS.c.titulo, _TABELA_IMOVEIS.c.bairro)
        .join(_TABELA_IMOVEIS, _TABELA_IMOVEIS.c.id == Recomendacao.imovel_id)
        .where(
            Recomendacao.channel == channel,
            Recomendacao.conversation_key == conversation_key,
            Recomendacao.reacao_lead.is_(None),
        )
        .order_by(
            Recomendacao.apresentado_em,
            Recomendacao.score_match.desc(),
            Recomendacao.imovel_id,
        )
    )
    async with session_factory() as session:
        linhas = (await session.execute(consulta)).all()

    return tuple(
        RecomendacaoPendente(imovel_id=linha.imovel_id, titulo=linha.titulo, bairro=linha.bairro)
        for linha in linhas
    )


@dataclass(frozen=True, slots=True)
class LinhaDaApresentacao:
    """Uma linha do lote que uma mensagem apresentou. TEC-275.

    Distinta de `RecomendacaoPendente`, que e o que o MODELO le (titulo e
    bairro, sem preco -- ver o docstring dela). Esta e o que a continuacao
    precisa para remontar a ficha: o preco apresentado e o kind com que ela
    saiu. Duas leituras diferentes da mesma tabela, com dois consumidores
    diferentes; fundi-las obrigaria uma das duas a carregar campo que nao usa.
    """

    imovel_id: uuid.UUID
    preco_centavos: int
    kind: str
    apresentado_em: datetime


async def ler_apresentacao_da_mensagem(
    session_factory: Any, *, message_id: uuid.UUID
) -> tuple[LinhaDaApresentacao, ...]:
    """O lote que ESTA mensagem apresentou, na ordem em que apresentou. TEC-275.

    **Mesma ordenacao de `ler_pendentes`** (`apresentado_em`, `score_match`
    DESC, `imovel_id`), e a mesma razao: aquela ordem reproduz a ordem de
    apresentacao real, porque e a ordem que `buscar` usa e nada entre a busca
    e a gravacao reordena. Escrever uma segunda regra aqui criaria duas copias
    que podem divergir, e o preco da divergencia e o ordinal do lead apontando
    para outro imovel.

    **NAO filtra `reacao_lead IS NULL`, e essa e a diferenca para
    `ler_pendentes`.** A continuacao precisa do lote inteiro para saber qual
    kind pertence a qual imovel; uma linha que ja ganhou reacao continua sendo
    parte do que aquela mensagem apresentou.

    **Linha sem `message_id` nunca entra**, e o filtro por igualdade ja
    garante isso: apresentacao anterior a TEC-275 nao tem dono e nao e
    continuavel (L2 do desenho).

    Devolve so linha completa -- as tres colunas da D2 preenchidas. Uma linha
    com dono mas sem kind seria de uma gravacao pela metade, que nenhum
    caminho de hoje produz; se aparecer, ficar de fora e mais seguro que
    entrar e deslocar posicao.
    """
    consulta = (
        select(
            Recomendacao.imovel_id,
            Recomendacao.preco_centavos,
            Recomendacao.kind,
            Recomendacao.apresentado_em,
        )
        .where(
            Recomendacao.message_id == message_id,
            Recomendacao.preco_centavos.is_not(None),
            Recomendacao.kind.is_not(None),
        )
        .order_by(
            Recomendacao.apresentado_em,
            Recomendacao.score_match.desc(),
            Recomendacao.imovel_id,
        )
    )
    async with session_factory() as session:
        linhas = (await session.execute(consulta)).all()

    return tuple(
        LinhaDaApresentacao(
            imovel_id=linha.imovel_id,
            preco_centavos=linha.preco_centavos,
            kind=linha.kind,
            apresentado_em=linha.apresentado_em,
        )
        for linha in linhas
    )


async def ler_descartes_por_distancia(
    session_factory: Any, *, channel: str, conversation_key: str
) -> tuple[DescartePorBairro, ...]:
    """Os descartes desta conversa, um por imovel, com o bairro dobrado e a categoria. TEC-163.

    **Le TODO descarte, de qualquer categoria -- inclusive sem categoria.**
    O nome cita distancia porque e o unico consumidor de hoje
    (`recomendacao.bairros_a_excluir`), nao porque o `WHERE` filtra por ela: a
    regra "so DISTANCIA conta" e decisao de negocio (RN-10.4), e decisao de
    negocio mora na funcao pura que se testa sem banco, nao numa clausula
    SQL que so se confere rodando contra o Postgres. Filtrar aqui tambem
    criaria uma segunda copia da regra, e as duas copias podem divergir no
    dia em que uma mudar sozinha.

    `bairro_busca` e nao `bairro`: e a forma que `FiltroDeBusca.
    bairros_excluidos` compara (ver `catalogo/schemas.py`), e devolver a
    forma crua aqui obrigaria `ferramenta_de_busca.py` a dobrar de novo --
    ou, pior, a esquecer de dobrar, o mesmo defeito que a TEC-160 pagou caro.
    """
    consulta = (
        select(_TABELA_IMOVEIS.c.bairro_busca, Recomendacao.motivo_descarte)
        .join(_TABELA_IMOVEIS, _TABELA_IMOVEIS.c.id == Recomendacao.imovel_id)
        .where(
            Recomendacao.channel == channel,
            Recomendacao.conversation_key == conversation_key,
            Recomendacao.reacao_lead == str(ReacaoLead.DESCARTE),
        )
    )
    async with session_factory() as session:
        linhas = (await session.execute(consulta)).all()

    return tuple(
        DescartePorBairro(
            bairro=linha.bairro_busca,
            categoria=(
                CategoriaDescarte(linha.motivo_descarte)
                if linha.motivo_descarte is not None
                else None
            ),
        )
        for linha in linhas
    )


async def gravar_reacoes(
    session_factory: Any,
    *,
    channel: str,
    conversation_key: str,
    resolvidas: Sequence[tuple[uuid.UUID, ReacaoDoImovel]],
) -> None:
    """Grava a reacao de cada imovel resolvido, e fecha o resto da conversa como NEUTRO. D8.

    **Fechar as pendentes nao mencionadas nao e cortesia, e a garantia de
    frequencia da chamada.** `classificador.reagir` dispara toda vez que
    existe linha com `reacao_lead IS NULL` na conversa (`ler_pendentes`). Se
    uma pendente nao mencionada continuasse em aberto, um lead que mudasse de
    assunto por tres turnos pagaria tres chamadas pelo MESMO imovel. Fechar
    aqui, no mesmo commit que grava as reacoes resolvidas, e o que faz a
    chamada disparar no MAXIMO uma vez por apresentacao.

    **`NEUTRO`, nunca `SEM_RESPOSTA`.** As duas significam ausencia de opiniao
    e RN-10.4 as conta diferente (ver o docstring de `ReacaoLead`): `NEUTRO`
    e "o lead respondeu neste turno, so nao falou deste imovel" -- ha
    resposta, so nao cobre esta linha, que e exatamente o que uma pendente
    nao mencionada aqui significa. `SEM_RESPOSTA` e para quando uma
    apresentacao NOVA supera uma pendente antiga sem o lead ter dito nada
    sobre nenhuma das duas -- nenhuma resposta existiu, e essa marcacao e de
    quem apresenta de novo: `conciliar_apresentacao`, logo abaixo, chamada no
    fim de `_apresentar`. **Ate a fix wave desta card a frase terminava em
    "e de quem apresenta de novo (`turno.py`)" e ninguem a cumpria** -- o
    valor era declarado pelo enum, documentado aqui e nunca escrito, e uma
    pendente sobrevivente de um `reagir` que falhou entrava na lista numerada
    do turno seguinte deslocando todos os ordinais.

    A atualizacao por resolvida ja filtra `reacao_lead IS NULL`: um ordinal
    resolvido so pode ter vindo de uma linha que `ler_pendentes` devolveu
    pendente no mesmo turno, e a guarda evita que uma corrida ou uma segunda
    chamada sobrescreva uma reacao ja gravada.

    Commita ao final, como `gravar_recomendacoes` -- o chamador nao abre
    sessao propria para esta escrita.
    """
    async with session_factory() as session:
        for imovel_id, reacao in resolvidas:
            categoria = None if reacao.categoria is None else str(reacao.categoria)
            await session.execute(
                update(Recomendacao)
                .where(
                    Recomendacao.channel == channel,
                    Recomendacao.conversation_key == conversation_key,
                    Recomendacao.imovel_id == imovel_id,
                    Recomendacao.reacao_lead.is_(None),
                )
                .values(reacao_lead=str(reacao.reacao), motivo_descarte=categoria)
            )

        await session.execute(
            update(Recomendacao)
            .where(
                Recomendacao.channel == channel,
                Recomendacao.conversation_key == conversation_key,
                Recomendacao.reacao_lead.is_(None),
            )
            .values(reacao_lead=str(ReacaoLead.NEUTRO))
        )
        await session.commit()
