"""O turno do WhatsApp herda o que a mesma pessoa disse no site. TEC-129, D4.

**So grava no par do WhatsApp, e isso e a card inteira.** A sessao web e
anonima e nada verifica que o telefone digitado e de quem o digitou (D1): o
que vai do site para o WhatsApp e o que a sessao disse, e nunca o contrario.
Uma absorcao que escrevesse no par web entregaria, no turno web seguinte, a
qualificacao do WhatsApp a quem digitou o numero de outra pessoa.

**O que o WhatsApp ja sabe prevalece.** Preenche so campo vazio: o numero e o
lado autenticado, e o que ele disse diretamente vale mais que o que uma sessao
anonima disse em nome dele.

**O que fica de fora, e por que** -- ver a D4 da spec por extenso:
`recomendacoes` (a linha sem reacao dispara a pergunta de reacao, e a ordem e
o ordinal), `conversation_intent` (confianca, desambiguacao e o contador de
fora de escopo sao do episodio, nao da pessoa), o resumo (um bloco a mais no
prompt a cada turno), score e temperatura (recalculados no proprio turno) e
opt-out, handoff e atendimento humano (uma sessao nao verificada nao silencia
nem escala o numero de outra pessoa).

**O orcamento e o investidor so atravessam dentro da mesma banda de
intencao** (revisao final da TEC-129). Um valor dito sob uma banda nao
significa nada na outra -- e o argumento da TEC-136, que faz
`aplicar_mudanca_de_intencao` apagar a faixa e a recusa do orcamento quando a
intencao troca de banda. Sem a mesma regra aqui, o turno seguinte a troca
acharia a faixa vazia e a repreencheria da sessao web, que estava na banda
antiga: o lead de aluguel carregaria para sempre o orcamento de compra. Por
isso a faixa de preco, a recusa do orcamento e os campos do investidor so vem
de uma origem cuja intencao esta na banda do destino, e "mesma banda" e
`not mudou_de_banda(origem, destino)` -- o predicado da TEC-136, e nao uma
segunda copia de `_BANDAS`. Isso herda as leituras dele para "sem banda":
origem sem intencao, com o destino numa banda, NAO passa (o valor entrou sob
a banda frouxa, que nao validou nada); intencao fora da tabela, em qualquer
ponta, passa. Destino sem intencao herda primeiro a intencao (da origem mais
recente que tem uma), e e ela que define a banda; se nenhuma origem tem
intencao, nao ha banda a respeitar e tudo passa -- a TEC-136 apaga a faixa
quando a primeira intencao chegar, pela mesma leitura de `antiga is None`.

**Os campos do investidor vem em bloco, de uma origem so**: a mais recente,
dentro da banda, que tem algum deles, e so se o WhatsApp ainda nao tem
nenhum. `perfil_investidor` e derivado de `horizonte` e
`retorno_esperado_tipo` (`gravar_investidor`); preenchidos campo a campo, o
perfil de uma sessao podia chegar ao lado do horizonte de outra, ou do
proprio WhatsApp, e dizer um perfil que nenhum dos dois estados sustenta.

Idempotente: roda em todo turno, e o segundo passe sobre o mesmo estado nao
muda nada. E isso que cobre a sessao web que continua viva depois de o
WhatsApp comecar.
"""

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agente.dinheiro import mudou_de_banda
from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import MARCA_DO_ORCAMENTO
from mobia.domain.identidade.repositorio import sessoes_vinculadas
from mobia.domain.identidade.telefone import normalizar
from mobia.domain.messages.canais import CANAL_WHATSAPP

