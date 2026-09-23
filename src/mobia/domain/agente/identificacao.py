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

from mobia.domain.conversa.regras import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
from mobia.domain.messages.models import Message

# **A TEC-130 chegou e este modulo continua derivando, de proposito.** O
# comentario que morava aqui prometia que, quando aquela card chegasse, o
# modulo passaria a "perguntar a entidade em vez de derivar". A D3 do desenho
# dela declinou: perguntar a entidade poe a varredura diaria no caminho
# critico da apresentacao -- com ela parada, ou apenas ainda nao executada no
# dia, a conversa continuaria ATIVA, esta funcao devolveria False e o lead que
# sumiu por meses voltaria sem ninguem se apresentar, em silencio. Derivar e o
# que torna a resposta verdadeira independentemente do cron. O que saiu daqui
# foi so a constante, para `conversa/regras.py`, que e onde os outros dois
# leitores dela vivem.
#
# **O CONTEXTO nao passa mais por aqui.** A dobra que separa a conversa nova
# da anterior chegou a ser ligada por esta funcao e deixou de ser, na rodada
# final de revisao da TEC-130: numa rajada de volta, quem carrega o turno e a
# mensagem mais nova do lote e ela encontra a irma de segundos atras, entao o
# predicado devolvia False justamente na reabertura. Quem decide a dobra e
# `_fronteira_do_silencio` (`context/montagem.py`), que procura um intervalo de
# 30 dias entre dois literais vizinhos. **A rajada continua cegando o que
# sobrou aqui** -- identificacao e apresentacao --, e isso e a lacuna
# pre-existente da TEC-139, nao da TEC-130.


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
# **Sao DUAS regras, com formas diferentes.**
#
# 1. `_PADRAO_DE_SEGUNDA_PESSOA` -- sujeito "voce"/"vc" junto do predicado, em
#    qualquer clausula da fala. "voce" so pode apontar para quem esta
#    respondendo o lead, entao o sujeito sozinho ja resolve e nada precisa
#    olhar para o que vem depois.
#
# 2. `_PADRAO_DE_PRIMEIRA_PESSOA` -- "to/estou falando com <sintagma>", onde o
#    sujeito e implicito na conjugacao (1a pessoa do singular, sempre o
#    proprio LEAD). Aqui o sujeito NAO basta: a regra exige tambem que o
#    sintagma esteja NU e no fim da pergunta.
#
# **Faixa estrita, pelo argumento de `context/gatilhos.py` e nao pelo do
# opt-out.** La deixar de detectar e violacao de LGPD e a faixa inequivoca e
# generosa. Aqui e o inverso: falso negativo devolve o comportamento de hoje
# (o lead nao recebe a oferta, e a identificacao proativa ja cobriu quem
# perguntou cedo), e falso positivo gruda uma oferta de corretor numa fala que
# nao perguntou nada -- que e o segundo criterio de aceite desta card, e e
# visivel ao lead.
#
# **Acaba aqui o criterio.** As duas regras acima mais a assimetria de erro
# sao tudo o que este modulo decide; a forma exata de cada padrao esta no
# comentario dele.
#
# ---------------------------------------------------------------------------
# **Historico**
# ---------------------------------------------------------------------------
#
# Daqui para baixo nada acrescenta criterio. Sao as cinco rodadas de fix que
# deram as duas regras a forma que elas tem, os quatro residuos que essas
# rodadas mediram e decidiram nao consertar, e a declaracao de recall. Cada
# bloco justifica uma decisao viva -- por isso nenhum saiu --, mas quem so
# precisa saber o que o detector decide ja leu tudo.
#
# **As faixas que ja foram largas, porque cada uma e uma classe de defeito que
# pode voltar:**
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
# do sintagma, dentro da mesma pergunta. "uma pessoa" sem modificador pergunta
# pela NATUREZA do interlocutor; "uma pessoa da locacao" pergunta QUAL
# interlocutor. Por isso `_PADRAO_DE_PRIMEIRA_PESSOA` exige que o sintagma
# termine a pergunta, admitindo depois dele apenas duas coisas:
#
# - um `_REFORCOS_DE_IDENTIDADE` ("de verdade", "mesmo", "real", ...) ou um
#   encerrador de turno ("hein", "viu", risada), que apertam a mesma pergunta
#   ou nao dizem nada, em vez de restringir o sintagma;
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
# **O corte e no PONTO DE INTERROGACAO, nao em fim de frase qualquer**
# (`_FIM_DA_PERGUNTA`). Algum corte e preciso, senao "to falando com uma
# pessoa? preciso de ajuda" nunca dispararia -- `_normalizar` troca pontuacao
# por espaco, e ai o `$` cairia so no fim do recado inteiro.
#
# **Mas cortar em `[?!.;]`, como a fix round 4 fazia, reabria a classe que ela
# existe para fechar** -- foi o Critical da fix round 5. "to falando com uma
# pessoa... da locacao?" tem reticencias ANTES do complemento, entao o corte
# caia cedo, o `$` caia junto e o complemento de setor saia da frase sem nunca
# ser olhado. Reticencias sao a pontuacao mais comum do WhatsApp brasileiro
# depois do proprio `?`, e o mesmo valia para "!" e ";" no meio do recado.
#
# Cortar so em `?` nao e remendo, e a regra certa: a ancora existe para achar
# o fim de uma PERGUNTA, e `?` e o unico sinal que marca isso. Ponto, ponto e
# virgula e exclamacao terminam frase sem terminar pergunta -- e uma frase
# terminada em ponto quase sempre e afirmacao, que nao e o que este detector
# procura. `\n` e virgula ficam de fora pelo motivo de sempre: quebra de linha
# no meio da frase e comum no WhatsApp, e cortar ali parteria o proprio termo.
#
# Custo aceito, e ele cresceu de proposito nesta rodada: sem `?` nenhum, "to
# falando com uma pessoa preciso de ajuda" e "to falando com uma pessoa.
# preciso de ajuda" nao disparam.
#
# **Quatro residuos conhecidos, medidos e nao consertados.**
#
# 1. Depois de "ou" a regra aceita qualquer coisa, entao "estou falando com
#    uma pessoa ou com alguem do financeiro?" dispara. A frase mistura as duas
#    perguntas e e rara o bastante para nao valer uma segunda allowlist, que
#    teria de enumerar como se nomeia uma maquina.
#    `test_disjuncao_com_setor_dispara_e_e_lacuna_declarada`
#    (`tests/unit/test_pergunta_se_e_robo.py`) trava a lacuna.
# 2. **Um `?` antes do complemento ainda corta cedo.** O Critical da round 5
#    (reticencias, "!" e ";") foi fechado tirando esses sinais do corte, mas o
#    `?` tem de continuar cortando -- e por isso "estou falando com uma
#    pessoa? da locacao?" dispara pela primeira frase. Aqui, ao contrario das
#    reticencias, o lead escreveu duas perguntas de verdade, e a primeira e
#    mesmo de identidade -- entao a oferta nao cai em fala que nao perguntou
#    nada. E o residuo mais benigno dos quatro.
#    `test_interrogacao_antes_do_complemento_dispara_e_e_lacuna_declarada`
#    (`tests/unit/test_pergunta_se_e_robo.py`) trava a lacuna.
#
#    **Os dois primeiros residuos ganharam teste na revisao final (M5).** Ate
#    ali eram os unicos declarados so em prosa, enquanto o 3 e o 4 ja tinham o
#    seu -- e sao justamente os dois que DISPARAM, entao prosa sozinha nao
#    avisaria se o comportamento mudasse.
# 3. **O detector nao separa PERGUNTA de AFIRMACAO, e isso atravessa AS DUAS
#    regras.** Em primeira pessoa, "estou falando com uma pessoa agora."
#    dispara -- o lead dizendo que fala com outro corretor neste momento --,
#    porque "agora" e "ai" sao encerradores validos e `_normalizar` come o
#    ponto. Em segunda pessoa e pior, e e a classe (C) da fix round 5: o
#    idioma de elogio brasileiro ("nossa, vc e um robo de tao rapido!") e fala
#    corrente e nao pergunta nada.
#
#    **A mitigacao do item anterior nao vale aqui, e e importante nao
#    confundir as duas.** Em primeira pessoa o caso realista traz complemento
#    ("...uma pessoa DA SUA EQUIPE"), e a regra do sintagma nu ja o barra. Em
#    segunda pessoa NAO EXISTE regra de sintagma nu: `_PADRAO_DE_SEGUNDA_PESSOA`
#    e alternacao de literais com `\b`, sem guarda de complemento, entao nada
#    ali filtra a afirmacao.
#
#    Fica declarado e nao consertado porque o dano e baixo, e por um motivo
#    que as quatro classes anteriores nao tinham: nessas falas o lead JA esta
#    tratando o interlocutor como maquina, entao a oferta de corretor e
#    inofensiva ou ate oportuna -- diferente de cair em fala sobre portao,
#    piscina, maquina de lavar ou setor. O conserto exigiria o "?", que
#    derrubaria a pergunta sem ponto de interrogacao.
#    `test_a_afirmacao_dispara_e_e_lacuna_declarada`
#    (`tests/unit/test_pergunta_se_e_robo.py`) trava a lacuna.
#
# 4. **O corte por clausula da regra de segunda pessoa (Task 2 do TEC-272,
#    ver `_CORTE_DE_CLAUSULA` abaixo) nao fecha conjuncao sem pontuacao.** "no
#    pacote vem voce e um robo aspirador?" e uma clausula so -- nao ha
#    `[?!.;]` nenhum entre o sujeito e o predicado --, entao o corte nao tem o
#    que cortar e o termo casa do mesmo jeito. Dos 7 casos medidos da classe
#    de fronteira de frase, 5 tinham pontuacao no meio e fecharam com o corte;
#    estes 2 nao. Fechar exigiria cortar tambem por conjuncao ("e"/"ou"), o
#    que corta frase legitima demais para valer a pena aqui.
#    `test_conjuncao_sem_pontuacao_e_lacuna_declarada`
#    (`tests/unit/test_pergunta_se_e_robo.py`) trava a lacuna.
#
# **A recall e inverificavel, e isso esta declarado no desenho (D3).** Nao ha
# fala real deste eixo em `evals/corpus/` -- zero ocorrencias nos cinco
# arquivos --, entao estes termos sao invencao. O que o teste prova e o lado
# negativo: que nenhum dos turnos reais do corpus dispara.
#
# **Inverificavel nao quer dizer informe: a FORMA da perda foi medida, e fica
# escrita aqui para a proxima rodada saber onde ampliar sem redescobrir.** O
# eixo robo/bot esta bem coberto nas duas regras; humano/maquina/gente so
# existe na forma DISJUNTIVA ("voce e humano ou maquina"), entao
# "voce e uma maquina?" nao dispara; e nada cobre os nomes que o proprio
# produto usa -- IA, chatbot e "assistente virtual" sao todos False, sendo
# que **"assistente virtual" e literalmente o termo do CA-04.1**. Tambem fica
# de fora o pedido de presenca sem sujeito ("tem um humano ai?"), que saiu da
# tabela na fix round 1. Nenhum destes e bug: a D2 do desenho autoriza a perda
# de recall, e cada termo novo e uma classe de falso positivo a medir antes.
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
    # "eh" tambem para BOT, e nao so para ROBO (fix da revisao final, M3).
    # Pelo mesmo argumento que o comentario de `_REFORCOS_DE_IDENTIDADE` usa
    # para admitir "neh": a tabela ja aceitava "eh" no lado do robo, entao
    # recusa-lo no lado do bot era incoerencia interna, nao decisao. Custo de
    # falso positivo zero pelo criterio desta faixa -- o sujeito continua
    # exigido por extenso, e "eh" e token proprio depois de `_normalizar`.
    "voce eh um bot",
    "vc eh um bot",
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
# ancora de fim de pergunta em `_PADRAO_DE_PRIMEIRA_PESSOA`.
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
# Duas familias, e nenhuma nomeia setor, papel ou atributo -- que e o que
# viraria roteamento:
#
# 1. **Reforco de identidade** ("de verdade", "de carne e osso", "real",
#    "viva", "humana"), que aperta a mesma pergunta. Concordancia nos dois
#    generos porque o sintagma varia ("uma pessoa viva", "um humano vivo").
# 2. **Encerrador de turno** -- deixis e marcador de discurso sem conteudo
#    restritivo ("hein", "viu", "certo", "serio", "por favor", "ai", "agora",
#    "ainda", risada). A fix round 5 acrescentou doze deles: todos disparavam
#    antes da round 4 e a ancora em `$` os tinha derrubado junto com o
#    roteamento, o que era perda de recall pura.
#
# **"neh" entra porque "eh" ja entrava.** `_TERMOS_DE_SEGUNDA_PESSOA` aceita
# "vc eh um robo" para "é"; nao aceitar "neh" para "né" era incoerencia
# interna da tabela, nao decisao.
#
# **"certo" e "serio" entram no masculino so, e isso e o que os mantem
# seguros.** Como marcador de discurso eles sao invariaveis ("..., certo?"),
# e como adjetivo concordam com o sintagma -- "uma pessoa certa" e roteamento
# ("a pessoa certa para isso"), e continua barrada porque "certa" nao esta
# aqui.
#
# **"aqui" ficou de fora e "ai" entrou, e a diferenca nao e arbitraria.** "ai"
# aponta para onde o INTERLOCUTOR esta ("tem uma pessoa ai?"), que e a propria
# pergunta desta faixa; "aqui" aponta para onde o LEAD esta e nao diz nada
# sobre quem responde. Mesmo criterio de sempre: o termo tem de falar do
# interlocutor.
_REFORCOS_DE_IDENTIDADE: tuple[str, ...] = (
    # Reforco de identidade.
    "de verdade",
    "de carne e osso",
    "real",
    "viva",
    "vivo",
    "humana",
    "humano",
    "mesmo",
    "de fato",
    # Encerrador de turno.
    "hein",
    "viu",
    "certo",
    "serio",
    "por favor",
    "pfv",
    "ai",
    "agora",
    "ainda",
    "ne",
    "neh",
)

