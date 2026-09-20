"""O `motivo_do_provedor` de embeddings tinha o nome do outro e garantia menor.

`infra/anthropic.py` extrai `status_code`, `error.type` e `error.message` do
corpo. `infra/embeddings.py` repassava `str(exc)[:300]` -- e o SDK da OpenAI
renderiza `str()` como `Error code: 400 - <corpo inteiro>`. O `input` daquela
chamada e o documento do imovel, montado a partir do arquivo importado.

Medido antes da TEC-292: o retorno era
`400: Error code: 400 - apartamento na Rua das Palmeiras com 3 quartos`.
"""

import httpx
from openai import APIConnectionError, BadRequestError

from mobia.infra.embeddings import motivo_do_provedor

SENTINELA = "apartamento na Rua das Palmeiras com 3 quartos"


def _erro_do_provedor(corpo: object) -> BadRequestError:
    """Um 400 do SDK cujo `str()` carrega o sentinela e cujo `body` nao."""
    requisicao = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    resposta = httpx.Response(400, request=requisicao)
    return BadRequestError(f"Error code: 400 - {SENTINELA}", response=resposta, body=corpo)


def test_o_texto_cru_do_sdk_nao_atravessa() -> None:
    """As duas assertas importam: a primeira prova que o `str()` do SDK de fato
    carrega o sentinela, e sem ela a segunda passaria mesmo que o SDK mudasse.
    """
    exc = _erro_do_provedor(
        {"error": {"type": "invalid_request_error", "message": "input is too long"}}
    )

    assert SENTINELA in str(exc), "o SDK mudou o render; o teste perdeu o alvo"

    motivo = motivo_do_provedor(exc)

    assert motivo == "400 invalid_request_error: input is too long"
    assert SENTINELA not in motivo


def test_sem_corpo_sobra_o_codigo_de_status() -> None:
    """Degradar para `400` e o comportamento certo: o codigo sozinho ja separa
    erro de conta de erro de contrato, que e o que a TEC-237 comprou.
    """
    exc = _erro_do_provedor(None)

    assert motivo_do_provedor(exc) == "400"
    assert SENTINELA not in motivo_do_provedor(exc)


def test_excecao_que_nao_e_de_status_nao_passa_nada() -> None:
    requisicao = httpx.Request("POST", "https://api.openai.com/v1/embeddings")

    assert motivo_do_provedor(APIConnectionError(request=requisicao)) is None