# Os criterios, e so eles: estes tres grupos mais `intencao`, que entra por ser
# a coluna de qualificacao, e nao a linha de `conversation_intent`, e que
# `_preencher` trata antes de todos porque e ela que define a banda. O que NAO
# entra e bookkeeping do turno -- `perguntados_sem_resposta`,
# `perguntas_feitas` -- e o que o turno recalcula, `temperatura*` e
# `qualificado_em`.
#
# Em tres grupos porque cada um atravessa por uma regra -- ver o docstring do
# modulo: os livres vem campo a campo de qualquer origem; o orcamento, campo a
# campo mas so de origem na banda do destino; o investidor, em bloco, de uma
# origem so na banda do destino.
_CAMPOS_LIVRES: tuple[str, ...] = (
    "regiao",
    "tipo_imovel",
    "quartos",
    "vagas",
    "urgencia",
    "forma_pagamento",
    "tem_imovel_para_vender",
)
_CAMPOS_DO_ORCAMENTO: tuple[str, ...] = ("faixa_preco_min_centavos", "faixa_preco_max_centavos")
_CAMPOS_DO_INVESTIDOR: tuple[str, ...] = (
    "ticket_investimento_centavos",
    "retorno_esperado_pct",
    "retorno_esperado_tipo",
    "horizonte",
    "tolerancia_reforma",
    "ja_investe_em_imoveis",
    "perfil_investidor",
)

# `campos_recusados` guarda o vocabulario da MARCA (`_marca_de` em
# `domain/context/repositorio.py`), nao nome de coluna -- e o unico nome desse
# vocabulario que cobre mais de uma coluna e o orcamento: `campos_a_recusar`
# grava toda recusa de faixa de preco sob `MARCA_DO_ORCAMENTO` -- importada, e
# nao escrita a mao aqui, pela razao que o comentario do descarte em
# `aplicar_mudanca_de_intencao` da --, ainda que o lead tenha se recusado a
# dar so um dos dois extremos (`_CAMPOS_DO_ORCAMENTO` -- ver `_preenchido` em
# `domain/context/qualificacao.py`, que trata os dois do mesmo jeito:
# "qualquer uma basta"). Por isso uma recusa de orcamento tem de
# cair quando QUALQUER um dos dois extremos ja esta preenchido no WhatsApp, e
# nao so quando os dois estao. Nomes fora deste mapa continuam resolvidos por
# `getattr` direto (o comportamento e o mesmo, com uma coluna so na tupla).
_COLUNAS_DO_CAMPO_RECUSADO: dict[str, tuple[str, ...]] = {
    MARCA_DO_ORCAMENTO: _CAMPOS_DO_ORCAMENTO,
}


def _ja_preenchido(destino: LeadQualification, campo: str) -> bool:
    colunas = _COLUNAS_DO_CAMPO_RECUSADO.get(campo, (campo,))
    return any(getattr(destino, coluna, None) is not None for coluna in colunas)


async def absorver_sessoes_vinculadas(
    session_factory: async_sessionmaker[AsyncSession], *, channel: str, conversation_key: str
) -> tuple[tuple[str, str], ...]:
    """Preenche o estado do WhatsApp com o das sessoes vinculadas; devolve os pares delas.

    Os pares vao para `montar_contexto`, que os poe na janela de literais. Sem
    vinculo -- ou com um `wa_id` que nao e brasileiro -- devolve `()` e nao
    escreve nada: o turno segue exatamente como antes desta card.

    **Canal que nao e o WhatsApp devolve `()` sem tocar no banco.** O gate de
    verdade e o do turno (`executar_turno` so chama isto no WhatsApp); este e
    a defesa em profundidade dele. Sem ela, uma chamada com o par web -- cujo
    `conversation_key` e um UUID, e os digitos de um UUID de vez em quando
    formam um telefone plausivel -- criaria uma linha `whatsapp` fantasma com a
    chave da sessao e devolveria, para a janela do turno web, as falas de
    outras sessoes vinculadas a esse numero.
    """
    if channel != CANAL_WHATSAPP:
        return ()
    telefone = normalizar(conversation_key)
    if telefone is None:
        return ()

    async with session_factory() as session:
        pares = await sessoes_vinculadas(session, telefone)
        if not pares:
            return ()

        origens = list(
            await session.scalars(
                select(LeadQualification)
                .where(
                    tuple_(LeadQualification.channel, LeadQualification.conversation_key).in_(pares)
                )
                # A mais recente primeiro: e ela que vence um campo que duas
                # sessoes preencheram diferente.
                .order_by(LeadQualification.updated_at.desc())
            )
        )
        if origens:
            await _preencher(session, conversation_key, origens)
            await session.commit()
    return tuple(pares)


