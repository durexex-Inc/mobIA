from collections.abc import Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from mobia.domain.agente.schemas import Extracao, FormaPagamento, Intencao, TipoImovel, Urgencia

_CAMPOS_ANOTAVEIS = frozenset(campo.name for campo in fields(Extracao))
_VOCABULARIO = {
    "tipo_imovel": TipoImovel,
    "urgencia": Urgencia,
    "forma_pagamento": FormaPagamento,
}


class CorpusInvalido(RuntimeError):
    """O corpus nao pode ser usado como regua deste jeito."""


@dataclass(frozen=True)
class TurnoAnotado:
    """Um turno do corpus, com o rotulo de intencao e a anotacao de extracao.

    `campos` ausente tira o turno da medicao de extracao de proposito -- e o
    jeito de dizer "esta fala nao afirma nada extraivel", ou "nao sei enumerar
    com confianca tudo o que ela afirma". `campos` presente e contrato de
    anotacao **completa**: ver o comentario em `_turno_de`.

    Duas regras de anotacao que a TEC-239 teve de decidir, porque o corpus as
    aplicava de dois jeitos:

    - **O imovel que o lead TEM nao e o que ele procura.** `Extracao` e sobre a
      busca, entao "comprei um apartamento com voces e agora preciso vender"
      afirma `tem_imovel_para_vender`, e nao `tipo_imovel: APARTAMENTO`.
    - **Pergunta sobre forma de pagamento conta como afirmacao.** "sera que da
      pra usar o fgts?" (`compra-03` t1) e "aceita financiamento?"
      (`borda-injecao-01` t2) anotam `forma_pagamento`: quem pergunta se pode
      usar um meio esta dizendo que pretende usa-lo. A regra esta escrita
      porque so o primeiro estava anotado, e duas leituras opostas da mesma
      forma de fala no mesmo corpus nao viram nota mais baixa do modelo --
      viram medicao errada.
    """

    lead: str
    intencao: Intencao
    campos: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConversaAnotada:
    id: str
    descricao: str
    turnos: list[TurnoAnotado]


def _turno_de(bruto: Any, conversa_id: str, arquivo: str) -> TurnoAnotado:
    if not isinstance(bruto, dict):
        raise CorpusInvalido(
            f"{arquivo}: conversa {conversa_id!r} tem turno que nao e um mapeamento"
        )
    try:
        intencao = Intencao(bruto["intencao"])
    except (KeyError, ValueError, TypeError) as exc:
        raise CorpusInvalido(
            f"{arquivo}: conversa {conversa_id!r} tem rotulo invalido {bruto.get('intencao')!r}"
        ) from exc
    texto = str(bruto.get("lead", "")).strip()
    if not texto:
        raise CorpusInvalido(f"{arquivo}: conversa {conversa_id!r} tem turno sem texto")

    campos_brutos = bruto.get("campos")
    if campos_brutos is None:
        campos = None
    elif not isinstance(campos_brutos, dict) or not campos_brutos:
        raise CorpusInvalido(
            f"{arquivo}: {conversa_id} tem `campos` que nao e objeto ou esta vazio. "
            f"Omita a chave para deixar o turno fora da medicao de extracao."
        )
    else:
        # Anotacao e contrato: `campos` presente significa "este turno esta
        # anotado por completo". A metrica conta campo extraido que nao esta
        # aqui como erro, entao uma anotacao parcial nao vira nota mais baixa
        # do modelo -- vira medicao errada.
        for nome, valor in campos_brutos.items():
            if nome not in _CAMPOS_ANOTAVEIS:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota campo desconhecido {nome!r}. "
                    f"Conhecidos: {sorted(_CAMPOS_ANOTAVEIS)}."
                )
            enum = _VOCABULARIO.get(nome)
            if enum is not None and valor not in [membro.value for membro in enum]:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota {nome}={valor!r}, fora do "
                    f"vocabulario {[membro.value for membro in enum]}."
                )
        campos = campos_brutos
    return TurnoAnotado(lead=texto, intencao=intencao, campos=campos)


def carregar(diretorio: Path) -> list[ConversaAnotada]:
    """Le todo `*.yaml` do diretorio e valida antes de devolver.

    Toda recusa nomeia o arquivo e a conversa: achar um typo em 50 arquivos
    sem essa pista e busca manual.
    """
    conversas: list[ConversaAnotada] = []
    vistos: dict[str, str] = {}

    for caminho in sorted(diretorio.glob("*.yaml")):
        arquivo = caminho.name
        carregado = yaml.safe_load(caminho.read_text(encoding="utf-8")) or []
        if not isinstance(carregado, list):
            raise CorpusInvalido(f"{arquivo}: raiz do arquivo tem de ser uma lista")

        for bruto in carregado:
            conversa_id = str(bruto.get("id", "")).strip()
            if not conversa_id:
                raise CorpusInvalido(f"{arquivo}: ha conversa sem id")
            if conversa_id in vistos:
                raise CorpusInvalido(
                    f"{arquivo}: id {conversa_id!r} ja usado em {vistos[conversa_id]}"
                )
            vistos[conversa_id] = arquivo

            turnos = [_turno_de(t, conversa_id, arquivo) for t in bruto.get("turnos") or []]
            if not turnos:
                raise CorpusInvalido(f"{arquivo}: conversa {conversa_id!r} nao tem turnos")

            conversas.append(
                ConversaAnotada(
                    id=conversa_id,
                    descricao=str(bruto.get("descricao", "")).strip(),
                    turnos=turnos,
                )
            )

    return conversas


def total_de_turnos(conversas: Sequence[ConversaAnotada]) -> int:
    return sum(len(conversa.turnos) for conversa in conversas)
