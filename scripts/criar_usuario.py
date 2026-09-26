"""Cria um usuario do dashboard. TEC-309, D8 -- a logica esta em `mobia.admin.usuarios`.

A senha e pedida pelo terminal, duas vezes, e **nunca por argumento**:
argumento de linha de comando fica no historico do shell e aparece na lista de
processos de quem estiver na mesma maquina.

Para ADMIN (ou com `--mfa`) o script imprime a URI `otpauth://` que o
aplicativo autenticador le. **Ela leva a semente do segundo fator em claro**:
entregue-a so a quem vai usar a conta, e nao a deixe num log.

Uso:
    ./.venv/Scripts/python.exe scripts/criar_usuario.py --email ana@x.com --nome "Ana" --papel ADMIN
    ./.venv/Scripts/python.exe scripts/criar_usuario.py --email paulo@x.com --nome "Paulo" \\
        --papel CORRETOR --corretor-id <uuid>
"""

import argparse
import asyncio
import getpass
import sys
import uuid

from mobia.admin.usuarios import RecusaDeCadastro, criar_usuario
from mobia.infra.db import dispose_engine, get_sessionmaker


def _pedir_senha() -> str:
    primeira = getpass.getpass("Senha: ")
    if getpass.getpass("Repita a senha: ") != primeira:
        raise RecusaDeCadastro("as duas senhas nao conferem.")
    return primeira


async def _executar(args: argparse.Namespace, senha_em_claro: str) -> int:
    try:
        async with get_sessionmaker()() as session:
            criado = await criar_usuario(
                session,
                email=args.email,
                nome=args.nome,
                papel=args.papel,
                senha_em_claro=senha_em_claro,
                corretor_id=args.corretor_id,
                com_mfa=args.mfa,
            )
            await session.commit()
    finally:
        await dispose_engine()

    print(f"usuario criado: {criado.usuario_id}")
    if criado.uri_do_totp:
        print("\nCadastre no aplicativo autenticador (leva a semente em claro):")
        print(criado.uri_do_totp)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cria um usuario do dashboard.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--nome", required=True)
    parser.add_argument("--papel", required=True, help="ADMIN, GERENTE, CORRETOR ou LEITURA")
    parser.add_argument("--corretor-id", type=uuid.UUID, default=None)
    parser.add_argument(
        "--mfa", action="store_true", help="liga o TOTP num papel que nao o exige (ADMIN ja exige)"
    )
    args = parser.parse_args(argv)

    try:
        return asyncio.run(_executar(args, _pedir_senha()))
    except RecusaDeCadastro as recusa:
        print(f"nao criado: {recusa}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
