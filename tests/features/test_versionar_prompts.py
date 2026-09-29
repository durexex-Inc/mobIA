"""Criterios de aceite da TEC-199 como testes executaveis. RF-19, RN-19.4, CA-19.2.

Os quatro cenarios do Gherkin, contra banco e sem reiniciar nada: a versao e
publicada ou revertida pela rota e lida pelo proximo turno, no mesmo processo,
sem cache a invalidar (D5 do desenho). Mais as bordas das rotas, a trilha e o
recorte por papel.

A card fala em "qualificador" e "consultor"; os dois agentes versionados sao
`AGENTE` e `INVESTIDOR` (D1).
"""

import time
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agente.classificador import MODELO_DO_AGENTE, MODELO_DO_INVESTIDOR
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.vocabulario import Acao
from mobia.domain.prompts.modelo import AgenteDoPrompt
from mobia.domain.usuarios import tokens

ROTA = "/api/v1/prompts"


def _bearer(papel: str = "ADMIN", usuario: uuid.UUID | None = None) -> dict[str, str]:
    token = tokens.emitir(
        usuario or uuid.uuid4(),
        papel,
        mfa=papel == "ADMIN",
        corretor_id=None,
        settings=get_settings(),
    )
    return {"Authorization": f"Bearer {token}"}


def _versao_do_agente(n: int) -> str:
    """Um texto valido e distinto por numero: o padrao com uma frase trocada,
    do mesmo tamanho ou menor, para caber no teto da D3."""
    return MODELO_DO_AGENTE.replace("Nao negocie valor", f"Sem negociar v{n:02d}")


async def _publicar(
    client: AsyncClient, agente: str, texto: str, *, usuario: uuid.UUID | None = None
) -> dict[str, Any]:
    resposta = await client.post(
        f"{ROTA}/{agente}/versoes", json={"texto": texto}, headers=_bearer(usuario=usuario)
    )
    assert resposta.status_code == 201, resposta.text
    corpo: dict[str, Any] = resposta.json()
    return corpo


# --- os quatro cenarios do Gherkin ---------------------------------------------


