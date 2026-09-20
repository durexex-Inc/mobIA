"""O que se pode logar de um erro de banco sem ecoar a linha que o causou.

Teste de integracao, e nao unitario, de proposito: o que se investiga aqui e a
FORMA da excecao que o asyncpg levanta e a SQLAlchemy embrulha. Duble nenhum
reproduz isso -- um `raise IntegrityError(...)` sintetico testaria a fixture,
nao o driver.
"""

import pytest
from sqlalchemy import text

from mobia.infra.db import get_engine, motivo_do_erro_de_banco

SENTINELA = "quero 2 quartos na zona sul"


async def _falhar(ddl_extra: str, params: dict) -> Exception:
    """Cria tabela temporaria, forca o INSERT a falhar e devolve a excecao."""
    conexao = await get_engine().connect()
    try:
        await conexao.execute(
            text(f"CREATE TEMP TABLE s (t varchar(8), c text, s int {ddl_extra})")
        )
        await conexao.execute(text("INSERT INTO s (t,c,s) VALUES ('a','ja existe',1)"))
        with pytest.raises(Exception) as capturada:
            await conexao.execute(text("INSERT INTO s (t,c,s) VALUES (:t,:c,:s)"), params)
        return capturada.value
    finally:
        await conexao.close()


async def test_violacao_de_check_nao_leva_a_linha_para_o_motivo() -> None:
    """O pior caso: o Postgres poe a LINHA INTEIRA no DETAIL.

    `Failing row contains (5511987654321, quero 2 quartos na zona sul, -1)` --
    e isso vem do servidor, entao o `hide_parameters=True` do cliente nao
    alcanca. As duas assertas importam: a primeira prova que o texto de fato
    carrega o sentinela, e sem ela a segunda seria asserta de ausencia sempre
    satisfeita (TEC-289).
    """
    exc = await _falhar(", CONSTRAINT ck_s CHECK (s >= 0)", {"t": "a", "c": SENTINELA, "s": -1})

    assert SENTINELA in str(exc), "o Postgres deixou de ecoar a linha; o teste perdeu o alvo"

    motivo = motivo_do_erro_de_banco(exc)
    assert motivo == "23514 table_name=s constraint_name=ck_s"
    assert SENTINELA not in motivo


async def test_violacao_de_unique_nomeia_a_constraint_sem_o_valor() -> None:
    exc = await _falhar(", CONSTRAINT uq_s UNIQUE (c)", {"t": "a", "c": "ja existe", "s": 1})

    assert "ja existe" in str(exc), "o Postgres deixou de ecoar o valor; o teste perdeu o alvo"
    assert motivo_do_erro_de_banco(exc) == "23505 table_name=s constraint_name=uq_s"


async def test_erro_sem_constraint_devolve_so_o_sqlstate() -> None:
    """`22001`, valor longo demais: nao ha constraint nem tabela a nomear."""
    exc = await _falhar("", {"t": "5511987654321", "c": SENTINELA, "s": 1})

    assert motivo_do_erro_de_banco(exc) == "22001"


def test_excecao_que_nao_e_de_banco_devolve_none() -> None:
    """Sem isso, o extrator poderia cair em algum ramo de melhor esforco -- que
    seria exatamente o buraco que ele existe para nao abrir.
    """
    assert motivo_do_erro_de_banco(ValueError("quero 2 quartos")) is None
