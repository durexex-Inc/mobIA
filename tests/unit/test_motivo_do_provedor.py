"""A excecao estreita a regra de nunca logar `str(exc)` (TEC-237).

O incidente: em 28/08/2026 o gate pago falhou em 100% das chamadas -- 50 de 50
conversas e 41 de 41 casos de moderacao -- com `BadRequestError`, e o
diagnostico levou um dia por tres hipoteses erradas. A causa estava na primeira
linha do corpo de erro, que ninguem via porque so o nome da classe era
registrado.

Estes testes travam as duas metades da decisao: o corpo de erro do provedor
passa, e qualquer outra excecao nao passa.
"""

import httpx
import pytest
from anthropic import APIConnectionError, BadRequestError, RateLimitError

from mobia.infra.anthropic import MAX_CARACTERES_DO_MOTIVO, motivo_do_provedor

FALA_DO_LEAD = "quero um apartamento de 3 quartos na zona sul ate 600 mil"


def _erro_do_provedor(status: int, corpo: object, *, request_id: str | None = None):
    """Um erro de status do SDK montado a mao, sem chamada paga.

    O criterio de aceite do card pede exatamente isto: o formato do motivo nao
    pode depender de reproduzir o incidente contra a API de verdade.
    """
    requisicao = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    cabecalhos = {"request-id": request_id} if request_id else {}
    resposta = httpx.Response(status, request=requisicao, headers=cabecalhos)
    classe = BadRequestError if status == 400 else RateLimitError
    return classe("erro", response=resposta, body=corpo)


def test_o_caso_que_originou_o_card_fica_diagnosticavel():
    """Saldo esgotado volta como 400, o mesmo codigo de um erro de contrato.

    Sem a mensagem nao ha como separar "a conta acabou" de "o schema quebrou",
    e foi essa ambiguidade que custou o dia de diagnostico.
    """
    exc = _erro_do_provedor(
        400,
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": (
                    "Your credit balance is too low to access the Anthropic API. "
                    "Please go to Plans & Billing to upgrade or purchase credits."
                ),
            },
        },
    )

    motivo = motivo_do_provedor(exc)

    assert motivo is not None
    assert "400" in motivo
    assert "invalid_request_error" in motivo
    # A palavra que resolve o incidente sem reproduzir nada.
    assert "credit balance is too low" in motivo


def test_excecao_que_nao_e_do_provedor_nao_produz_texto_nenhum():
    """A garantia da TEC-134, que este card nao pode afrouxar.

    `KeyError`/`TypeError` de um schema inesperado ecoam o valor recebido na
    mensagem, e esse valor pode ser a fala do lead. A guarda nao e filtrar o
    texto: e nao ter ramo nenhum para excecao que nao seja do protocolo.
    """
    for exc in (
        KeyError(FALA_DO_LEAD),
        TypeError(FALA_DO_LEAD),
        ValueError(FALA_DO_LEAD),
        RuntimeError(FALA_DO_LEAD),
        Exception(FALA_DO_LEAD),
    ):
        assert motivo_do_provedor(exc) is None, f"{type(exc).__name__} vazou texto"


def test_erro_de_conexao_do_sdk_tambem_nao_passa():
    """`APIConnectionError` e do SDK mas nao carrega corpo do servidor.

    Ele nao e `APIStatusError` -- nao houve resposta HTTP --, entao nao ha
    corpo gerado pelo servidor para citar. A distincao do card e essa, e nao
    "veio do SDK".
    """
    requisicao = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    assert motivo_do_provedor(APIConnectionError(request=requisicao)) is None


def test_request_id_entra_para_a_proxima_investigacao():
    """Handle de correlacao com o suporte do provedor, sem conteudo nenhum."""
    exc = _erro_do_provedor(
        429,
        {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
        request_id="req_011CTabc",
    )
    assert "request_id=req_011CTabc" in (motivo_do_provedor(exc) or "")


def test_mensagem_longa_e_cortada():
    """Log estruturado nao e lugar de despejo, e o teto tambem estreita o
    risco de um corpo de erro que cite mais do que devia."""
    exc = _erro_do_provedor(
        400, {"type": "error", "error": {"type": "invalid_request_error", "message": "x" * 5000}}
    )

    motivo = motivo_do_provedor(exc) or ""

    assert motivo.endswith("...")
    assert "x" * (MAX_CARACTERES_DO_MOTIVO + 1) not in motivo


@pytest.mark.parametrize(
    "corpo",
    [
        None,
        "corpo que nao e dict",
        {},
        {"error": None},
        {"error": "nao e dict"},
        {"type": "error"},
        {"error": {}},
        {"error": {"type": 123, "message": ["nao", "e", "string"]}},
    ],
)
def test_corpo_fora_do_formato_nao_derruba_o_caminho_de_erro(corpo):
    """Esta funcao roda **dentro** de um `except`. Se ela levantar, troca uma
    falha diagnosticavel por um traceback sem relacao com a causa -- que e o
    oposto do que o card pede. No pior caso ela devolve so o status.
    """
    motivo = motivo_do_provedor(_erro_do_provedor(400, corpo))

    assert motivo is not None
    assert motivo.startswith("400")
