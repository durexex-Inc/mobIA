"""Carrega o catalogo de imoveis a partir de um arquivo CSV ou JSON.

TEC-156, RN-08.1. Mesmo molde de `admin/reativar.py`: `main` sincrono chamando
`asyncio.run`, e a logica async num `_importar` separado -- um teste async nao
pode chamar `main` de dentro de um loop ja rodando ("cannot be called from a
running event loop").

**Nao enfileira.** Processa no proprio processo, ao contrario do endpoint
HTTP. O quarto cenario Gherkin diz "executado em base vazia", e um seed que
exige Redis e worker no ar nao serve a esse cenario -- nem a quem acabou de
clonar o repositorio. As duas entradas chamam a mesma `importacao.executar`.

**Sai com 0 mesmo havendo rejeicoes.** O primeiro cenario Gherkin exige que
3 linhas ruins terminem "com sucesso": rejeicao e resultado esperado da
RN-08.5, nao falha do processo. `--falhar-se-rejeitar` inverte isso para quem
quiser o seed dentro de um pipeline que deva parar.

Uso:
    python -m mobia.admin.seed_catalogo
    python -m mobia.admin.seed_catalogo --arquivo /caminho/base.csv
    python -m mobia.admin.seed_catalogo --arquivo base.csv --falhar-se-rejeitar
"""

import argparse
import asyncio
import sys
from pathlib import Path

from mobia.domain.catalogo.enums import OrigemImportacao
from mobia.domain.catalogo.importacao import executar, registrar
from mobia.domain.catalogo.schemas import Relatorio
from mobia.infra.db import get_sessionmaker

ARQUIVO_PADRAO = Path(__file__).resolve().parents[3] / "data" / "seed" / "imoveis.csv"


async def _importar(*, arquivo: Path, origem: OrigemImportacao) -> Relatorio:
    """A logica async, separada de `main` para o teste chamar direto."""
    sessionmaker = get_sessionmaker()
    conteudo = arquivo.read_bytes()
    async with sessionmaker() as session:
        importacao_id = await registrar(
            session, origem=origem, nome_arquivo=arquivo.name, conteudo=conteudo
        )
        await session.commit()
    return await executar(sessionmaker, importacao_id=importacao_id)


def _imprimir(relatorio: Relatorio) -> None:
    print(f"processados : {relatorio.processados}")
    print(f"inseridos   : {relatorio.inseridos}")
    print(f"atualizados : {relatorio.atualizados}")
    print(f"inalterados : {relatorio.inalterados}")
    print(f"rejeitados  : {relatorio.rejeitados}")
    if relatorio.erros:
        print("\nrejeicoes:")
        for erro in relatorio.erros:
            print(f"  linha {erro.linha}: {erro.motivo}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Carrega o catalogo de imoveis a partir de um arquivo."
    )
    parser.add_argument(
        "--arquivo",
        type=Path,
        default=ARQUIVO_PADRAO,
        help=f"CSV ou JSON a importar (padrao: {ARQUIVO_PADRAO})",
    )
    parser.add_argument(
        "--falhar-se-rejeitar",
        action="store_true",
        help="sai com 1 se houver qualquer rejeicao (para uso em pipeline)",
    )
    args = parser.parse_args(argv)

    if not args.arquivo.is_file():
        print(f"arquivo nao encontrado: {args.arquivo}", file=sys.stderr)
        return 2

    relatorio = asyncio.run(_importar(arquivo=args.arquivo, origem=OrigemImportacao.CLI))
    _imprimir(relatorio)

    if args.falhar_se_rejeitar and relatorio.rejeitados:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