# A risada e a unica coisa desta allowlist que NAO e literal, e por isso nao
# passa por `re.escape`: o lead escreve de "kk" a "kkkkkkkk", "rs" ou "rsrs",
# "haha" ou "hahaha". Enumerar cada comprimento seria pior que um fragmento de
# regex de uma linha.
#
# `{2,}` nos tres, e nao `+`: "ha" com uma silaba so e o verbo "há" ("estou
# falando com uma pessoa ha meia hora"), e "k" sozinho nao e risada nenhuma.
_RISADA = r"k{2,}|(?:rs)+|(?:ha){2,}"

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
    + r"|"
    + _RISADA
    + r"))*(?:\s+ou\b.*)?$"
)

# So o ponto de interrogacao -- ver o Critical da fix round 5, no comentario
# de cima, para por que ponto, exclamacao e ponto-e-virgula sairam daqui.
# Corta so a regra de PRIMEIRA pessoa -- ver `_CORTE_DE_CLAUSULA`, logo
# abaixo, para por que a de segunda pessoa corta em sinais diferentes.
_FIM_DA_PERGUNTA = re.compile(r"\?+")

# Corta a regra de SEGUNDA pessoa em clausula, consertado na Task 2 do
# TEC-272 (ruling T1-G, achado B2: "sexta classe, fronteira de frase").
# `_PADRAO_DE_SEGUNDA_PESSOA` corria sobre o recado normalizado inteiro sem
# nenhum corte, e `_normalizar` troca pontuacao por espaco -- entao o sujeito
# de uma frase colava com o predicado da frase seguinte: "bom dia pra voce! e
# um robo aspirador que vem junto no apto?" normalizava para "...pra voce e
# um robo aspirador..." e casava "voce e um robo", ressuscitando verbatim as
# classes de portao automatico e robo aspirador de piscina que as rodadas 1 e
# 3 ja tinham fechado, por um mecanismo diferente.
#
# **`[?!.;]`, e nao so `?` como `_FIM_DA_PERGUNTA`.** As duas regras cortam
# por motivos diferentes: a de primeira pessoa ancora o FIM DE UMA PERGUNTA
# (por isso so `?` conta, ver o Critical da fix round 5 acima); a de segunda
# pessoa so precisa impedir que sujeito e predicado de FRASES diferentes se
# colem, e qualquer um dos quatro sinais termina uma frase para esse fim.
#
# Medido: cortar aqui fecha 5 dos 7 casos desta classe e nao quebra nenhuma
# das 89 falas que este arquivo ja fixava antes da Task 2.
# `test_fronteira_de_frase_na_segunda_pessoa_nao_dispara`
# (`tests/unit/test_pergunta_se_e_robo.py`) trava o conserto. Os 2 casos
# restantes -- conjuncao sem pontuacao entre sujeito e predicado -- nao
# fecham por corte de clausula nenhum: viram o quarto residuo declarado,
# abaixo, e `test_conjuncao_sem_pontuacao_e_lacuna_declarada` trava a lacuna.
_CORTE_DE_CLAUSULA = re.compile(r"[?!.;]+")

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

    Duas regras, descritas no comentario de `_TERMOS_DE_SEGUNDA_PESSOA`, e as
    duas correm clausula a clausula -- mas cortadas por sinais diferentes,
    cada um com a sua razao no comentario do proprio corte:
    `_PADRAO_DE_SEGUNDA_PESSOA` corta em `[?!.;]` (`_CORTE_DE_CLAUSULA`);
    `_PADRAO_DE_PRIMEIRA_PESSOA` corta so em `?` (`_FIM_DA_PERGUNTA`), porque
    precisa do fim de uma PERGUNTA como ancora em `$`.

    **A de segunda pessoa passou a cortar na Task 2 do TEC-272.** Ate ali ela
    corria sobre o recado inteiro normalizado, e essa afirmacao aqui dizia que
    ela "nao ganha nada com o corte e perderia o termo que um '?' partisse no
    meio" -- falso nas duas metades, medido por execucao (ruling T1-G,
    achado B2): cortar fecha 5 dos 7 casos da classe de fronteira de frase e
    nao quebra nenhuma das 89 falas que este arquivo ja fixava, e nao ha
    frasagem da tabela em que um "?" caia DENTRO do termo em vez de nas suas
    bordas. Custo aceito: uma pergunta de segunda pessoa partida por
    pontuacao no meio do proprio termo ("voce e... um robo?") deixa de
    disparar -- falso negativo, devolve o comportamento de hoje.

    Nunca levanta: texto sem letra nenhuma normaliza para vazio e devolve
    False, mesma garantia de `gatilhos_de`.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    segunda_pessoa = any(
        _PADRAO_DE_SEGUNDA_PESSOA.search(clausula) is not None
        for clausula in (_normalizar(parte) for parte in _CORTE_DE_CLAUSULA.split(texto))
        if clausula
    )
    if segunda_pessoa:
        return True
    return any(
        _PADRAO_DE_PRIMEIRA_PESSOA.search(frase) is not None
        for frase in (_normalizar(parte) for parte in _FIM_DA_PERGUNTA.split(texto))
        if frase
    )


