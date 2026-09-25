"""O refresh rotativo e a revogacao por familia. TEC-201, D4.

O que vai para o cliente e um valor aleatorio e opaco; o banco guarda so o
SHA-256 dele. Vazamento da tabela nao da sessao a ninguem.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import Settings
from mobia.domain.usuarios.models import SessaoDeRefresh

log = structlog.get_logger(__name__)


class RefreshInvalido(Exception):
    """O refresh nao existe, expirou, foi revogado ou ja tinha sido usado.

    Um tipo so, pela mesma razao de `TokenInvalido`: distinguir os casos na
    resposta contaria a quem sonda o que ele acertou.
    """


@dataclass(frozen=True)
class RefreshEmitido:
    """O que o cliente recebe e o que o banco guardou."""

    token: str
    familia: uuid.UUID


def _digest(token: str) -> str:
    """SHA-256 em hexadecimal.

    **Hash simples, e nao Argon2 como a senha.** A entrada aqui tem 256 bits de
    entropia gerados por nos -- nao ha dicionario que a ataque, entao o custo
    de um hash de senha por requisicao de refresh seria pago a toa. O criterio
    que separa os dois casos e a entropia da entrada, nao o fato de ser
    segredo.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def emitir(
    session: AsyncSession,
    *,
    usuario_id: uuid.UUID,
    settings: Settings,
    familia: uuid.UUID | None = None,
) -> RefreshEmitido:
    """Cria um refresh. **Nao commita** -- a disciplina do repo.

    `familia=None` comeca uma corrente nova (login); passar a familia existente
    continua a corrente (rotacao).
    """
    token = secrets.token_urlsafe(32)
    agora = datetime.now(UTC)
    corrente = familia or uuid.uuid4()

    session.add(
        SessaoDeRefresh(
            id=uuid.uuid4(),
            usuario_id=usuario_id,
            familia=corrente,
            digest=_digest(token),
            expira_em=agora + timedelta(days=settings.refresh_dias),
            criado_em=agora,
        )
    )
    return RefreshEmitido(token=token, familia=corrente)


async def revogar_familia(session: AsyncSession, familia: uuid.UUID) -> None:
    """Derruba a corrente inteira. **Nao commita.**

    Usado pelo logout e pela deteccao de reuso. Marca todas, inclusive as ja
    usadas: o custo e nulo e o resultado nao depende da ordem em que as linhas
    foram criadas.
    """
    await session.execute(
        update(SessaoDeRefresh)
        .where(SessaoDeRefresh.familia == familia, SessaoDeRefresh.revogado_em.is_(None))
        .values(revogado_em=datetime.now(UTC))
    )


async def consumir(
    session: AsyncSession, token: str, *, settings: Settings
) -> tuple[uuid.UUID, RefreshEmitido]:
    """Troca um refresh por outro. Devolve o usuario e o token novo.

    **O reuso derruba a familia inteira, e isso inclui quem estava usando
    legitimamente.** Um refresh ja consumido, apresentado de novo, significa que
    duas partes tem o mesmo valor: a legitima e quem o copiou. Nao ha como
    saber qual das duas esta pedindo agora, e deixar passar seria escolher
    ficar com o ladrao dentro. E a recomendacao da OAuth 2.0 Security BCP.

    **Nao commita** -- quem chama decide o que mais entra na transacao.
    """
    linha = (
        await session.execute(
            select(SessaoDeRefresh).where(SessaoDeRefresh.digest == _digest(token))
        )
    ).scalar_one_or_none()

    if linha is None:
        raise RefreshInvalido("desconhecido")

    if linha.usado_em is not None:
        # Nao ha `raise` antes da revogacao de proposito: o efeito colateral e
        # o ponto, e perde-lo por uma reordenacao deixaria o ladrao com a
        # corrente viva.
        await revogar_familia(session, linha.familia)
        log.error(
            "auth.refresh_reusado",
            usuario_id=str(linha.usuario_id),
            familia=str(linha.familia),
        )
        raise RefreshInvalido("reuso")

    if linha.revogado_em is not None:
        raise RefreshInvalido("revogado")

    # `expira_em` vem do banco com tzinfo (a coluna e timestamptz), entao a
    # comparacao com um `datetime` ciente e valida. Comparar com `utcnow()`
    # ingenuo levantaria TypeError -- e e o tipo de erro que so aparece quando
    # o primeiro refresh expira, dias depois do deploy.
    if linha.expira_em <= datetime.now(UTC):
        raise RefreshInvalido("expirado")

    linha.usado_em = datetime.now(UTC)
    novo = await emitir(
        session, usuario_id=linha.usuario_id, settings=settings, familia=linha.familia
    )
    return linha.usuario_id, novo


async def revogar_por_token(session: AsyncSession, token: str) -> bool:
    """Revoga a familia do refresh apresentado. Devolve se achou alguma.

    **Nao commita.** Existe para o logout nao precisar do `_digest` privado
    nem montar a consulta por fora: o formato do digest e detalhe deste modulo,
    e quem o vazasse acabaria com duas versoes da mesma regra.
    """
    linha = (
        await session.execute(
            select(SessaoDeRefresh).where(SessaoDeRefresh.digest == _digest(token))
        )
    ).scalar_one_or_none()
    if linha is None:
        return False
    await revogar_familia(session, linha.familia)
    return True
