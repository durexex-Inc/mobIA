"""Semente de producao: o admin inicial e o catalogo, sem terminal.

**Existe para o deploy.** `scripts/criar_usuario.py` pede a senha em dois
prompts de terminal -- certo para quem opera a mao, inutil num `heroku run` de
uma linha. Aqui o admin vem de variavel de ambiente (`SEED_ADMIN_*`), o
catalogo do CSV versionado, e o processo e IDEMPOTENTE: rodar de novo nao
duplica nem falha. A logica de cada parte continua em `mobia.admin.usuarios`
(admin) e `mobia.admin.seed_catalogo` (catalogo); este modulo so as junta e as
torna repetiveis.

O admin:
    SEED_ADMIN_EMAIL   -- obrigatorio.
    SEED_ADMIN_SENHA   -- obrigatorio; pelo menos 12 caracteres.
    SEED_ADMIN_NOME    -- opcional (padrao "Administrador").

**ADMIN nasce com MFA sempre** (regra da TEC-201). Quando o usuario e criado,
o script imprime UMA VEZ a URI `otpauth://` -- ela leva a semente do segundo
fator em claro. Cadastre-a no aplicativo autenticador e nao a deixe em log.
Se o admin ja existir, o script diz isso e nao imprime nada: a semente so
aparece no nascimento.

O catalogo (`data/seed/imoveis.csv`) e carregado so quando a tabela de imoveis
esta VAZIA, para nao reprocessar a cada deploy. `--sem-catalogo` pula essa
etapa; `--catalogo <arquivo>` troca o CSV padrao; `--forcar-catalogo` importa
mesmo com a base ja povoada (a importacao e upsert, entao nao duplica).

Codigos de saida: `0` tudo certo (admin criado ou ja existia), `1` erro.

Uso:
    python -m mobia.admin.seed_producao
    python -m mobia.admin.seed_producao --sem-catalogo
    python -m mobia.admin.seed_producao --catalogo data/seed/imoveis.csv
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import func, select

from mobia.admin.seed_catalogo import ARQUIVO_PADRAO, _importar
from mobia.admin.usuarios import RecusaDeCadastro, criar_usuario
from mobia.domain.catalogo.enums import OrigemImportacao, StatusImportacao
from mobia.domain.catalogo.models import Imovel
from mobia.infra.db import dispose_engine, get_sessionmaker


class FalhaDeSeed(RuntimeError):
    """A semente nao pode ser aplicada, e a mensagem diz por que."""


async def _semear_admin() -> None:
    """Cria o admin de `SEED_ADMIN_*`, ou informa que ja existe. Idempotente."""
    email = os.environ.get("SEED_ADMIN_EMAIL", "").strip()
    senha = os.environ.get("SEED_ADMIN_SENHA", "")
    nome = os.environ.get("SEED_ADMIN_NOME", "").strip() or "Administrador"
    if not email or not senha:
        raise FalhaDeSeed(
            "defina SEED_ADMIN_EMAIL e SEED_ADMIN_SENHA no ambiente para criar o admin."
        )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            criado = await criar_usuario(
                session,
                email=email,
                nome=nome,
                papel="ADMIN",
                senha_em_claro=senha,
            )
            await session.commit()
        except RecusaDeCadastro as recusa:
            # "ja existe usuario com o e-mail ..." e o caminho idempotente: um
            # segundo deploy nao deve falhar so porque o admin ja nasceu. As
            # demais recusas (senha curta, papel) sao erro de configuracao e
            # sobem como falha.
            if "ja existe" in str(recusa):
                print(f"admin ja existe: {email} (nada a fazer)")
                return
            raise FalhaDeSeed(str(recusa)) from recusa

    print(f"admin criado: {email}")
    if criado.uri_do_totp:
        print("\n>>> CADASTRE NO APLICATIVO AUTENTICADOR (a URI leva a semente em claro):")
        print(criado.uri_do_totp)
        print(">>> Ela NAO sera mostrada de novo.\n")


async def _catalogo_vazio() -> bool:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        total = await session.scalar(select(func.count()).select_from(Imovel))
    return not total


async def _semear_catalogo(*, arquivo: Path, forcar: bool) -> None:
    if not arquivo.is_file():
        raise FalhaDeSeed(f"arquivo de catalogo nao encontrado: {arquivo}")
    if not forcar and not await _catalogo_vazio():
        print("catalogo ja povoado (pulado; use --forcar-catalogo para reimportar)")
        return

    relatorio = await _importar(arquivo=arquivo, origem=OrigemImportacao.CLI)
    print(
        "catalogo: "
        f"status={relatorio.status} processados={relatorio.processados} "
        f"inseridos={relatorio.inseridos} atualizados={relatorio.atualizados} "
        f"rejeitados={relatorio.rejeitados}"
    )
    if relatorio.status is StatusImportacao.FALHOU:
        motivos = "; ".join(e.motivo for e in relatorio.erros if e.linha == 0)
        raise FalhaDeSeed(f"importacao do catalogo falhou: {motivos or 'sem detalhe'}")


async def _executar(args: argparse.Namespace) -> None:
    try:
        await _semear_admin()
        if not args.sem_catalogo:
            await _semear_catalogo(arquivo=args.catalogo, forcar=args.forcar_catalogo)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semente de producao: admin inicial e catalogo.")
    parser.add_argument(
        "--catalogo",
        type=Path,
        default=ARQUIVO_PADRAO,
        help=f"CSV ou JSON do catalogo (padrao: {ARQUIVO_PADRAO})",
    )
    parser.add_argument(
        "--sem-catalogo", action="store_true", help="cria so o admin, sem tocar no catalogo"
    )
    parser.add_argument(
        "--forcar-catalogo",
        action="store_true",
        help="importa o catalogo mesmo com a base ja povoada (upsert, nao duplica)",
    )
    args = parser.parse_args(argv)

    try:
        asyncio.run(_executar(args))
    except FalhaDeSeed as falha:
        print(f"seed nao aplicada: {falha}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
