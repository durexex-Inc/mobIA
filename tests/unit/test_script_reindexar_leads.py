"""Os avisos de `scripts/reindexar_leads.py`. TEC-203.

O script roda uma vez, em janela de manutencao, e o que ele imprime e tudo o
que o operador ve. Um par pulado ou uma chave anterior errada que so
aparecesse no log estruturado passariam em branco.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from mobia.domain.identidade.reindexacao import Reindexacao

CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "reindexar_leads.py"


def _script() -> ModuleType:
    especificacao = importlib.util.spec_from_file_location("_reindexar_leads", CAMINHO)
    assert especificacao is not None and especificacao.loader is not None
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def test_sem_nada_estranho_nao_ha_aviso() -> None:
    resultado = Reindexacao(mudados=3, sem_identidade=0, lead_refs_recalculados=0)
    assert _script().avisos(anterior="a", atual="a", resultado=resultado) == []


def test_par_sem_identidade_vira_aviso_com_a_contagem() -> None:
    resultado = Reindexacao(mudados=3, sem_identidade=2, lead_refs_recalculados=0)
    (aviso,) = _script().avisos(anterior="a", atual="a", resultado=resultado)
    assert "2 par(es) sem identidade" in aviso


def test_chave_anterior_que_nao_casou_nada_vira_aviso() -> None:
    resultado = Reindexacao(mudados=0, sem_identidade=0, lead_refs_recalculados=0)
    (aviso,) = _script().avisos(anterior="velha", atual="nova", resultado=resultado)
    assert "AUDITORIA_CHAVE_DO_LEAD_ANTERIOR" in aviso


def test_chave_anterior_que_casou_nao_avisa() -> None:
    resultado = Reindexacao(mudados=0, sem_identidade=0, lead_refs_recalculados=5)
    assert _script().avisos(anterior="velha", atual="nova", resultado=resultado) == []
