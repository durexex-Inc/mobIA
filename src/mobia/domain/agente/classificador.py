import json
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol, cast

import structlog
from anthropic import transform_schema
from anthropic.types import Message

from mobia.app.config import get_settings
from mobia.domain.agente.schemas import (
    Extracao,
    FormaPagamento,
    Intencao,
    PerguntaDeDesambiguacao,
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
SISTEMA_DO_AGENTE = (
    "Voce e o assistente virtual de uma imobiliaria brasileira, atendendo um lead "
    "por mensagem. A cada turno voce faz tres coisas: classifica a intencao do "
    "lead, extrai o que ele procura, e responde a ele.\n\n"
    "Intencoes possiveis: COMPRA (quer comprar para morar), ALUGUEL (quer alugar), "
    "INVESTIMENTO (compra para renda ou revenda, nao para morar), VENDER_IMOVEL "
    "(quer vender o que tem), SUPORTE_CONTRATO (duvida sobre contrato vigente), "
    "INDEFINIDA (ainda nao da para saber), FORA_DE_ESCOPO (nao e assunto "
    "imobiliario).\n\n"
    "A confianca e o quanto voce considera a classificacao segura, de 0 a 1.\n\n"
    "Responda em portugues do Brasil, em tom de conversa. Use o resumo e o "
    "estado de qualificacao como memoria: nao repergunte o que ja esta "
    "preenchido. Nao invente informacao sobre imoveis que nao esteja no "
    "contexto."
    "\n\nNa extracao, preencha so o que a fala DESTE turno afirma, mesmo que "
    "ja esteja no estado; o resto e null. "
    'null e "nao falou disso agora", nunca "nao sei". Nao infira: '
    "extrair o que a fala nao afirma conta erro igual a nao extrair o que ela "
    "afirma. O imovel que o lead ja tem nao e o que ele procura. "
    "Urgencia so com marco temporal explicito; pressa nao basta."
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
    },
    "required": ["intencao", "confianca", "resposta"],
    "additionalProperties": False,
}

# Limites das guardas. Nao vao para o schema: `minimum`/`maximum` nao estao na
# lista que o compilador do servidor aceita (mesma razao documentada em
# `_SCHEMA_COMPILADO`), entao a faixa e checada aqui, em codigo.
PRECO_MINIMO = Decimal("1")
# `lead_qualification.faixa_preco_*` e `numeric(12,2)`: dez digitos antes da
# virgula. 10^9 cabe com folga; um valor maior seria DataError no commit e
# derrubaria o turno inteiro por causa de um campo opcional.
PRECO_MAXIMO = Decimal("1000000000")
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


