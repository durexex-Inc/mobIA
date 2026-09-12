import json
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol, cast

import structlog
from anthropic import transform_schema
from anthropic.types import Message

from mobia.app.config import get_settings
from mobia.domain.agente.dinheiro import Recusa, parsear
from mobia.domain.agente.ferramenta_de_busca import FERRAMENTA_DE_BUSCA, PortaDeBusca
from mobia.domain.agente.schemas import (
    CategoriaDescarte,
    Extracao,
    FormaPagamento,
    Intencao,
    PerguntaDeDesambiguacao,
    ReacaoDoImovel,
    ReacaoLead,
    ReacoesDoTurno,
    RespostaDoAgente,
    TipoImovel,
    Urgencia,
    normalizar_regiao,
)
from mobia.domain.context.montagem import ContextoMontado, montar_prompt
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client

log = structlog.get_logger(__name__)

MAX_TOKENS_DA_RESPOSTA = 1500

# Orcamento: SISTEMA_DO_AGENTE e uma das quatro parcelas da subcontagem que
# test_diferenca_entre_o_contado_e_o_enviado mede, em test_config.py (as
# outras tres: -SISTEMA de montagem.py, +schema compilado, +rotulos de
# montar_prompt). Alongar este texto gasta reserva de contexto: cada caractere
# aqui e enviado em toda chamada e nunca contado por montar_contexto.
#
# **Quanto ainda cabe nao esta escrito neste comentario, de proposito**
# (TEC-243): e valor derivado, muda a cada mudanca de prompt ou de schema, e
# transcrito a mao envelhecia sem ninguem notar. Antes de acrescentar texto
# aqui, rode:
#
#     python -m pytest -q -k margem_do_orcamento -s
#
# A margem que sobrar e deliberada, nao descuido -- guardada por
# test_a_margem_do_orcamento_do_prompt_e_deliberada, para a proxima card nao
# gastar sem saber que estava gastando a reserva. Ela sempre coube em dezenas
# de caracteres, nunca em centenas.
#
# Nenhum campo de SCHEMA_DA_EXTRACAO ganhou "description": descrever so os
# tres enums (tipo_imovel, urgencia, forma_pagamento) custaria da ordem de
# 300 caracteres -- estoura sozinho a folga, e estourava tambem na card
# anterior, quando ela era a maior que ja foi. Descrever os tres enums nunca
# coube num orcamento so de prosa.
#
# A abertura diz "extrai o que ele procura", nao "extrai o que ele disse
# sobre o que procura". A forma longa e mais precisa e custa 18 caracteres a
# mais (127 contra 109) -- cortada pelo orcamento. A precisao perdida volta
# na regra de "null" logo abaixo, que diz explicitamente "so o que a fala
# DESTE turno afirma". Sem este registro, quem achar a abertura imprecisa vai
# "melhora-la" sem olhar a conta, e descobre o estouro no CI.
#
# A ordem enunciada na abertura (classifica, extrai, responde) NAO e a ordem
# dos campos em SCHEMA_DA_RESPOSTA -- "extracao" e anexada mais abaixo,
# nas duas linhas logo depois da definicao do schema SCHEMA_DA_EXTRACAO. Mover "extracao"
# para antes de "resposta" teria custo zero de orcamento, mas mudaria a
# ordem de geracao do modelo num caminho pago, para todo turno de producao;
# decisao recusada por falta de instrumento para medir o efeito. Quem for
# editar o prompt: isto nao e inconsistencia para "consertar".
#
# A clausula da memoria foi **reescrita** e nao acrescentada, na TEC-257.
# "nao repergunte o que ja esta preenchido nem o que o lead ignorou" custava
# +6,25 tokens sobre uma margem de 4,2; encurtar a clausula existente para
# "nao repergunte o preenchido nem o ignorado" cobre os dois casos por +0,75.
# "o ignorado" depende de o modelo ligar a palavra a linha
# "(perguntado, sem resposta)" que `_texto_do_estado` poe no estado -- a forma
# explicita existia e custava 3,25, recusada por nao deixar folga para
# ninguem depois.
#
# A TEC-146 (Task 7) acrescentou " Orcamento vago: peca confirmacao." ao
# final, depois das quatro tasks anteriores da mesma card terem trocado dois
# campos numericos do schema por um campo de string na Task 4 -- essa troca
# tinha liberado a margem de 32,2 que esta clausula gasta. Custou 8,4 (32,2
# -> 23,8), perto dos ~8,5 estimados no proxy antes de escrever. Nao e
# reescrita de clausula existente como a da TEC-257: esta e regra nova, sem
# forma anterior para encolher. A forma longa e mais precisa -- "se o valor
# de orcamento nao trouxer ordem de grandeza clara, peca confirmacao ao
# lead" -- custaria ~21 e nao caberia nos 32,2 sem cortar outro texto; a
# curta faz o mesmo servico porque o parser deterministico (`dinheiro.py`,
# Tasks 1-3) e quem decide "vago", nao o modelo -- o prompt so precisa
# lembrar o modelo de perguntar quando `extrair` (Task 4) ja recusou gravar.
SISTEMA_DO_AGENTE = (
    "Voce e o assistente virtual de uma imobiliaria brasileira, atendendo um lead "
    "por mensagem. A cada turno voce faz tres coisas: classifica a intencao do "
    "lead, extrai o que ele procura, e responde a ele.\n\n"
    "Intencoes possiveis: COMPRA (quer comprar para morar), ALUGUEL (quer alugar), "
    "INVESTIMENTO (compra para renda ou revenda, nao para morar), VENDER_IMOVEL "
    "(quer vender o que tem), SUPORTE_CONTRATO (duvida sobre contrato vigente), "
    "INDEFINIDA (ainda nao da para saber), FORA_DE_ESCOPO (nao e assunto "
    "imobiliario).\n\n"
    "A confianca e o quanto voce considera a classificacao segura.\n\n"
    "Responda em portugues do Brasil, em tom de conversa. Use o resumo e o "
    "estado de qualificacao como memoria: nao repergunte o preenchido nem o "
    "ignorado. Nao invente informacao sobre imoveis que nao esteja no "
    "contexto. Nao negocie valor: e com o corretor."
    "\n\nNa extracao, preencha so o que a fala DESTE turno afirma, mesmo que "
    "ja esteja no estado; o resto e null. "
    'null e "nao falou disso agora", nunca "nao sei". Nao infira: '
    "extrair o que a fala nao afirma conta erro igual a nao extrair o que ela "
    "afirma. O imovel que o lead ja tem nao e o que ele procura. "
    "Urgencia so com marco temporal explicito; pressa nao basta."
    " Orcamento vago: peca confirmacao."
)

