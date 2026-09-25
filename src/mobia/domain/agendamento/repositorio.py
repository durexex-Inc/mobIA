"""Reservar, confirmar e ler a agenda do corretor. TEC-168, RN-11.4, RT-07.

Recebe a sessao e **nao commita** -- o commit e de quem chama, como em
`registrar_handoff` e `criar_corretor`. A exclusao por intervalo e do banco
(migration 0044); este modulo so traduz a recusa dele em `Conflito` e faz a
expiracao preguicosa que o banco nao consegue fazer sozinho (D3 do desenho).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agendamento.janelas import Intervalo, TipoDeCompromisso
from mobia.domain.agendamento.models import (
    EXCLUSAO_DE_SOBREPOSICAO,
    Agendamento,
    StatusDoAgendamento,
)

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


def _e_sobreposicao(exc: IntegrityError) -> bool:
    """Distingue a recusa da exclusao de qualquer outra falha de integridade.

    Mesma forma de `_e_email_duplicado` (`corretores/repositorio.py`): pelo
    NOME da constraint, com o texto como fallback para driver que nao expoe
    `constraint_name`. Tratar todo IntegrityError como conflito esconderia
    um CHECK violado atras de "horario ocupado".
    """
    original = exc.orig
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
) -> Reserva | Conflito:
    """Reserva `janela` por `DURACAO_DA_RESERVA`, ou devolve `Conflito`.

    Antes de inserir, marca EXPIRADO as reservas vencidas **deste corretor**
    que sobrepoem a janela: a constraint nao olha o relogio, e sem isso uma
    reserva morta barraria o lugar para sempre.

    **Em `Conflito`, so o SAVEPOINT desta chamada volta.** Um `session.rollback()`
    de sessao inteira expira TODO objeto carregado na sessao -- inclusive o
    `Corretor` que quem chama ja tinha em maos --, e o acesso sincrono a um
    atributo expirado fora de contexto async explode com `MissingGreenlet`
    (visto em `test_sessao_continua_utilizavel_depois_do_conflito`). Por isso
    o UPDATE de expiracao e o INSERT entram num `session.begin_nested()`: em
    conflito, so o que esta chamada tentou e desfeito -- o resto da sessao,
    inclusive escrita pendente anterior de quem chama, continua de pe.
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
    """A implementacao real de `AgendaDoCorretor` (TEC-165).

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
                    or_(
                        Agendamento.status == StatusDoAgendamento.CONFIRMADO,
                        and_(
                            Agendamento.status == StatusDoAgendamento.RESERVADO,
                            Agendamento.reservado_ate > de,
                        ),
                    ),
                )
                .order_by(Agendamento.inicio)
            )
            return [Intervalo(inicio, fim) for inicio, fim in linhas.all()]
