"""TEC-203: toda coluna LargeBinary cifrada esta no `recifrar`, ou declara por que nao."""

import importlib
import pkgutil

from sqlalchemy import LargeBinary

import mobia.domain
from mobia.admin.recifrar import COLUNAS_CIFRADAS
from mobia.domain.messages.models import Base

# LargeBinary que NAO e cifrado. Cada entrada diz por que.
NAO_CIFRADAS = {
    # O arquivo de importacao do catalogo (planilha), dado publico do imovel.
    ("importacoes", "arquivo"),
}


def _importar_todos_os_modelos() -> None:
    """Registra no `Base.metadata` todo modelo de `mobia.domain`.

    Mesma tecnica de `tests/unit/test_tabelas_com_chave_de_lead.py`: nao ha
    modulo que importe todos os `models.py` do dominio, entao uma tabela nova
    so cai nesta guarda se a importacao for varrida por `pkgutil`.
    """
    for modulo in pkgutil.walk_packages(mobia.domain.__path__, "mobia.domain."):
        if modulo.name.rsplit(".", 1)[-1] == "models":
            importlib.import_module(modulo.name)


def test_toda_coluna_binaria_esta_coberta() -> None:
    _importar_todos_os_modelos()
    binarias = {
        (t.name, c.name)
        for t in Base.metadata.tables.values()
        for c in t.c
        if isinstance(c.type, LargeBinary)
    }
    cobertas = {(c.tabela, c.coluna) for c in COLUNAS_CIFRADAS}
    assert binarias == cobertas | NAO_CIFRADAS