MAX_TOKENS_DA_PERGUNTA = 300

SISTEMA_DA_DESAMBIGUACAO = (
    "Voce e o assistente virtual de uma imobiliaria brasileira. A ultima "
    "mensagem do lead nao deixou claro o que ele quer, e voce nao pode "
    "adivinhar.\n\n"
    "Escreva uma unica pergunta, aberta, em portugues do Brasil e em tom de "
    "conversa, que ajude o lead a explicar o que procura. Nao ofereca menu de "
    "opcoes numeradas. Nao assuma nenhuma intencao. Nao faca mais de uma "
    "pergunta. Devolva apenas o texto da pergunta, sem aspas e sem comentario."
)

# TEC-163, D6. Segunda chamada, no molde de SISTEMA_DA_DESAMBIGUACAO: este
# texto NAO entra na subcontagem de `test_a_margem_do_orcamento_do_prompt_e_
# deliberada`, que mede SISTEMA_DO_AGENTE, o schema compilado, os rotulos de
# montar_prompt e o `tools=`. Os campos de reacao no schema PRINCIPAL
# custariam ~50 tokens contra uma margem de 6,2 -- por isso a chamada e
# separada, e por isso alongar ESTE texto e barato enquanto alongar aquele nao e.
#
# "Use o numero do imovel" e a D7: ordinal, nunca UUID. O modelo nunca produz
# identificador que o codigo nao consiga conferir.
SISTEMA_DA_REACAO = (
    "O lead acabou de ver os imoveis abaixo, numerados. Diga, para cada um que "
    "ele mencionou, se houve INTERESSE ou DESCARTE, e no descarte a categoria: "
    "DISTANCIA, PRECO, TAMANHO ou OUTRO. Use o numero do imovel. Imovel que ele "
    "nao mencionou fica de fora da lista."
)

MAX_TOKENS_DA_REACAO = 300

# Derivado do enum de proposito: duas listas mantidas a mao divergem, e a
# divergencia so aparece quando o modelo devolve um valor que o codigo nao
# sabe converter. `minimum`/`maximum` ficam aqui como parte do contrato do
# modulo (testados abaixo) mesmo sabendo que o compilador de schema da API
# nao os suporta -- ver `_SCHEMA_COMPILADO`.
SCHEMA_DA_RESPOSTA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intencao": {"type": "string", "enum": [membro.value for membro in Intencao]},
        "confianca": {"type": "number", "minimum": 0, "maximum": 1},
        "resposta": {"type": "string"},
        # TEC-257. Lista de strings livre, e nao enum dos campos de extracao: o
        # enum impede o modelo inventar nome, e custaria +56,0 tokens contra
        # +18,5 desta forma. Nome inventado nao casa em `campos_a_marcar`, e
        # e descartado -- marca de MENOS, que e o erro seguro quando a marca
        # e permanente. Marcar de mais mataria o campo em silencio.
        #
        # Sem `description`: nenhum campo deste schema tem, e uma aqui
        # custaria mais que o campo inteiro. O modelo infere o vocabulario de
        # `extracao`, no mesmo objeto, que carrega os mesmos nomes (TEC-146
        # trocou dois campos numericos por um de expressao, entao a contagem
        # exata de campos de SCHEMA_DA_EXTRACAO nao e mais nove -- ver
        # `test_todos_os_oito_campos_sao_obrigatorios_e_anulaveis`).
        "perguntou": {"type": "array", "items": {"type": "string"}},
        # TEC-148. Os campos que o lead se negou a informar, declarados pelo
        # modelo. Mesma forma de `perguntou`, e no fim pela mesma razao: a
        # TEC-240 recusou reordenar campos do schema porque muda a ordem de
        # geracao num caminho pago em todo turno de producao.
        #
        # Custou 17,6 tokens do orcamento, e o teto de 655 nao se mexeu --
        # ver a docstring de `test_a_margem_do_orcamento_do_prompt_e_deliberada`.
        "recusou": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intencao", "confianca", "resposta"],
    "additionalProperties": False,
}

MAX_AMBIENTES = 20
# `lead_qualification.regiao` e `String(120)`.
MAX_CARACTERES_DA_REGIAO = 120


def _anulavel(tipo: dict[str, Any]) -> dict[str, Any]:
    """Anulabilidade em `anyOf`, nunca em `type` como lista.

    `transform_schema` (anthropic/lib/_parse/_transform.py) declara
    `SupportedTypes` como `Literal` de tipos **unicos** e encerra o dispatch em
    `assert_never(type_)`. Um `{"type": ["string", "null"]}` nao casa com ramo
    nenhum e estoura ali -- e como `_SCHEMA_COMPILADO` e calculado no import
    deste modulo, a falha seria na carga, nao numa chamada. `anyOf` e tratado
    por recursao, e `"null"` esta entre os tipos suportados.
    """
    return {"anyOf": [tipo, {"type": "null"}]}


def _enum_anulavel(enum: type[StrEnum]) -> dict[str, Any]:
    return _anulavel({"type": "string", "enum": [membro.value for membro in enum]})


# Lista de objetos, cada um com o ordinal (1..N, nunca UUID -- D7) e a reacao;
# `categoria` so faz sentido com DESCARTE, mas fica anulavel em vez de exigido
# condicionalmente porque o compilador de schema da API nao expressa "campo A
# obrigatorio quando campo B vale X" (mesma razao de `_anulavel` acima). O
# codigo, nao o schema, e quem descarta uma `categoria` presente com
# INTERESSE -- ver `_reacoes_de`.
SCHEMA_DA_REACAO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ordinal": {"type": "integer"},
                    "reacao": {
                        "type": "string",
                        "enum": [ReacaoLead.INTERESSE.value, ReacaoLead.DESCARTE.value],
                    },
                    "categoria": _enum_anulavel(CategoriaDescarte),
                },
                "required": ["ordinal", "reacao", "categoria"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reacoes"],
    "additionalProperties": False,
}


