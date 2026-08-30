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

    `campos` tem tres estados, e cada um significa uma coisa diferente:

    - ausente (`None`): o turno fica fora da medicao de extracao de proposito
      -- "nao sei enumerar com confianca tudo o que esta fala afirma".
    - `{}`: o turno esta anotado por completo, e a anotacao e "nada foi
      afirmado". Qualquer campo que o modelo devolver aqui e invencao.
    - dict nao vazio: o turno afirma alguma coisa, e a anotacao diz o que.

    `campos` presente (os dois ultimos casos) e contrato de anotacao
    **completa**: ver o comentario em `_turno_de`.

    Convencao de indice de turno: **0-based**, igual ao `enumerate` que produz
    `Discrepancia.indice` no relatorio. "primeiro turno" e indice 0, "segundo
    turno" e indice 1. Nao use "t1"/"t2" pra descrever turno deste corpus: essa
    notacao le como 1-based pra quem nao conhece esta convencao, e ja apontou
    pro turno errado mais de uma vez neste README.

    Regras de anotacao que o corpus aplica, e a card que decidiu cada uma:

    - **O imovel que o lead TEM nao e o que ele procura (TEC-239).** `Extracao`
      e sobre a busca, entao "comprei um apartamento com voces e agora preciso
      vender" afirma `tem_imovel_para_vender`, e nao `tipo_imovel: APARTAMENTO`.
    - **Pergunta sobre forma de pagamento conta como afirmacao (TEC-239).**
      "sera que da pra usar o fgts?" (`compra-03` indice 0) e "aceita
      financiamento?" (`borda-injecao-01` indice 1) anotam `forma_pagamento`:
      quem pergunta se pode usar um meio esta dizendo que pretende usa-lo. A
      regra esta escrita porque so o primeiro estava anotado, e duas leituras
      opostas da mesma forma de fala no mesmo corpus nao viram nota mais baixa
      do modelo -- viram medicao errada.
    - **`regiao` se anota como toponimo, sem preposicao (TEC-241).** "usp", nao
      "perto da usp"; "vila madalena", nao "estacao vila madalena". Desde a
      TEC-241 a medicao normaliza os dois lados, entao anotacao suja ainda
      casa -- mas escrever ja canonico e o que faz o YAML dizer a mesma coisa
      que o banco guarda. As duas anotacoes antigas com preposicao
      (`aluguel-01`, `aluguel-07`) ficaram como estavam de proposito:
      reanota-las seria mexer na regua sem necessidade.
    - **Sinonimo de tipologia se anota pelo valor do vocabulario (TEC-242).**
      `kitnet`, `studio`, `flat` e `cobertura` sao `APARTAMENTO`; `sobrado` e
      `CASA`. Nao ha traducao em codigo, e nao pode haver: o schema da chamada
      e estrito, entao o modelo ja devolve o valor do enum -- ele traduz
      sozinho. O que faltava era o corpus decidir a mesma traducao, e sem essa
      decisao a traducao certa contava `extra`.

      O criterio que separa um sinonimo de um conteiner generico: a fala tem
      de **nomear a tipologia**, e nao so citar um substantivo que pode ser
      residencial ou comercial. `compra-06` indice 1 ("tem churrasqueira na
      **cobertura**...") e indice 2 ("o valor do condominio dessa
      **cobertura**") anotam `tipo_imovel`, porque `cobertura` nomeia; ja
      `aluguel-09` indice 2 ("pode ter animal de estimacao no **predio**?")
      fica de fora, porque `predio` e conteiner generico -- a mesma forma de
      fala, com um substantivo que nao decide tipologia nenhuma.

      `republica` NAO tem traducao: e uso, nao tipologia, e pode ser casa ou
      apartamento. O unico turno que a usa (`aluguel-07`, primeiro turno) diz
      "republica ou kitnet" -- o lead oferece duas e nao escolhe --, entao ele
      fica sem `tipo_imovel`, de proposito.
    - **O que decide entre negativo e fora da medicao (TEC-245).** Pergunta de
      processo NAO e motivo de exclusao por si so: o corpus anota `{}` em
      dezenas delas. O que exclui e a fala **pressupor um campo sem afirma-lo**
      ("pode ter animal no predio?" pressupoe o predio) ou **sugerir um valor
      sem nomea-lo** ("precisa ser terrea" sugere CASA; "850 mil ta acima do
      que consigo" sugere um teto). Nos dois casos um negativo puniria o
      modelo por ler a fala com razao, e um positivo inventaria anotacao --
      por isso o turno sai da medicao, com o motivo escrito.

      Anafora pura ("aquele mesmo predio", "ali mesmo", "nessa faixa") e
      negativo, e nao exclusao: a fala nao nomeia nada, e repetir o campo do
      turno anterior e `extra` de proposito.

      **Esta regra colide com a da TEC-242, e a colisao esta em aberto por
      decisao.** "aquele mesmo predio" (`aluguel-01` indice 1) e negativo aqui,
      enquanto "pode ter animal de estimacao no predio?" (`aluguel-09` indice
      2) fica fora da medicao pela regra acima. As duas sao pergunta de
      processo com `predio` apontando pro imovel que o turno 0 ja estabeleceu,
      e mesmo assim um modelo que devolve `tipo_imovel` leva invencao numa e
      nada na outra. E classe, e nao turno: sete turnos do corpus tem dica de
      tipologia na fala (`predio`, `condominio`, `unidade`) -- `aluguel-01`
      indices 1 e 2, `aluguel-02` indice 1, `investimento-01` indice 2,
      `investimento-08` indices 0 e 2, todos negativos e todos anotados pela
      TEC-245, mais `aluguel-09` indice 2, o excluido.

      Nao esta resolvida porque os dois jeitos de resolver custam mais do que
      ela. Medir `aluguel-09` indice 2 derruba uma decisao da TEC-238 que a
      TEC-242 reafirmou e que o spec desta card diz confirmar -- isso e card
      propria, e nao nota de rodape. Excluir `aluguel-01` indice 1 contradiz o
      comentario de `borda-longa-01` indice 2, que diz que repetir os campos do
      turno anterior conta `extra` DE PROPOSITO, e cascatearia pelos outros
      cinco. O que custa deixar assim esta medido: a regua cobra invencao num
      turno e perdoa a uma conversa de distancia, dentro desta classe e so
      dela. E reversivel, e agora esta escrito onde o proximo anotador le.

      Turno fora da medicao tem entrada em `_FORA_DA_MEDICAO`
      (`tests/unit/test_evals_corpus_real.py`), com o motivo em uma linha. Nao
      ha mais turno sem `campos` por acidente.
    """

    lead: str
    intencao: Intencao
    campos: dict[str, Any] | None = None

    @property
    def anotado(self) -> bool:
        """O turno entra na medicao de extracao."""
        return self.campos is not None

    @property
    def positivo(self) -> bool:
        """O turno afirma alguma coisa, e a anotacao diz o que."""
        return self.campos is not None and self.campos != {}

    @property
    def negativo(self) -> bool:
        """O turno esta anotado como "o lead nao afirmou nada".

        Tudo que o modelo devolver aqui e invencao, sem ambiguidade: o turno
        esta anotado por completo, e o completo e vazio. E o unico formato em
        que `extra` acusa o modelo em vez de acusar a medicao.
        """
        return self.campos == {}


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

    # Distingue por PRESENCA da chave, e nunca por veracidade do valor:
    # `bruto.get("campos")` devolve None tanto para chave ausente quanto para
    # `campos:` sem valor, e desde a TEC-238 esses dois significam coisas
    # opostas.
    if "campos" not in bruto:
        campos = None
    else:
        campos_brutos = bruto["campos"]
        if campos_brutos is None:
            raise CorpusInvalido(
                f"{arquivo}: {conversa_id} tem `campos` sem valor, que nao diz nada. "
                f"Omita a chave para deixar o turno fora da medicao de extracao, "
                f"ou escreva `campos: {{}}` para dizer que o lead nao afirmou "
                f"nada neste turno."
            )
        if not isinstance(campos_brutos, dict):
            raise CorpusInvalido(f"{arquivo}: {conversa_id} tem `campos` que nao e um objeto.")
        # Anotacao e contrato: `campos` presente significa "este turno esta
        # anotado por completo". A metrica conta campo extraido que nao esta
        # aqui como erro, entao uma anotacao parcial nao vira nota mais baixa
        # do modelo -- vira medicao errada. `{}` e o caso limite disso: nada
        # esperado, tudo obtido e erro.
        for nome, valor in campos_brutos.items():
            if nome not in _CAMPOS_ANOTAVEIS:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota campo desconhecido {nome!r}. "
                    f"Conhecidos: {sorted(_CAMPOS_ANOTAVEIS)}."
                )
            # Mesmo typo de `campos:` nulo, um nivel abaixo: `{nome}:` sem
            # valor carrega como `{nome!r}: None` e nao diz nada. Sem esta
            # recusa o valor passava para regiao/quartos/vagas/os dois
            # precos e virava um `faltou` que o modelo nunca tem como
            # satisfazer, porque `preenchidos()` jamais devolve `None`.
            if valor is None:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota {nome!r} sem valor, que nao diz "
                    f"nada. Omita o campo se o lead nao afirmou isso, ou de um valor."
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
