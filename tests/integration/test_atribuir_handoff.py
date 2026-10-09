"""TEC-404, D1, D6 e D7: o admin troca o corretor, e o prazo recomeca."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update

from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.notificacao.envio import notificar
from tests.conftest import cabecalho_de


async def _handoff(semear_handoff_com_resumo) -> uuid.UUID:
    return await semear_handoff_com_resumo(resumo="texto")


async def _linha(session: Any, handoff_id: uuid.UUID) -> Handoff:
    # `populate_existing`, e nao `expire_all()`: expirar tudo expiraria tambem
    # os `Corretor` semeados, e ler `a.id` depois dispararia um refresh
    # sincrono -- `MissingGreenlet` numa sessao async.
    consulta = (
        select(Handoff).where(Handoff.id == handoff_id).execution_options(populate_existing=True)
    )
    return (await session.execute(consulta)).scalar_one()


async def _jobs(redis_pool) -> list[bytes]:
    return list(await redis_pool.keys("arq:job:notificar:*"))


async def _eventos_de_atribuicao(session: Any) -> int:
    return (
        await session.execute(
            text("SELECT count(*) FROM eventos_auditoria WHERE acao = 'HANDOFF_ATRIBUIDO'")
        )
    ).scalar_one()


async def test_atribui_handoff_sem_corretor(
    client, session, semear_corretor, semear_handoff_com_resumo, redis_pool
) -> None:
    handoff_id = await _handoff(semear_handoff_com_resumo)
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(corretor_id=None, aviso_manual_pendente=True, status=Status.ESCALADO.value)
    )
    await session.commit()
    a = await semear_corretor(email="a@ex.com")

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {
        "status": Status.PENDENTE.value,
        "corretorId": str(a.id),
        "aceitoDesfeito": False,
    }
    linha = await _linha(session, handoff_id)
    assert linha.corretor_id == a.id
    assert linha.status == Status.PENDENTE
    assert linha.aviso_manual_pendente is False
    assert linha.sla_limite_em is None
    assert linha.notificado_em is None
    assert any(b":atribuicao:" in k for k in await _jobs(redis_pool))


async def test_aceito_por_a_passa_para_b_e_a_trilha_registra(
    client, session, semear_corretor, semear_handoff_com_resumo
) -> None:
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)
    agora = datetime.now(UTC)
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(
            corretor_id=a.id,
            status=Status.ACEITO.value,
            aceito_em=agora,
            notificado_em=agora,
            sla_limite_em=agora + timedelta(hours=4),
        )
    )
    await session.commit()

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(b.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["aceitoDesfeito"] is True
    linha = await _linha(session, handoff_id)
    assert (linha.corretor_id, linha.status, linha.aceito_em) == (b.id, Status.PENDENTE, None)
    assert (linha.sla_limite_em, linha.notificado_em) == (None, None)
    evento = (
        (
            await session.execute(
                text("SELECT detalhes FROM eventos_auditoria WHERE acao = 'HANDOFF_ATRIBUIDO'")
            )
        )
        .mappings()
        .one()
    )
    assert evento["detalhes"] == {
        "corretor_anterior": str(a.id),
        "corretor_novo": str(b.id),
        "aceito_desfeito": "sim",
    }


async def test_mesmo_corretor_em_pendente_nao_faz_nada(
    client, session, semear_corretor, semear_handoff_com_resumo, redis_pool
) -> None:
    a = await semear_corretor(email="a@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)
    await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(corretor_id=a.id))
    await session.commit()
    antes = await _jobs(redis_pool)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["aceitoDesfeito"] is False
    assert await _jobs(redis_pool) == antes
    assert await _eventos_de_atribuicao(session) == 0


async def test_mesmo_corretor_em_aceito_desfaz_o_aceite(
    client, session, semear_corretor, semear_handoff_com_resumo, redis_pool
) -> None:
    """D7 so poupa o PENDENTE: o mesmo dono num ACEITO volta a pendente dele."""
    a = await semear_corretor(email="a@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)
    agora = datetime.now(UTC)
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(corretor_id=a.id, status=Status.ACEITO.value, aceito_em=agora)
    )
    await session.commit()

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["aceitoDesfeito"] is True
    linha = await _linha(session, handoff_id)
    assert (linha.status, linha.aceito_em) == (Status.PENDENTE, None)
    assert await _eventos_de_atribuicao(session) == 1
    assert any(b":atribuicao:" in k for k in await _jobs(redis_pool))


async def test_corretor_inativo_e_422_e_nada_muda(
    client, session, semear_corretor, semear_handoff_com_resumo
) -> None:
    inativo = await semear_corretor(email="i@ex.com", ativo=False)
    handoff_id = await _handoff(semear_handoff_com_resumo)
    antes = (await _linha(session, handoff_id)).corretor_id
    # Devolve a conexao ao pool antes da rota: com ela presa aqui, a rota
    # abriria uma conexao nova, e cada connect novo e uma chance a mais do
    # `[WinError 64]` desta maquina (ver o CLAUDE.md).
    await session.commit()

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(inativo.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 422
    assert (await _linha(session, handoff_id)).corretor_id == antes
    assert await _eventos_de_atribuicao(session) == 0


async def test_corretor_inexistente_e_422(client, session, semear_handoff_com_resumo) -> None:
    handoff_id = await _handoff(semear_handoff_com_resumo)
    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(uuid.uuid4())},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 422


async def test_concluido_e_409(client, session, semear_corretor, semear_handoff_com_resumo) -> None:
    a = await semear_corretor(email="a@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)
    await session.execute(
        update(Handoff).where(Handoff.id == handoff_id).values(status=Status.CONCLUIDO.value)
    )
    await session.commit()

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )

    assert resposta.status_code == 409
    assert (await _linha(session, handoff_id)).status == Status.CONCLUIDO


async def test_inexistente_e_404(client, semear_corretor) -> None:
    a = await semear_corretor(email="a@ex.com")
    resposta = await client.post(
        f"/api/v1/handoffs/{uuid.uuid4()}/atribuir",
        json={"corretorId": str(a.id)},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 404


async def test_corretor_e_gerente_nao_atribuem(
    client, session, semear_corretor, semear_handoff_com_resumo
) -> None:
    a = await semear_corretor(email="a@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)
    for papel in ("CORRETOR", "GERENTE"):
        resposta = await client.post(
            f"/api/v1/handoffs/{handoff_id}/atribuir",
            json={"corretorId": str(a.id)},
            headers=cabecalho_de(papel, corretor_id=a.id if papel == "CORRETOR" else None),
        )
        assert resposta.status_code == 403
    assert (await _linha(session, handoff_id)).corretor_id != a.id


class _CanalEspiao:
    """Copia do duble de `test_notificacao_envio.py` -- sem importar de outro teste."""

    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.recebidas: list[str] = []

    async def enviar(self, *, destino: str, aviso: Any) -> None:
        self.recebidas.append(destino)


class _OutboundFalso:
    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        return True


# Os mesmos dois candidatos de `_CANDIDATOS_DE_JANELA` em
# `test_notificacao_envio.py`, ~12h opostos e nenhum cruzando a meia-noite. A
# jornada de B e a que fica mais longe de AGORA, escolhida pela mesma regra de
# la (maior folga ciclica); a de A e a outra. Como o prazo sempre cai dentro da
# jornada de quem o conta (`limite_de_aceite`), e as duas jornadas nao se
# encostam, um prazo contado pela jornada de A nunca caberia na de B -- seja
# qual for a hora em que a suite roda.
_CANDIDATOS_DE_JANELA: tuple[tuple[int, int], ...] = ((2, 9), (14, 21))


def _folga_em_minutos(momento_min: int, inicio_hora: int, fim_hora: int) -> int:
    """Copia de `test_notificacao_envio.py`: distancia ciclica ate a janela, -1 dentro dela."""
    inicio_min = inicio_hora * 60
    fim_min = fim_hora * 60
    if inicio_min <= momento_min <= fim_min:
        return -1
    ida = (inicio_min - momento_min) % 1440
    volta = (momento_min - fim_min) % 1440
    return min(ida, volta)


async def test_a_notificacao_seguinte_conta_o_prazo_pela_jornada_do_novo(
    client, session, session_factory, semear_corretor, semear_handoff_com_resumo, settings
) -> None:
    """D1: o prazo recomeca pela jornada de B, e nao pela de A."""
    fuso = settings.fuso_de_envio
    agora = datetime.now(UTC).astimezone(fuso)
    momento_min = agora.hour * 60 + agora.minute
    fora = max(_CANDIDATOS_DE_JANELA, key=lambda janela: _folga_em_minutos(momento_min, *janela))
    (dentro,) = (janela for janela in _CANDIDATOS_DE_JANELA if janela != fora)
    a = await semear_corretor(email="a@ex.com", horario_inicio=dentro[0], horario_fim=dentro[1])
    b = await semear_corretor(email="b@ex.com", horario_inicio=fora[0], horario_fim=fora[1])
    handoff_id = await _handoff(semear_handoff_com_resumo)
    await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(corretor_id=a.id))
    await session.commit()

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(b.id)},
        headers=cabecalho_de("ADMIN"),
    )
    assert resposta.status_code == 200, resposta.text

    # O que o worker faria com o job enfileirado.
    email = _CanalEspiao("email")
    await notificar(
        session_factory, canais=(email,), outbound=_OutboundFalso(), handoff_id=handoff_id
    )

    linha = await _linha(session, handoff_id)
    assert linha.corretor_id == b.id
    assert email.recebidas == [b.email]
    assert linha.sla_limite_em is not None
    limite = linha.sla_limite_em.astimezone(fuso)
    assert fora[0] <= limite.hour <= fora[1]