# A oferta que o CA-04.1 pede junto da confirmacao. Texto que o lead recebe,
# entao COM acento (TEC-267) -- ao contrario dos prompts de sistema deste
# repo, que sao instrucao para o modelo e continuam sem.
TEXTO_DA_OFERTA_DE_CORRETOR = "Se preferir falar com um corretor, é só me dizer."

# Linha em branco e nao espaco, pelo mesmo argumento de
# `SEPARADOR_DA_IDENTIFICACAO` logo acima: as duas frases tem autores
# diferentes -- uma e resposta ao lead, a outra e constante do repositorio -- e
# coladas parecem uma frase so mal pontuada.
SEPARADOR_DA_OFERTA = "\n\n"


def ja_oferece_corretor(texto: str) -> bool:
    """O texto que o lead vai receber ja oferece um corretor?

    **A palavra basta, e e isso que torna este detector barato.** "Corretor"
    nao aparece na fala do agente por acaso: nas sete trilhas deterministicas
    que a mencionam -- a identificacao, a busca inconclusiva, o sem-resultado
    pos-ampliacao, o encaminhamento de venda, as duas variantes do pedido de
    humano e o teto de perguntas -- ela aparece sempre oferecendo um. O
    unitario deste modulo deriva essa lista por importacao e confere uma a uma.

    **A assimetria esta na direcao certa.** Falso positivo (achar oferta onde
    nao ha) nao anexa nada e devolve o comportamento de hoje; falso negativo
    duplica a oferta na mesma mensagem. Errar para o lado de nao anexar e o
    lado barato.

    **Roda sobre o texto FINAL, nao sobre a resposta crua do modelo** -- e essa
    escolha, feita em `turno.py`, e o que faz uma regra so cobrir as
    duplicacoes possiveis: o modelo ter oferecido sozinho e a identificacao
    ter oferecido no prefixo.

    **A trilha deterministica era a terceira delas, e desde a revisao final
    ela ja nao chega aqui:** `turno.py` so chama `texto_com_oferta` quando o
    texto ainda e a resposta do modelo (`texto_substituido`), porque a
    precondicao do CA-04.1 e o agente CONFIRMAR -- e texto nosso substituindo
    a resposta nao confirma nada. A verificacao das sete constantes continua
    valendo como rede: ela e o que avisa se uma trilha futura passar a
    duplicar por outro caminho, e o prefixo da identificacao E uma delas.
    """
    return "corretor" in _normalizar(texto)


