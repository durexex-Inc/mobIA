"""Ler o modelo vigente, publicar, reverter, e as listas. TEC-199, D4 e D5.

**Sem cache, de proposito**, pelo argumento de `configuracao/repositorio.py`:
cada turno le os modelos vigentes na hora, e e isso que faz o rollback valer
no turno seguinte sem invalidacao nenhuma -- a CA-19.2 pede menos de 30 s.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos repositorios deste repo. Quem chama commita junto com o evento
da trilha.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.prompts.modelo import AgenteDoPrompt, diff_entre, modelo_padrao
from mobia.domain.prompts.models import AtivacaoDePrompt, VersaoDePrompt


class Motivo(StrEnum):
    PUBLICACAO = "PUBLICACAO"
    ROLLBACK = "ROLLBACK"


class VersaoInexistente(LookupError):
    """Rollback para um numero que nunca foi publicado. Vira 404."""


class JaEAtiva(ValueError):
    """Rollback para a versao que ja vale. Vira 409."""


@dataclass(frozen=True)
class Ativa:
    """A versao que vale agora, com quem a escreveu e quem a ativou.

    Depois de um rollback os dois diferem, e a card pede os dois: "quem a
    publicou e quando" e a versao; o rollback e a ativacao. Na versao 0 nao ha
    autor nem instante de versao -- o padrao nao foi publicado por ninguem.
    """

    agente: AgenteDoPrompt
    numero: int
    texto: str
    publicada_por: str | None
    publicada_em: datetime | None
    ativada_por: str | None
    ativada_em: datetime | None
    motivo: Motivo | None


async def _ultima_ativacao(
    session: AsyncSession, agente: AgenteDoPrompt
) -> AtivacaoDePrompt | None:
    return (
        await session.execute(
            select(AtivacaoDePrompt)
            .where(AtivacaoDePrompt.agente == agente.value)
            .order_by(AtivacaoDePrompt.criado_em.desc(), AtivacaoDePrompt.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _versao(session: AsyncSession, agente: AgenteDoPrompt, numero: int) -> VersaoDePrompt:
    linha = (
        await session.execute(
            select(VersaoDePrompt).where(
                VersaoDePrompt.agente == agente.value, VersaoDePrompt.numero == numero
            )
        )
    ).scalar_one_or_none()
    if linha is None:
        raise VersaoInexistente(f"{agente.value} nao tem versao {numero}")
    return linha


async def ativa(session: AsyncSession, agente: AgenteDoPrompt) -> Ativa:
    """A vigente de um agente. Sem ativacao nenhuma, o padrao do codigo."""
    ativacao = await _ultima_ativacao(session, agente)
    if ativacao is None or ativacao.numero == 0:
        return Ativa(
            agente=agente,
            numero=0,
            texto=modelo_padrao(agente),
            publicada_por=None,
            publicada_em=None,
            ativada_por=ativacao.autor if ativacao else None,
            ativada_em=ativacao.criado_em if ativacao else None,
            motivo=Motivo(ativacao.motivo) if ativacao else None,
        )
    versao = await _versao(session, agente, ativacao.numero)
    return Ativa(
        agente=agente,
        numero=versao.numero,
        texto=versao.texto,
        publicada_por=versao.autor,
        publicada_em=versao.criado_em,
        ativada_por=ativacao.autor,
        ativada_em=ativacao.criado_em,
        motivo=Motivo(ativacao.motivo),
    )


async def modelos_vigentes(session: AsyncSession) -> dict[AgenteDoPrompt, str]:
    """O texto vigente de cada agente. E o que o turno le uma vez (D5)."""
    return {agente: (await ativa(session, agente)).texto for agente in AgenteDoPrompt}


def padroes() -> dict[AgenteDoPrompt, str]:
    """Os modelos do codigo. A queda do turno quando a leitura falha."""
    return {agente: modelo_padrao(agente) for agente in AgenteDoPrompt}


async def _ativar(
    session: AsyncSession, *, agente: AgenteDoPrompt, numero: int, motivo: Motivo, autor: str
) -> AtivacaoDePrompt:
    linha = AtivacaoDePrompt(
        id=uuid.uuid4(), agente=agente.value, numero=numero, motivo=motivo.value, autor=autor
    )
    session.add(linha)
    await session.flush()
    await session.refresh(linha)
    return linha


def _rotulo(agente: AgenteDoPrompt, numero: int) -> str:
    return f"{agente.value.lower()} v{numero}" + (" (padrao)" if numero == 0 else "")


async def publicar(
    session: AsyncSession, *, agente: AgenteDoPrompt, texto: str, autor: str
) -> tuple[VersaoDePrompt, AtivacaoDePrompt]:
    """Grava a versao seguinte e a ativa. Quem chama ja validou o texto e ja
    conferiu que ele difere do vigente.

    O numero e `max + 1` nesta transacao; duas publicacoes simultaneas colidem
    no `UNIQUE (agente, numero)` e a segunda leva `IntegrityError`.
    """
    vigente = await ativa(session, agente)
    maior = (
        await session.execute(
            select(func.coalesce(func.max(VersaoDePrompt.numero), 0)).where(
                VersaoDePrompt.agente == agente.value
            )
        )
    ).scalar_one()
    numero = int(maior) + 1
    versao = VersaoDePrompt(
        id=uuid.uuid4(),
        agente=agente.value,
        numero=numero,
        texto=texto,
        anterior=vigente.numero,
        diff=diff_entre(
            vigente.texto,
            texto,
            de=_rotulo(agente, vigente.numero),
            para=_rotulo(agente, numero),
        ),
        autor=autor,
    )
    session.add(versao)
    await session.flush()
    await session.refresh(versao)
    ativacao = await _ativar(
        session, agente=agente, numero=numero, motivo=Motivo.PUBLICACAO, autor=autor
    )
    return versao, ativacao


async def reverter(
    session: AsyncSession, *, agente: AgenteDoPrompt, numero: int, autor: str
) -> AtivacaoDePrompt:
    """Ativa uma versao que ja existe, ou o padrao (0). Nao cria versao.

    `VersaoInexistente` para numero nunca publicado; `JaEAtiva` para a que ja
    vale -- um rollback que nao muda nada poria no historico uma reversao que
    nao aconteceu.
    """
    if numero != 0:
        await _versao(session, agente, numero)
    if (await ativa(session, agente)).numero == numero:
        raise JaEAtiva(f"a versao {numero} de {agente.value} ja e a ativa")
    return await _ativar(session, agente=agente, numero=numero, motivo=Motivo.ROLLBACK, autor=autor)


async def versao(session: AsyncSession, *, agente: AgenteDoPrompt, numero: int) -> VersaoDePrompt:
    return await _versao(session, agente, numero)


async def listar_versoes(
    session: AsyncSession, *, agente: AgenteDoPrompt, limite: int
) -> list[VersaoDePrompt]:
    return list(
        (
            await session.execute(
                select(VersaoDePrompt)
                .where(VersaoDePrompt.agente == agente.value)
                .order_by(VersaoDePrompt.numero.desc())
                .limit(limite)
            )
        ).scalars()
    )


async def historico(
    session: AsyncSession, *, agente: AgenteDoPrompt, limite: int
) -> list[AtivacaoDePrompt]:
    """As ativacoes, mais recente primeiro. O quarto cenario da card."""
    return list(
        (
            await session.execute(
                select(AtivacaoDePrompt)
                .where(AtivacaoDePrompt.agente == agente.value)
                .order_by(AtivacaoDePrompt.criado_em.desc(), AtivacaoDePrompt.id.desc())
                .limit(limite)
            )
        ).scalars()
    )
