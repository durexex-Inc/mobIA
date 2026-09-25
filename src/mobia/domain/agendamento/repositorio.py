"""Reservar, confirmar e ler a agenda do corretor. TEC-168, RN-11.4, RT-07.

Recebe a sessao e **nao commita** -- o commit e de quem chama, como em
`registrar_handoff` e `criar_corretor`. A exclusao por intervalo e do banco
(migration 0044); este modulo so traduz a recusa dele em `Conflito` e faz a
expiracao preguicosa que o banco nao consegue fazer sozinho (D3 do desenho).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, and_, cast, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from mobia.app.config import get_settings
from mobia.domain.agendamento.janelas import (
    AgendaDoCorretor,
    ContadorDeVisitas,
    Intervalo,
    TipoDeCompromisso,
    propor_janelas_do_corretor,
)
from mobia.domain.agendamento.models import (
    EXCLUSAO_DE_SOBREPOSICAO,
    Agendamento,
    StatusDoAgendamento,
)
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.corretores.models import Corretor

# RN-11.4. Regra do SRS, nao configuracao -- o argumento da D4 da TEC-285.
DURACAO_DA_RESERVA = timedelta(minutes=5)


@dataclass(frozen=True)
class Reserva:
    id: uuid.UUID
    janela: Intervalo
    reservado_ate: datetime


@dataclass(frozen=True)
class Conflito:
    pass


@dataclass(frozen=True)
class Confirmado:
    id: uuid.UUID
    janela: Intervalo


@dataclass(frozen=True)
class Expirado:
    pass


def _ocupa_em(momento: datetime) -> ColumnElement[Any]:
    """O compromisso que ocupa o corretor em `momento`. D3 da TEC-168.

    Confirmado ocupa sempre; reservado, so enquanto a reserva vale. Uma
    funcao so para `ocupados` e `visitas_por_dia` (TEC-166, D6): a
    disponibilidade e a capacidade nunca podem discordar sobre uma reserva
    vencida.
    """
    return or_(
        Agendamento.status == StatusDoAgendamento.CONFIRMADO,
        and_(
            Agendamento.status == StatusDoAgendamento.RESERVADO,
            Agendamento.reservado_ate > momento,
        ),
    )


def _e_sobreposicao(exc: IntegrityError) -> bool:
    """Distingue a recusa da exclusao de qualquer outra falha de integridade.

    Mesma forma de `_e_email_duplicado` (`corretores/repositorio.py`): pelo
    NOME da constraint, com o texto como fallback para driver que nao expoe
    `constraint_name`. Tratar todo IntegrityError como conflito esconderia
    um CHECK violado atras de "horario ocupado".

    **Com asyncpg, o nome estruturado mora um nivel abaixo de `exc.orig`.**
    `exc.orig` e o `IntegrityError` que o SQLAlchemy adapta, e ele nao tem
    `constraint_name`; quem tem e o erro do proprio asyncpg, que o dialeto
    deixa em `exc.orig.__cause__`. Por isso o `__cause__` e checado primeiro;
    `exc.orig` direto continua checado depois, para o driver que exponha o
    campo sem esse nivel a mais; e o texto e o ultimo fallback, para quem nao
    expoe nada estruturado.
    """
    original = exc.orig
    nome = getattr(getattr(original, "__cause__", None), "constraint_name", None)
    if nome is None:
        nome = getattr(original, "constraint_name", None)
    if nome is not None:
        return bool(nome == EXCLUSAO_DE_SOBREPOSICAO)
    return EXCLUSAO_DE_SOBREPOSICAO in str(original)


async def reservar(
    session: AsyncSession,
    *,
    corretor_id: uuid.UUID,
    channel: str,
    conversation_key: str,
    janela: Intervalo,
    tipo: TipoDeCompromisso,
    imovel_id: uuid.UUID | None,
    agora: datetime,
    motivo: MotivoDaAlocacao,
) -> Reserva | Conflito:
    """Reserva `janela` por `DURACAO_DA_RESERVA`, ou devolve `Conflito`.

    Antes de inserir, marca EXPIRADO as reservas vencidas **deste corretor**
    que sobrepoem a janela: a constraint nao olha o relogio, e sem isso uma
    reserva morta barraria o lugar para sempre.

    `motivo` e o que `alocar` deu a este corretor (TEC-166); a reserva o
    grava para a gerente ler depois.

    **Em `Conflito`, so o SAVEPOINT desta chamada volta.** Um `session.rollback()`
    de sessao inteira expira TODO objeto carregado na sessao -- inclusive o
    `Corretor` que quem chama ja tinha em maos --, e o acesso sincrono a um
    atributo expirado fora de contexto async explode com `MissingGreenlet`
    (visto em `test_sessao_continua_utilizavel_depois_do_conflito`). Por isso
    o UPDATE de expiracao e o INSERT entram num `session.begin_nested()`: em
    conflito, so o que esta chamada tentou e desfeito -- o resto da sessao,
    inclusive escrita pendente anterior de quem chama, continua de pe.

    **Nao reconta capacidade.** A exclusao do banco so recusa sobreposicao de
    horario; duas chamadas concorrentes reservando slots DIFERENTES do mesmo
    corretor no mesmo dia podem ambas suceder e passar de `capacidade_diaria`
    -- nada aqui rele `visitas_por_dia` nem trava a linha do corretor antes de
    inserir. Capacidade e conferida so na hora de propor janela (`alocar`,
    `reservar_ou_alternativas`); na hora de gravar, ela e so aspiracional
    (Important 2 da revisao final da TEC-166).
    """
    try:
        async with session.begin_nested():
            await session.execute(
                update(Agendamento)
                .where(
                    Agendamento.corretor_id == corretor_id,
                    Agendamento.status == StatusDoAgendamento.RESERVADO,
                    Agendamento.reservado_ate <= agora,
                    Agendamento.inicio < janela.fim,
                    Agendamento.fim > janela.inicio,
                )
                .values(status=StatusDoAgendamento.EXPIRADO)
            )
            agendamento = Agendamento(
                id=uuid.uuid4(),
                corretor_id=corretor_id,
                channel=channel,
                conversation_key=conversation_key,
                imovel_id=imovel_id,
                tipo=str(tipo),
                inicio=janela.inicio,
                fim=janela.fim,
                status=StatusDoAgendamento.RESERVADO,
                reservado_ate=agora + DURACAO_DA_RESERVA,
                criado_em=agora,
                confirmado_em=None,
                motivo_da_alocacao=str(motivo),
            )
            session.add(agendamento)
            await session.flush()
    except IntegrityError as erro:
        if _e_sobreposicao(erro):
            return Conflito()
        raise
    return Reserva(agendamento.id, janela, agendamento.reservado_ate)


async def confirmar(
    session: AsyncSession, *, reserva_id: uuid.UUID, agora: datetime
) -> Confirmado | Expirado:
    """Confirma a reserva se ela ainda vale; senao `Expirado`, sem gravar nada.

    Um UPDATE so, com a condicao inteira no WHERE: nao ha janela entre ler
    "ainda vale" e gravar "confirmado" em que a reserva possa vencer ou ser
    atropelada. Vencida, ja confirmada, ja expirada ou inexistente -- as quatro
    viram `Expirado`, e quem chama oferece de novo.
    """
    resultado = await session.execute(
        update(Agendamento)
        .where(
            Agendamento.id == reserva_id,
            Agendamento.status == StatusDoAgendamento.RESERVADO,
            Agendamento.reservado_ate > agora,
        )
        .values(status=StatusDoAgendamento.CONFIRMADO, confirmado_em=agora)
        .returning(Agendamento.inicio, Agendamento.fim)
    )
    linha = resultado.first()
    if linha is None:
        return Expirado()
    return Confirmado(reserva_id, Intervalo(linha.inicio, linha.fim))


class AgendaPostgres:
    """A implementacao real de `AgendaDoCorretor` e `ContadorDeVisitas` (TEC-165, TEC-166).

    Abre a propria sessao: e porta de leitura, chamada pelo motor de janelas,
    e le so o que ja foi commitado -- que e o que importa para propor horario.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ocupados(
        self, corretor_id: uuid.UUID, de: datetime, ate: datetime
    ) -> list[Intervalo]:
        # Sobrepoe `[de, ate]`, e nao "contido nele": um compromisso que comecou
        # antes de `de` ainda ocupa. E as reservas contam so se ainda valem em
        # `de` -- a leitura e a outra metade da expiracao preguicosa.
        async with self._session_factory() as session:
            linhas = await session.execute(
                select(Agendamento.inicio, Agendamento.fim)
                .where(
                    Agendamento.corretor_id == corretor_id,
                    Agendamento.inicio < ate,
                    Agendamento.fim > de,
                    _ocupa_em(de),
                )
                .order_by(Agendamento.inicio)
            )
            return [Intervalo(inicio, fim) for inicio, fim in linhas.all()]

    async def visitas_por_dia(
        self, corretor_ids: Sequence[uuid.UUID], *, de: date, ate: date, agora: datetime
    ) -> dict[tuple[uuid.UUID, date], int]:
        # A data e a de `inicio` no fuso da imobiliaria, calculada no SQL: uma
        # visita as 23h30 de quinta em Sao Paulo ja e sexta em UTC, e conta
        # para quinta.
        if not corretor_ids:
            return {}
        data_local = cast(func.timezone(get_settings().followup_fuso, Agendamento.inicio), Date)
        # Subconsulta, e nao GROUP BY sobre `data_local` direto: cada uso da
        # expressao vira um bind parameter proprio (`$1`, `$2`), e o Postgres
        # nao reconhece `timezone($2, inicio)` no GROUP BY como a mesma
        # expressao de `timezone($1, inicio)` no SELECT.
        visitas = (
            select(Agendamento.corretor_id.label("corretor_id"), data_local.label("dia"))
            .where(
                Agendamento.corretor_id.in_(corretor_ids),
                Agendamento.tipo == TipoDeCompromisso.VISITA_PRESENCIAL,
                data_local >= de,
                data_local <= ate,
                _ocupa_em(agora),
            )
            .subquery()
        )
        async with self._session_factory() as session:
            linhas = await session.execute(
                select(visitas.c.corretor_id, visitas.c.dia, func.count()).group_by(
                    visitas.c.corretor_id, visitas.c.dia
                )
            )
            return {(corretor_id, dia): total for corretor_id, dia, total in linhas.all()}


