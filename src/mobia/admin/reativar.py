"""Devolve um lead que pediu opt-out ao estado respondivel.

Script, e nao endpoint HTTP, porque este projeto nao tem camada de
autenticacao: existe uma rota (o webhook, autenticado por HMAC da Meta) e nada
mais -- JWT, OIDC e papeis sao a TEC-201. Um endpoint sem autenticacao que
reverte protecao de LGPD e pior que nao ter reativacao nenhuma.

Quem consegue rodar isto ja tem acesso ao servidor e ao banco, e isso E a
autenticacao. A logica mora em `optout.repositorio.reativar`; quando o
dashboard existir (TEC-189) ele chama a mesma funcao.

Uso:
    python -m mobia.admin.reativar --channel wa --key 5548999998888 \\
        --autor "Paulo M." --motivo "lead pediu por telefone"
"""

import argparse
import asyncio
import sys

from mobia.domain.optout.repositorio import reativar
from mobia.infra.db import get_sessionmaker


async def _executar(*, channel: str, key: str, autor: str, motivo: str) -> int:
    """A logica async, separada de `main` para o teste chamar direto.

    `main` chama `asyncio.run`, e um teste async ja roda dentro de um loop --
    chamar `main` de dentro dele estoura "cannot be called from a running
    event loop". O teste da logica chama esta funcao com `await`; so o teste
    do argumento obrigatorio ausente, que nem chega a tocar o loop, continua
    chamando `main`.
    """
    await reativar(
        get_sessionmaker(),
        channel=channel,
        conversation_key=key,
        autor=autor,
        motivo=motivo,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reativa um lead que pediu opt-out.")
    parser.add_argument("--channel", required=True, help="canal do lead, por exemplo wa")
    parser.add_argument("--key", required=True, help="conversation_key do lead")
    parser.add_argument("--autor", required=True, help="quem esta reativando")
    # Obrigatorio, e sem default: a RN-14.3 exige justificativa, e um default
    # vazio a tornaria decorativa.
    parser.add_argument("--motivo", required=True, help="por que o lead volta a receber")
    args = parser.parse_args(argv)

    return asyncio.run(
        _executar(channel=args.channel, key=args.key, autor=args.autor, motivo=args.motivo)
    )


if __name__ == "__main__":
    sys.exit(main())
