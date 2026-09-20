"""O `TRUNCATE` de `banco_limpo` tem teto de espera e diz quem o bloqueou.

Estes testes cobrem a fixture, e nao codigo de producao. Existem porque o
`lock_timeout` sozinho passaria sem o diagnostico: quem remover o `except` que
consulta `pg_locks` continuaria tendo um teto funcionando e uma mensagem que
manda o leitor rodar tudo de novo -- que e o custo que a TEC-291 veio cortar.

**Nao usam a fixture `banco_limpo` para a parte bloqueadora.** Bloquear o
`TRUNCATE` que a propria fixture roda no setup seria travar o teste antes de
ele comecar -- exatamente o sintoma que se quer reproduzir, no lugar errado.
Cada teste monta as suas duas conexoes e desfaz as duas no `finally`.
"""

import pytest
from conftest import (
    _ESPERA_MAXIMA_PELO_LOCK,
    _comando_de_truncate,
    _quem_segura_o_lock,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

# Bem abaixo do teto de producao da fixture: o teste precisa do estouro, e nao
# de esperar os 10s reais por ele. O que se afirma aqui e a forma da mensagem,
# nao a grandeza do teto -- essa e escolha registrada em `conftest.py`.
_TETO_CURTO = "300ms"


async def test_o_truncate_bloqueado_estoura_em_vez_de_esperar_para_sempre(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as bloqueadora:
        # `ACCESS SHARE` -- o lock mais fraco que existe, tomado por um SELECT
        # qualquer. E o ponto: nao e preciso um escritor para pendurar a suite.
        await bloqueadora.execute(text("SELECT count(*) FROM imoveis"))
        try:
            async with session_factory() as truncadora:
                await truncadora.execute(text(f"SET LOCAL lock_timeout = '{_TETO_CURTO}'"))
                with pytest.raises(Exception) as capturado:
                    await truncadora.execute(text(await _comando_de_truncate(truncadora)))
                assert getattr(capturado.value.orig, "sqlstate", None) == "55P03"
                await truncadora.rollback()
        finally:
            await bloqueadora.rollback()


async def test_o_diagnostico_nomeia_o_backend_que_segura_o_lock(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as bloqueadora:
        await bloqueadora.execute(text("SELECT count(*) FROM imoveis"))
        pid_bloqueador = await bloqueadora.scalar(text("SELECT pg_backend_pid()"))
        try:
            async with session_factory() as perguntando:
                descricao = await _quem_segura_o_lock(perguntando)
        finally:
            await bloqueadora.rollback()

    assert f"pid {pid_bloqueador}" in descricao, descricao
    # Sem o estado e a idade, o leitor sabe que alguem segura e nao sabe se e um
    # teste vivo ou uma transacao esquecida -- que e a pergunta que decide o caso.
    assert "idle in transaction" in descricao, descricao
    assert "transacao aberta ha" in descricao, descricao


async def test_o_diagnostico_ignora_quem_nao_toca_as_tabelas_da_suite(
    session_factory: async_sessionmaker,
) -> None:
    """Uma conexao aberta que nao travou tabela nenhuma nao pode virar suspeita.

    Se qualquer backend vivo aparecesse na lista, a mensagem apontaria para os
    proprios vizinhos do xdist em toda execucao paralela, e quem lesse aprenderia
    a ignora-la.
    """
    async with session_factory() as inocente:
        await inocente.execute(text("SELECT 1"))
        pid_inocente = await inocente.scalar(text("SELECT pg_backend_pid()"))
        try:
            async with session_factory() as perguntando:
                descricao = await _quem_segura_o_lock(perguntando)
        finally:
            await inocente.rollback()

    assert f"pid {pid_inocente}" not in descricao, descricao


async def test_sem_bloqueador_o_diagnostico_diz_isso_em_vez_de_ficar_mudo(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as perguntando:
        descricao = await _quem_segura_o_lock(perguntando)
    assert "nenhum backend segura lock agora" in descricao, descricao


def test_o_teto_da_fixture_nao_e_zero() -> None:
    """Zero, em `lock_timeout`, significa "espere para sempre" -- o estado antigo.

    A guarda existe porque a troca e muda: quem escrever `'0'` para "desligar o
    teto num diagnostico" nao ve erro nenhum, ve a suite voltar a pendurar.
    """
    assert _ESPERA_MAXIMA_PELO_LOCK not in ("0", "0s", "")
