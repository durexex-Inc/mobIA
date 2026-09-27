"""Cenarios Gherkin de TEC-381.

Funcionalidade: Pseudonimizacao antes do envio ao modelo

Ponta a ponta: a mensagem entra pelo webhook e `process_message` roda o turno
com dubles que GUARDAM o que receberiam. O que se afirma e o que o provedor
receberia -- o prompt que `montar_prompt` renderiza, que e o que o adaptador
real envia, e o texto que a moderacao de entrada receberia -- e, do outro lado,
que o banco continua com o original.
"""

import json
from typing import Any

from conftest import (
    ClassificadorFake,
    ContadorFake,
    ModeradorFake,
    ResumidorFake,
    pmid_do_whatsapp,
)
from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.context.montagem import montar_prompt
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.messages.models import Message
from mobia.domain.moderacao.port import Direcao
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.domain.privacidade.pseudonimo import MARCADOR_DE_NOME, MARCADOR_DE_TELEFONE
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker
from mobia.infra.signature import SIGNATURE_HEADER, compute_signature
from mobia.workers.jobs.process_message import process_message


class ClassificadorQueGuarda(ClassificadorFake):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.prompts: list[str] = []

    async def classificar(self, contexto, *, porta=None):
        # O mesmo `montar_prompt` que `ClassificadorAnthropic` chama: e o texto
        # que sairia para a Anthropic.
        self.prompts.append(montar_prompt(contexto, omitir_sistema=True))
        return await super().classificar(contexto, porta=porta)


class ModeradorQueGuarda(ModeradorFake):
    def __init__(self) -> None:
        super().__init__()
        self.textos_de_entrada: list[str] = []

    async def moderar(self, texto, *, direcao):
        if direcao == Direcao.ENTRADA:
            self.textos_de_entrada.append(texto)
        return await super().moderar(texto, direcao=direcao)


class WhatsAppQueRegistra:
    def __init__(self) -> None:
        self.envios: list[dict[str, Any]] = []

    async def send(self, message_id: Any, kind: str, payload: dict[str, Any]) -> bool:
        self.envios.append(payload)
        return True


def _envelope(provider_message_id: str, texto: str) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "111111111",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "222222222"},
                            "messages": [
                                {
                                    "from": "5511966667777",
                                    "id": provider_message_id,
                                    "timestamp": "1758700000",
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


async def _turno(client, session, settings, provider_message_id: str, texto: str, **fake: Any):
    body = json.dumps(_envelope(provider_message_id, texto)).encode("utf-8")
    headers = {
        SIGNATURE_HEADER: compute_signature(settings.whatsapp_app_secret, body),
        "Content-Type": "application/json",
    }
    assert (
        await client.post("/webhooks/whatsapp", content=body, headers=headers)
    ).status_code == 200
    procurado = pmid_do_whatsapp(provider_message_id)
    linha = (
        await session.execute(select(Message).where(Message.provider_message_id == procurado))
    ).scalar_one()

    classificador = ClassificadorQueGuarda(**fake)
    moderador = ModeradorQueGuarda()
    whatsapp = WhatsAppQueRegistra()
    ctx = {
        "session_factory": get_sessionmaker(),
        "outbound": whatsapp,
        "classificador": classificador,
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": moderador,
        "agendador": AgendadorNoop(),
        "agendador_de_avisos": AgendadorDeAvisosNoop(),
        "indicadores": {CANAL_WHATSAPP: IndicadorNoop()},
    }
    assert await process_message(ctx, str(linha.id)) == "respondido"
    return linha, classificador, moderador, whatsapp


async def test_nome_substituido_quando_o_prompt_nao_precisa_dele(client, session, settings) -> None:
    """Cenario: Nome substituido quando o prompt nao precisa dele.

    O lead se apresenta com nome completo. O prompt e a moderacao recebem o
    marcador; o banco, o nome.
    """
    texto = "Oi, me chamo Marina Souza e procuro um apartamento de 2 quartos"

    linha, classificador, moderador, whatsapp = await _turno(
        client,
        session,
        settings,
        "wamid.NOME1",
        texto,
    )

    [prompt] = classificador.prompts
    assert "Marina" not in prompt and "Souza" not in prompt
    assert f"me chamo {MARCADOR_DE_NOME}" in prompt
    assert all("Marina" not in enviado for enviado in moderador.textos_de_entrada)
    assert moderador.textos_de_entrada, "a moderacao de entrada tinha de ter rodado"

    assert decrypt(linha.text_body, aad_de(linha.id, "text_body")) == texto

    # A guarda de saida (o marcador copiado pelo modelo) mora no adaptador
    # real, que este duble substitui: quem a exercita e
    # `tests/unit/test_classificador.py`.
    assert len(whatsapp.envios) == 1


async def test_telefone_digitado_pelo_lead_nao_vai_ao_provedor(client, session, settings) -> None:
    """Cenario: Telefone digitado pelo lead nao vai ao provedor."""
    texto = "pode me ligar no (48) 99999-0000, quero ver casas no Campeche"

    linha, classificador, moderador, _ = await _turno(
        client, session, settings, "wamid.TEL1", texto
    )

    [prompt] = classificador.prompts
    assert "99999" not in prompt
    assert f"me ligar no {MARCADOR_DE_TELEFONE}, quero ver casas no Campeche" in prompt
    assert all("99999" not in enviado for enviado in moderador.textos_de_entrada)
    assert decrypt(linha.text_body, aad_de(linha.id, "text_body")) == texto
