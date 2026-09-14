"""Pergunta de desambiguacao nao conta no teto. TEC-149, cenario 2, D6.

Esta garantia e ESTRUTURAL e nao condicional: a desambiguacao nao tem como
declarar pergunta, entao nao tem como incrementar o contador. O teste existe
para que a estrutura nao mude em silencio -- acrescentar `perguntou` a
`PerguntaDeDesambiguacao` faria o caminho de desambiguacao passar a gastar
orcamento do lead sem que uma linha de `turno.py` mudasse.
"""

import dataclasses

from mobia.domain.agente.schemas import PerguntaDeDesambiguacao


def test_a_desambiguacao_nao_declara_pergunta() -> None:
    campos = {campo.name for campo in dataclasses.fields(PerguntaDeDesambiguacao)}
    assert "perguntou" not in campos, (
        "PerguntaDeDesambiguacao ganhou `perguntou`: o caminho de "
        "desambiguacao passou a poder gastar o teto da RN-05.5, e o cenario 2 "
        "do Gherkin da TEC-149 deixou de valer por construcao. Decida em "
        "codigo se ele conta, em vez de deixar a estrutura decidir."
    )
