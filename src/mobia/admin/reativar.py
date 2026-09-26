"""Devolve um lead que pediu opt-out ao estado respondivel.

Script, e nao endpoint HTTP, porque este projeto nao tem camada de
autenticacao: existe uma rota (o webhook, autenticado por HMAC da Meta) e nada
mais -- JWT, OIDC e papeis sao a TEC-201. Um endpoint sem autenticacao que
reverte protecao de LGPD e pior que nao ter reativacao nenhuma.

Quem consegue rodar isto ja tem acesso ao servidor e ao banco, e isso E a
autenticacao. A logica mora em `optout.repositorio.reativar`; quando o
dashboard existir (TEC-189) ele chama a mesma funcao.

**`--key` e o valor cru desde a TEC-203** (telefone no WhatsApp, sessao no
web), e nao mais o `conversation_key`: quem opera nao tem como digitar um HMAC
que nunca viu. `_chave_do_lead` acha a chave antes de chamar `reativar` -- e
so aceita chave que TEM identidade. A chave calculada sobre o que o operador
digitou pode nao ser a de lead nenhum (canal escrito errado, o numero com o 9
que o `wa_id` nao tem); gravar mesmo assim poria na trilha de LGPD a
reativacao de um lead inexistente, com o de verdade ainda em opt-out. Sem
identidade, o script recusa e nao grava nada.

Uso:
    python -m mobia.admin.reativar --channel whatsapp --key "+55 48 99999-8888" \\
        --autor "Paulo M." --motivo "lead pediu por telefone"
"""

import argparse
import asyncio
import re
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.identidade.indice import chave_de
from mobia.domain.identidade.models import IdentidadeDeLead
from mobia.domain.identidade.telefone import grafias_do_wa_id, normalizar
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.optout.repositorio import reativar
from mobia.infra.db import get_sessionmaker


def _candidatos(channel: str, key: str) -> list[str]:
    """Os valores crus que `key` pode ser, o mais literal primeiro.

    No WhatsApp: os digitos como vieram (o `wa_id` exato, se o operador o
    copiou) e depois as grafias do numero normalizado, com e sem o 9. No web:
    a sessao na forma que o widget grava (`str(uuid.UUID(...))`). Canal
    desconhecido nao tem candidato nenhum.
    """
    if channel == CANAL_WHATSAPP:
        digitos = re.sub(r"\D", "", key)
        canonico = normalizar(key)
        grafias = grafias_do_wa_id(canonico) if canonico else ()
        return list(dict.fromkeys([digitos, *grafias]))
    if channel == CANAL_WEB:
        try:
            return [str(uuid.UUID(key.strip()))]
        except ValueError:
            return [key.strip()]
    return []


async def _chave_do_lead(session: AsyncSession, channel: str, key: str) -> str | None:
    """A chave do lead que `key` identifica, ou `None` se nenhum.

    A grafia exata ganha. Sem ela, se as duas grafias do numero tiverem
    identidade -- duas conversas, uma com e outra sem o 9 --, nao ha como
    escolher, e o resultado tambem e `None`: o operador passa o `wa_id` exato.
    """
    candidatos = [chave_de(channel, valor) for valor in _candidatos(channel, key)]
    if not candidatos:
        return None
    existentes = set(
        (
            await session.scalars(
                select(IdentidadeDeLead.conversation_key).where(
                    IdentidadeDeLead.channel == channel,
                    IdentidadeDeLead.conversation_key.in_(candidatos),
                )
            )
        ).all()
    )
    if candidatos[0] in existentes:
        return candidatos[0]
    return existentes.pop() if len(existentes) == 1 else None


async def _executar(*, channel: str, key: str, autor: str, motivo: str) -> int:
    """A logica async, separada de `main` para o teste chamar direto.

    `main` chama `asyncio.run`, e um teste async ja roda dentro de um loop --
    chamar `main` de dentro dele estoura "cannot be called from a running
    event loop". O teste da logica chama esta funcao com `await`; so o teste
    do argumento obrigatorio ausente, que nem chega a tocar o loop, continua
    chamando `main`.
    """
    fabrica = get_sessionmaker()
    async with fabrica() as session:
        chave = await _chave_do_lead(session, channel, key)
    if chave is None:
        print(
            f"nenhum lead com esse valor no canal {channel!r} (canais: {CANAL_WHATSAPP!r},"
            f" {CANAL_WEB!r}); nada foi gravado. No WhatsApp, se o numero tiver duas"
            " conversas (com e sem o 9), passe o wa_id exato.",
            file=sys.stderr,
        )
        return 1
    await reativar(fabrica, channel=channel, conversation_key=chave, autor=autor, motivo=motivo)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reativa um lead que pediu opt-out.")
    parser.add_argument("--channel", required=True, help="canal do lead: whatsapp ou web")
    parser.add_argument("--key", required=True, help="telefone do lead (WhatsApp) ou sessao (web)")
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
