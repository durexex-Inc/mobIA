"""TEC-404, D1, D6 e D7: o admin troca o corretor, e o prazo recomeca.

Tambem as corridas da atribuicao com quem disputa a mesma linha -- o aceite do
dono anterior, a escalada e um `notificar` antigo em voo --, cada uma forcada
na ordem ruim em vez de esperada ao acaso.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update

from mobia.api.routes import handoffs as rota_de_handoffs
from mobia.domain.auditoria.vocabulario import Ator, AtorTipo
from mobia.domain.handoff.atribuicao import atribuir
from mobia.domain.handoff.escalada import escalar_vencidos
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.notificacao.envio import notificar
from tests.conftest import cabecalho_de

_ADMIN = Ator(AtorTipo.USUARIO, id=str(uuid.uuid4()))


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
    assert resposta.json() == {
        "status": Status.PENDENTE.value,
        "corretorId": str(a.id),
        "aceitoDesfeito": False,
    }
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


async def _atribuir_e_commitar(session_factory, *, handoff_id: uuid.UUID, corretor_id: uuid.UUID):
    async with session_factory() as outra:
        await atribuir(
            outra, handoff_id=handoff_id, corretor_id=corretor_id, ator=_ADMIN, origem=None
        )
        await outra.commit()


async def _acessos_negados(session: Any) -> int:
    return (
        await session.execute(
            text("SELECT count(*) FROM eventos_auditoria WHERE acao = 'ACESSO_NEGADO'")
        )
    ).scalar_one()


async def test_dono_anterior_nao_aceita_depois_da_atribuicao(
    client, session, semear_corretor, semear_handoff_com_resumo
) -> None:
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)
    await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(corretor_id=a.id))
    await session.commit()
    atribuicao = await client.post(
        f"/api/v1/handoffs/{handoff_id}/atribuir",
        json={"corretorId": str(b.id)},
        headers=cabecalho_de("ADMIN"),
    )
    assert atribuicao.status_code == 200, atribuicao.text

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar",
        headers=cabecalho_de("CORRETOR", corretor_id=a.id),
    )

    assert resposta.status_code == 403
    assert resposta.json()["detail"] == "forbidden"
    linha = await _linha(session, handoff_id)
    assert (linha.corretor_id, linha.status, linha.aceito_em) == (b.id, Status.PENDENTE, None)


async def test_atribuicao_entre_a_checagem_de_dono_e_o_aceite_vira_403(
    client, session, session_factory, semear_corretor, semear_handoff_com_resumo, monkeypatch
) -> None:
    """A corrida, na ordem ruim: `_exigir_dono_do` aprova A, a atribuicao a B
    commita, e SO DEPOIS o UPDATE do aceite roda. E o WHERE dele que tem de
    recusar -- a checagem anterior ja passou."""
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)
    await session.execute(update(Handoff).where(Handoff.id == handoff_id).values(corretor_id=a.id))
    await session.commit()

    original = rota_de_handoffs._exigir_dono_do

    async def _checa_e_entao_atribui(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        await _atribuir_e_commitar(session_factory, handoff_id=handoff_id, corretor_id=b.id)

    monkeypatch.setattr(rota_de_handoffs, "_exigir_dono_do", _checa_e_entao_atribui)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar",
        headers=cabecalho_de("CORRETOR", corretor_id=a.id),
    )

    assert resposta.status_code == 403
    assert resposta.json()["detail"] == "forbidden"
    linha = await _linha(session, handoff_id)
    assert (linha.corretor_id, linha.status, linha.aceito_em) == (b.id, Status.PENDENTE, None)
    assert await _acessos_negados(session) == 1


class _SessaoComGancho:
    """Repassa tudo a sessao real, mas roda `gancho` antes do SEGUNDO `execute`."""

    def __init__(self, sessao: Any, gancho: Any) -> None:
        self._sessao = sessao
        self._gancho = gancho
        self._chamadas = 0

    async def __aenter__(self) -> "_SessaoComGancho":
        await self._sessao.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._sessao.__aexit__(*exc)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        self._chamadas += 1
        if self._chamadas == 2:
            await self._gancho()
        return await self._sessao.execute(*args, **kwargs)

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._sessao, nome)


async def test_escalada_que_ja_tinha_selecionado_nao_escala_o_recem_atribuido(
    session, session_factory, semear_corretor, semear_handoff_com_resumo
) -> None:
    """`escalar_vencidos` seleciona o handoff vencido de A; a atribuicao a B
    commita antes do UPDATE dela. O UPDATE tem de ver o prazo zerado e nao
    escalar."""
    a = await semear_corretor(email="a@ex.com")
    b = await semear_corretor(email="b@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(corretor_id=a.id, sla_limite_em=datetime.now(UTC) - timedelta(minutes=5))
    )
    await session.commit()

    disparou = False

    async def _atribui_uma_vez() -> None:
        nonlocal disparou
        if not disparou:
            disparou = True
            await _atribuir_e_commitar(session_factory, handoff_id=handoff_id, corretor_id=b.id)

    fabrica: Any = lambda: _SessaoComGancho(session_factory(), _atribui_uma_vez)  # noqa: E731

    total = await escalar_vencidos(fabrica, canais=())

    assert disparou
    assert total == 0
    linha = await _linha(session, handoff_id)
    assert (linha.corretor_id, linha.status) == (b.id, Status.PENDENTE)


async def test_notificar_antigo_em_voo_nao_grava_por_cima_da_atribuicao(
    session, session_factory, semear_corretor, semear_handoff_com_resumo
) -> None:
    """O caso do portal: handoff sem dono, o `notificar` do nascimento escolheria
    o plantonista. A atribuicao a B segura a linha; o job tem de esperar e ler
    B, e nao gravar o plantonista e o prazo dele por cima."""
    await semear_corretor(email="plantao@ex.com", plantao=True)
    b = await semear_corretor(email="b@ex.com")
    handoff_id = await _handoff(semear_handoff_com_resumo)

    atribuindo = session_factory()
    await atribuir(atribuindo, handoff_id=handoff_id, corretor_id=b.id, ator=_ADMIN, origem=None)
    email = _CanalEspiao("email")
    job = asyncio.create_task(
        notificar(
            session_factory, canais=(email,), outbound=_OutboundFalso(), handoff_id=handoff_id
        )
    )
    try:
        await asyncio.sleep(1)
        assert not job.done(), "notificar devia esperar o lock da atribuicao"
        await atribuindo.commit()
    finally:
        await atribuindo.close()
    await job

    linha = await _linha(session, handoff_id)
    assert linha.corretor_id == b.id
    assert email.recebidas == [b.email]
    assert linha.sla_limite_em is not None
