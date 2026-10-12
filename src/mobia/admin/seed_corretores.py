"""Semente dos corretores de demonstracao.

Cria os corretores que hoje aparecem no painel "Corretores cadastrados" (o
perfil, na tabela `corretores`) e, para cada um, um usuario de login com papel
CORRETOR ligado ao perfil por `corretor_id`.

A senha dos corretores e a mesma dos admins: vem de `SEED_CORRETOR_SENHA` ou,
na ausencia dela, de `SEED_ADMIN_SENHA` -- de modo que "a senha deles e a mesma
do Eduardo e do Renato" sem o segredo precisar ser repetido no codigo.

Idempotente: um segundo `run` nao duplica nem o perfil (UNIQUE do e-mail) nem o
login; apenas completa o que faltar (por exemplo, criar o login de um corretor
cujo perfil ja existe).

Uso:
    python -m mobia.admin.seed_corretores              # perfis + logins
    python -m mobia.admin.seed_corretores --sem-login  # so os perfis
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.admin.usuarios import RecusaDeCadastro, criar_usuario
from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.repositorio import (
    DadosDoCorretor,
    EmailJaCadastrado,
    criar_corretor,
)
from mobia.domain.usuarios.models import Usuario
from mobia.infra.db import dispose_engine, get_sessionmaker

PAPEL_CORRETOR = "CORRETOR"

# Os corretores que hoje existem em producao. `ativo` nasce True no banco e nao
# e informado aqui (DadosDoCorretor nao carrega `id`, `ativo` nem carimbos).
CORRETORES: tuple[DadosDoCorretor, ...] = (
    DadosDoCorretor(
        nome="Francisca Rebeca Galvão",
        email="francisca.galvao@mobia.com",
        telefone="4829658789",
        creci="548365-F",
        especialidades=["COMPRA", "ALUGUEL"],
        regioes_atuacao=[
            "ingleses",
            "canasvieiras",
            "jurere",
            "sambaqui",
            "daniela",
            "praia do forte",
        ],
        horario_inicio=9,
        horario_fim=19,
        capacidade_diaria=8,
        plantao=False,
        gerente=False,
    ),
    DadosDoCorretor(
        nome="Lucas Juliio Marcos Nunes",
        email="lucas.nunes@mobia.com",
        telefone="4898756545",
        creci="548522-F",
        especialidades=["COMPRA", "ALUGUEL", "INVESTIMENTO"],
        regioes_atuacao=[
            "centro",
            "saco dos limoes",
            "agronomica",
            "trindade",
            "itacorubi",
            "joao paulo",
            "saco grande",
            "pantanal",
        ],
        horario_inicio=10,
        horario_fim=20,
        capacidade_diaria=5,
        plantao=False,
        gerente=False,
    ),
)


class FalhaDeSeed(RuntimeError):
    """A semente nao pode ser aplicada, e a mensagem diz por que."""


def _senha_dos_corretores() -> str:
    """A mesma senha dos admins (SEED_ADMIN_SENHA), salvo override explicito."""
    senha = os.environ.get("SEED_CORRETOR_SENHA") or os.environ.get(
        "SEED_ADMIN_SENHA", ""
    )
    if not senha:
        raise FalhaDeSeed(
            "defina SEED_ADMIN_SENHA (ou SEED_CORRETOR_SENHA) no ambiente para "
            "a senha dos corretores."
        )
    return senha


async def _semear_corretor(
    session: AsyncSession,
    dados: DadosDoCorretor,
    *,
    com_login: bool,
    senha: str,
) -> None:
    """Cria (ou completa) um corretor e seu login. Idempotente."""
    corretor = await session.scalar(
        select(Corretor).where(Corretor.email == dados.email)
    )
    if corretor is None:
        try:
            corretor = await criar_corretor(session, dados)
        except EmailJaCadastrado:
            # Corrida improvavel: outro processo criou entre o SELECT e o INSERT.
            corretor = await session.scalar(
                select(Corretor).where(Corretor.email == dados.email)
            )
    await session.flush()

    if com_login and corretor is not None:
        ja_tem_login = await session.scalar(
            select(Usuario.id).where(Usuario.email == dados.email)
        )
        if ja_tem_login is None:
            try:
                # Sem `com_mfa`: um CORRETOR entra so com a senha (o default de
                # `criar_usuario` so liga MFA para ADMIN).
                await criar_usuario(
                    session,
                    email=dados.email,
                    nome=dados.nome,
                    papel=PAPEL_CORRETOR,
                    senha_em_claro=senha,
                    corretor_id=corretor.id,
                )
            except RecusaDeCadastro as recusa:
                # "ja existe" e o caminho idempotente; o resto e erro de verdade.
                if "ja existe" not in str(recusa):
                    raise
    await session.commit()


async def _executar(args: argparse.Namespace) -> None:
    senha = "" if args.sem_login else _senha_dos_corretores()
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            for dados in CORRETORES:
                await _semear_corretor(
                    session, dados, com_login=not args.sem_login, senha=senha
                )
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Semente dos corretores de demonstracao (perfil + login CORRETOR)."
    )
    parser.add_argument(
        "--sem-login",
        action="store_true",
        help="cria so o perfil do corretor, sem o usuario de login",
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