SCHEMA_DA_EXTRACAO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "faixa_preco_expressao": _anulavel({"type": "string"}),
        "regiao": _anulavel({"type": "string"}),
        "tipo_imovel": _enum_anulavel(TipoImovel),
        "quartos": _anulavel({"type": "integer"}),
        "vagas": _anulavel({"type": "integer"}),
        "urgencia": _enum_anulavel(Urgencia),
        "forma_pagamento": _enum_anulavel(FormaPagamento),
        "tem_imovel_para_vender": _anulavel({"type": "boolean"}),
    },
    # Todos obrigatorios, todos anulaveis: forcar o modelo a dizer `null`
    # explicitamente e mais confiavel que aceitar chave ausente. O parse
    # tolera a ausencia de todo modo -- ver `extrair`.
    "required": [
        "faixa_preco_expressao",
        "regiao",
        "tipo_imovel",
        "quartos",
        "vagas",
        "urgencia",
        "forma_pagamento",
        "tem_imovel_para_vender",
    ],
    "additionalProperties": False,
}

# `extracao` e anexada aqui, e nao na definicao de SCHEMA_DA_RESPOSTA la em
# cima, porque SCHEMA_DA_EXTRACAO so existe a esta altura do modulo.
#
# **A ordem e deliberada, e e o assunto da TEC-244.** O modelo preenche o
# objeto na ordem declarada: com `extracao` depois de `resposta`, ele formulava
# o que dizer ao lead antes de ter isolado o que a fala afirma. A abertura de
# SISTEMA_DO_AGENTE sempre anunciou "classifica, extrai, responde"; o schema
# entregava intencao, confianca, resposta, extracao. O prompt e o schema se
# contradiziam, e a TEC-240 escolheu a frase certa pelo argumento certo e
# descreveu o schema errado.
#
# Custo de orcamento: zero. Mesmas chaves, mesmo conteudo -- so a ordem muda,
# e `test_diferenca_entre_o_contado_e_o_enviado` continua medindo o mesmo
# `json.dumps`. Foi por isso que a TEC-240 identificou a saida e a recusou:
# de graca em tokens, mas muda a ordem de geracao num caminho pago, para todo
# turno de producao, numa card que nao podia medir nada.
_ORDEM_DOS_CAMPOS = ("intencao", "confianca", "extracao", "resposta", "perguntou", "recusou")

SCHEMA_DA_RESPOSTA["properties"]["extracao"] = SCHEMA_DA_EXTRACAO
if set(SCHEMA_DA_RESPOSTA["properties"]) != set(_ORDEM_DOS_CAMPOS):
    # Guarda de import, nao assert: `python -O` removeria o assert e a
    # reordenacao abaixo descartaria em silencio o campo novo.
    raise RuntimeError(
        "SCHEMA_DA_RESPOSTA mudou de campos e _ORDEM_DOS_CAMPOS nao acompanhou: "
        f"{sorted(SCHEMA_DA_RESPOSTA['properties'])} != {sorted(_ORDEM_DOS_CAMPOS)}"
    )
SCHEMA_DA_RESPOSTA["properties"] = {
    campo: SCHEMA_DA_RESPOSTA["properties"][campo] for campo in _ORDEM_DOS_CAMPOS
}
SCHEMA_DA_RESPOSTA["required"] = list(_ORDEM_DOS_CAMPOS)


def _lista_de_nomes(bruto: Any) -> tuple[str, ...]:
    """Nomes de campo que o modelo declara sobre o proprio turno.

    Serve `perguntou` (o que ele perguntou) e `recusou` (o que o lead se
    negou a informar). Uma funcao para os dois porque a normalizacao e
    identica, e duas copias divergiriam -- a divergencia so apareceria na
    borda, que e onde este tipo de campo erra.

    Nao valida os nomes de proposito: quem filtra contra `fields(Extracao)`
    sao `campos_a_marcar` e `campos_a_recusar`, que tambem logam o que
    descartaram. Duas filtragens divergiriam.

    Nao levanta nunca. Estes campos sao o modelo relatando o que ele mesmo
    fez -- uma forma errada aqui nao pode custar o turno inteiro, que ja foi
    pago e ja tem resposta valida para o lead.
    """
    if not isinstance(bruto, list):
        return ()
    return tuple(item for item in bruto if isinstance(item, str))


def _ambientes(bruto: Any) -> int | None:
    if isinstance(bruto, bool) or not isinstance(bruto, int):
        return None
    return bruto if 0 <= bruto <= MAX_AMBIENTES else None


def _membro(enum: type[StrEnum], bruto: Any) -> Any:
    if not isinstance(bruto, str):
        return None
    try:
        return enum(bruto)
    except ValueError:
        return None


def _reacoes_de(bruto: Any) -> tuple[ReacaoDoImovel, ...]:
    """Converte a lista `reacoes` do modelo, descartando o item que nao serve.

    `SCHEMA_DA_REACAO` e estrito (`output_config.format`), entao um item bem
    formado ja chega com `ordinal` inteiro e `reacao` em INTERESSE/DESCARTE --
    esta guarda e defesa a mais, no mesmo espirito de `extrair`: um item
    malformado nao pode derrubar os outros itens do mesmo turno.

    Ordinal fora de faixa (1..N) nao e responsabilidade desta funcao -- quem
    resolve ordinal contra a lista apresentada e `resolver_ordinais`
    (`recomendacao.py`, Task 6). Aqui so se descarta o que nem chega a ser um
    ordinal (nao inteiro, ou `bool`, que e subclasse de `int` em Python).

    **`categoria` so sobrevive com DESCARTE, e e aqui que ela cai.** O schema
    EXIGE a chave em todo item (anulavel, nao opcional -- o compilador da API
    nao expressa "obrigatoria quando `reacao` vale X"), entao o modelo
    preencher `categoria` num item de INTERESSE nao e caso exotico. Sem esta
    guarda, `gravar_reacoes` escrevia `reacao_lead='INTERESSE'` com
    `motivo_descarte='DISTANCIA'`: um motivo de descarte numa linha que nao e
    descarte. Nenhum consumidor de hoje le errado por causa disso -- a
    contagem da RN-10.4 filtra por DESCARTE antes --, mas a coluna e definida
    pela D13 como a categoria do DESCARTE, e a linha estaria afirmando algo
    que nao aconteceu. O comentario de `SCHEMA_DA_REACAO` ja prometia esta
    guarda ("o codigo, nao o schema, e quem descarta uma `categoria` presente
    com INTERESSE") desde antes de ela existir; a fix wave desta card a
    escreveu em vez de apagar a promessa, porque a promessa estava certa.
    """
    if not isinstance(bruto, list):
        return ()
    resultado: list[ReacaoDoImovel] = []
    for item in bruto:
        if not isinstance(item, dict):
            continue
        ordinal = item.get("ordinal")
        reacao = _membro(ReacaoLead, item.get("reacao"))
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or reacao is None:
            continue
        categoria = (
            _membro(CategoriaDescarte, item.get("categoria"))
            if reacao is ReacaoLead.DESCARTE
            else None
        )
        resultado.append(ReacaoDoImovel(ordinal=ordinal, reacao=reacao, categoria=categoria))
    return tuple(resultado)


