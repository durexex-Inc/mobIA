"""A unica parte do follow-up que o modelo escreve: a frase de abertura.

TEC-184, D4. O fato -- imovel novo ou queda de preco -- e escolhido e
renderizado por codigo (`mensagem.py`); daqui sai so uma frase que entra como
PREFIXO e e a primeira coisa cortada pelo teto de 600 caracteres.

**Por que a chamada mora aqui, e nao em `_chamar` do classificador.** A
decisao da Step 1 desta task, com o criterio que o brief fixou: reusar
`ClassificadorAnthropic._chamar` exigiria fabricar um `ContextoMontado` so
para satisfazer a assinatura -- ele recebe `contexto` e passa por
`montar_prompt`, e o follow-up nao tem turno nenhum para montar. Os seis
campos daquele dataclass mentiriam um a um: `literais=[]` diria que a
conversa nao tem mensagem (tem, so nao foram lidas), `tokens=0` diria que o
contexto foi medido e deu zero, `degradado=False` afirmaria sobre uma poda
que nunca rodou, e `sistema` teria de carregar um prompt que nao e o do
turno. Um objeto vazio criado para caber numa assinatura mente sobre o que
aconteceu, e e a proxima pessoa que paga.

A chamada propria tambem e o molde ja usado por quem faz uma chamada curta e
fora do turno: `handoff/resumo.py` e `context/resumo.py` chamam
`get_client()` direto, com system, um texto e `max_tokens` proprio. O que
`_chamar` oferece a mais -- laco de `tool_use`, `output_config`, soma de
tokens entre duas chamadas, `cache_control` sobre um prefixo que se repete --
nao tem consumidor aqui: esta chamada nao declara ferramenta, nao pede JSON,
acontece uma vez por follow-up e o prefixo e curto de mais para cachear.

**Nenhum numero de preco passa pelo modelo** -- e a terceira vez que o repo
firma isso (D7 da TEC-265, D8 da TEC-154). Por isso o texto da novidade e
montado AQUI, por `_novidade_em_palavras`, em vez de o chamador passar a
legenda pronta: a legenda carrega preco, e um parametro de texto livre
deixaria a regra na mao de quem chama.

**Este modulo faz I/O; `mensagem.py` nao faz.** A separacao e a mesma que
aquele modulo ja declara na docstring -- a regra de qual novidade vence e
pura e testavel sem Postgres; a chamada ao modelo e a leitura do resumo vivem
deste lado.
"""

import re
import time
import unicodedata
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agente.apresentacao import Ficha
from mobia.domain.agente.citacao import divergencias_de
from mobia.domain.context.repositorio import ler_resumo
from mobia.domain.followup.mensagem import QuedaDePreco
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client, motivo_do_provedor

log = structlog.get_logger(__name__)

SISTEMA_DO_FOLLOWUP = (
    "Voce e o assistente virtual de uma imobiliaria brasileira. Um lead parou "
    "de responder e vamos retomar o contato com uma novidade que JA foi "
    "escolhida -- ela vem pronta depois da sua frase, e voce nao a escreve.\n\n"
    "Escreva UMA frase curta, em portugues do Brasil, em tom de conversa, "
    "ligando o que o lead procurava a essa novidade. Nada de saudacao sem "
    "conteudo: 'oi, tudo bem?' e variacoes estao proibidas.\n\n"
    "Nao escreva preco, porcentagem nem qualquer numero: eles saem prontos "
    "abaixo da sua frase. Nao cite imovel que nao esteja no contexto. Nao "
    "prometa nada e nao negocie valor."
)

# Uma frase. O teto existe para que uma resposta longa nao pague tokens que a
# regra dos 600 caracteres vai cortar de qualquer jeito.
MAX_TOKENS_DA_ABERTURA = 120

