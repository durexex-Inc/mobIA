"""O painel de custo de IA. TEC-191, RN-17.4 e RNF-06.

**Agrega, nao recalcula.** A fonte e `message_telemetry`, uma linha por
resposta do agente com o `cost_usd` que a TEC-126 gravou na hora. Nenhum preco
e reaplicado aqui: se a tabela de precos mudar, o passado continua custando o
que custou.

**O periodo conta quando o gasto aconteceu** (D1, decisao do Eduardo,
26/09/2026): `message_telemetry.created_at` dentro do recorte, e nao a coorte
do funil. O funil pergunta o que aconteceu com quem chegou no mes; este painel
pergunta quanto se gastou no mes -- e so essa pergunta tem um orcamento com que
comparar.

As contas puras (orcamento proporcional, alerta, media) ficam em funcoes sem
I/O no topo, testadas em `tests/unit/`; a consulta vem depois.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.models import LeadQualification
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.metricas.filtros import Recorte

# RNF-06: "<= US$ 0,12 por conversa qualificada". Requisito, e nao
# configuracao -- a card pede que o alvo seja EXIBIDO, nao ajustado.
ALVO_POR_LEAD_QUALIFICADO_USD = Decimal("0.12")

# D3. O alerta acende a partir de 80% do orcamento do periodo, inclusive.
LIMIAR_DO_ALERTA = Decimal("0.80")

# D3. O mes do orcamento tem 30 dias, sempre: um periodo de 30 dias e o
# orcamento mensal inteiro. Um mes real de 31 dias usa 103% dele (L2).
DIAS_DO_MES_DO_ORCAMENTO = 30

# Seis casas, a escala de `message_telemetry.cost_usd`: menos que isso
# arredondaria o custo de uma resposta barata para zero.
_SEIS_CASAS = Decimal("0.000001")


def media(total: Decimal, quantos: int) -> Decimal | None:
    """Nula com denominador zero: "nao houve conversa" nao e "custou zero"."""
    if quantos == 0:
        return None
    return (total / quantos).quantize(_SEIS_CASAS)


def orcamento_do_periodo(mensal: Decimal, *, dias: int) -> Decimal:
    """O mensal proporcional aos dias do periodo (D3)."""
    return (mensal * dias / DIAS_DO_MES_DO_ORCAMENTO).quantize(_SEIS_CASAS)


@dataclass(frozen=True)
class Orcamento:
    mensal_usd: Decimal
    do_periodo_usd: Decimal
    consumido_usd: Decimal
    consumido_pct: Decimal
    alerta: bool


def avaliar_orcamento(mensal: Decimal, *, dias: int, consumido: Decimal) -> Orcamento:
    """O bloco de orcamento. `consumido` e o da operacao INTEIRA, sem filtro (D3)."""
    do_periodo = orcamento_do_periodo(mensal, dias=dias)
    fracao = consumido / do_periodo
    return Orcamento(
        mensal_usd=mensal,
        do_periodo_usd=do_periodo,
        consumido_usd=consumido,
        consumido_pct=(fracao * 100).quantize(Decimal("0.01")),
        alerta=fracao >= LIMIAR_DO_ALERTA,
    )


@dataclass(frozen=True)
class TokensDoModelo:
    entrada: int
    saida: int
    cache_leitura: int
    cache_escrita: int


@dataclass(frozen=True)
class CustoDoPeriodo:
    total_usd: Decimal
    # D2. Linhas com `cost_usd` nulo -- modelo sem preco cadastrado. Nao
    # entram no total, e o numero diz quantas ficaram de fora.
    mensagens_sem_preco: int
    conversas: int
    leads_qualificados: int
    tokens_por_modelo: dict[str, TokensDoModelo]


def _gastos(recorte: Recorte, *, com_filtros: bool) -> Select[MessageTelemetry, str, str]:
    """As linhas de telemetria do periodo, com a conversa de cada uma.

    `intencao` e `temperatura` filtram pela qualificacao ATUAL da conversa,
    como no funil; `canal`, pela conversa da mensagem.
    """
    consulta = (
        select(MessageTelemetry, Message.channel, Message.conversation_key)
        .join(Message, Message.id == MessageTelemetry.message_id)
        .where(
            MessageTelemetry.created_at >= recorte.inicio,
            MessageTelemetry.created_at < recorte.fim,
        )
    )
    if not com_filtros:
        return consulta
    if recorte.canal is not None:
        consulta = consulta.where(Message.channel == recorte.canal)
    if recorte.intencao is not None or recorte.temperatura is not None:
        consulta = consulta.join(
            LeadQualification,
            and_(
                LeadQualification.channel == Message.channel,
                LeadQualification.conversation_key == Message.conversation_key,
            ),
        )
        if recorte.intencao is not None:
            consulta = consulta.where(LeadQualification.intencao == recorte.intencao)
        if recorte.temperatura is not None:
            consulta = consulta.where(LeadQualification.temperatura == recorte.temperatura)
    return consulta


async def total_sem_filtros(session: AsyncSession, *, recorte: Recorte) -> Decimal:
    """O gasto da operacao inteira no periodo -- o que o orcamento compara (D3)."""
    gastos = _gastos(recorte, com_filtros=False).subquery()
    valor: Decimal | int = (
        await session.execute(select(func.coalesce(func.sum(gastos.c.cost_usd), 0)))
    ).scalar_one()
    return Decimal(valor).quantize(_SEIS_CASAS)


async def custo_do_periodo(session: AsyncSession, *, recorte: Recorte) -> CustoDoPeriodo:
    gastos = _gastos(recorte, com_filtros=True).subquery()

    total, sem_preco, conversas = (
        await session.execute(
            select(
                func.coalesce(func.sum(gastos.c.cost_usd), 0),
                func.count().filter(gastos.c.cost_usd.is_(None)),
                func.count(func.distinct(func.row(gastos.c.channel, gastos.c.conversation_key))),
            )
        )
    ).one()

    tokens = {
        str(modelo): TokensDoModelo(
            entrada=int(entrada),
            saida=int(saida),
            cache_leitura=int(leitura),
            cache_escrita=int(escrita),
        )
        for modelo, entrada, saida, leitura, escrita in (
            await session.execute(
                select(
                    gastos.c.model,
                    func.sum(gastos.c.tokens_in),
                    func.sum(gastos.c.tokens_out),
                    func.coalesce(func.sum(gastos.c.cache_read_tokens), 0),
                    func.coalesce(func.sum(gastos.c.cache_write_tokens), 0),
                )
                .group_by(gastos.c.model)
                .order_by(gastos.c.model)
            )
        ).all()
    }

    # D1. Os que se QUALIFICARAM no periodo, e nao os donos das conversas que
    # custaram: e custo de aquisicao, e o gasto com quem nao qualificou tambem
    # foi gasto para achar quem qualificou.
    qualificados = select(func.count()).where(
        LeadQualification.qualificado_em >= recorte.inicio,
        LeadQualification.qualificado_em < recorte.fim,
    )
    if recorte.canal is not None:
        qualificados = qualificados.where(LeadQualification.channel == recorte.canal)
    if recorte.intencao is not None:
        qualificados = qualificados.where(LeadQualification.intencao == recorte.intencao)
    if recorte.temperatura is not None:
        qualificados = qualificados.where(LeadQualification.temperatura == recorte.temperatura)

    return CustoDoPeriodo(
        total_usd=Decimal(total).quantize(_SEIS_CASAS),
        mensagens_sem_preco=int(sem_preco),
        conversas=int(conversas),
        leads_qualificados=int((await session.execute(qualificados)).scalar_one()),
        tokens_por_modelo=tokens,
    )