async def test_publicar_sobre_a_versao_3_cria_a_4_com_autor_instante_e_diff(
    client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 1."""
    for n in (1, 2, 3):
        await _publicar(client, "AGENTE", _versao_do_agente(n))
    admin = uuid.uuid4()

    corpo = await _publicar(client, "AGENTE", _versao_do_agente(4), usuario=admin)

    assert corpo["publicada"] is True
    assert corpo["ativa"]["versao"] == 4
    assert corpo["ativa"]["publicadaPor"] == str(admin)
    versao = corpo["versao"]
    assert versao["versao"] == 4
    assert versao["anterior"] == 3
    assert versao["autor"] == str(admin)
    assert versao["em"]
    assert "--- agente v3" in versao["diff"]
    assert "+++ agente v4" in versao["diff"]
    assert "Sem negociar v03" in versao["diff"]
    assert "Sem negociar v04" in versao["diff"]


async def test_o_rollback_vale_no_turno_seguinte(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    rodar_turno: Any,
    classificador_fake: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
) -> None:
    """Cenario 2, CA-19.2: a versao ruim e revertida, e o proximo turno ja manda
    a anterior -- sem reiniciar nada. O limite de 30 s e folgado: o que vale e
    que a leitura acontece no turno, e nao num cache."""
    await _publicar(client, "AGENTE", _versao_do_agente(1))
    await _publicar(client, "AGENTE", _versao_do_agente(2))

    classificador = classificador_fake()
    vistos: list[str] = []
    original = classificador.classificar

    async def _guardando(contexto: Any, *, porta: Any = None) -> Any:
        vistos.append(contexto.prompts[AgenteDoPrompt.AGENTE])
        return await original(contexto, porta=porta)

    classificador.classificar = _guardando

    inicio = time.monotonic()
    resposta = await client.post(f"{ROTA}/AGENTE/rollback", json={"versao": 1}, headers=_bearer())
    assert resposta.status_code == 200, resposta.text
    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    assert time.monotonic() - inicio < 30
    assert vistos == [_versao_do_agente(1)]


async def test_o_rollback_do_agente_nao_mexe_no_investidor(
    client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 3."""
    await _publicar(client, "AGENTE", _versao_do_agente(1))
    await _publicar(client, "AGENTE", _versao_do_agente(2))
    investidor = MODELO_DO_INVESTIDOR.replace("nao negocie valor", "nao discuta valor")
    await _publicar(client, "INVESTIDOR", investidor)

    await client.post(f"{ROTA}/AGENTE/rollback", json={"versao": 1}, headers=_bearer())

    itens = {i["agente"]: i for i in (await client.get(ROTA, headers=_bearer())).json()["itens"]}
    assert itens["AGENTE"]["versao"] == 1
    assert itens["INVESTIDOR"]["versao"] == 1
    assert itens["INVESTIDOR"]["motivo"] == "PUBLICACAO"
    ativa = (await client.get(f"{ROTA}/INVESTIDOR", headers=_bearer())).json()["ativa"]
    assert ativa["texto"] == investidor


async def test_o_historico_traz_autor_momento_e_destino_do_rollback(
    client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 4."""
    await _publicar(client, "AGENTE", _versao_do_agente(1))
    await _publicar(client, "AGENTE", _versao_do_agente(2))
    quem_reverteu = uuid.uuid4()

    await client.post(
        f"{ROTA}/AGENTE/rollback", json={"versao": 1}, headers=_bearer(usuario=quem_reverteu)
    )

    itens = (await client.get(f"{ROTA}/AGENTE/historico", headers=_bearer())).json()["itens"]
    assert itens[0]["motivo"] == "ROLLBACK"
    assert itens[0]["versao"] == 1
    assert itens[0]["autor"] == str(quem_reverteu)
    assert itens[0]["em"]
    assert [i["motivo"] for i in itens[1:]] == ["PUBLICACAO", "PUBLICACAO"]
    # E a ativa se identifica com os dois: quem escreveu a 1, quem a reativou.
    ativa = (await client.get(f"{ROTA}/AGENTE", headers=_bearer())).json()["ativa"]
    assert ativa["versao"] == 1
    assert ativa["ativadaPor"] == str(quem_reverteu)
    assert ativa["publicadaPor"] != str(quem_reverteu)


# --- as bordas -----------------------------------------------------------------


async def test_sem_publicacao_vale_o_padrao(client: AsyncClient, banco_limpo: None) -> None:
    ativa = (await client.get(f"{ROTA}/AGENTE", headers=_bearer())).json()["ativa"]
    assert ativa["versao"] == 0
    assert ativa["padrao"] is True
    assert ativa["texto"] == MODELO_DO_AGENTE


async def test_rollback_para_0_volta_ao_padrao(client: AsyncClient, banco_limpo: None) -> None:
    await _publicar(client, "AGENTE", _versao_do_agente(1))

    resposta = await client.post(f"{ROTA}/AGENTE/rollback", json={"versao": 0}, headers=_bearer())

    assert resposta.status_code == 200, resposta.text
    ativa = (await client.get(f"{ROTA}/AGENTE", headers=_bearer())).json()["ativa"]
    assert ativa["versao"] == 0
    assert ativa["texto"] == MODELO_DO_AGENTE


async def test_rollback_traz_tempo_de_ativacao_nao_negativo(
    client: AsyncClient, banco_limpo: None
) -> None:
    """TEC-339, D1: o unico "tempo ate ativacao" que existe e quanto a propria
    chamada levou -- nao ha cache nem fila para propagar."""
    await _publicar(client, "AGENTE", _versao_do_agente(1))

    resposta = await client.post(f"{ROTA}/AGENTE/rollback", json={"versao": 0}, headers=_bearer())

    assert resposta.status_code == 200, resposta.text
    tempo = resposta.json()["tempoDeAtivacaoMs"]
    assert isinstance(tempo, int)
    assert tempo >= 0


async def test_rollback_recusado_nao_traz_tempo_de_ativacao(
    client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.post(f"{ROTA}/AGENTE/rollback", json={"versao": 7}, headers=_bearer())

    assert resposta.status_code == 404
    assert "tempoDeAtivacaoMs" not in resposta.json()


async def test_republicar_depois_do_rollback_compara_com_a_que_valia(
    client: AsyncClient, banco_limpo: None
) -> None:
    """A anterior de uma versao e a que VALIA, e nao `numero - 1` (D4)."""
    await _publicar(client, "AGENTE", _versao_do_agente(1))
    await _publicar(client, "AGENTE", _versao_do_agente(2))
    await client.post(f"{ROTA}/AGENTE/rollback", json={"versao": 1}, headers=_bearer())

    corpo = await _publicar(client, "AGENTE", _versao_do_agente(3))

    assert corpo["versao"]["versao"] == 3
    assert corpo["versao"]["anterior"] == 1


async def test_texto_igual_ao_vigente_nao_grava(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.post(
        f"{ROTA}/AGENTE/versoes", json={"texto": MODELO_DO_AGENTE}, headers=_bearer()
    )

    assert resposta.status_code == 200
    assert resposta.json()["publicada"] is False
    versoes = (await client.get(f"{ROTA}/AGENTE/versoes", headers=_bearer())).json()["itens"]
    assert versoes == []


async def test_sem_marcador_e_422_e_nada_muda(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.post(
        f"{ROTA}/AGENTE/versoes", json={"texto": "Seja breve {tom}."}, headers=_bearer()
    )

    assert resposta.status_code == 422
    assert "{assistente}" in resposta.json()["detail"]
    assert (await client.get(f"{ROTA}/AGENTE", headers=_bearer())).json()["ativa"]["versao"] == 0


async def test_rollback_para_versao_inexistente_e_404(
    client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.post(f"{ROTA}/AGENTE/rollback", json={"versao": 7}, headers=_bearer())
    assert resposta.status_code == 404


async def test_rollback_para_a_ativa_e_409(client: AsyncClient, banco_limpo: None) -> None:
    await _publicar(client, "AGENTE", _versao_do_agente(1))
    resposta = await client.post(f"{ROTA}/AGENTE/rollback", json={"versao": 1}, headers=_bearer())
    assert resposta.status_code == 409


async def test_a_versao_traz_o_texto_e_a_0_e_o_padrao(
    client: AsyncClient, banco_limpo: None
) -> None:
    await _publicar(client, "AGENTE", _versao_do_agente(1))

    um = (await client.get(f"{ROTA}/AGENTE/versoes/1", headers=_bearer())).json()
    zero = (await client.get(f"{ROTA}/AGENTE/versoes/0", headers=_bearer())).json()

    assert um["texto"] == _versao_do_agente(1)
    assert zero == {"versao": 0, "padrao": True, "texto": MODELO_DO_AGENTE}


async def test_publicacao_e_rollback_entram_na_trilha(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D7: uma linha cada, com o agente em `campo` e sem o texto."""
    await _publicar(client, "INVESTIDOR", MODELO_DO_INVESTIDOR.replace("Nao infira", "Nao chute"))
    await client.post(f"{ROTA}/INVESTIDOR/rollback", json={"versao": 0}, headers=_bearer())

    eventos = list(
        (
            await session.execute(
                select(EventoAuditoria).order_by(EventoAuditoria.criado_em, EventoAuditoria.id)
            )
        ).scalars()
    )
    assert [(e.acao, e.campo) for e in eventos] == [
        (Acao.PROMPT_PUBLICADO.value, "INVESTIDOR"),
        (Acao.PROMPT_REVERTIDO.value, "INVESTIDOR"),
    ]
    assert all(e.entidade == "configuracao_agente" for e in eventos)


async def test_gerente_nao_mexe_em_prompt(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.post(
        f"{ROTA}/AGENTE/rollback", json={"versao": 0}, headers=_bearer("GERENTE")
    )
    assert resposta.status_code == 403