# As palavras com que uma mensagem so de cortesia e feita. A guarda nao
# procura frase pronta: uma prosa e saudacao vazia quando TODA palavra dela
# esta aqui. "Vi que voce procurava perto da praia" tem `voce` na lista e
# passa, porque `vi` e `procurava` nao estao -- e e assim que a regra erra
# por falta, como a guarda de citacao, em vez de descartar prosa boa.
#
# Sem acento na lista porque `_sem_acento` normaliza antes de comparar: o
# modelo escreve portugues acentuado (a forma mais provavel de "ola" leva
# acento no a), e comparar bytes crus deixaria passar justamente essa.
_PALAVRAS_DE_SAUDACAO = frozenset(
    {
        "ai",
        "bem",
        "beleza",
        "blz",
        "boa",
        "bom",
        "com",
        "como",
        "dia",
        "e",
        "ei",
        "entao",
        "esta",
        "noite",
        "oi",
        "ola",
        "opa",
        "por",
        "salve",
        "ta",
        "tarde",
        "td",
        "tudo",
        "vai",
        "vc",
        "voce",
    }
)

_PALAVRA = re.compile(r"[a-z]+")


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))


def _e_so_saudacao(prosa: str) -> bool:
    """A prosa nao diz nada alem de cumprimentar. RN-13.2.

    Texto sem palavra nenhuma (so pontuacao, so emoji) cai aqui tambem, e o
    desfecho e o mesmo: nao serve de abertura.
    """
    palavras = _PALAVRA.findall(_sem_acento(prosa.lower()))
    return all(palavra in _PALAVRAS_DE_SAUDACAO for palavra in palavras)


def _novidade_em_palavras(ficha: Ficha | None, queda: QuedaDePreco | None) -> str:
    """A novidade descrita SEM numero de preco, do jeito que o modelo pode ler.

    Titulo e bairro bastam para a frase ligar o que o lead procurava ao que
    vai sair abaixo dela. O preco -- os dois, no caso da queda -- fica de fora
    por regra, e a queda entra como fato qualitativo: "caiu", nunca "caiu de X
    para Y".

    Queda sem ficha nao tem ramo proprio: `texto_do_followup` ja recusa esse
    par, e repetir a guarda aqui criaria uma segunda opiniao sobre a mesma
    invariante. A prosa e ornamento e nao e lugar de validar a montagem.
    """
    if ficha is None:
        return (
            "Nao ha imovel novo nem queda de preco; a mensagem vai convidar o "
            "lead para agendar uma visita."
        )
    onde = f"{ficha.titulo}, no bairro {ficha.bairro}"
    if queda is not None:
        return f"O preco de um imovel que o lead ja viu caiu. Imovel: {onde}."
    return f"Entrou no catalogo um imovel que casa o que o lead procurava. Imovel: {onde}."


def _turno(resumo: str | None, ficha: Ficha | None, queda: QuedaDePreco | None) -> str:
    partes = []
    if resumo:
        partes.append(f"Resumo da conversa ate agora:\n{resumo}")
    partes.append(
        f"Novidade que sai logo abaixo da sua frase:\n{_novidade_em_palavras(ficha, queda)}"
    )
    return "\n\n".join(partes)


def _candidatos(ficha: Ficha | None, queda: QuedaDePreco | None) -> list[dict[str, Any]]:
    """O que a mensagem sustenta, na forma que `divergencias_de` recebe.

    So o imovel da novidade: e o unico que a mensagem mostra. Com queda entra
    tambem o preco ANTIGO, porque ele sai impresso na mesma mensagem (`De R$
    620.000 por R$ 590.000`) -- a pergunta que a guarda faz e "o turno
    sustenta isto?", e sustenta.

    Sem `codigo` de proposito: `Ficha` nao carrega o codigo do catalogo, entao
    qualquer `AP-1004` na abertura diverge. E exatamente o caso que a D5
    descreve -- o modelo inventar um segundo imovel.
    """
    if ficha is None:
        return []
    candidatos: list[dict[str, Any]] = [{"preco_centavos": ficha.preco_centavos}]
    if queda is not None:
        candidatos.append({"preco_centavos": queda.preco_antes_centavos})
    return candidatos