SCHEMA_DA_EXTRACAO: dict[str, Any] = {
    "type": "object",
    "properties": {
        "faixa_preco_min": _anulavel({"type": "number"}),
        "faixa_preco_max": _anulavel({"type": "number"}),
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
        "faixa_preco_min",
        "faixa_preco_max",
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
_ORDEM_DOS_CAMPOS = ("intencao", "confianca", "extracao", "resposta")

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


def _numero(bruto: Any) -> Decimal | None:
    """Converte sem nunca levantar, e recusa bool antes de tudo.

    `isinstance(True, int)` e verdadeiro em Python: sem a recusa explicita,
    `"quartos": true` viraria 1 quarto silenciosamente.
    """
    if isinstance(bruto, bool) or not isinstance(bruto, int | float | str):
        return None
    try:
        valor = Decimal(str(bruto))
    except InvalidOperation:
        return None
    # NaN e infinito passam pelo Decimal. `is_finite` os pega antes de qualquer
    # comparacao -- toda comparacao com NaN e falsa, e um NaN que escapasse
    # seria gravado no banco como campo valido.
    return valor if valor.is_finite() else None


def _preco(bruto: Any) -> Decimal | None:
    valor = _numero(bruto)
    if valor is None or not (PRECO_MINIMO <= valor <= PRECO_MAXIMO):
        return None
    return valor


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


def extrair(bruto: Any) -> Extracao:
    """Converte o objeto `extracao` do modelo, descartando o que nao serve.

    **Nunca levanta.** A extracao viaja na mesma chamada que a resposta ao
    lead, e um numero malformado nao pode matar uma resposta entregavel:
    extracao e enriquecimento, a resposta e o produto. Campo que falha na
    guarda e descartado; os outros campos do mesmo turno seguem.

    Nenhuma guarda e cosmetica -- cada uma existe porque o valor recusado
    seria `DataError` no commit (`regiao` acima de 120 caracteres, preco acima
    de `numeric(12,2)`) ou dado errado gravado em silencio (`true` virando 1
    quarto, NaN virando preco).
    """
    if not isinstance(bruto, dict):
        return Extracao()

    minimo = _preco(bruto.get("faixa_preco_min"))
    maximo = _preco(bruto.get("faixa_preco_max"))
    # Faixa invertida descarta os dois lados: nao ha como saber qual dos dois o
    # modelo errou, e gravar um deles produziria um filtro pior que nenhum.
    # `>` e nao `>=`: "exatamente 600 mil" e faixa valida com os dois iguais.
    if minimo is not None and maximo is not None and minimo > maximo:
        log.info("extracao.faixa_invertida_descartada")
        minimo = maximo = None

    return Extracao(
        faixa_preco_min=minimo,
        faixa_preco_max=maximo,
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


class RespostaInvalida(RuntimeError):
    """O modelo nao devolveu algo utilizavel neste turno."""


class ClassificadorPort(Protocol):
    async def classificar(self, contexto: ContextoMontado) -> RespostaDoAgente: ...
    async def desambiguar(self, contexto: ContextoMontado) -> PerguntaDeDesambiguacao: ...


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
    ) -> tuple[str, Message, int]:
        """Chama o modelo e recusa qualquer parada que nao valha a pena aproveitar.

        Comum a `classificar` e `desambiguar`: as duas fazem uma chamada, medem
        a latencia e tem o mesmo criterio do que e uma resposta utilizavel --
        `end_turn` com texto nao vazio. O que muda entre elas fica nos
        parametros (schema, teto de tokens, system prompt, mensagem de erro
        para o caso vazio) e no que cada uma faz com o texto depois de
        receber -- isso continua em cada metodo, nao aqui.
        """
        comeco = time.monotonic()
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
            "messages": [{"role": "user", "content": montar_prompt(contexto, omitir_sistema=True)}],
        }
        if output_config is not None:
            kwargs["output_config"] = output_config
        # cast: **kwargs apaga a sobrecarga que o SDK usa para distinguir
        # `Message` de `AsyncStream` por `stream=`. Nenhuma chamada deste
        # modulo pede streaming -- `stream` nunca entra em `kwargs` -- entao
        # o retorno real e sempre `Message`.
        resposta = cast(Message, await get_client().messages.create(**kwargs))
        latency_ms = int((time.monotonic() - comeco) * 1000)

        # end_turn e a unica parada normal em qualquer chamada deste modulo:
        # nenhuma declara tools, nenhuma configura stop_sequence.
        if resposta.stop_reason != "end_turn":
            raise RespostaInvalida(f"stop_reason={resposta.stop_reason!r}")

        texto = "".join(bloco.text for bloco in resposta.content if bloco.type == "text").strip()
        if not texto:
            raise RespostaInvalida(mensagem_se_vazia)

        return texto, resposta, latency_ms

    async def classificar(self, contexto: ContextoMontado) -> RespostaDoAgente:
        settings = get_settings()
        # refusal e max_tokens sao os dois outros jeitos documentados de sair
        # de um json_schema estrito, alem de end_turn -- e nenhum dos dois
        # produz um JSON que valha a pena tentar decodificar. A recusa de
        # `_chamar` para qualquer stop_reason != end_turn cobre os dois.
        texto, resposta, latency_ms = await self._chamar(
            contexto,
            modelo=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_RESPOSTA,
            system=SISTEMA_DO_AGENTE,
            mensagem_se_vazia="resposta veio vazia",
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA_COMPILADO}},
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
            # `Decimal(str(...))` -- um NaN ali nunca satisfaria `>= 0.8` nem
            # `< 0.6` de quem consome depois, e a ramificacao simplesmente nao
            # aconteceria, em silencio.
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
                extracao=extrair(dados.get("extracao")),
                cache_write=getattr(resposta.usage, "cache_creation_input_tokens", 0) or 0,
                cache_read=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
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

        Recebe o mesmo contexto da primeira, montado de novo do zero -- este
        projeto nao declara nenhum `cache_control` (ver `grep -rn
        "cache_control" src/ tests/`), entao nao ha prefixo quente para
        aproveitar, e mesmo que houvesse, `system` precede `messages` no
        corpo da requisicao: trocar o system prompt invalidaria qualquer
        cache do que vem depois dele. O turno ambiguo paga o contexto de
        entrada inteiro (ate `contexto_teto_de_tokens`) **duas vezes**, uma
        por chamada -- e input domina a contagem de tokens. Sem
        `output_config`: a saida e uma frase, nao ha campo para validar, e o
        compilador de schema do servidor e uma chance a mais de 400 num
        caminho que ja e o de excecao.
        """
        settings = get_settings()
        # `max_tokens` curto de proposito faz do truncamento um risco real
        # aqui -- meia pergunta e pior que nenhuma. E a recusa de `_chamar`
        # para qualquer stop_reason != end_turn que impede isso de chegar ao
        # lead.
        texto, resposta, latency_ms = await self._chamar(
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
