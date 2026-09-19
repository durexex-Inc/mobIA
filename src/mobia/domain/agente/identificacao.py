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
# **Sao DUAS regras, com formas diferentes, e o resto deste comentario e a
# razao de cada uma ser do jeito que e.**
#
# 1. `_PADRAO_DE_SEGUNDA_PESSOA` -- sujeito "voce"/"vc" junto do predicado, em
#    qualquer lugar da fala. "voce" so pode apontar para quem esta respondendo
#    o lead, entao o sujeito sozinho ja resolve e nada precisa olhar para o
#    que vem depois.
#
# 2. `_PADRAO_DE_PRIMEIRA_PESSOA` -- "to/estou falando com <sintagma>", onde o
#    sujeito e implicito na conjugacao (1a pessoa do singular, sempre o
#    proprio LEAD). Aqui o sujeito NAO basta: a regra exige tambem que o
#    sintagma esteja NU e no fim da frase. A razao esta na fix round 4, mais
#    abaixo.
#
# **Historico das faixas que ja foram largas, porque cada uma e uma classe de
# defeito que pode voltar:**
#
# - Ate a fix round 1 (review) este comentario afirmava criterio de sujeito e
#   a tabela nao cumpria: os termos eram so predicado ("e um robo", "tudo
#   automatico"), sem exigir de quem se fala. A mesma rodada acrescentou o
#   `\b` de fechamento do padrao (ver `_PADRAO_DE_SEGUNDA_PESSOA`).
# - A fix round 2 (review) exigiu o sujeito por extenso em cada termo, porque
#   `_normalizar` tira acento e "e" de conjuncao vira o mesmo token de "e"
#   verbo: "o apartamento tem ar condicionado e uma maquina de lavar" casava
#   "e uma maquina".
# - A fix round 3 (review) tirou a familia "isso"/"isso ai"/"isso aqui"
#   inteira. "isso" e ANAFORICO: o antecedente pode ser qualquer coisa que a
#   conversa acabou de citar -- "isso e um robo que limpa a piscina sozinho"
#   aponta para um aspirador, nao para o interlocutor. Nao ha aperto de
#   palavra-chave que resolva anafora, porque "isso e automatico ou tem alguem
#   ai?" e "isso e automatico ou tem alguem que assina esse contrato?" so se
#   distinguem pelo discurso anterior, que este detector nunca ve (recebe um
#   turno so, sem historico).
#
# **A perda da round 3 e barata, e ela tem numero.** A sonda da TEC-139
# (`evals/relatorios/2026-09-11-tec-139-identificacao-036d973.md`) mediu
# exatamente a frasagem que saiu, "isso e automatico ou tem alguem ai?" (caso
# 3): confirma SIM, oferece corretor SIM -- o modelo ja resolve essa sozinho.
# Os dois casos que a sonda mediu FALHANDO -- "vc e um robo?" e "to falando
# com uma pessoa?" (casos 1 e 2) -- sao a razao desta card existir, e cada um
# e coberto por uma das duas regras acima.
# `test_a_pergunta_com_isso_nao_dispara_e_e_lacuna_declarada`
# (`tests/unit/test_pergunta_se_e_robo.py`) fixa a lacuna como decisao, no
# molde de `test_o_interlocutor_de_terceiro_dispara_e_e_lacuna_declarada`
# (`tests/unit/test_deteccao_de_humano.py`).
#
# **Fix round 4 (review): sujeito certo, pergunta errada.** "estou falando com
# uma pessoa da locacao?" tem o sujeito inequivoco que as tres rodadas
# anteriores perseguiram -- e mesmo assim nao e pergunta de identidade, e
# pergunta de ROTEAMENTO: o lead quer saber se caiu no setor certo, nao se
# fala com uma maquina. "setor de locacao", "financeiro", "juridico",
# "vendas", "suporte" sao vocabulario corrente de atendimento imobiliario,
# entao a classe e frequente.
#
# O discriminante nao esta no sujeito nem no termo -- esta no que vem DEPOIS
# do sintagma, dentro da mesma frase. "uma pessoa" sem modificador pergunta
# pela NATUREZA do interlocutor; "uma pessoa da locacao" pergunta QUAL
# interlocutor. Por isso `_PADRAO_DE_PRIMEIRA_PESSOA` exige que o sintagma
# termine a frase, admitindo depois dele apenas duas coisas:
#
# - um `_REFORCOS_DE_IDENTIDADE` ("de verdade", "mesmo", "real", ...), que
#   aperta a mesma pergunta em vez de restringir o sintagma;
# - "ou" seguido do resto da frase, que e a alternativa explicita ("...ou com
#   um robo?"). O primeiro membro da disjuncao ja e o sintagma NU, entao a
#   frase comeca perguntando pela natureza do interlocutor mesmo quando o
#   segundo membro nomeia um setor -- ver o residuo 1, abaixo.
#
# **Nao da para barrar a preposicao e pronto, e "de verdade" e a prova.**
# "estou falando com uma pessoa de verdade?" e provavelmente a frasagem mais
# natural deste eixo e carrega a mesma preposicao de "de vendas". Um lookahead
# negativo sobre `d[aeo]s?` barraria as duas. Por isso a regra e uma ALLOWLIST
# fechada ancorada em `$`, e nao uma blocklist de preposicao: com a allowlist,
# palavra desconhecida depois do sintagma derruba o casamento por omissao --
# inclusive as que nenhuma blocklist de preposicao pegaria, como "estou
# falando com uma pessoa responsavel pela locacao?" ou "...com uma pessoa
# especializada em investimento?", que sao adjetivo e nao preposicao.
#
# **O corte e por FRASE, nao pela mensagem inteira** (`_FIM_DE_FRASE`), senao
# "to falando com uma pessoa? preciso de ajuda" nunca dispararia --
# `_normalizar` troca pontuacao por espaco, e ai o `$` cairia so no fim do
# recado. O corte nao inclui `\n` nem virgula: quebra de linha no meio da
# frase e comum no WhatsApp, e cortar ali parteria o proprio termo. Custo
# aceito: sem pontuacao nenhuma, "to falando com uma pessoa preciso de ajuda"
# nao dispara.
#
# **Dois residuos conhecidos da round 4, medidos e nao consertados.**
#
# 1. Depois de "ou" a regra aceita qualquer coisa, entao "estou falando com
#    uma pessoa ou com alguem do financeiro?" dispara. A frase mistura as duas
#    perguntas e e rara o bastante para nao valer uma segunda allowlist, que
#    teria de enumerar como se nomeia uma maquina.
# 2. O detector nao separa PERGUNTA de AFIRMACAO, porque `_normalizar` come a
#    pontuacao: "ja estou falando com uma pessoa." dispara igual a "to falando
#    com uma pessoa?". Exigir "?" fecharia isso, mas derrubaria junto a
#    pergunta sem ponto de interrogacao, que no WhatsApp e comum -- e ai o
#    conserto custaria mais recall do que a classe que ele evita, que precisa
#    de um contexto raro (o lead relatando atendimento paralelo) e cujo
#    complemento quase sempre nomeia de quem se fala ("...uma pessoa DA SUA
#    EQUIPE"), o que a propria regra do sintagma nu ja barra.
#
# **A recall e inverificavel, e isso esta declarado no desenho (D3).** Nao ha
# fala real deste eixo em `evals/corpus/` -- zero ocorrencias nos cinco
# arquivos --, entao estes termos sao invencao. O que o teste prova e o lado
# negativo: que nenhum dos turnos reais do corpus dispara.
_TERMOS_DE_SEGUNDA_PESSOA: tuple[str, ...] = (
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
)