async def reservar_ou_alternativas(
    session: AsyncSession,
    *,
    corretor: Corretor,
    agenda: AgendaDoCorretor,
    visitas: ContadorDeVisitas,
    channel: str,
    conversation_key: str,
    janela: Intervalo,
    tipo: TipoDeCompromisso,
    imovel_id: uuid.UUID | None,
    agora: datetime,
    ate: datetime,
    motivo: MotivoDaAlocacao,
) -> Reserva | list[Intervalo]:
    """A reserva, ou as janelas que sobraram -- nunca um erro tecnico.

    Em `Conflito` com escritor concorrente de OUTRA sessao, quem venceu ja
    commitou (foi o commit dele que fez esta gravacao ser recusada), entao a
    agenda que o motor le ja o enxerga e as alternativas nao incluem o
    horario perdido. Mas `AgendaPostgres` le so o que ja foi commitado: se o
    conflito for com uma reserva pendente da PROPRIA sessao de quem chama
    (reservar duas vezes na mesma transacao, antes do commit), a agenda ainda
    nao a enxerga, e as alternativas podem incluir o horario que acabou de
    perder. `ate` e o horizonte das alternativas e vem de quem chama, como no
    motor.

    As alternativas continuam no mesmo corretor (D7 da TEC-166): o conflito e
    sobre um slot dele, e realocar no meio da disputa trocaria o corretor sem
    que nada na alocacao tivesse mudado. **Mas respeitam a capacidade dele**
    (Important 1 da revisao final): para `VISITA_PRESENCIAL`, todo dia local
    em que `visitas` ja contar `capacidade_diaria` ou mais fica de fora das
    alternativas, mesmo sem nenhum compromisso que ocupe aquele horario
    especifico -- a exclusao do banco so impede sobreposicao de horario, ela
    nao impede excesso de reservas. Para `REUNIAO_REMOTA` o contador nem e
    chamado, o mesmo que D5 decide para `janelas_alocadas`.
    """
    resultado = await reservar(
        session,
        corretor_id=corretor.id,
        channel=channel,
        conversation_key=conversation_key,
        janela=janela,
        tipo=tipo,
        imovel_id=imovel_id,
        agora=agora,
        motivo=motivo,
    )
    if isinstance(resultado, Reserva):
        return resultado

    dias_lotados: set[date] = set()
    if tipo is TipoDeCompromisso.VISITA_PRESENCIAL:
        fuso = get_settings().fuso_de_envio
        contagem = await visitas.visitas_por_dia(
            [corretor.id],
            de=agora.astimezone(fuso).date(),
            ate=ate.astimezone(fuso).date(),
            agora=agora,
        )
        dias_lotados = {
            dia for (_, dia), total in contagem.items() if total >= corretor.capacidade_diaria
        }
    return await propor_janelas_do_corretor(
        corretor=corretor,
        agenda=agenda,
        agora=agora,
        ate=ate,
        tipo=tipo,
        dias_lotados=dias_lotados,
    )