async def _preencher(
    session: AsyncSession, conversation_key: str, origens: list[LeadQualification]
) -> None:
    # Garante a linha antes do `FOR UPDATE`: sem ela nao ha o que travar, e dois
    # turnos simultaneos do mesmo numero criariam a linha os dois.
    await session.execute(
        pg_insert(LeadQualification)
        .values(channel=CANAL_WHATSAPP, conversation_key=conversation_key)
        .on_conflict_do_nothing(index_elements=["channel", "conversation_key"])
    )
    destino = (
        await session.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == CANAL_WHATSAPP,
                LeadQualification.conversation_key == conversation_key,
            )
            .with_for_update()
        )
    ).scalar_one()

    # A intencao primeiro: sem ela no destino, e a herdada que define a banda.
    if destino.intencao is None:
        destino.intencao = next(
            (origem.intencao for origem in origens if origem.intencao is not None), None
        )
    na_banda = [origem for origem in origens if _na_banda_do_destino(origem, destino)]

    _preencher_campo_a_campo(destino, _CAMPOS_LIVRES, origens)
    _preencher_campo_a_campo(destino, _CAMPOS_DO_ORCAMENTO, na_banda)

    if all(getattr(destino, campo) is None for campo in _CAMPOS_DO_INVESTIDOR):
        fonte = next(
            (
                origem
                for origem in na_banda
                if any(getattr(origem, campo) is not None for campo in _CAMPOS_DO_INVESTIDOR)
            ),
            None,
        )
        if fonte is not None:
            for campo in _CAMPOS_DO_INVESTIDOR:
                setattr(destino, campo, getattr(fonte, campo))

    # Uniao, menos o que o destino ja tem preenchido: a recusa no site sobre um
    # campo que o WhatsApp respondeu depois nao pode fazer o agente tratar como
    # recusado o que a pessoa ja disse. `_ja_preenchido` cobre o caso do
    # orcamento, onde a marca recusada e as colunas de valor nao tem o mesmo
    # nome -- ver o comentario de `_COLUNAS_DO_CAMPO_RECUSADO` acima. A recusa
    # do orcamento e da banda, como o valor: de origem fora dela, nao entra.
    recusados = set(destino.campos_recusados or [])
    for origem in origens:
        da_origem = set(origem.campos_recusados or [])
        if origem not in na_banda:
            da_origem.discard(MARCA_DO_ORCAMENTO)
        recusados |= da_origem
    recusados = {campo for campo in recusados if not _ja_preenchido(destino, campo)}
    if recusados != set(destino.campos_recusados or []):
        destino.campos_recusados = sorted(recusados)


def _preencher_campo_a_campo(
    destino: LeadQualification, campos: tuple[str, ...], origens: list[LeadQualification]
) -> None:
    """Cada campo vazio do destino recebe o da origem mais recente que o tem."""
    for campo in campos:
        if getattr(destino, campo) is not None:
            continue
        for origem in origens:
            valor = getattr(origem, campo)
            if valor is not None:
                setattr(destino, campo, valor)
                break


def _na_banda_do_destino(origem: LeadQualification, destino: LeadQualification) -> bool:
    """O orcamento desta origem vale na banda do destino? Ver o docstring do modulo.

    `Intencao(...)` sem guarda, como em `aplicar_mudanca_de_intencao`: a coluna
    so e escrita a partir de `Intencao.value`.
    """
    if destino.intencao is None:
        return True
    antiga = Intencao(origem.intencao) if origem.intencao is not None else None
    return not mudou_de_banda(antiga, Intencao(destino.intencao))
