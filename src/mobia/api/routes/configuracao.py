"""A configuracao do agente, ajustavel sem deploy. TEC-198, RN-19.3 e RN-19.5.

Tres rotas, todas com `CONFIGURAR_AGENTE` (so ADMIN): ler a vigente com os
limites, alterar, e ler o historico. **A alteracao vale na proxima execucao,
sem reiniciar nada** (CA-19.1): nao ha cache a invalidar, porque cada leitor
carrega a vigente na hora -- ver `domain/configuracao/repositorio.py`.

**O formato e plano**, com os pesos como `pesoUrgencia` etc. e a cadencia em
horas por temperatura: e o que a tela edita campo a campo, e o que a tabela de
versoes guarda.
"""

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.api.middleware import origem_da_requisicao
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import Acao, Entidade
from mobia.domain.configuracao import vigente
from mobia.domain.configuracao.repositorio import (
    como_plano,
    configuracao_vigente,
    diferencas,
    gravar_versao,
    historico,
)
from mobia.domain.configuracao.vigente import ConfiguracaoInvalida, Tom
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/configuracao", tags=["configuracao"])

_ADMIN = Depends(Exige(Permissao.CONFIGURAR_AGENTE))

# O nome na API -> o nome plano da tabela.
_CAMPOS = {
    "nomeDoAssistente": "nome_do_assistente",
    "tom": "tom",
    "tetoDePerguntas": "teto_de_perguntas",
    "pesoCompletude": "peso_completude",
    "pesoUrgencia": "peso_urgencia",
    "pesoCatalogo": "peso_catalogo",
    "pesoEngajamento": "peso_engajamento",
    "pesoCapacidade": "peso_capacidade",
    "cadencia": "cadencia",
}
_DA_TABELA = {coluna: nome for nome, coluna in _CAMPOS.items()}


def _na_api(plano: dict[str, object]) -> dict[str, object]:
    return {_DA_TABELA[coluna]: valor for coluna, valor in plano.items()}


_LIMITES: dict[str, object] = {
    "nomeDoAssistente": {"maximoDeCaracteres": vigente.TETO_DO_NOME, "nulavel": True},
    "tom": {"valores": [t.value for t in Tom]},
    "tetoDePerguntas": {
        "minimo": vigente.TETO_MINIMO_DE_PERGUNTAS,
        "maximo": vigente.TETO_MAXIMO_DE_PERGUNTAS,
    },
    "pesos": {
        "minimo": 0,
        "maximo": vigente.PESO_MAXIMO,
        "somaMaxima": vigente.SOMA_MAXIMA_DOS_PESOS,
    },
    "cadencia": {
        "tentativasPorTemperatura": {t: len(i) for t, i in vigente.padrao().cadencia.items()},
        "horaMinima": int(vigente.INTERVALO_MINIMO_DA_CADENCIA / timedelta(hours=1)),
        "horaMaxima": int(vigente.INTERVALO_MAXIMO_DA_CADENCIA / timedelta(hours=1)),
    },
}


@router.get("/agente")
async def ler(_: IdentidadeDaRequisicao = _ADMIN) -> dict[str, object]:
    """A vigente e os limites de cada campo -- a tela nao guarda segunda copia deles."""
    async with get_sessionmaker()() as session:
        config = await configuracao_vigente(session)
    return {"configuracao": _na_api(como_plano(config)), "limites": _LIMITES}


class PedidoDeAlteracao(BaseModel):
    """Os campos de `_CAMPOS`, todos opcionais. Ausente nao muda.

    A borda so confere a forma; as faixas sao de `vigente.validar`, que as
    explica em texto e junta todas as violacoes numa resposta so.
    """

    model_config = ConfigDict(extra="forbid")

    nomeDoAssistente: str | None = None  # noqa: N815
    tom: Tom | None = None
    tetoDePerguntas: int | None = None  # noqa: N815
    pesoCompletude: int | None = None  # noqa: N815
    pesoUrgencia: int | None = None  # noqa: N815
    pesoCatalogo: int | None = None  # noqa: N815
    pesoEngajamento: int | None = None  # noqa: N815
    pesoCapacidade: int | None = None  # noqa: N815
    cadencia: dict[str, list[Annotated[int, Field(strict=True)]]] | None = None