# Primeira pessoa: "[eu] to/estou falando com <sintagma>". O sujeito e
# implicito na conjugacao verbal e so pode ser o proprio LEAD -- mas, ao
# contrario da segunda pessoa, isso sozinho nao basta (fix round 4, no
# comentario acima). Quem fecha a regra e `_REFORCOS_DE_IDENTIDADE` mais a
# ancora de fim de frase em `_PADRAO_DE_PRIMEIRA_PESSOA`.
_TERMOS_DE_PRIMEIRA_PESSOA: tuple[str, ...] = (
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

# O que pode vir depois do sintagma sem deixar de ser pergunta de identidade.
# Todos APERTAM a mesma pergunta ("de verdade", "de carne e osso", "real",
# "viva", "humana", "mesmo") ou sao deixis sem conteudo restritivo ("ai",
# "agora", "ne") -- nenhum nomeia setor, papel ou atributo, que e o que
# viraria roteamento. Concordancia nos dois generos porque o sintagma varia
# ("uma pessoa viva", "um humano vivo").
#
# **"aqui" ficou de fora e "ai" entrou, e a diferenca nao e arbitraria.** "ai"
# aponta para onde o INTERLOCUTOR esta ("tem uma pessoa ai?"), que e a propria
# pergunta desta faixa; "aqui" aponta para onde o LEAD esta e nao diz nada
# sobre quem responde. Mesmo criterio de sempre: o termo tem de falar do
# interlocutor.
_REFORCOS_DE_IDENTIDADE: tuple[str, ...] = (
    "de verdade",
    "de carne e osso",
    "real",
    "viva",
    "vivo",
    "humana",
    "humano",
    "mesmo",
    "ai",
    "agora",
    "ne",
)

# `\b` no INICIO E NO FIM de cada alternativa. O do inicio e pelo mesmo motivo
# de `_PADRAO_POR_MOTIVO` em `context/gatilhos.py`: sem ele, um termo casaria
# escondido dentro de uma palavra maior.
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
_PADRAO_DE_SEGUNDA_PESSOA = re.compile(
    r"\b(?:" + "|".join(re.escape(termo) for termo in _TERMOS_DE_SEGUNDA_PESSOA) + r")\b"
)

# Aqui o fechamento nao e `\b` e sim `$`: depois do sintagma so cabem zero ou
# mais reforcos de identidade e, opcionalmente, "ou" com o resto da frase.
# Qualquer outra palavra derruba o casamento -- que e exatamente o que separa
# "...uma pessoa de verdade?" de "...uma pessoa de vendas?". O `\b` de
# abertura continua necessario pelo motivo de sempre: sem ele, "to falando"
# casaria dentro de "canto falando".
#
# Nao falta `\b` antes do `$`: ou o sintagma termina a frase, ou o que vem
# depois comeca com `\s+` -- nos dois casos ha limite de palavra.
_PADRAO_DE_PRIMEIRA_PESSOA = re.compile(
    r"\b(?:"
    + "|".join(re.escape(termo) for termo in _TERMOS_DE_PRIMEIRA_PESSOA)
    + r")(?:\s+(?:"
    + "|".join(re.escape(reforco) for reforco in _REFORCOS_DE_IDENTIDADE)
    + r"))*(?:\s+ou\b.*)?$"
)

# Ponto final, interrogacao, exclamacao e ponto-e-virgula -- sem `\n` e sem
# virgula, de proposito (ver a fix round 4 no comentario de cima).
_FIM_DE_FRASE = re.compile(r"[?!.;]+")

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

    Duas regras, descritas no comentario de `_TERMOS_DE_SEGUNDA_PESSOA`: a de
    segunda pessoa corre sobre o recado inteiro normalizado, a de primeira
    pessoa corre frase a frase porque precisa do fim da frase como ancora.

    A de segunda pessoa NAO corre frase a frase de proposito: ela nao ganha
    nada com o corte e perderia o termo que a pontuacao partisse no meio.

    Nunca levanta: texto sem letra nenhuma normaliza para vazio e devolve
    False, mesma garantia de `gatilhos_de`.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    if _PADRAO_DE_SEGUNDA_PESSOA.search(normalizado) is not None:
        return True
    return any(
        _PADRAO_DE_PRIMEIRA_PESSOA.search(frase) is not None
        for frase in (_normalizar(parte) for parte in _FIM_DE_FRASE.split(texto))
        if frase
    )