def _regiao(bruto: Any) -> str | None:
    """Normaliza antes de truncar, e descarta o que sobra vazio.

    `normalizar_regiao` ja faz o colapso de espaco e o `casefold`, entao o
    `strip` de antes ficou dentro dela. O truncamento continua por ultimo, e a
    ordem importa: normalizar pode ALONGAR (`casefold` de `ß` vira `ss`, e de
    `ﬃ` vira `ffi`), por isso o truncamento vem depois, nunca antes. Truncar
    primeiro normalizaria o resultado ja cortado em 120 e poderia devolver
    mais que 120 caracteres depois do `casefold` -- acima de
    `lead_qualification.regiao` (`String(120)`) e `DataError` no commit,
    exatamente a falha que esta guarda existe para evitar.
    """
    if not isinstance(bruto, str):
        return None
    limpa = normalizar_regiao(bruto)
    return limpa[:MAX_CARACTERES_DA_REGIAO] if limpa else None


def extrair(bruto: Any, intencao: Intencao) -> Extracao:
    """Converte o objeto `extracao` do modelo, descartando o que nao serve.

    **Nunca levanta.** A extracao viaja na mesma chamada que a resposta ao
    lead, e um numero malformado nao pode matar uma resposta entregavel:
    extracao e enriquecimento, a resposta e o produto. Campo que falha na
    guarda e descartado; os outros campos do mesmo turno seguem.

    Nenhuma guarda e cosmetica -- cada uma existe porque o valor recusado
    seria `DataError` no commit (`regiao` acima de 120 caracteres) ou dado
    errado gravado em silencio (`true` virando 1 quarto).

    `intencao` entra desde a TEC-146: a banda de plausibilidade do preco,
    calculada em `dinheiro.parsear`, depende dela -- R$ 1.500 e aluguel
    corriqueiro e preco de compra absurdo.
    """
    if not isinstance(bruto, dict):
        return Extracao()

    minimo = maximo = None
    expressao = bruto.get("faixa_preco_expressao")
    # Nula ou vazia nao e recusa: e o turno comum, que nao falou de dinheiro.
    # Logar aqui contaria erro para todo turno sem orcamento -- a maioria.
    if isinstance(expressao, str) and expressao.strip():
        resultado = parsear(expressao, intencao)
        if isinstance(resultado, Recusa):
            log.info("extracao.preco_recusado", motivo=resultado.motivo.value)
        else:
            minimo, maximo = resultado.min_centavos, resultado.max_centavos

    return Extracao(
        faixa_preco_min_centavos=minimo,
        faixa_preco_max_centavos=maximo,
        regiao=_regiao(bruto.get("regiao")),
        tipo_imovel=_membro(TipoImovel, bruto.get("tipo_imovel")),
        quartos=_ambientes(bruto.get("quartos")),
        vagas=_ambientes(bruto.get("vagas")),
        urgencia=_membro(Urgencia, bruto.get("urgencia")),
        forma_pagamento=_membro(FormaPagamento, bruto.get("forma_pagamento")),
        tem_imovel_para_vender=(
            valor if isinstance(valor := bruto.get("tem_imovel_para_vender"), bool) else None
        ),
    )


# `output_config.format` bruto (sem `output_format=` Pydantic) vai direto pro
# corpo da requisicao sem passar pelo `transform_schema` do SDK -- essa
# funcao so roda no caminho de `client.messages.parse()`. `minimum`/`maximum`
# nao estao na lista de palavras-chave que o compilador de schema do servidor
# aceita (ver a doc da skill claude-api, "JSON Schema Limitations"), entao
# manda-los seria um 400 na primeira chamada real. `transform_schema` dobra
# as duas chaves para dentro de `description` (o modelo ainda le o intervalo,
# so que como texto) e nao muta `SCHEMA_DA_RESPOSTA` -- os testes de schema
# continuam lendo o dict original. Compilado uma vez no import: e uma funcao
# pura do dict acima, que nao muda em runtime.
_SCHEMA_COMPILADO = transform_schema(SCHEMA_DA_RESPOSTA)

# Mesmo tratamento por simetria e seguranca, nao por uma chave incompativel
# conhecida: SCHEMA_DA_REACAO nao tem `minimum`/`maximum`, so `anyOf`+`null`
# (mesmo padrao de SCHEMA_DA_EXTRACAO, que ja atravessa este mesmo
# `transform_schema` dentro de SCHEMA_DA_RESPOSTA). Compilado uma vez no
# import, como o de cima.
_SCHEMA_DA_REACAO_COMPILADO = transform_schema(SCHEMA_DA_REACAO)


class RespostaInvalida(RuntimeError):
    """O modelo nao devolveu algo utilizavel neste turno."""


class LacoDeBuscaExcedido(RuntimeError):
    """O modelo pediu a ferramenta duas vezes no mesmo turno.

    D4 do desenho: o teto e um round-trip. Nao e falha do modelo nem do
    provedor -- e o teto funcionando --, e por isso tem tipo proprio: o turno
    a trata pelo texto fixo (`turno.py`), e nao pelo caminho de excecao que
    marca a mensagem como FAILED e reenfileira.
    """


class ClassificadorPort(Protocol):
    async def classificar(
        self, contexto: ContextoMontado, *, porta: PortaDeBusca | None = None
    ) -> RespostaDoAgente: ...
    async def desambiguar(self, contexto: ContextoMontado) -> PerguntaDeDesambiguacao: ...
    async def reagir(
        self, contexto: ContextoMontado, *, apresentados: list[str]
    ) -> ReacoesDoTurno: ...


async def _tool_result(porta: PortaDeBusca, bloco: Any) -> dict[str, Any]:
    """O bloco `tool_result` de um `tool_use`, com `is_error` quando a porta errou."""
    saida = await porta(dict(bloco.input))
    return {
        "type": "tool_result",
        "tool_use_id": bloco.id,
        "content": json.dumps(saida, ensure_ascii=False),
        **({"is_error": True} if "erro" in saida else {}),
    }


