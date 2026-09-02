from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import Decimal, DecimalException
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

# TEC-146. A anotacao fica em reais porque e artefato humano; o banco guarda
# centavos. A conversao mora aqui, no unico ponto em que o corpus vira dado,
# para nao haver duas unidades circulando no runner.
_EM_REAIS = {
    "faixa_preco_min": "faixa_preco_min_centavos",
    "faixa_preco_max": "faixa_preco_max_centavos",
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
    - **Pressuposicao nao e afirmacao (TEC-254).** "queremos comprar nosso
      primeiro imovel" **nao** anota `tem_imovel_para_vender: false`, por mais
      que a conclusao seja obvia para um humano. A regra sai do prompt, que e
      o contrato a que o modelo responde: desde a TEC-240 ele diz *"Nao
      infira: extrair o que a fala nao afirma conta erro igual a nao extrair o
      que ela afirma"*. Anotar o pressuposto cobra do modelo o oposto do que
      se pede a ele.

      Um turno cujo unico conteudo extraivel e pressuposto e **negativo**, e
      nao exclusao -- pressuposicao nao esta entre as tres familias que a
      exclusao reserva, e foi a TEC-246 que a tirou daquela lista.

      Nomear entre alternativas, porem, **e** afirmar: "procuro republica ou
      kitnet" anota `tipo_imovel: APARTAMENTO`, porque `kitnet` esta no
      vocabulario e oferecer uma segunda opcao nao desfaz o que foi nomeado.
      A linha e entre o que a fala **diz** e o que ela deixa concluir.
    - **`regiao` se anota como toponimo, sem preposicao (TEC-241).** "usp", nao
      "perto da usp"; "vila madalena", nao "estacao vila madalena". Desde a
      TEC-241 a medicao normaliza os dois lados, entao anotacao suja ainda
      casa -- mas escrever ja canonico e o que faz o YAML dizer a mesma coisa
      que o banco guarda. As duas anotacoes antigas com preposicao
      (`aluguel-01`, `aluguel-07`) ficaram como estavam de proposito:
      reanota-las seria mexer na regua sem necessidade.
    - **`regiao` se anota pelo LUGAR, e nao pela string do lead (TEC-248).**
      "estou de mudanca pra sp" anota `sao paulo`, e nao `sp`. A sonda dos
      sete `divergiu` mediu o modelo devolvendo o lugar em todos eles --
      "sao paulo" para "sp", "avenida paulista" para "paulista", com acento
      e com a cidade anexada -- e em nenhum ele errou a regiao. Anotar a
      abreviacao do lead punia o modelo por acertar, e era a anotacao que
      estava errada, nao ele.

      A regra e irma da de cima: aquela tira a preposicao, esta tira a
      abreviacao. As duas dizem a mesma coisa -- o campo guarda o toponimo
      que o filtro SQL da TEC-158 compara, e nao a forma como o lead o
      escreveu.
    - **Sinonimo de tipologia se anota pelo valor do vocabulario (TEC-242).**
      `kitnet`, `studio`, `flat` e `cobertura` sao `APARTAMENTO`; `sobrado` e
      `CASA`. Nao ha traducao em codigo, e nao pode haver: o schema da chamada
      e estrito, entao o modelo ja devolve o valor do enum -- ele traduz
      sozinho. O que faltava era o corpus decidir a mesma traducao, e sem essa
      decisao a traducao certa contava `extra`.

      `chacara` e `sitio` sao `RURAL` (TEC-246). Entram pelo mesmo motivo dos
      outros: ninguem diz "quero comprar um rural", entao sem a traducao no
      corpus a extracao certa contaria `extra`.

      O criterio que separa um sinonimo de um conteiner generico: a fala tem
      de **nomear a tipologia**, e nao so citar um substantivo que pode ser
      residencial ou comercial. `compra-06` indice 1 ("tem churrasqueira na
      **cobertura**...") e indice 2 ("o valor do condominio dessa
      **cobertura**") anotam `tipo_imovel`, porque `cobertura` nomeia; ja
      `aluguel-09` indice 2 ("pode ter animal de estimacao no **predio**?")
      NAO anota `tipo_imovel`, porque `predio` e conteiner generico -- a
      mesma forma de fala, com um substantivo que nao decide tipologia
      nenhuma. Nao anotar `tipo_imovel` nao e ficar fora da medicao: esse
      turno e **negativo**, e o marcador seguinte ("o que decide entre
      negativo e fora da medicao") diz por que.

      `republica` NAO tem traducao: e uso, nao tipologia, e pode ser casa ou
      apartamento. O unico turno que a usa (`aluguel-07`, primeiro turno) diz
      "republica ou kitnet" -- o lead oferece duas e nao escolhe --, entao ele
      fica sem `tipo_imovel`, de proposito.
    - **O que decide entre negativo e fora da medicao (TEC-245, TEC-246).**
      Pergunta de processo NAO exclui por si so: o corpus anota `{}` em dezenas
      delas, e desde a TEC-246 **pressupor um campo tambem nao exclui** --
      "pode ter animal no predio?" (`aluguel-09` indice 2) e "quanto tempo leva
      pra avaliar o imovel?" (`follow-up-03` indice 1) sao negativos, pela
      mesma razao que `aluguel-01` indice 1: a fala nao nomeia nada, e repetir
      o campo do turno anterior conta `extra` de proposito.

      Sai da medicao o turno que cai numa destas tres, e so nelas:

      1. **Sugere um valor sem nomea-lo.** "precisa ser terrea" sugere CASA;
         "850 mil ta acima do que consigo" sugere um teto; "perto do metro" e
         proximidade sem toponimo. Um negativo puniria o modelo por ler a fala
         com razao.
      2. **Nomeia algo que o vocabulario nao expressa.** "parcelamento direto
         com o proprietario" e "permuta com meu carro na entrada" nao sao
         valores de `FormaPagamento`.
      3. **Incerteza declarada sobre o que a fala afirma.** "depois eu vejo com
         calma" pode ou nao ser `SEM_PRESSA`; "faz diferenca no financiamento?"
         pressupoe o meio, e se pressupor equivale a pretender e questao que a
         regra da TEC-239 nao decide. Omissao nao e asercao de completude, e um
         negativo e afirmacao forte.

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


def _centavos_da_anotacao(valor: Any, *, arquivo: str, conversa_id: str, nome: str) -> int:
    """Converte a anotacao em reais para centavos, recusando o resto.

    A forma anterior era `int(valor) * 100`, e ela furava o contrato deste
    modulo em tres pontos de uma vez -- **toda** recusa daqui nomeia arquivo e
    conversa, porque um corpus de centenas de turnos sem endereco nao e
    corrigivel:

    - `faixa_preco_max: seiscentos mil` levantava `ValueError` cru, sem dizer
      onde. Agora e `CorpusInvalido` com o endereco, como as outras recusas.
    - `600000.75` era truncado para R$ 600.000 em silencio -- o `int()` come a
      fracao antes da multiplicacao. Agora os centavos entram, e so uma fracao
      de centavo (que nao existe) e recusada.
    - `faixa_preco_max: true` virava 100 centavos: `bool` e subclasse de `int`
      em Python, entao `int(True)` e 1. Um `true` digitado onde ia um numero
      passava a medir o modelo contra R$ 1,00.

    **String nao e aceita, nem a que parece numero.** `"600.000"` e a forma
    pt-BR de seiscentos mil e a forma en-US de seiscentos, e `Decimal` le a
    segunda -- um erro de 1000x numa anotacao que e o baseline medido da
    TEC-145, exatamente a classe de erro que a D7 evita mandando o corpus
    ficar em reais. Nao ha desempate possivel aqui, entao a saida e mandar
    quem anota escrever um numero YAML (`faixa_preco_max: 600000`) em vez de
    adivinhar a convencao.

    `Decimal(str(valor))` e nao `Decimal(valor)`: o YAML entrega `600000.5`
    como float binario, e a conversao direta traria o lixo da base 2.
    """
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        raise CorpusInvalido(
            f"{arquivo}: {conversa_id} anota {nome}={valor!r}, que nao e um numero "
            f"de reais. Escreva um numero YAML, sem aspas."
        )
    try:
        centavos = Decimal(str(valor)).scaleb(2)
    except DecimalException as exc:
        raise CorpusInvalido(
            f"{arquivo}: {conversa_id} anota {nome}={valor!r}, que nao e um numero "
            f"de reais."
        ) from exc
    # `float("nan")` e `float("inf")` sao `float` validos e chegam ate aqui:
    # `scaleb` nao levanta para nenhum dos dois, e `int(Infinity)` levantaria
    # `OverflowError` cru la embaixo.
    if not centavos.is_finite():
        raise CorpusInvalido(
            f"{arquivo}: {conversa_id} anota {nome}={valor!r}, que nao e um numero "
            f"de reais."
        )
    if centavos != centavos.to_integral_value():
        raise CorpusInvalido(
            f"{arquivo}: {conversa_id} anota {nome}={valor!r}, que tem fracao de "
            f"centavo. Anote em reais com no maximo duas casas."
        )
    return int(centavos)


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
        campos = {}
        for nome, valor in campos_brutos.items():
            # `_EM_REAIS` traduz o nome de anotacao (reais) para o nome de
            # gravacao (centavos) antes de qualquer checagem, para que o nome
            # que o autor do YAML escreve seja o validado contra o vocabulario
            # e o nome que sai daqui seja o que `Extracao`/o banco esperam.
            nome_final = _EM_REAIS.get(nome, nome)
            if nome_final not in _CAMPOS_ANOTAVEIS:
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
            enum = _VOCABULARIO.get(nome_final)
            if enum is not None and valor not in [membro.value for membro in enum]:
                raise CorpusInvalido(
                    f"{arquivo}: {conversa_id} anota {nome}={valor!r}, fora do "
                    f"vocabulario {[membro.value for membro in enum]}."
                )
            campos[nome_final] = (
                _centavos_da_anotacao(valor, arquivo=arquivo, conversa_id=conversa_id, nome=nome)
                if nome in _EM_REAIS
                else valor
            )
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
