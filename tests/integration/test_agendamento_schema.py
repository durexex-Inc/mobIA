"""A garantia de nao sobreposicao, testada no banco. TEC-168, RT-07.

Os inserts aqui sao SQL cru de proposito: o cenario da card diz que a
segunda gravacao e recusada pela constraint, e so um insert que nao passa
pelo repositorio prova que a garantia e do banco e nao do codigo.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mobia.domain.agendamento.models import EXCLUSAO_DE_SOBREPOSICAO

SP = ZoneInfo("America/Sao_Paulo")


def _qui(hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 8, 27, hora, minuto, tzinfo=SP)


async def _inserir(session, *, corretor_id, inicio, fim, status="CONFIRMADO") -> None:
    await session.execute(
        text(
            "INSERT INTO agendamentos (id, corretor_id, channel, conversation_key, imovel_id,"
            " tipo, inicio, fim, status, reservado_ate, criado_em, confirmado_em,"
            " motivo_da_alocacao)"
            " VALUES (:id, :corretor_id, 'whatsapp', :chave, NULL, 'VISITA_PRESENCIAL',"
            " :inicio, :fim, :status, :inicio, :inicio, NULL, 'MATCH_EXATO')"
        ),
        {
            "id": uuid.uuid4(),
            "corretor_id": corretor_id,
            "chave": str(uuid.uuid4())[:20],
            "inicio": inicio,
            "fim": fim,
            "status": status,
        },
    )
    await session.commit()


async def test_sobreposicao_e_barrada_pelo_banco(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))
    with pytest.raises(IntegrityError) as erro:
        await _inserir(session, corretor_id=corretor.id, inicio=_qui(10, 30), fim=_qui(11, 30))
    assert EXCLUSAO_DE_SOBREPOSICAO in str(erro.value)


async def test_horarios_que_encostam_convivem(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(11), fim=_qui(12))


async def test_corretores_diferentes_no_mesmo_horario_convivem(session, semear_corretor) -> None:
    paulo = await semear_corretor(email="paulo@teste.com")
    ana = await semear_corretor(email="ana@teste.com")
    await _inserir(session, corretor_id=paulo.id, inicio=_qui(10), fim=_qui(11))
    await _inserir(session, corretor_id=ana.id, inicio=_qui(10), fim=_qui(11))


async def test_expirado_nao_entra_na_exclusao(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(
        session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11), status="EXPIRADO"
    )
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))


async def test_reservado_entra_na_exclusao(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(
        session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11), status="RESERVADO"
    )
    with pytest.raises(IntegrityError):
        await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))


@pytest.mark.parametrize("status", ["CANCELADO", "REAGENDADO", "REALIZADO", "NO_SHOW"])
async def test_os_status_do_ciclo_nao_entram_na_exclusao(
    session, semear_corretor, status: str
) -> None:
    """TEC-172, D2: e isto que "libera o slot" quer dizer.

    A CA-12.2 pede que o horario volte ao pool em menos de 10 segundos depois
    do cancelamento, e o que existe e o tempo de um UPDATE: o WHERE da
    `ex_agendamentos_sem_sobreposicao` e allowlist de RESERVADO e CONFIRMADO,
    entao qualquer um dos quatro status do ciclo tira a linha do indice no
    mesmo statement.

    **Este teste prova isso contra o BANCO, com insert cru**, e nao contra o
    modelo -- a constraint nao e declarada no `Agendamento` (ver a docstring
    dele). Se alguem "consertar" aquele WHERE para incluir os status novos,
    e aqui que aparece.
    """
    corretor = await semear_corretor(email="paulo@teste.com")
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11), status=status)
    await _inserir(session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11))


async def test_status_fora_do_vocabulario_e_recusado(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    with pytest.raises(IntegrityError):
        await _inserir(
            session, corretor_id=corretor.id, inicio=_qui(10), fim=_qui(11), status="PENDENTE"
        )


async def test_intervalo_invertido_e_recusado(session, semear_corretor) -> None:
    corretor = await semear_corretor(email="paulo@teste.com")
    with pytest.raises(IntegrityError):
        await _inserir(session, corretor_id=corretor.id, inicio=_qui(11), fim=_qui(10))
