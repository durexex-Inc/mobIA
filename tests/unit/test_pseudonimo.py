"""TEC-381: nome e telefone do lead nao saem para o provedor."""

import uuid

import pytest

from mobia.domain.agente.delimitacao import delimitar
from mobia.domain.context.montagem import _texto_da
from mobia.domain.messages.enums import MessageContentType, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.privacidade.pseudonimo import (
    MARCADOR_DE_NOME,
    MARCADOR_DE_TELEFONE,
    pseudonimizar,
    sem_marcadores,
)
from mobia.infra.crypto import aad_de, encrypt

N = MARCADOR_DE_NOME
T = MARCADOR_DE_TELEFONE


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("meu número é (48) 99999-0000", f"meu número é {T}"),
        ("liga no 48 9 9999 0000 por favor", f"liga no {T} por favor"),
        ("+55 11 98888-7777", T),
        (
            "o meu é 11987654321 e o da minha esposa 11912345678",
            f"o meu é {T} e o da minha esposa {T}",
        ),
        ("fixo: (21) 3333-4444", f"fixo: {T}"),
    ],
)
def test_telefone_vira_marcador(texto: str, esperado: str) -> None:
    assert pseudonimizar(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "até 500.000 reais",
        "protocolo 2026092712345678",
        "CPF 01234567890",
        "apartamento 1203, bloco 2",
        "quero 3 quartos entre 400 e 600 mil",
    ],
)
def test_numero_que_nao_e_telefone_passa(texto: str) -> None:
    assert pseudonimizar(texto) == texto


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Oi, me chamo Marina Souza e procuro casa", f"Oi, me chamo {N} e procuro casa"),
        ("meu nome é marina", f"meu nome é {N}"),
        ("Meu nome completo é Ana Maria da Silva", f"Meu nome completo é {N}"),
        ("sou a Clara, do anúncio", f"sou a {N}, do anúncio"),
        ("Aqui é o João Pedro", f"Aqui é o {N}"),
        ("quem fala é a Beatriz dos Santos Lima", f"quem fala é a {N}"),
        ("me chamo Marina, meu número é 48999990000", f"me chamo {N}, meu número é {T}"),
    ],
)
def test_nome_anunciado_vira_marcador(texto: str, esperado: str) -> None:
    assert pseudonimizar(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "sou o dono do apartamento",
        "sou a pessoa que ligou ontem",
        "aqui é o bairro que eu quero",
        "Marina aqui, tudo bem?",  # nome solto: limite declarado (D3)
        "quero morar na Vila Mariana",
    ],
)
def test_sem_anuncio_explicito_nada_muda(texto: str) -> None:
    assert pseudonimizar(texto) == texto


@pytest.mark.parametrize("texto", [N, T, f"me chamo {N}, meu número é {T}"])
def test_pseudonimizar_de_novo_nao_muda(texto: str) -> None:
    """O resumo e gerado das literais ja pseudonimizadas e volta ao prompt."""
    assert pseudonimizar(texto) == texto


@pytest.mark.parametrize(
    ("fala", "limpa"),
    [
        (f"Oi, {N}! Tudo bem?", "Oi! Tudo bem?"),
        (f"Obrigado, {N}.", "Obrigado."),
        (f"{N}, encontrei três opções.", "encontrei três opções."),
        (f"Vou passar o {T} ao corretor.", "Vou passar o seu telefone ao corretor."),
        ("Encontrei três opções.", "Encontrei três opções."),
    ],
)
def test_marcador_copiado_pelo_modelo_nao_chega_ao_lead(fala: str, limpa: str) -> None:
    assert sem_marcadores(fala) == limpa


def _linha(role, texto: str):
    identificador = uuid.uuid4()
    return Message(
        id=identificador,
        role=role,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
    )


def test_o_contexto_leva_a_fala_do_lead_pseudonimizada() -> None:
    linha = _linha(MessageRole.LEAD, "me chamo Marina, meu número é 48999990000")

    assert _texto_da(linha) == "[LEAD] " + delimitar(f"me chamo {N}, meu número é {T}")


def test_a_fala_do_corretor_nao_e_pseudonimizada() -> None:
    """O nome na fala do corretor e o dele (D1), e o agente precisa dele para
    dizer quem vai atender."""
    linha = _linha(MessageRole.CORRETOR, "Oi! Aqui é o João, vou te ajudar")

    assert _texto_da(linha) == "[CORRETOR] Oi! Aqui é o João, vou te ajudar"
