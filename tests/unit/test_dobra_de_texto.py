"""A dobra de texto que a busca estruturada compara.

TEC-158, D6. Basename distinto de tudo em `tests/integration/`.
"""

from mobia.domain.agente.schemas import normalizar_regiao
from mobia.domain.texto import dobrar


def test_dobra_caixa_e_acento() -> None:
    assert dobrar("Aclimação") == "aclimacao"
    assert dobrar("Vila Madalena") == "vila madalena"
    assert dobrar("SÃO PAULO") == "sao paulo"


def test_dobra_e_idempotente() -> None:
    uma_vez = dobrar("Aclimação")
    assert dobrar(uma_vez) == uma_vez


def test_dobra_colapsa_espaco_interno() -> None:
    # Um arquivo com dois espacos nao pode deixar a linha inalcancavel.
    assert dobrar("  Vila   Madalena  ") == "vila madalena"


def test_a_dobra_nao_come_prefixo_de_referencia() -> None:
    """A diferenca entre `dobrar` e `normalizar_regiao`, afirmada.

    `estacao ` e `avenida ` sao ruido de FALA. Aplicados a nome de bairro
    comeriam o nome de um bairro chamado "Estacao" -- por isso a dobra
    compartilhada nao os toca, e so `normalizar_regiao` os remove.
    """
    assert dobrar("Estação Vila Madalena") == "estacao vila madalena"
    assert normalizar_regiao("estacao vila madalena") == "vila madalena"


def test_normalizar_regiao_continua_dobrando() -> None:
    """A composicao nao pode ter perdido a dobra pelo caminho."""
    assert normalizar_regiao("perto da Aclimação") == "aclimacao"
