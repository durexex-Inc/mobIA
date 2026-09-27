"""A lista de leads, o apelido opaco de cada um e o dado que so a revelacao
mostra. TEC-192 e TEC-195, RF-18, RN-18.1 e RN-18.5.

**A espinha dorsal e `messages`, e nao `conversas`** (D1 do desenho). Parece
contraintuitivo e nao e: o unico INSERT de `conversas` esta em
`encerrar_conversa`, entao so existe linha para conversa ENCERRADA -- usa-la
como base listaria exatamente os leads que ja acabaram. `lead_qualification`
tambem nao serve, porque o lead que disse "oi" e parou nao tem linha la. A
unica tabela com uma linha garantida por lead e `messages`.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos repositorios deste repo.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.vocabulario import CAMPO_TELEFONE
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import Status
from mobia.domain.handoff.models import Handoff
from mobia.domain.identidade.indice import chave_de, indice_de_telefone, telefones_de
from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.identidade.telefone import grafias_do_wa_id, normalizar
from mobia.domain.leads.consulta import SEM_RECORTE, Cursor, Filtro, FiltroInvalido, RecorteDoPapel
from mobia.domain.leads.mascara import mascarar_telefone
from mobia.domain.leads.models import ReferenciaDeLead
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.messages.models import Message

_SO_DIGITOS = re.compile(r"\D+")


@dataclass(frozen=True)
class LeadDaLista:
    """Uma linha da lista. E o que a card pede, menos o que nao existe.

    **Sem `nome`**: nenhuma tabela deste sistema guarda o nome do lead (Emenda
    E-02 da RN-15.1).

    **Sem `conversation_key`, desde a TEC-195**, e a ausencia e a card inteira:
    no WhatsApp aquele campo era o telefone do lead, e ele saia em claro para
    todo papel com `VER_LEADS`. Desde a TEC-203 o campo e um HMAC, e continua
    fora mesmo assim: quem aponta para um lead agora e `lead_id`, o
    apelido opaco de `referencias_de_lead`; quem mostra o telefone e
    `telefone`, ja mascarado. Nao ha caminho por esta dataclass que reconstrua
    o par -- que e o ponto de ela nao o carregar.

    `channel` fica: dizer que o lead veio do WhatsApp ou do site nao identifica
    ninguem, e a tela ordena por isso.

    **`telefone` nulo e "nao ha numero", e nao "nao pode ver"**: todo chamador
    recebe mascarado (D4), e o lead web que nunca digitou telefone simplesmente
    nao tem um.
    """

    lead_id: uuid.UUID
    channel: str
    telefone: str | None
    score: int | None
    temperatura: str | None
    status: str
    regiao: str | None
    intencao: str | None
    qualificado_em: datetime | None
    ultima_interacao_em: datetime


def _ultima_interacao() -> Any:
    """O instante da fala mais recente de cada conversa, e a lista de leads.

    Espelho do `_nascimento()` de `metricas/repositorio.py`, com `max` no lugar
    de `min` -- e a mesma razao: `messages` e a unica tabela que tem esse
    instante. O indice `ix_messages_timeline` cobre o par, entao o agrupamento
    nao e varredura cega.
    """
    return (
        select(
            Message.channel.label("channel"),
            Message.conversation_key.label("conversation_key"),
            func.max(Message.created_at).label("ultima_interacao_em"),
        )
        .group_by(Message.channel, Message.conversation_key)
        .subquery()
    )


def _score_corrente() -> Any:
    """O score de agora de cada lead: a ultima linha da trilha.

    `DISTINCT ON` e nao `max(created_at)` com auto-join: a trilha guarda o
    TOTAL de cada recalculo, entao o que se quer e a LINHA mais recente, e nao
    o maior valor -- um lead que esfriou tem total menor no registro mais novo,
    e `max` devolveria o score de quando ele estava quente.

    O `ORDER BY` e exatamente o do indice `ix_lead_score_audit_lead`
    (`channel, conversation_key, created_at DESC`), que existe para esta
    pergunta.
    """
    return (
        select(
            LeadScoreAudit.channel.label("channel"),
            LeadScoreAudit.conversation_key.label("conversation_key"),
            LeadScoreAudit.total_novo.label("score"),
        )
        # `distinct_on` e nao `.distinct(col)`: o segundo produz o mesmo SQL e
        # esta deprecado na SQLAlchemy 2.1, com warning por execucao.
        .ext(distinct_on(LeadScoreAudit.channel, LeadScoreAudit.conversation_key))
        .order_by(
            LeadScoreAudit.channel,
            LeadScoreAudit.conversation_key,
            LeadScoreAudit.created_at.desc(),
        )
        .subquery()
    )


def _onde_a_busca_bate(base: Any, termo: str) -> Any:
    """Bairro de interesse, ou telefone -- nas duas origens dele. D3.

    **Nao ha busca por nome**, porque nao ha nome (L1). A card pede as tres, e
    esta e a unica das tres que nao tem de onde sair.

    O telefone mora em dois lugares e os dois entram: no WhatsApp, o
    `conversation_key` e o HMAC do `wa_id` (TEC-203); no web, a sessao e
    anonima e o numero so existe se o lead o digitou, em `vinculos_de_sessao`
    (TEC-129), cifrado e com `telefone_indice` ao lado.

    **O termo e comparado em duas formas.** `%termo%` cru para a regiao; para
    telefone, so os digitos, levados a forma canonica: quem digita
    "+55 (48) 99999-0000" procura `5548999990000`.

    **Telefone so bate com o numero completo** (TEC-203, decisao 3 do
    desenho). HMAC nao admite substring, e guardar indice dos ultimos digitos
    vazaria agrupamento e seria mais uma coluna a rotacionar. O numero entra
    nas duas grafias do `wa_id` -- `grafias_do_wa_id` --, porque a Meta pode
    ter entregado o celular sem o 9 e o par guarda o HMAC do `wa_id` cru.

    **A busca por telefone SOBREVIVEU ao mascaramento da TEC-195, e isso e um
    oraculo declarado** (D8). Quem nao pode ler o numero ainda pode CONFIRMAR
    um que ja suspeita, vendo se a busca devolve alguem. E confirmacao, nao
    descoberta -- o espaco de numeros e grande demais para varrer --, e o preco
    de fechar seria tirar da tela a forma mais usada de achar um lead, que a
    RN-18.1 pede por escrito. Quem decidir o contrario decide contra aquela
    regra, e isso e card de produto.
    """
    alvos: list[Any] = [LeadQualification.regiao.ilike(f"%{termo}%")]

    digitos = _SO_DIGITOS.sub("", termo)
    canonico = normalizar(digitos) if digitos else None
    if canonico is not None:
        alvos.append(
            base.c.conversation_key.in_(
                [chave_de(CANAL_WHATSAPP, grafia) for grafia in grafias_do_wa_id(canonico)]
            )
        )
        alvos.append(
            select(VinculoDeSessao.channel)
            .where(
                VinculoDeSessao.channel == base.c.channel,
                VinculoDeSessao.conversation_key == base.c.conversation_key,
                VinculoDeSessao.telefone_indice == indice_de_telefone(canonico),
            )
            .exists()
        )

    return or_(*alvos)


@dataclass(frozen=True)
class _Posicao:
    """O cursor JA RESOLVIDO: o par que o `lead_id` dele nomeia.

    **Existe porque a ordem continua sendo por par, e o cursor deixou de
    carrega-lo** (TEC-195, D3). O que viaja para o cliente e o apelido opaco; o
    que o `ORDER BY` compara e `(channel, conversation_key)`, que nao mudou.
    Trocar tambem a ordem exigiria juntar `referencias_de_lead` na consulta, e
    lead ainda sem apelido -- eles nascem sob demanda -- ficaria fora dela.
    """

    score: int | None
    channel: str
    conversation_key: str


def _depois_do_cursor(base: Any, score: Any, posicao: _Posicao) -> Any:
    """A pagina seguinte, por keyset. D5 do desenho.

    A ordem e `score DESC NULLS LAST, channel, conversation_key`, e este
    predicado e o complemento exato dela:

    - com score no cursor, vem depois quem tem score MENOR, quem nao tem score
      nenhum (porque nulo vai para o fim), e quem empata e perde no desempate;
    - sem score no cursor, ja se esta na cauda dos sem score, e so o desempate
      decide.

    **`OFFSET` nao serve aqui, e nao e questao de gosto:** o score e
    recalculado a cada turno, e um lead que sobe entre a primeira e a segunda
    pagina faz uma linha ser pulada e outra aparecer duas vezes. O defeito e
    invisivel em teste de pagina unica.
    """
    desempate = func.row(base.c.channel, base.c.conversation_key) > func.row(
        posicao.channel, posicao.conversation_key
    )

    if posicao.score is None:
        return and_(score.c.score.is_(None), desempate)

    return or_(
        score.c.score < posicao.score,
        score.c.score.is_(None),
        and_(score.c.score == posicao.score, desempate),
    )


def _consulta(
    filtro: Filtro, *, recorte: RecorteDoPapel, posicao: _Posicao | None = None
) -> Select[Any]:
    base = _ultima_interacao()
    score = _score_corrente()

    consulta = (
        select(
            base.c.channel,
            base.c.conversation_key,
            base.c.ultima_interacao_em,
            score.c.score,
            LeadQualification.temperatura,
            LeadQualification.regiao,
            LeadQualification.intencao,
            LeadQualification.qualificado_em,
            Conversa.status,
        )
        .select_from(base)
        .join(
            score,
            (score.c.channel == base.c.channel)
            & (score.c.conversation_key == base.c.conversation_key),
            isouter=True,
        )
        .join(
            LeadQualification,
            (LeadQualification.channel == base.c.channel)
            & (LeadQualification.conversation_key == base.c.conversation_key),
            isouter=True,
        )
        # LEFT JOIN, e e ele que torna a D8 necessaria: `conversas` so tem
        # linha depois do encerramento, entao a ausencia AQUI significa ATIVA.
        .join(
            Conversa,
            (Conversa.channel == base.c.channel)
            & (Conversa.conversation_key == base.c.conversation_key),
            isouter=True,
        )
    )

    if filtro.canal is not None:
        consulta = consulta.where(base.c.channel == filtro.canal)

    if filtro.temperatura is not None:
        consulta = consulta.where(LeadQualification.temperatura == filtro.temperatura)

    if filtro.status == Status.ATIVA.value:
        # A ausencia de linha e ATIVA (D8). Sem o `is_(None)`, filtrar por
        # ATIVA devolveria so os leads que ja foram encerrados e reabertos --
        # o oposto do pedido.
        consulta = consulta.where(or_(Conversa.status.is_(None), Conversa.status == Status.ATIVA))
    elif filtro.status is not None:
        consulta = consulta.where(Conversa.status == filtro.status)

    if filtro.busca is not None:
        consulta = consulta.where(_onde_a_busca_bate(base, filtro.busca))

    if recorte.nao_ve_nada:
        # Fail-CLOSED explicito, e nao "sem filtro". Ver `RecorteDoPapel`.
        return consulta.where(false())

    # **O do papel vence o da query, e por isso e aplicado depois** (D7). Mandar
    # `corretorId=<outro>` sendo CORRETOR nao alarga nada: os dois viram AND, e
    # o recorte do papel esta sempre presente.
    for dono in (filtro.corretor_id, recorte.corretor_id if recorte.e_corretor else None):
        if dono is not None:
            consulta = consulta.where(
                select(Handoff.id)
                .where(
                    Handoff.channel == base.c.channel,
                    Handoff.conversation_key == base.c.conversation_key,
                    Handoff.corretor_id == dono,
                )
                .exists()
            )

    if posicao is not None:
        consulta = consulta.where(_depois_do_cursor(base, score, posicao))

    return consulta.order_by(
        score.c.score.desc().nullslast(),
        base.c.channel,
        base.c.conversation_key,
    )


async def referencias_para(
    session: AsyncSession, pares: Sequence[tuple[str, str]]
) -> dict[tuple[str, str], uuid.UUID]:
    """O apelido opaco de cada par, criando o que faltar. TEC-195, D2.

    **Duas consultas para a pagina inteira, e nao duas por lead.** O INSERT em
    lote com `ON CONFLICT DO NOTHING` cria o que nao existe, e o SELECT seguinte
    le tudo -- inclusive o que ja existia e o que outra requisicao criou entre
    os dois.

    **O `ON CONFLICT` e o que torna o get-or-create seguro sob concorrencia.**
    Sem ele, duas requisicoes simultaneas para o mesmo lead produziriam dois
    apelidos, e o mesmo lead teria dois enderecos -- a trilha de auditoria
    registraria os dois como entidades diferentes, e nada juntaria os dois
    depois.

    **Nao commita**, como os outros repositorios deste repo. Quem chama e a
    rota, que ja abre e fecha a sessao.
    """
    if not pares:
        return {}

    agora = datetime.now(UTC)
    await session.execute(
        insert(ReferenciaDeLead)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "channel": channel,
                    "conversation_key": conversation_key,
                    "criado_em": agora,
                }
                for channel, conversation_key in pares
            ]
        )
        .on_conflict_do_nothing(constraint="uq_referencias_de_lead_conversa"),
    )

    linhas = (
        await session.execute(
            select(
                ReferenciaDeLead.channel,
                ReferenciaDeLead.conversation_key,
                ReferenciaDeLead.id,
            ).where(
                func.row(ReferenciaDeLead.channel, ReferenciaDeLead.conversation_key).in_(
                    [func.row(channel, chave) for channel, chave in pares]
                )
            )
        )
    ).all()
    return {(linha.channel, linha.conversation_key): linha.id for linha in linhas}


async def referencias_existentes(
    session: AsyncSession, pares: Sequence[tuple[str, str]]
) -> dict[tuple[str, str], uuid.UUID]:
    """O apelido de cada par que JA tem um -- so leitura, sem criar nada.

    Para quem lista algo que nao e o painel de leads e nao pode recriar um
    apelido que outra transacao acabou de apagar. O caso que a trouxe (TEC-207,
    revisao final, M2): a fila de solicitacoes de titular le a solicitacao
    ABERTA, e se uma anonimizacao commitar entre essa leitura e um
    `referencias_para`, o get-or-create recriava a linha sob a chave antiga,
    que a chave de indice ainda liga ao telefone. Par sem apelido fica fora
    do dicionario.
    """
    if not pares:
        return {}
    linhas = (
        await session.execute(
            select(
                ReferenciaDeLead.channel,
                ReferenciaDeLead.conversation_key,
                ReferenciaDeLead.id,
            ).where(
                func.row(ReferenciaDeLead.channel, ReferenciaDeLead.conversation_key).in_(
                    [func.row(channel, chave) for channel, chave in pares]
                )
            )
        )
    ).all()
    return {(linha.channel, linha.conversation_key): linha.id for linha in linhas}


async def par_de(session: AsyncSession, lead_id: uuid.UUID) -> tuple[str, str] | None:
    """O par que este apelido nomeia, ou `None` se ele nao existe.

    O caminho inverso de `referencias_para`, e o unico. E ele que permite a
    revelacao voltar ao telefone -- a razao de esta referencia ser uma linha e
    nao um HMAC como o `lead_ref` da trilha.
    """
    linha = (
        await session.execute(
            select(ReferenciaDeLead.channel, ReferenciaDeLead.conversation_key).where(
                ReferenciaDeLead.id == lead_id
            )
        )
    ).first()
    return (linha.channel, linha.conversation_key) if linha is not None else None


async def listar_leads(
    session: AsyncSession, *, filtro: Filtro, recorte: RecorteDoPapel = SEM_RECORTE
) -> tuple[list[LeadDaLista], Cursor | None]:
    """A pagina pedida e o cursor da proxima, ou `None` quando acabou.

    **Pede um item a mais do que o limite, e o descarta.** E o que responde
    "ha proxima pagina?" sem um `COUNT(*)` sobre a consulta inteira -- que
    custaria a agregacao de `messages` duas vezes por requisicao para produzir
    um numero que o cliente nao usa para nada alem de saber se continua.

    `recorte` vem da claim do JWT, nunca da query: ver a D7 e `RecorteDoPapel`.

    **O cursor chega com o apelido e e resolvido aqui** (TEC-195, D3). Apelido
    que nao existe e cursor invalido, e nao primeira pagina: quem chamou perdeu
    o lugar, e devolver o comeco em silencio faria a tela mostra-lo como se
    fosse a continuacao.
    """
    posicao: _Posicao | None = None
    if filtro.cursor is not None:
        par = await par_de(session, filtro.cursor.lead_id)
        if par is None:
            raise FiltroInvalido("cursor invalido")
        posicao = _Posicao(score=filtro.cursor.score, channel=par[0], conversation_key=par[1])

    linhas = (
        await session.execute(
            _consulta(filtro, recorte=recorte, posicao=posicao).limit(filtro.limite + 1)
        )
    ).all()

    tem_mais = len(linhas) > filtro.limite
    visiveis = linhas[: filtro.limite]
    pares = [(linha.channel, linha.conversation_key) for linha in visiveis]
    apelidos = await referencias_para(session, pares)
    # **O telefone sai de duas origens, e `telefones_de` junta as duas**: a
    # identidade do WhatsApp e o vinculo cifrado do web (TEC-203). Uma consulta
    # por origem para a pagina inteira, e nao uma por linha.
    telefones = await telefones_de(session, pares)

    pagina = [
        LeadDaLista(
            lead_id=apelidos[(linha.channel, linha.conversation_key)],
            channel=linha.channel,
            telefone=(
                mascarar_telefone(telefone)
                if (telefone := telefones[(linha.channel, linha.conversation_key)])
                else None
            ),
            score=linha.score,
            temperatura=linha.temperatura,
            # A ausencia de linha em `conversas` e ATIVA (D8), e a traducao
            # mora aqui e nao no SQL: quem le a resposta nao deve precisar
            # saber que a tabela so nasce no encerramento.
            status=linha.status or Status.ATIVA.value,
            regiao=linha.regiao,
            intencao=linha.intencao,
            qualificado_em=linha.qualificado_em,
            ultima_interacao_em=linha.ultima_interacao_em,
        )
        for linha in visiveis
    ]

    if not tem_mais or not pagina:
        return pagina, None

    ultimo = pagina[-1]
    return pagina, Cursor(score=ultimo.score, lead_id=ultimo.lead_id)


async def e_lead_do_corretor(
    session: AsyncSession, *, par: tuple[str, str], corretor_id: uuid.UUID | None
) -> bool:
    """Se este lead ja foi repassado a este corretor.

    Mesmo vinculo que o recorte da lista usa (`handoffs.corretor_id`), pela
    mesma razao: antes do repasse o lead nao tem dono. Corretor sem vinculo
    devolve falso -- fail-CLOSED, como `RecorteDoPapel.nao_ve_nada`.
    """
    if corretor_id is None:
        return False
    channel, conversation_key = par
    return (
        await session.execute(
            select(Handoff.id)
            .where(
                Handoff.channel == channel,
                Handoff.conversation_key == conversation_key,
                Handoff.corretor_id == corretor_id,
            )
            .limit(1)
        )
    ).first() is not None


async def valor_revelado(session: AsyncSession, *, par: tuple[str, str], campo: str) -> str | None:
    """O dado pessoal em claro. So `revelar` chama, e so depois de registrar.

    **`telefone` sai na forma canonica com `+`**, e nao nos digitos crus do
    `wa_id`: quem revela vai discar ou copiar, e `5548999990021` obriga a tela
    a formatar de novo -- uma segunda regra de formatacao, livre para divergir
    da que a mascara usa. Vem de `telefones_de`, pelas duas origens (TEC-203).

    **`email` devolve `None`, e isso nao e falha** (TEC-195, D7): nenhuma
    tabela deste sistema guarda e-mail de lead. O campo e aceito pelo
    vocabulario para que a tela nao precise mudar no dia em que a coluna
    nascer; ate la, nulo diz "nao ha", que e a verdade.
    """
    if campo != CAMPO_TELEFONE:
        return None
    telefone = (await telefones_de(session, [par]))[par]
    return f"+{telefone}" if telefone else None
