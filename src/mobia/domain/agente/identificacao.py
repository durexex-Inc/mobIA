"""Quem o agente diz que e, e quando ele diz (TEC-139).

**A fronteira de conversa que este modulo precisa nao existe, ainda que a
TEC-138 ja tenha criado uma entidade `Conversa`.** A emenda E-01 da TEC-148
sob a RN-05.7 registra que `conversation_key` e o id externo do LEAD, que
nenhuma tabela distinguia conversas, e que introduzir a entidade foi
deferido -- sem dizer para quem. Quem nomeia a TEC-130 como a criadora e a
propria emenda E-01 desta card (TEC-139) sob a RN-04.1. A TEC-138 chegou
primeiro, mas `Conversa` (`domain/conversa/models.py`) guarda SE a conversa
esta encerrada, com a MESMA chave de sempre -- nao QUANDO uma sessao comeca
e a proxima termina, que e o que este modulo perguntaria se pudesse. Ate
isso existir, o substituto abaixo continua de pe.

"Conversa nova" e uma janela de silencio: nada deste lead nos ultimos 30
dias. O numero e `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA`, que a TEC-138
tambem importa para medir a janela do proprio encerramento
(`conversa/repositorio.py`) -- usar outro numero aqui criaria duas
definicoes de "quanto tempo e silencio" no mesmo sistema.
"""

import re
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message

# Mesmo limiar da TEC-130. Quando aquela card chegar, este modulo passa a
# perguntar a entidade em vez de derivar, e esta constante sai.
DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA = 30


async def e_conversa_nova(
    session_factory: async_sessionmaker[AsyncSession],
    message: Message,
    *,
    agora: datetime,
) -> bool:
    """Houve silencio longo o bastante ANTES desta mensagem?

    **O predicado olha para tras no tempo, nao para "qualquer outra
    mensagem".** A ingestao grava a fala em `messages` antes de o worker
    rodar (`IngestionService._persist`), e faz isso para a LISTA inteira do
    payload de uma vez, so depois enfileirando uma a uma. Duas mensagens no
    mesmo webhook -- ou dois webhooks em sequencia, que e como o lead manda
    "oi" e depois "quero um apto de 2 quartos" -- deixam as duas linhas
    commitadas antes de qualquer turno rodar. Uma versao que exclui so a
    mensagem corrente (`Message.id != message.id`) acha a OUTRA mensagem da
    rajada dos dois lados: o turno de A ve B e o turno de B ve A, nenhum dos
    dois se identifica, e a conversa fica sem identificacao ate 30 dias de
    silencio. `Message.created_at < message.created_at` fecha isso: só uma
    mensagem ANTERIOR no tempo conta, entao a primeira da rajada nao encontra
    nada e a segunda encontra a primeira.

    O desempate por `Message.id` cobre o caso em que duas linhas da mesma
    rajada compartilham o `created_at` do servidor (dois inserts na mesma
    transacao podem ter o mesmo carimbo): sem ele, as duas ficariam de novo
    cegas uma para a outra, o mesmo defeito da rajada por outra porta.

    Empate na janela de 30 dias resolvido para o lado conservador:
    exatamente 30 dias ainda nao abre conversa nova. Nao repetir a
    identificacao incomoda menos que repeti-la, e o empate ficar ao acaso e o
    defeito que a TEC-229 documentou.

    `agora` entra por parametro e nao sai de `datetime.now()` aqui dentro,
    como `candidatos_a_followup` (`followup/repositorio.py`) e
    `tentativa_devida` (`followup/cadencia.py`) ja fazem: sem isso nenhum
    teste consegue posicionar o relogio no exato instante em que carimbou a
    mensagem anterior, e o teste do empate deixaria de exercitar um empate.
    """
    corte = agora - timedelta(days=DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA)
    async with session_factory() as session:
        anterior = await session.scalar(
            select(Message.id)
            .where(
                Message.channel == message.channel,
                Message.conversation_key == message.conversation_key,
                Message.created_at >= corte,
                or_(
                    Message.created_at < message.created_at,
                    and_(
                        Message.created_at == message.created_at,
                        Message.id < message.id,
                    ),
                ),
            )
            .limit(1)
        )
    return anterior is None