def texto_com_oferta(corpo_do_lead: str | None, texto: str) -> str:
    """A oferta do CA-04.1, anexada so quando falta.

    O CA-04.1 pede duas coisas ao confirmar ser assistente virtual: confirmar
    E oferecer corretor. A TEC-139 mediu e so a primeira acontecia de forma
    confiavel -- o modelo confirmava em todos os casos sondados e oferecia em
    parte deles, e os que nao ofereciam eram as perguntas neutras.

    **A guarda olha o `texto` ja montado, e nao a resposta crua do modelo.** E
    o que faz uma regra so cobrir as duplicacoes possiveis: o modelo ter
    oferecido sozinho e a identificacao ter oferecido no prefixo. Nenhuma
    precisa de caso proprio -- a pergunta nao e QUEM ofereceu, e se a
    mensagem oferece.

    **As substituicoes deterministicas de `turno.py` nao dependem mais desta
    guarda**, porque desde a revisao final o proprio `turno.py` nao chama esta
    funcao quando substituiu o texto do modelo: ali o agente nao confirmou
    nada, e a precondicao do CA-04.1 e a confirmacao. Sao seis blocos que
    trocam o texto, produzindo sete constantes; quatro delas ja diziam
    "corretor" e se calavam aqui, e as tres que nao diziam -- encaminhamento
    de suporte, encerramento fora de escopo e o texto neutro da moderacao de
    saida -- recebiam a oferta e nao deviam.

    `corpo_do_lead` e opcional porque em `executar_turno` ele e `str | None`,
    do mesmo jeito que `pediu_optout` e `gatilhos_de` ja tratam la.
    """
    if not corpo_do_lead or not perguntou_se_e_robo(corpo_do_lead):
        return texto
    if ja_oferece_corretor(texto):
        return texto
    return f"{texto}{SEPARADOR_DA_OFERTA}{TEXTO_DA_OFERTA_DE_CORRETOR}"
