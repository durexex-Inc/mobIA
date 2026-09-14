"""O vocabulario da trilha do investidor. TEC-153, RN-05.2 e RN-07.2."""

import dataclasses

from mobia.domain.agente.investidor import (
    CAMPOS_DO_INVESTIDOR,
    ExtracaoDoInvestidor,
    Horizonte,
    PerfilInvestidor,
    RespostaDoInvestidor,
    RetornoEsperadoTipo,
)
from mobia.domain.agente.schemas import RespostaDoAgente


def test_o_horizonte_tem_as_tres_faixas_da_rn_05_2() -> None:
    assert [h.value for h in Horizonte] == ["CURTO", "MEDIO", "LONGO"]


def test_o_tipo_de_retorno_separa_renda_de_valorizacao() -> None:
    """E o campo que o percentual nao consegue ser: 8% ao ano descreve tanto
    aluguel quanto revenda."""
    assert [t.value for t in RetornoEsperadoTipo] == ["ALUGUEL", "REVENDA", "AMBOS"]


def test_o_perfil_tem_os_tres_da_rn_07_2() -> None:
    assert [p.value for p in PerfilInvestidor] == ["RENDA", "VALORIZACAO", "MISTO"]


def test_a_extracao_do_investidor_nasce_toda_vazia() -> None:
    """Campo ausente e o estado normal da qualificacao progressiva."""
    vazia = ExtracaoDoInvestidor()
    assert all(getattr(vazia, campo.name) is None for campo in dataclasses.fields(vazia))


def test_campos_do_investidor_acompanha_o_dataclass() -> None:
    """Pinado contra o dataclass, e nao escrito a mao: uma segunda lista de
    nomes divergiria em silencio, que e o defeito que a TEC-146 gastou uma
    card inteira consertando."""
    assert CAMPOS_DO_INVESTIDOR == {
        campo.name for campo in dataclasses.fields(ExtracaoDoInvestidor)
    }


def test_a_resposta_do_investidor_espelha_a_resposta_do_agente_mais_a_extracao() -> None:
    """RespostaDoInvestidor e o mesmo envelope de RespostaDoAgente -- o que
    `turno.py` e `record_agent_message` leem de uma chamada ao modelo -- mais
    o campo que so a trilha do investidor carrega. Pinado contra os dois
    dataclasses para que uma mudanca em RespostaDoAgente que ninguem espelhe
    aqui quebre este teste em vez do turno, no ramo do investidor."""
    campos_do_agente = {campo.name for campo in dataclasses.fields(RespostaDoAgente)}
    campos_do_investidor = {campo.name for campo in dataclasses.fields(RespostaDoInvestidor)}
    assert campos_do_investidor == campos_do_agente | {"investidor"}