# Generico de proposito: nao ha nome de imobiliaria configuravel em
# `app/config.py`, e a propria RN-04.1 e generica ("assistente virtual da
# imobiliária"). Inventar um campo de configuracao que ninguem pediu seria
# maior que esta card.
#
# Nao se apresenta com nome de gente: a mesma regra proibe fingir ser pessoa
# fisica, e "Oi, sou a Marina" violaria o que este texto existe para cumprir.
#
# Oferece o corretor porque a terceira regra da card pede isso ao se
# identificar -- aqui no caminho proativo.
TEXTO_DA_IDENTIFICACAO = (
    "Oi! Sou o assistente virtual da imobiliária. Posso te ajudar a encontrar "
    "um imóvel, e a qualquer momento te passo para um corretor."
)

# Linha em branco e nao espaco: as duas frases tem autores diferentes -- uma e
# constante do repositorio, a outra e resposta ao lead -- e coladas parecem
# uma frase so mal pontuada.
SEPARADOR_DA_IDENTIFICACAO = "\n\n"


# O lead perguntando se fala com uma maquina (TEC-272), para anexar a oferta
# de corretor que o CA-04.1 pede junto da confirmacao.
#
# **Faixa estrita, pelo argumento de `context/gatilhos.py` e nao pelo do
# opt-out.** La deixar de detectar e violacao de LGPD e a faixa inequivoca e
# generosa. Aqui e o inverso: falso negativo devolve o comportamento de hoje
# (o lead nao recebe a oferta, e a identificacao proativa ja cobriu quem
# perguntou cedo), e falso positivo gruda uma oferta de corretor numa fala que
# nao perguntou nada -- que e o segundo criterio de aceite desta card, e e
# visivel ao lead.
#
# **O criterio e o SUJEITO junto do predicado, e o sujeito e sempre O
# INTERLOCUTOR -- nunca o substantivo sozinho, e nunca qualquer sujeito.**
# Ate a fix round 1 (review) este comentario ja fazia essa afirmacao e a
# tabela nao cumpria: os termos eram so o predicado ("e um robo", "e humano
# ou maquina", "tudo automatico"), sem exigir de quem se fala. A fix round 2
# (review) tentou consertar exigindo um sujeito por extenso -- mas um dos
# sujeitos aceitos, "isso", reabriu a mesma classe pela fix round 3: "isso" e
# ANAFORICO, e o antecedente pode ser qualquer coisa que a conversa tenha
# acabado de citar, nunca so o interlocutor. "isso e um robo que limpa a
# piscina sozinho" tem "isso" apontando para um ROBO ASPIRADOR DE PISCINA, um
# produto do imovel, nao para quem esta respondendo o lead. O token "isso"
# aparece na frase; o REFERENTE dele nao e o interlocutor -- e a afirmacao
# acima fala do referente, nao do token, entao exigir o token nao bastava.
#
# **A familia "isso"/"isso ai"/"isso aqui" saiu inteira, e nao foi apertada.**
# Nao ha aperto de palavra-chave que resolva anafora: "isso e automatico ou
# tem alguem ai?" (a pergunta que a card quer pegar) e "isso e automatico ou
# tem alguem que assina manualmente esse contrato?" (fala sobre o CONTRATO)
# sao estruturalmente identicas -- a unica diferenca e o que "isso" retoma, e
# isso mora no discurso anterior, que este detector nunca ve (recebe um
# turno so, sem historico). Fechar o segundo caso sem perder o primeiro
# exigiria casar a frase inteira da card, que e decorar o caso de teste.
#
# **A perda e barata, e ela tem numero.** A sonda da TEC-139
# (`evals/relatorios/2026-09-11-tec-139-identificacao-036d973.md`) mediu
# exatamente a frasagem que sai, "isso e automatico ou tem alguem ai?" (caso
# 3): confirma SIM, oferece corretor SIM -- o modelo ja resolve essa sozinha,
# sem ajuda deste detector. Os dois casos que a sonda mediu FALHANDO --
# "vc e um robo?" e "to falando com uma pessoa?" (casos 1 e 2), os dois com
# sujeito inequivoco -- sao a razao desta card existir, e continuam cobertos.
# `test_a_pergunta_com_isso_nao_dispara_e_e_lacuna_declarada`
# (`tests/unit/test_pergunta_se_e_robo.py`) fixa esta lacuna como decisao, no
# molde de `test_o_interlocutor_de_terceiro_dispara_e_e_lacuna_declarada`
# (`tests/unit/test_deteccao_de_humano.py`).
#
# **O sujeito aceito agora e so o que nunca e anaforico:** segunda pessoa
# ("voce", "vc") -- que so pode se referir a quem esta na conversa -- ou
# primeira pessoa implicita na conjugacao ("to falando com...", "estou
# falando com..." -- o sujeito e sempre o proprio LEAD). Nenhum termo aqui e
# mais predicado sozinho, e nenhum sujeito aqui precisa de antecedente fora
# da frase.
#
# **A recall e inverificavel, e isso esta declarado no desenho (D3).** Nao ha
# fala real deste eixo em `evals/corpus/` -- zero ocorrencias nos cinco
# arquivos --, entao estes termos sao invencao. O que o teste prova e o lado
# negativo: que nenhum dos turnos reais do corpus dispara.
_TERMOS_DA_PERGUNTA: tuple[str, ...] = (
    # SUJEITO (voce/vc) + verbo de ligacao (e/eh) + ROBO ou BOT.
    "voce e um robo",
    "voce e robo",
    "voce eh um robo",
    "vc e um robo",
    "vc e robo",
    "vc eh um robo",
    "voce e um bot",
    "vc e um bot",
    # SUJEITO + verbo + HUMANO/MAQUINA, nos dois sentidos -- "voce e humano
    # ou maquina?" e "voce e maquina ou humano?" sao a mesma pergunta.
    "voce e humano ou maquina",
    "voce e maquina ou humano",
    "vc e humano ou maquina",
    "vc e maquina ou humano",
    # SUJEITO + verbo + GENTE, sempre com o "ou" colado: sem ele, "voce e
    # gente" sozinho e afirmacao, nao pergunta, e nao ha frasagem da card
    # que a use assim.
    "voce e gente ou",
    "vc e gente ou",
    # Primeira pessoa: "[eu] to/estou falando com X" -- o sujeito e
    # implicito na conjugacao verbal (1a pessoa do singular), e so pode ser
    # o proprio LEAD perguntando com quem fala.
    "to falando com uma pessoa",
    "to falando com um humano",
    "to falando com uma maquina",
    "to falando com um robo",
    "to falando com gente",
    "estou falando com uma pessoa",
    "estou falando com um humano",
    "estou falando com uma maquina",
    "estou falando com um robo",
    "estou falando com gente",
)