async def redigir_abertura(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    ficha: Ficha | None,
    queda: QuedaDePreco | None,
) -> str | None:
    """A frase de abertura do follow-up, ou `None` quando ela nao deve ser usada.

    `None` nos quatro casos, e o chamador trata todos como "sem prefixo",
    NUNCA como erro: a chamada falhou, o texto veio vazio, o texto e so
    saudacao (RN-13.2) ou `divergencias_de` acusou citacao que a mensagem nao
    sustenta. A prosa e ornamento -- o fato sai sozinho, e por isso a
    mensagem nunca fica vazia (D6). E a mesma postura da porta de busca, que
    devolve `erro` no `tool_result` em vez de derrubar o turno.

    `ficha` e `queda` sao os MESMOS valores que vao para `texto_do_followup`:
    quem chama escolhe a novidade uma vez e passa aos dois, e e isso que
    impede a abertura de falar de um imovel e o corpo de outro.
    """
    settings = get_settings()
    comeco = time.monotonic()
    try:
        resumo = await ler_resumo(session, channel, conversation_key)
        resposta = await get_client().messages.create(
            model=settings.modelo_agente,
            max_tokens=MAX_TOKENS_DA_ABERTURA,
            system=SISTEMA_DO_FOLLOWUP,
            messages=[
                {"role": "user", "content": _turno(resumo.texto if resumo else None, ficha, queda)}
            ],
        )
    except Exception as exc:
        # Larga de proposito, e e a unica forma que atende o contrato: o
        # chamador nao tem o que fazer com uma falha daqui, e qualquer
        # excecao que subisse custaria ao lead o follow-up inteiro -- a
        # mensagem que ele ia receber existe e esta pronta sem esta frase.
        # Entram a leitura do resumo (um `ConnectionResetError` e rotineiro
        # nesta base) e a chamada ao provedor.
        #
        # `Exception` e nao `BaseException`: o `CancelledError` do ARQ
        # cancelando o job tem de continuar subindo, senao a varredura
        # seguiria enviando depois de cancelada.
        log.warning(
            "followup.abertura_descartada",
            channel=channel,
            motivo="falhou",
            erro=type(exc).__name__,
            provedor=motivo_do_provedor(exc),
        )
        return None

    if resposta.stop_reason != "end_turn":
        # `max_tokens` corta a frase no meio e ela sai parecendo inteira --
        # mesma guarda de `handoff/resumo.py`. La o desfecho e levantar,
        # porque o resumo E a entrega; aqui e descartar, porque a entrega
        # sobrevive sem a frase.
        log.warning(
            "followup.abertura_descartada",
            channel=channel,
            motivo="parada_anormal",
            stop_reason=resposta.stop_reason,
        )
        return None

    texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
    if not texto or _e_so_saudacao(texto):
        log.info("followup.abertura_descartada", channel=channel, motivo="sem_conteudo")
        return None

    divergencias = divergencias_de(
        texto,
        candidatos=_candidatos(ficha, queda),
        faixa=(None, None),
    )
    if divergencias:
        # Faixa vazia acima, e nao a do lead: a excecao que `turno.py` abre
        # para o modelo ecoar o proprio orcamento existe porque la o lead
        # acabou de falar de dinheiro. Aqui o prompt PROIBE numero, ninguem
        # esta ecoando ninguem, e toda cifra na abertura e coisa que o modelo
        # trouxe sozinho.
        #
        # A prosa barrada nao entra no log, pela mesma razao de
        # `citacao.bloqueada`: registra-la criaria no log exatamente o que a
        # guarda impediu de sair. Os valores divergentes entram -- sao o
        # unico dado que torna a linha investigavel.
        log.error(
            "followup.abertura_descartada",
            channel=channel,
            motivo="citacao_divergente",
            tipos=[d.tipo for d in divergencias],
            citados=[d.citado for d in divergencias],
        )
        return None

    tokens_in = resposta.usage.input_tokens
    tokens_out = resposta.usage.output_tokens
    # So numeros e id de modelo, nunca o resumo que entrou nem a frase que
    # saiu. `caracteres` existe porque e ele que diz quanto da prosa o teto de
    # 600 vai poder manter.
    log.info(
        "followup.abertura_redigida",
        channel=channel,
        modelo=settings.modelo_agente,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=int((time.monotonic() - comeco) * 1000),
        caracteres=len(texto),
        custo_usd=str(custo_em_dolar(settings.modelo_agente, tokens_in, tokens_out)),
    )
    return texto