def _candidatos_de(blocos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Os candidatos que sairam dos `tool_result` deste turno.

    D8: eles saem do laco junto com a resposta. Se morressem aqui, a TEC-161
    teria de refazer a busca para validar -- e validar contra uma segunda busca
    e validar contra outra coisa, nao contra o que o modelo viu.
    """
    encontrados: list[dict[str, Any]] = []
    for bloco in blocos:
        if bloco.get("is_error"):
            continue
        encontrados.extend(json.loads(bloco["content"]).get("candidatos", []))
    return encontrados


def _criterios_de(blocos: list[dict[str, Any]]) -> list[str]:
    """Os criterios PEDIDOS que sairam dos `tool_result` deste turno. TEC-163.

    Repassa, sem interpretar, o que `_criterios_de` de `ferramenta_de_busca.py`
    montou -- e o de la e o filtro ANTES do relaxamento, nao o que os
    candidatos satisfazem. A distincao importa para quem grava
    `motivo_match`, e o docstring daquela funcao a explica por inteiro; o
    relaxamento viaja por fora, nos quatro booleanos de
    `_CHAVES_DO_RELAXAMENTO`.

    Mesmo padrao de `_candidatos_de`: concatena em vez de sobrescrever. Hoje
    ha no maximo um bloco de busca por turno (D4 da TEC-265), mas se um dia
    houver dois, a soma continua sendo os criterios que produziram os
    candidatos que o modelo viu -- nao so os da ultima busca.
    """
    encontrados: list[str] = []
    for bloco in blocos:
        if bloco.get("is_error"):
            continue
        encontrados.extend(json.loads(bloco["content"]).get("criterios", []))
    return encontrados


# As quatro chaves de relaxamento do `tool_result`, na ordem em que
# `_relaxamento_de` as devolve. Uma tupla e nao quatro variaveis soltas: os
# quatro sao o MESMO tipo de fato lido do MESMO lugar, e a lista evita que
# acrescentar um quinto vire um quinto `or` copiado a mao.
_CHAVES_DO_RELAXAMENTO = (
    "relaxamento_aplicado",
    "relaxamento_sem_resultado",
    "relaxamento_de_preco",
    "relaxamento_de_bairro",
)


def _relaxamento_de(blocos: list[dict[str, Any]]) -> tuple[bool, bool, bool, bool]:
    """O que o relaxamento fez neste turno, na ordem de `_CHAVES_DO_RELAXAMENTO`.

    **Qualquer bloco basta**, e nao o ultimo: se algum dos candidatos que o
    modelo viu veio de um passe relaxado, o lead tem de ser avisado -- a card
    diz "sempre avisado". E o mesmo raciocinio pelo qual `_candidatos_de`
    concatena em vez de sobrescrever.

    Hoje `blocos` tem exatamente um elemento: `_chamar` levanta
    `LacoDeBuscaExcedido` no `tool_use` da tentativa 2 (o teto da D4) e o
    `tool_choice` manda `disable_parallel_tool_use: True`, entao nao ha nem
    segunda rodada nem duas buscas na mesma. O laco fica assim mesmo porque a
    API entrega uma LISTA de blocos e acumular e a semantica certa no dia em
    que qualquer um dos dois limites sair -- e, nesse dia, ler so o ultimo
    bloco apagaria o aviso em silencio, que e o modo de falha caro.
    """
    encontrados = [False] * len(_CHAVES_DO_RELAXAMENTO)
    for bloco in blocos:
        if bloco.get("is_error"):
            continue
        conteudo = json.loads(bloco["content"])
        for indice, chave in enumerate(_CHAVES_DO_RELAXAMENTO):
            encontrados[indice] = encontrados[indice] or bool(conteudo.get(chave))
    aplicado, sem_resultado, de_preco, de_bairro = encontrados
    return aplicado, sem_resultado, de_preco, de_bairro


class ClassificadorAnthropic:
    async def _chamar(
        self,
        contexto: ContextoMontado,
        *,
        modelo: str,
        max_tokens: int,
        system: str,
        mensagem_se_vazia: str,
        output_config: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        porta: PortaDeBusca | None = None,
        texto_adicional: str | None = None,
    ) -> tuple[str, Message, int, list[dict[str, Any]], bool, bool, bool, bool, list[str]]:
        """Chama o modelo e recusa qualquer parada que nao valha a pena aproveitar.

        Comum a `classificar`, `desambiguar` e `reagir`: as tres fazem uma
        chamada, medem a latencia e tem o mesmo criterio do que e uma resposta
        utilizavel -- `end_turn` com texto nao vazio. O que muda entre elas
        fica nos parametros (schema, teto de tokens, system prompt, mensagem
        de erro para o caso vazio) e no que cada uma faz com o texto depois de
        receber -- isso continua em cada metodo, nao aqui.

        `tools`/`porta` so chegam de `classificar`: `desambiguar` e `reagir`
        nao declaram ferramenta, entao para elas o laco abaixo sempre sai na
        primeira volta.

        `texto_adicional` so chega de `reagir`: os imoveis apresentados, numa
        lista numerada, anexados ao turno montado normalmente. Nenhum dos
        outros dois metodos precisa anexar nada alem do que `montar_prompt` ja
        produz.
        """
        comeco = time.monotonic()
        conteudo_do_turno = montar_prompt(contexto, omitir_sistema=True)
        if texto_adicional is not None:
            conteudo_do_turno = f"{conteudo_do_turno}\n\n{texto_adicional}"
        kwargs: dict[str, Any] = {
            "model": modelo,
            "max_tokens": max_tokens,
            # `system` vai como bloco com `cache_control` em vez de string
            # crua: o prefixo -- este texto mais o schema de `output_config` --
            # e identico em toda chamada, e sem isto ele e pago inteiro toda
            # vez. Medido em 30/08/2026: 1.652 tokens, 88% da entrada de uma
            # execucao do gate.
            #
            # O minimo cacheavel e POR MODELO e nao e monotonico entre
            # geracoes -- 512 no opus-5, 1.024 no sonnet-5, 4.096 no
            # haiku-4-5 --, e prefixo curto de mais nao cacheia E NAO DA ERRO:
            # sai `cache_creation_input_tokens: 0` e ninguem percebe. Por isso
            # `test_o_prefixo_cacheavel_passa_o_minimo_do_modelo` amarra o
            # tamanho ao modelo configurado, e por isso o log abaixo carrega
            # os dois contadores.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            # omitir_sistema=True: o `system` dedicado acima ja cobre a
            # persona. Reenviar `contexto.sistema` aqui duplicaria a mesma
            # instrucao, mais fraca, dentro do turno do usuario.
            "messages": [{"role": "user", "content": conteudo_do_turno}],
        }
        if output_config is not None:
            kwargs["output_config"] = output_config
        if tools is not None:
            # Ordem de renderizacao do cache e `tools` -> `system` ->
            # `messages`: com o breakpoint no `system`, uma lista de
            # ferramentas byte-estavel entra DENTRO do prefixo cacheado, e o
            # `test_o_prefixo_cacheavel_passa_o_minimo_do_modelo` continua
            # valendo porque o prefixo so cresce.
            kwargs["tools"] = tools
            # `auto`, e nao forcado: o `claude-sonnet-5` aceita `any`/`tool`,
            # mas forcar gastaria uma busca em TODO turno, inclusive nos que
            # nao pedem imovel.
            #
            # `disable_parallel_tool_use: True` porque o uso paralelo vem
            # LIGADO por padrao: uma unica mensagem do assistente pode trazer
            # varios blocos `tool_use`, e o laco abaixo executa todos eles (ver
            # o `for b in blocos` mais adiante). Sem esta chave, quantas
            # buscas o turno faz por round-trip fica a criterio do modelo, e a
            # D4 -- "teto de um round-trip por turno" -- so limitaria QUANTAS
            # VEZES o laco chama o modelo, nao quantas buscas ele dispara
            # numa unica chamada. E suportado com `auto` (a proibicao de
            # `any`/`tool` e so dos modelos Fable 5.1/Mythos 5.1).
            kwargs["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}

        candidatos: list[dict[str, Any]] = []
        # Mesmo default de `candidatos`, e pelo mesmo motivo: sem tool_use
        # neste turno, nao houve busca -- e portanto nenhum criterio para
        # relatar.
        criterios: list[str] = []
        # Mesmo default de `candidatos`, e pelo mesmo motivo: sem tool_use
        # neste turno, nao houve relaxamento nenhum para relatar.
        relaxou_e_achou = relaxou_sem_resultado = relaxou_preco = relaxou_bairro = False
        # Somados ao longo do laco pelo mesmo motivo que a latencia sai dele:
        # um turno com busca faz DUAS chamadas de verdade, cada uma cobrando
        # tokens de verdade. Os quatro contadores, nao so entrada/saida --
        # `custo_em_dolar` usa os quatro na MESMA formula (ver
        # `mobia.domain.messages.recorder`), entao somar dois e deixar dois
        # vindo so da ultima chamada produziria um custo errado de um jeito
        # que ninguem consegue reconstruir depois. "Tokens do turno" vale
        # para os quatro campos ou para nenhum. Reportar so a ultima chamada
        # subestimaria o custo de todo turno que busca, do mesmo jeito que a
        # latencia mediria so metade se ficasse dentro do laco.
        tokens_in_do_turno = 0
        tokens_out_do_turno = 0
        cache_write_do_turno = 0
        cache_read_do_turno = 0
        for tentativa in (1, 2):
            # cast: **kwargs apaga a sobrecarga que o SDK usa para distinguir
            # `Message` de `AsyncStream` por `stream=`. Nenhuma chamada deste
            # modulo pede streaming -- `stream` nunca entra em `kwargs` --
            # entao o retorno real e sempre `Message`.
            resposta = cast(Message, await get_client().messages.create(**kwargs))
            tokens_in_do_turno += resposta.usage.input_tokens
            tokens_out_do_turno += resposta.usage.output_tokens
            # `or 0` cobre o valor real de producao (None quando a chamada
            # nao tocou cache), nao um duble incompleto -- o duble de teste
            # sempre declara os dois campos (ver `_resposta_falsa` e
            # `_resposta_tool_use`).
            cache_write_do_turno += resposta.usage.cache_creation_input_tokens or 0
            cache_read_do_turno += resposta.usage.cache_read_input_tokens or 0

            if resposta.stop_reason == "tool_use":
                if porta is None or tentativa == 2:
                    # Segunda vez: o teto da D4. Primeira vez sem porta: o
                    # modelo pediu ferramenta que nao declaramos.
                    raise LacoDeBuscaExcedido(f"tool_use na tentativa {tentativa}")
                blocos = [b for b in resposta.content if b.type == "tool_use"]
                kwargs["messages"] = [
                    *kwargs["messages"],
                    {"role": "assistant", "content": resposta.content},
                    {"role": "user", "content": [await _tool_result(porta, b) for b in blocos]},
                ]
                candidatos = _candidatos_de(kwargs["messages"][-1]["content"])
                criterios = _criterios_de(kwargs["messages"][-1]["content"])
                relaxou_e_achou, relaxou_sem_resultado, relaxou_preco, relaxou_bairro = (
                    _relaxamento_de(kwargs["messages"][-1]["content"])
                )
                continue

            # `end_turn` e a unica parada aproveitavel: `max_tokens` e
            # `refusal` nao produzem JSON que valha decodificar.
            if resposta.stop_reason != "end_turn":
                raise RespostaInvalida(f"stop_reason={resposta.stop_reason!r}")

            texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
            if not texto:
                raise RespostaInvalida(mensagem_se_vazia)
            latency_ms = int((time.monotonic() - comeco) * 1000)
            # `classificar`/`desambiguar` leem os quatro contadores de
            # `resposta.usage`, nao de itens a mais na tupla -- sobrescrever
            # aqui com o total do turno evita duplicar o dado em dois lugares
            # que podiam divergir.
            resposta.usage.input_tokens = tokens_in_do_turno
            resposta.usage.output_tokens = tokens_out_do_turno
            resposta.usage.cache_creation_input_tokens = cache_write_do_turno
            resposta.usage.cache_read_input_tokens = cache_read_do_turno
            return (
                texto,
                resposta,
                latency_ms,
                candidatos,
                relaxou_e_achou,
                relaxou_sem_resultado,
                relaxou_preco,
                relaxou_bairro,
                criterios,
            )

        raise LacoDeBuscaExcedido("laco de tool use nao convergiu")

    async def classificar(
        self, contexto: ContextoMontado, *, porta: PortaDeBusca | None = None
    ) -> RespostaDoAgente:
        settings = get_settings()
        # refusal e max_tokens sao os dois outros jeitos documentados de sair
        # de um json_schema estrito, alem de end_turn -- e nenhum dos dois
        # produz um JSON que valha a pena tentar decodificar. A recusa de
        # `_chamar` para qualquer stop_reason != end_turn cobre os dois.
        (
            texto,
            resposta,
            latency_ms,
            candidatos,
            relaxou_e_achou,
            relaxou_sem_resultado,
            relaxou_preco,
            relaxou_bairro,
            criterios,
        ) = await self._chamar(
            contexto,
            modelo=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_RESPOSTA,
            system=SISTEMA_DO_AGENTE,
            mensagem_se_vazia="resposta veio vazia",
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA_COMPILADO}},
            # `tools` so entra quando ha porta injetada: sem ela, `_chamar` nao
            # tem como executar o `tool_use` e o teto da D4 derrubaria o turno
            # a toa (ver `test_sem_porta_a_ferramenta_nao_e_declarada`).
            tools=[FERRAMENTA_DE_BUSCA] if porta is not None else None,
            porta=porta,
        )

        try:
            dados = json.loads(texto)
            intencao = Intencao(dados["intencao"])

            confianca_bruta = dados["confianca"]
            # additionalProperties/enum/type sao os unicos campos que o
            # compilador do servidor de fato impoe (ver _SCHEMA_COMPILADO
            # acima) -- o intervalo [0, 1] de `confianca` nunca foi garantido
            # la.
            #
            # A comparacao de faixa e a **primeira** checagem depois do tipo, e
            # a ordem importa. Um `math.isfinite` aqui na frente recebe o int
            # arbitrario que `json.loads` aceita sem reclamar (um inteiro JSON
            # de ~320 digitos) e levanta OverflowError ao converter para float
            # -- ArithmeticError, fora do `except` abaixo, escapando cru e
            # quebrando o contrato de que RespostaInvalida e o unico modo de
            # falha deste modulo. `0 <= x <= 1` trabalha em precisao
            # arbitraria e rejeita o valor sem converter nada.
            #
            # E ela sozinha ja cobre `NaN`/`Infinity`/`-Infinity`, os literais
            # nao-padrao que `json.loads` aceita: toda comparacao com NaN e
            # falsa e os infinitos caem fora da faixa. Nenhum deles chega ao
            # `Decimal(str(...))` -- um NaN ali nunca satisfaria o
            # `< LIMIAR_DE_DESAMBIGUACAO` de quem consome depois, e a
            # ramificacao simplesmente nao aconteceria, em silencio.
            if (
                isinstance(confianca_bruta, bool)
                or not isinstance(confianca_bruta, int | float)
                or not (0 <= confianca_bruta <= 1)
            ):
                # RuntimeError nao esta no tuple do except abaixo -- propaga
                # direto, sem virar `type(exc).__name__`. Mensagem fixa, sem
                # o valor: e erro de contrato, nao motivo para expor o que
                # veio.
                raise RespostaInvalida("campo confianca fora do intervalo [0, 1]")

            resultado = RespostaDoAgente(
                intencao=intencao,
                # `conversation_intent.confianca` e `numeric(3,2)`: o Postgres
                # arredonda ao gravar, e um `Decimal` sem arredondar aqui vira
                # dois valores para o mesmo limiar -- o em-memoria (usado por
                # `deve_desambiguar` neste turno) e o gravado (usado por
                # `efetiva` em todo turno seguinte) podem discordar sobre o
                # mesmo par (intencao, confianca) quando o valor bruto cai
                # perto da borda (ex.: 0.599 nao desambigua se arredondar para
                # 0.60, mas o turno ja decidiu desambiguar com o valor cru).
                # Quantizar aqui, com a mesma escala da coluna, elimina essa
                # divergencia: o que este turno decide e exatamente o que fica
                # gravado.
                #
                # `ROUND_HALF_UP`, nao o `ROUND_HALF_EVEN` default do
                # `Decimal` -- e o modo que o Postgres usa para `numeric`
                # (round half away from zero). Os dois so divergem exatamente
                # na borda de 0,005: 0.585 vira 0.59 no Postgres e 0.58 no
                # bankers' rounding do Python.
                confianca=Decimal(str(confianca_bruta)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                resposta=dados["resposta"].strip(),
                modelo=settings.modelo_agente,
                tokens_in=resposta.usage.input_tokens,
                tokens_out=resposta.usage.output_tokens,
                latency_ms=latency_ms,
                extracao=extrair(dados.get("extracao"), intencao),
                perguntou=_lista_de_nomes(dados.get("perguntou")),
                recusou=_lista_de_nomes(dados.get("recusou")),
                cache_write=getattr(resposta.usage, "cache_creation_input_tokens", 0) or 0,
                cache_read=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
                candidatos=candidatos,
                criterios=criterios,
                relaxou_e_achou=relaxou_e_achou,
                relaxou_sem_resultado=relaxou_sem_resultado,
                relaxou_preco=relaxou_preco,
                relaxou_bairro=relaxou_bairro,
            )
        except (
            json.JSONDecodeError,
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            InvalidOperation,
        ) as exc:
            # Nunca interpola `texto` nem `dados`: carregam a resposta
            # destinada ao lead. So o nome da classe, nunca `str(exc)` --
            # `KeyError`/`TypeError` de um schema com formato inesperado
            # podem ecoar o proprio valor recebido na mensagem da excecao.
            raise RespostaInvalida(type(exc).__name__) from exc

        if not resultado.resposta:
            raise RespostaInvalida("campo resposta veio vazio")

        escrito_no_cache = resultado.cache_write
        lido_do_cache = resultado.cache_read
        # So numeros e id de modelo. Nem a resposta, nem o prompt, nem a
        # intencao classificada -- essa ultima nao e conteudo do lead, mas
        # tambem nao ajuda em log e mantem a regra simples.
        log.info(
            "agente.turno_gerado",
            modelo=resultado.modelo,
            tokens_in=resultado.tokens_in,
            tokens_out=resultado.tokens_out,
            # A unica guarda contra o cache falhar em silencio. Se um
            # invalidador entrar no prefixo, `cache_read` cai a zero e nada
            # mais avisa -- a chamada continua correta, so mais cara.
            cache_write=escrito_no_cache,
            cache_read=lido_do_cache,
            latency_ms=resultado.latency_ms,
            # Os dois contadores entram na conta: sem eles o custo cairia
            # junto com `tokens_in` sem o gasto ter caido tanto, e o painel
            # passaria a subestimar -- ver TEC-251 no docstring de
            # `custo_em_dolar`.
            custo_usd=str(
                custo_em_dolar(
                    resultado.modelo,
                    resultado.tokens_in,
                    resultado.tokens_out,
                    cache_write=escrito_no_cache,
                    cache_read=lido_do_cache,
                )
            ),
        )
        return resultado

    async def desambiguar(self, contexto: ContextoMontado) -> PerguntaDeDesambiguacao:
        """A segunda chamada do turno ambiguo: uma pergunta, sem schema.

        Recebe o mesmo contexto da primeira, montado de novo do zero -- o
        `system` desta chamada e enviado com `cache_control` como qualquer
        outro (`_chamar` nao distingue), mas e um texto DIFERENTE do de
        `classificar` (`SISTEMA_DA_DESAMBIGUACAO`, nao `SISTEMA_DO_AGENTE`),
        entao nao aproveita o prefixo quente que aquela chamada escreveu. E
        `system` precede `messages` no corpo da requisicao: trocar o system
        prompt invalidaria qualquer cache do que vem depois dele. O turno
        ambiguo paga o contexto de entrada inteiro (ate
        `contexto_teto_de_tokens`) **duas vezes**, uma por chamada -- e input
        domina a contagem de tokens. Sem
        `output_config`: a saida e uma frase, nao ha campo para validar, e o
        compilador de schema do servidor e uma chance a mais de 400 num
        caminho que ja e o de excecao.
        """
        settings = get_settings()
        # `max_tokens` curto de proposito faz do truncamento um risco real
        # aqui -- meia pergunta e pior que nenhuma. E a recusa de `_chamar`
        # para qualquer stop_reason != end_turn que impede isso de chegar ao
        # lead.
        # Sem `tools`/`porta`: a desambiguacao nunca busca imovel, entao o
        # quarto item (candidatos), os quatro booleanos de relaxamento e a
        # lista de criterios (TEC-163) saem sempre vazios/False e nao servem
        # a esta chamada -- so `classificar` devolve algo la.
        (
            texto,
            resposta,
            latency_ms,
            _candidatos,
            _relaxou_e_achou,
            _relaxou_sem_resultado,
            _relaxou_preco,
            _relaxou_bairro,
            _criterios,
        ) = await self._chamar(
            contexto,
            modelo=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_PERGUNTA,
            system=SISTEMA_DA_DESAMBIGUACAO,
            mensagem_se_vazia="pergunta veio vazia",
        )

        # So numeros e id de modelo -- a pergunta vai para o lead, nao para o log.
        log.info(
            "agente.desambiguacao_gerada",
            modelo=settings.modelo_agente,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            # Este caminho nao manda schema, entao o prefixo dele e so o
            # system prompt da desambiguacao -- provavelmente abaixo do minimo
            # do modelo, e portanto sem cache. Registrar mesmo assim: e o que
            # transforma "nao cacheia" de suposicao em dado.
            cache_write=getattr(resposta.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
            latency_ms=latency_ms,
            custo_usd=str(
                custo_em_dolar(
                    settings.modelo_agente,
                    resposta.usage.input_tokens,
                    resposta.usage.output_tokens,
                    cache_write=getattr(resposta.usage, "cache_creation_input_tokens", 0) or 0,
                    cache_read=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
                )
            ),
        )
        return PerguntaDeDesambiguacao(
            texto=texto,
            modelo=settings.modelo_agente,
            cache_write=getattr(resposta.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            latency_ms=latency_ms,
        )

    async def reagir(self, contexto: ContextoMontado, *, apresentados: list[str]) -> ReacoesDoTurno:
        """A terceira chamada possivel do turno: o que o lead achou do que viu.

        TEC-163, D6. Chamada dedicada, separada de `classificar`, pela mesma
        razao estrutural de `desambiguar`: um schema proprio, fora da
        subcontagem que `test_a_margem_do_orcamento_do_prompt_e_deliberada`
        mede. Ao contrario de `desambiguar`, esta SEMPRE manda `output_config`
        -- a saida e uma lista estruturada (ordinal, reacao, categoria), nao
        uma frase livre.

        `apresentados` e a lista numerada que `resolver_ordinais` (Task 6) vai
        ler de volta contra o ordinal que o modelo devolver -- esta chamada so
        a repassa como texto, na mesma mensagem do turno.

        Sem `tools`/`porta`: esta chamada nunca busca imovel, entao o quarto
        item (candidatos), os quatro booleanos de relaxamento e a lista de
        criterios saem sempre vazios/False, do mesmo jeito que em
        `desambiguar`.
        """
        settings = get_settings()
        (
            texto,
            resposta,
            latency_ms,
            _candidatos,
            _relaxou_e_achou,
            _relaxou_sem_resultado,
            _relaxou_preco,
            _relaxou_bairro,
            _criterios,
        ) = await self._chamar(
            contexto,
            modelo=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_REACAO,
            system=SISTEMA_DA_REACAO,
            mensagem_se_vazia="reacoes vieram vazias",
            output_config={
                "format": {"type": "json_schema", "schema": _SCHEMA_DA_REACAO_COMPILADO}
            },
            texto_adicional="Imoveis apresentados:\n" + "\n".join(apresentados),
        )

        try:
            dados = json.loads(texto)
            reacoes = _reacoes_de(dados.get("reacoes"))
        except (json.JSONDecodeError, AttributeError) as exc:
            # AttributeError cobre o topo nao vir como objeto (`dados.get`
            # falhando num JSON valido mas com forma errada, ex.: uma lista
            # solta) -- o compilador de schema do servidor deveria impedir
            # isso, mas a guarda nao custa e evita um traceback cru.
            #
            # Mesma disciplina de `classificar`: nunca interpola `texto`, que
            # carrega a lista de imoveis apresentados.
            raise RespostaInvalida(type(exc).__name__) from exc

        # So numeros e id de modelo -- nenhum destes conta o que o lead disse.
        log.info(
            "agente.reacao_gerada",
            modelo=settings.modelo_agente,
            tokens_in=resposta.usage.input_tokens,
            tokens_out=resposta.usage.output_tokens,
            cache_write=getattr(resposta.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
            latency_ms=latency_ms,
            custo_usd=str(
                custo_em_dolar(
                    settings.modelo_agente,
                    resposta.usage.input_tokens,
                    resposta.usage.output_tokens,
                    cache_write=getattr(resposta.usage, "cache_creation_input_tokens", 0) or 0,
                    cache_read=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
                )
            ),
        )
        return ReacoesDoTurno(reacoes=reacoes, modelo=settings.modelo_agente)
