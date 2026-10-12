"""A 0072 da fala aos pedidos do portal gravados antes dela.

Basename distinto de tudo em `tests/unit/`.
"""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text


async def test_a_0072_grava_a_fala_dos_pedidos_antigos_uma_vez_so(session: Any) -> None:
    imovel = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO imoveis (id, codigo, titulo, descricao, tipo, operacao, preco_venda, "
            "bairro, bairro_busca, cidade, uf, zona, area_util_m2, quartos, suites, banheiros, "
            "vagas, caracteristicas, fotos, status) VALUES (:id, :cod, 't', 'd', 'APARTAMENTO', "
            "'VENDA', 1, 'b', 'b', 'c', 'SP', 'SUL', 1, 1, 1, 1, 1, '{}', '{}', 'DISPONIVEL')"
        ),
        {"id": imovel, "cod": f"AP-{uuid.uuid4().hex[:8]}"},
    )
    antigo = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO solicitacoes_de_interesse (id, imovel_id, channel, conversation_key, "
            "criado_em) VALUES (:id, :imovel, 'portal', 'chave-antiga', :quando)"
        ),
        {"id": antigo, "imovel": imovel, "quando": datetime(2026, 10, 1, tzinfo=UTC)},
    )
    await session.commit()

    caminho = Path(__file__).parents[2] / "alembic/versions/0072_pedido_do_portal_vira_fala.py"
    spec = importlib.util.spec_from_file_location("m0072", caminho)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    def _rodar() -> None:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        conexao = session.sync_session.connection()
        with Operations.context(MigrationContext.configure(conexao)):
            modulo.upgrade()

    await session.run_sync(lambda _: _rodar())
    await session.run_sync(lambda _: _rodar())  # idempotente
    await session.commit()

    falas = (
        (
            await session.execute(
                text("SELECT provider_message_id, created_at, status FROM messages")
            )
        )
        .mappings()
        .all()
    )
    assert len(falas) == 1
    assert falas[0]["provider_message_id"] == f"interesse:{antigo}"
    assert falas[0]["created_at"] == datetime(2026, 10, 1, tzinfo=UTC)
    assert falas[0]["status"] is None
