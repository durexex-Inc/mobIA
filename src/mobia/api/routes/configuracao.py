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
from decimal import Decimal
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
    id_da_vigente,
)
from mobia.domain.configuracao.vigente import ConfiguracaoInvalida, PosicaoDoBotao, Tom
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
    "orcamentoMensalUsd": "orcamento_mensal_usd",
    "corPrimaria": "cor_primaria",
    "posicaoDoBotao": "posicao_do_botao",
    "dominiosDoChat": "dominios_do_chat",
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
    # TEC-191, D3. Mensal; o painel de custo o faz proporcional ao periodo.
    "orcamentoMensalUsd": {
        "minimo": vigente.ORCAMENTO_MINIMO,
        "maximo": vigente.ORCAMENTO_MAXIMO,
        "nulavel": True,
    },
    # TEC-344, D1. O formato e conferido em `vigente.validar`.
    "corPrimaria": {"formato": "#RRGGBB"},
    "posicaoDoBotao": {"valores": [p.value for p in PosicaoDoBotao]},
    # TEC-345, D1. O formato de cada um e conferido em `vigente.validar`.
    "dominiosDoChat": {
        "maximo": vigente.MAXIMO_DE_DOMINIOS_DO_CHAT,
        "formato": "host ou host:porta, em minusculas",
    },
}


@router.get("/agente")
async def ler(_: IdentidadeDaRequisicao = _ADMIN) -> dict[str, object]:
    """A vigente, os limites de cada campo e a versao (TEC-337, D1).

    `versao` e o `id` da ultima linha gravada, como string, ou `null` quando
    ninguem nunca editou -- a tela guarda o valor e o devolve em `seVersao`
    no `PATCH`, para a rota saber se a vigente mudou desde que a tela leu."""
    async with get_sessionmaker()() as session:
        config = await configuracao_vigente(session)
        versao = await id_da_vigente(session)
    return {
        "configuracao": _na_api(como_plano(config)),
        "limites": _LIMITES,
        "versao": str(versao) if versao is not None else None,
    }


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
    # `null` LIMPA o orcamento, como o nome do assistente: os dois sao os
    # campos da configuracao que tem "nenhum" como valor legitimo.
    orcamentoMensalUsd: Decimal | None = None  # noqa: N815
    corPrimaria: str | None = None  # noqa: N815
    posicaoDoBotao: PosicaoDoBotao | None = None  # noqa: N815
    # `[]` LIMPA a lista; `null` e recusado, como a cor.
    dominiosDoChat: list[str] | None = None  # noqa: N815
    # TEC-337, D1. Fora de `_CAMPOS`: nao e um campo da configuracao, e o
    # token de concorrencia. Ausente = sem checagem (compatibilidade); `null`
    # bate com "ninguem editou ainda" -- o mesmo `None` que `id_da_vigente`
    # devolve nesse caso.
    seVersao: str | None = None  # noqa: N815


def _mudancas(pedido: PedidoDeAlteracao) -> dict[str, Any]:
    """O pedido no formato de `vigente.aplicar`. A cadencia vira `timedelta`."""
    mudancas: dict[str, Any] = {}
    for nome in pedido.model_fields_set:
        if nome == "seVersao":
            continue
        valor = getattr(pedido, nome)
        coluna = _CAMPOS[nome]
        if coluna == "cadencia" and valor is not None:
            valor = {t: tuple(timedelta(hours=h) for h in horas) for t, horas in valor.items()}
        elif coluna == "tom" and valor is not None:
            valor = Tom(valor)
        elif coluna == "posicao_do_botao" and valor is not None:
            valor = PosicaoDoBotao(valor)
        elif coluna == "dominios_do_chat" and valor is not None:
            valor = tuple(valor)
        mudancas[coluna] = valor
    if mudancas.get("tom", "") is None or mudancas.get("teto_de_perguntas", 0) is None:
        raise ConfiguracaoInvalida("tom e limite de perguntas nao podem ser nulos")
    if any(mudancas.get(c, 0) is None for c in mudancas if c.startswith("peso_")):
        raise ConfiguracaoInvalida("peso nao pode ser nulo")
    if "cadencia" in mudancas and mudancas["cadencia"] is None:
        raise ConfiguracaoInvalida("cadencia nao pode ser nula")
    # TEC-344, D1. Ao contrario do nome e do orcamento, "nenhum" nao e valor
    # legitimo aqui: o botao sempre tem cor e lado.
    if mudancas.get("cor_primaria", "") is None or mudancas.get("posicao_do_botao", "") is None:
        raise ConfiguracaoInvalida("cor primaria e posicao do botao nao podem ser nulas")
    # TEC-345. "Nenhum dominio" e `[]`, e nao `null`: com dois jeitos de dizer
    # a mesma coisa, a tela e o historico teriam de tratar os dois.
    if "dominios_do_chat" in mudancas and mudancas["dominios_do_chat"] is None:
        raise ConfiguracaoInvalida("dominios do chat nao podem ser nulos: use [] para nenhum")
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

    **`seVersao`, quando presente, confere a concorrencia antes de tudo** (D1,
    TEC-337): em desacordo com `id_da_vigente`, `409` e nada e gravado --
    nem validado, nem aplicado. Ausente do pedido, pula a checagem inteira
    (compatibilidade com quem ainda nao acompanha versao).
    """
    async with get_sessionmaker()() as session:
        if "seVersao" in pedido.model_fields_set:
            vigente_id = await id_da_vigente(session)
            esperado = str(vigente_id) if vigente_id is not None else None
            if pedido.seVersao != esperado:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="a configuracao foi alterada por outra pessoa desde que a tela "
                    "foi carregada; recarregue antes de salvar",
                )
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
