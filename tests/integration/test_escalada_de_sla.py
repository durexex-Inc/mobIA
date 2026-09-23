"""A varredura que escala o handoff sem aceite dentro do prazo. TEC-178."""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import eventos_de_log  # type: ignore[import-not-found]
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.escalada import escalar_vencidos
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.notificacao.mensagem import Aviso


class _CanalEspiao:
    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.recebidas: list[tuple[str, str, str]] = []

    async def enviar(self, *, destino: str, aviso: Aviso) -> None:
        self.recebidas.append((destino, aviso.assunto, aviso.corpo))


async def _marcar_sla(
    session: AsyncSession, *, handoff_id: uuid.UUID, sla_limite_em: datetime | None
) -> None:
    await session.execute(
        update(Handoff).where(Handoff.id == handoff_id).values(sla_limite_em=sla_limite_em)
    )
    await session.commit()


async def _marcar_status(session: AsyncSession, *, handoff_id: uuid.UUID, status: Status) -> None:
    await session.execute(
        update(Handoff).where(Handoff.id == handoff_id).values(status=status.value)
    )
    await session.commit()


async def test_handoff_vencido_escala_e_tenta_avisar_o_gerente(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    await semear_corretor(email="gerente@x.com", gerente=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    await _marcar_sla(
        session, handoff_id=handoff_id, sla_limite_em=datetime.now(UTC) - timedelta(minutes=1)
    )
    email = _CanalEspiao("email")

    total = await escalar_vencidos(session_factory, canais=(email,))

    assert total == 1
    assert len(email.recebidas) == 1
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.status == Status.ESCALADO


async def test_handoff_dentro_do_prazo_nao_escala(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    await semear_corretor(email="gerente@x.com", gerente=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    await _marcar_sla(
        session, handoff_id=handoff_id, sla_limite_em=datetime.now(UTC) + timedelta(hours=1)
    )

    total = await escalar_vencidos(session_factory, canais=(_CanalEspiao("email"),))

    assert total == 0
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.status == Status.PENDENTE


async def test_handoff_ja_escalado_nao_escala_de_novo(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """A prova da D6: sem coluna "ja escalei", a linha some do conjunto sozinha
    porque a selecao filtra por `status = 'PENDENTE'`.
    """
    await semear_corretor(email="gerente@x.com", gerente=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    await _marcar_sla(
        session, handoff_id=handoff_id, sla_limite_em=datetime.now(UTC) - timedelta(minutes=1)
    )
    await _marcar_status(session, handoff_id=handoff_id, status=Status.ESCALADO)

    total = await escalar_vencidos(session_factory, canais=(_CanalEspiao("email"),))

    assert total == 0
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.status == Status.ESCALADO


async def test_handoff_com_sla_nulo_nao_e_tocado(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """`sla_limite_em` nulo significa "ainda nao notificado" ou "sem a quem
    cobrar" -- nunca "prazo zero". A varredura nao pode tratar isso como
    vencido.
    """
    await semear_corretor(email="gerente@x.com", gerente=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    total = await escalar_vencidos(session_factory, canais=(_CanalEspiao("email"),))

    assert total == 0
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.status == Status.PENDENTE
    assert linha.sla_limite_em is None


async def test_escalada_nao_vaza_o_resumo_no_log_nem_no_canal(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor, caplog
) -> None:
    """M9 da revisao final: o precedente e `test_resumir_loga_metricas_sem_conteudo`
    (`tests/unit/test_resumo.py`). Hoje `escalar_vencidos` nao decifra o
    resumo e o `corpo` da cobranca e texto fixo -- mas nada testado impede
    que a proxima mao acrescente o resumo ao corpo ou ao log da escalada.
    """
    texto_do_resumo_do_lead = "## Quem e o lead\nfulano de tal, cpf 000.000.000-00"
    await semear_corretor(email="gerente@x.com", gerente=True)
    handoff_id = await semear_handoff_com_resumo(resumo=texto_do_resumo_do_lead)
    await _marcar_sla(
        session, handoff_id=handoff_id, sla_limite_em=datetime.now(UTC) - timedelta(minutes=1)
    )
    email = _CanalEspiao("email")

    with caplog.at_level("INFO"):
        total = await escalar_vencidos(session_factory, canais=(email,))

    assert total == 1
    assert len(email.recebidas) == 1
    _, _, corpo = email.recebidas[0]
    assert "fulano" not in corpo
    assert "fulano" not in caplog.text


async def test_sem_gerente_cadastrado_escala_mesmo_assim_e_loga(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, caplog
) -> None:
    """A marcacao e o que importa; o aviso e so o que falta."""
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    await _marcar_sla(
        session, handoff_id=handoff_id, sla_limite_em=datetime.now(UTC) - timedelta(minutes=1)
    )

    with caplog.at_level("WARNING"):
        total = await escalar_vencidos(session_factory, canais=(_CanalEspiao("email"),))

    assert total == 1
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.status == Status.ESCALADO

    avisos = eventos_de_log(caplog, "handoff.escalado_sem_gerente")
    assert len(avisos) == 1
    assert avisos[0].corpo["handoff_id"] == str(handoff_id)