def _mudancas(pedido: PedidoDeAlteracao) -> dict[str, Any]:
    """O pedido no formato de `vigente.aplicar`. A cadencia vira `timedelta`."""
    mudancas: dict[str, Any] = {}
    for nome in pedido.model_fields_set:
        valor = getattr(pedido, nome)
        coluna = _CAMPOS[nome]
        if coluna == "cadencia" and valor is not None:
            valor = {t: tuple(timedelta(hours=h) for h in horas) for t, horas in valor.items()}
        elif coluna == "tom" and valor is not None:
            valor = Tom(valor)
        mudancas[coluna] = valor
    if mudancas.get("tom", "") is None or mudancas.get("teto_de_perguntas", 0) is None:
        raise ConfiguracaoInvalida("tom e limite de perguntas nao podem ser nulos")
    if any(mudancas.get(c, 0) is None for c in mudancas if c.startswith("peso_")):
        raise ConfiguracaoInvalida("peso nao pode ser nulo")
    if "cadencia" in mudancas and mudancas["cadencia"] is None:
        raise ConfiguracaoInvalida("cadencia nao pode ser nula")
    return mudancas


@router.patch("/agente")
async def alterar(
    pedido: PedidoDeAlteracao,
    request: Request,
    identidade: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """Grava uma versao nova com a vigente e as mudancas por cima. D1 e D2.

    **Fora da faixa e 422 e nada e gravado** -- o terceiro cenario, "o valor
    anterior permanece", e consequencia de a vigente ser a ultima linha.
    **Nada mudou, nada e gravado**: uma versao identica a anterior poria no
    historico uma alteracao que nao aconteceu.

    **Um `CONFIGURACAO_ALTERADA` por campo na trilha, no mesmo commit**, com
    o nome do campo e sem o valor -- o valor fica na tabela de versoes.
    """
    async with get_sessionmaker()() as session:
        atual = await configuracao_vigente(session)
        try:
            nova = vigente.validar(vigente.aplicar(atual, _mudancas(pedido)))
        except ConfiguracaoInvalida as erro:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
            ) from erro

        mudou = diferencas(como_plano(atual), como_plano(nova))
        if mudou:
            versao = await gravar_versao(session, config=nova, autor=identidade.para_log())
            for mudanca in mudou:
                await registrar_evento(
                    session,
                    ator=identidade.como_ator(),
                    acao=Acao.CONFIGURACAO_ALTERADA,
                    entidade=Entidade.CONFIGURACAO_AGENTE,
                    entidade_id=str(versao.id),
                    campo=_DA_TABELA[mudanca.campo],
                    origem=origem_da_requisicao(request),
                )
            await session.commit()

    return {
        "configuracao": _na_api(como_plano(nova)),
        "alterados": [_DA_TABELA[m.campo] for m in mudou],
    }


@router.get("/agente/historico")
async def ler_historico(
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    _: IdentidadeDaRequisicao = _ADMIN,
) -> dict[str, object]:
    """Cada versao, da mais nova para a mais velha, com autor, instante e o que
    mudou -- valor anterior e novo. O quarto cenario."""
    async with get_sessionmaker()() as session:
        entradas = await historico(session, limite=limite)
    return {
        "itens": [
            {
                "id": str(e.id),
                "autor": e.autor,
                "em": e.em.isoformat(),
                "mudancas": [
                    {"campo": _DA_TABELA[m.campo], "anterior": m.anterior, "novo": m.novo}
                    for m in e.mudancas
                ],
            }
            for e in entradas
        ]
    }
