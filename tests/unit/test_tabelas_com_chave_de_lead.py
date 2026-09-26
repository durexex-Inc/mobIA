"""TEC-203, D3: toda tabela com `conversation_key` entra na reindexacao."""

import importlib
import pkgutil

import mobia.domain
from mobia.domain.identidade.reindexacao import TABELAS_COM_CHAVE_DE_LEAD
from mobia.domain.messages.models import Base


def _importar_todos_os_modelos() -> None:
    """Registra no `Base.metadata` todo modelo de `mobia.domain`.

    Nao ha modulo que importe todos: `alembic/env.py` importa quatro, e os
    outros entram no metadata so por quem os usa. Importar todo `models.py`
    do dominio e o que faz uma tabela nova, num pacote novo, cair nesta guarda
    sem ninguem lembrar de acrescenta-la a uma lista de imports.
    """
    for modulo in pkgutil.walk_packages(mobia.domain.__path__, "mobia.domain."):
        if modulo.name.rsplit(".", 1)[-1] == "models":
            importlib.import_module(modulo.name)


def test_toda_tabela_com_conversation_key_esta_na_lista() -> None:
    _importar_todos_os_modelos()
    com_chave = {t.name for t in Base.metadata.tables.values() if "conversation_key" in t.c}
    # `identidades_de_lead` tem `conversation_key` porque E a identidade: a
    # reindexacao a reescreve a parte (apaga e regrava), nao por UPDATE.
    assert com_chave - {"identidades_de_lead"} == set(TABELAS_COM_CHAVE_DE_LEAD)


def test_a_guarda_enxerga_os_modelos() -> None:
    """Sem isto, um `walk_packages` que nao achasse nada deixaria a guarda de
    cima comparando so o que ja estava importado por acaso."""
    _importar_todos_os_modelos()
    assert "vinculos_de_sessao" in Base.metadata.tables
    assert "agendamentos" in Base.metadata.tables
