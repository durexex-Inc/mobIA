"""Ler a configuracao vigente, gravar uma versao nova, montar o historico. TEC-198.

**Sem cache, de proposito** (D1). Cada leitor carrega a vigente na hora -- uma
consulta por `criado_em DESC LIMIT 1` numa tabela de poucas linhas. E isso que
faz a CA-19.1 ("sem reiniciar a aplicacao") ser verdade sem invalidacao: nao
ha o que invalidar. Um cache por processo precisaria de aviso entre API e
worker, e o aviso que se perde deixaria um worker usando o peso velho sem
sintoma nenhum.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos repositorios deste repo.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.configuracao.models import VersaoDaConfiguracao
from mobia.domain.configuracao.vigente import ConfiguracaoDoAgente, Pesos, Tom, padrao

_UMA_HORA = timedelta(hours=1)


def _da_linha(linha: VersaoDaConfiguracao) -> ConfiguracaoDoAgente:
    return ConfiguracaoDoAgente(
        nome_do_assistente=linha.nome_do_assistente,
        tom=Tom(linha.tom),
        teto_de_perguntas=linha.teto_de_perguntas,
        pesos=Pesos(
            completude=linha.peso_completude,
            urgencia=linha.peso_urgencia,
            catalogo=linha.peso_catalogo,
            engajamento=linha.peso_engajamento,
            capacidade=linha.peso_capacidade,
        ),
        cadencia={
            temperatura: tuple(timedelta(hours=h) for h in horas)
            for temperatura, horas in linha.cadencia.items()
        },
    )


def como_plano(config: ConfiguracaoDoAgente) -> dict[str, object]:
    """O retrato no formato plano da tabela e da API. A cadencia em horas."""
    return {
        "nome_do_assistente": config.nome_do_assistente,
        "tom": config.tom.value,
        "teto_de_perguntas": config.teto_de_perguntas,
        "peso_completude": config.pesos.completude,
        "peso_urgencia": config.pesos.urgencia,
        "peso_catalogo": config.pesos.catalogo,
        "peso_engajamento": config.pesos.engajamento,
        "peso_capacidade": config.pesos.capacidade,
        "cadencia": {
            temperatura: [int(i / _UMA_HORA) for i in intervalos]
            for temperatura, intervalos in config.cadencia.items()
        },
    }


async def configuracao_vigente(session: AsyncSession) -> ConfiguracaoDoAgente:
    """A versao mais recente, ou o padrao quando nunca houve edicao."""
    linha = (
        await session.execute(
            select(VersaoDaConfiguracao)
            .order_by(VersaoDaConfiguracao.criado_em.desc(), VersaoDaConfiguracao.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _da_linha(linha) if linha is not None else padrao()


async def gravar_versao(
    session: AsyncSession, *, config: ConfiguracaoDoAgente, autor: str
) -> VersaoDaConfiguracao:
    """Acrescenta a versao. Quem chama ja validou e ja conferiu que algo mudou."""
    linha = VersaoDaConfiguracao(id=uuid.uuid4(), autor=autor, **como_plano(config))
    session.add(linha)
    await session.flush()
    await session.refresh(linha)
    return linha


@dataclass(frozen=True)
class Mudanca:
    campo: str
    anterior: object
    novo: object


@dataclass(frozen=True)
class EntradaDoHistorico:
    """Uma versao e o que ela mudou em relacao a anterior. O quarto cenario."""

    id: uuid.UUID
    autor: str
    em: datetime
    mudancas: tuple[Mudanca, ...]


def diferencas(antes: dict[str, object], depois: dict[str, object]) -> tuple[Mudanca, ...]:
    return tuple(
        Mudanca(campo=campo, anterior=antes[campo], novo=depois[campo])
        for campo in depois
        if antes[campo] != depois[campo]
    )


async def historico(session: AsyncSession, *, limite: int) -> list[EntradaDoHistorico]:
    """As versoes mais recentes primeiro, cada uma comparada com a anterior.

    A primeira versao de todas e comparada com o PADRAO, e nao com nada: foi
    ele que valeu ate ela, e "anterior: padrao" e a resposta verdadeira.
    Pede uma linha a mais do que o limite para ter com quem comparar a mais
    antiga da pagina.
    """
    linhas = list(
        (
            await session.execute(
                select(VersaoDaConfiguracao)
                .order_by(VersaoDaConfiguracao.criado_em.desc(), VersaoDaConfiguracao.id.desc())
                .limit(limite + 1)
            )
        ).scalars()
    )
    planos = [como_plano(_da_linha(linha)) for linha in linhas]
    entradas = []
    for indice, linha in enumerate(linhas[:limite]):
        anterior = planos[indice + 1] if indice + 1 < len(planos) else como_plano(padrao())
        entradas.append(
            EntradaDoHistorico(
                id=linha.id,
                autor=linha.autor,
                em=linha.criado_em,
                mudancas=diferencas(anterior, planos[indice]),
            )
        )
    return entradas