# Um padrao so, com `\b` no INICIO E NO FIM de cada alternativa. O do inicio
# e pelo mesmo motivo de `_PADRAO_POR_MOTIVO` em `context/gatilhos.py`: sem
# ele, um termo casaria escondido dentro de uma palavra maior.
#
# **O do fim nao tem equivalente em `gatilhos.py`, e foi bug ate a fix round
# 1 (review) -- o comentario daquela rodada chegou a afirmar uma protecao que
# o codigo nao dava.** `gatilhos.py` dispensa o fechamento porque o problema
# que aquela correcao resolvia era outro: o OBJETO (`visita`, `proposta`,
# ...) ser prefixo de palavra maior ("visitante") nunca foi o risco ali.
# Aqui e exatamente esse risco: sem o `\b` de fechamento, um termo terminado
# em palavra curta casaria escondido dentro de uma palavra maior --
# "voce e um bot" dentro de "voce e um botao (esse controle)", por exemplo.
# `re.escape` porque os termos sao literais, nunca regex.
_PADRAO_DA_PERGUNTA = re.compile(
    r"\b(?:" + "|".join(re.escape(termo) for termo in _TERMOS_DA_PERGUNTA) + r")\b"
)

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    **E o mesmo transform de `optout/deteccao.py` e de `context/gatilhos.py`, e
    a terceira copia e deliberada pela mesma razao que a segunda.** Aquele
    modulo registra que compartilhar acoplaria um detector comercial a um
    detector de decisao de LGPD. Aqui a copia e ainda mais barata de justificar:
    este detector so decide se uma frase e anexada a uma resposta, e nao tem
    negocio nenhum puxando mudanca no caminho regulado.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", sem_acento)).strip()


def perguntou_se_e_robo(texto: str) -> bool:
    """O lead perguntou se esta falando com uma maquina.

    Nunca levanta: texto sem letra nenhuma normaliza para vazio e devolve
    False, mesma garantia de `gatilhos_de`.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    return _PADRAO_DA_PERGUNTA.search(normalizado) is not None
