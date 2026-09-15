"""O lead pediu para falar com uma pessoa.

TEC-143. Deterministico e sem chamada paga, pela mesma razao que
`domain/optout/deteccao.py` declara para o opt-out: a decisao nao pode depender
de um provedor estar de pe. Aqui o argumento e ainda mais direto -- o provedor
falha pior justamente quando o lead ja esta irritado o bastante para pedir uma
pessoa.

Medido na TEC-143: acrescentar `FALAR_COM_HUMANO` ao enum `Intencao` custaria
5 tokens no schema compilado e levaria a margem do orcamento de prompt de 6,2
para 1,2 -- mas o que decidiu nao foi o custo, foi a dependencia.
"""

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from mobia.app.config import get_settings
from mobia.domain.outbound.horario import horario_permite_envio

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")

# Casam por substring: carregam o verbo ou a preposicao que os torna um pedido,
# e nenhum e palavra solta.
#
# **Nenhum termo aqui e so um substantivo, e isso e deliberado.** O modulo de
# opt-out registra o preco de errar nisso: "nao quero mais receber nada" saiu
# dos inequivocos porque "nada" aceita complemento partitivo e cada refinamento
# de busca silenciava um comprador.
#
# **INVARIANTE: quando "pessoa", "humano" ou "alguem" ocupam papel de DESTINO
# ("quero uma ___", "me transfere pra uma ___", "me passa pra uma ___"),
# carregam qualificador explicitado.** Quando ocupam papel de INTERLOCUTOR
# ("falar com uma ___"), nao carregam qualificador porque o verbo ja os
# desambigua. Quando ocupam papel de ATRIBUTO, qualificando outro substantivo
# ("atendimento humano"), nao carregam qualificador porque nao ocupam o lugar
# onde "fisica/juridica" apareceria. "Pessoa fisica" e "pessoa juridica" sao
# vocabulario de contrato imobiliario neste dominio -- "quero uma pessoa fisica
# no contrato" nao e pedido de transferencia, e "mudar o titular para uma pessoa
# juridica" e assunto de reescritura. Mas "falar com uma pessoa juridica" e
# pedido legitimo -- quem pergunta "posso falar com uma pessoa juridica?" quer
# mesmo um humano, e essa colisao erra na direcao barata (transferencia extra,
# nao silencio).
#
# **QUARTO EIXO, acrescentado na revisao final: o termo tem de fixar que o
# interlocutor e NOSSO, e tem de ser falso sob negacao.** Os tres papeis acima
# falam so de papel gramatical -- nao olham polaridade, nem de quem e a pessoa
# do outro lado. As quatro rodadas de revisao anteriores geraram CASOS e nao
# CRITERIO, e por isso os dois buracos passaram. Quem acrescentar termo aqui
# roda estas duas frases antes de commitar, e as duas tem de devolver False:
#
#     pediu_humano("nao quero <termo>")
#     pediu_humano("<termo> do banco")
#
# A primeira e coberta de graca pela guarda de negacao abaixo
# (`_NEGACAO_ANTES`); a segunda nao tem guarda nenhuma e depende so do termo.
# `"falar com uma pessoa"` REPROVA a segunda e fica assim mesmo -- e a frase
# literal do criterio de aceite da card, e qualifica-la mataria o caso central.
# O residual esta declarado como lacuna nomeada no desenho (banco, cartorio,
# financiamento, familia, prefeitura): e a excecao conhecida, nao a regra.
#
# Foram removidos por falso positivo durante as revisoes:
# - "quero uma pessoa", "queria uma pessoa": colisao com pessoa fisica/juridica
#   (papel de DESTINO)
# - "me passa pra uma pessoa", "me passa para uma pessoa": objeto "pessoa" nua
#   (papel de DESTINO)
# - "me transfere": verbo sem objeto
# - "me transfere pra uma pessoa", "me transfere para uma pessoa": objeto nua
#   (papel de DESTINO)
# - "atendimento humano" bare: violava invariante de verbo/preposicao
#
# Em lugar deles, os termos mantidos sao formas com qualificador explicitado
# ("de verdade", "da equipe", "de alguem") quando pessoa/humano sao DESTINO,
# ou termos onde pessoa/humano sao INTERLOCUTOR ("falar com uma ___"), ou
# formas com objeto que nao colide ("atendente", "corretor", "robo"). Custo de
# recall e aceitavel -- o desenho ja declara recall como lacuna.
_TERMOS_INEQUIVOCOS: tuple[str, ...] = (
    "falar com uma pessoa",
    "falar com um humano",
    "falar com humano",
    "falar com um atendente",
    "falar com uma atendente",
    "falar com atendente",
    "falar com alguem de verdade",
    "falar com um corretor de verdade",
    "quero uma pessoa de verdade",
    "quero uma pessoa da equipe",
    "queria uma pessoa de verdade",
    "me passa pra um atendente",
    "me passa para um atendente",
    "me transfere pra um atendente",
    "me transfere para um atendente",
    "quero atendimento humano",
    "nao quero falar com robo",
    "cansei de robo",
    "para de robo",
)

# So casam a mensagem INTEIRA. Um lead que escreve so "atendente" esta pedindo;
# o mesmo substantivo dentro de uma frase e assunto, nao pedido.
_TERMOS_AMBIGUOS: frozenset[str] = frozenset({"atendente", "humano", "pessoa real"})

# Guarda de negacao (fix de revisao final, Important 4). Sem ela,
# "nao quero falar com atendente, so me manda os imoveis" e "nao precisa falar
# com um humano, resolvo por aqui" DISPARAVAM -- conferido rodando. O
# argumento do desenho para aceitar falso positivo ("errar por sobra manda o
# lead para um humano, que e o destino que ele teria de qualquer forma") nao
# cobre este caso: aqui o lead disse o CONTRARIO, e o preco nao e uma
# transferencia a mais -- e o agente calar para sempre numa conversa que o
# lead quis seguir com o robo.
#
# So nega o que esta IMEDIATAMENTE antes do termo. O verbo e opcional porque
# os dois formatos existem: "nao quero " + "falar com atendente" (o verbo fica
# FORA do termo) e "nao " + "quero uma pessoa de verdade" (o verbo e a
# PRIMEIRA palavra do termo). "nao sei se quero falar com uma pessoa" nao e
# negado -- ha palavras no meio, e a duvida erra na direcao barata.
#
# **"nao quero falar com robo" continua disparando, e e por construcao.** Ali
# a negacao e sobre o ROBO e nao sobre o humano, e o termo INTEIRO esta na
# lista: ele casa no comeco da mensagem, sem nada antes dele, entao nao ha
# prefixo para esta guarda olhar.
#
# **A PONTUACAO DEPOIS DO "nao" IMPORTA, e ela e o unico sinal que separa os
# dois usos.** Este e o achado da re-revisao, e foi uma quebra que a propria
# guarda acima introduziu: "Nao, quero falar com atendente" e "Nao. Quero
# falar com uma pessoa" sao PEDIDOS, nao recusas. O "nao" ali e de CONTRASTE
# -- o lead esta negando o que veio antes ("nao [quero seguir com o robo],
# quero falar com atendente"), e nao o pedido que vem depois. `_normalizar`
# apaga a virgula antes de qualquer comparacao, entao "nao, quero" e "nao
# quero" colapsavam na mesma string e a guarda barrava os dois.
#
# Barrar o pedido e FALSO NEGATIVO, que e a direcao cara: o lead pede uma
# pessoa e continua preso no loop de robo, que e literalmente a dor que a card
# existe para resolver. Os falsos positivos das quatro rodadas anteriores eram
# baratos em comparacao. E a guarda estava acertando "nao, prefiro falar com
# um humano" por ACIDENTE -- ali ha uma palavra a mais entre o "nao" e o termo
# --, nao por regra; assimetria e sinal de que a regra nao existia.
#
# Por isso a guarda NAO le a string normalizada: ela le uma segunda
# normalizacao que troca cada corrida de pontuacao por um token de pausa
# (`_PAUSA`). "nao , quero ..." vira "nao | quero ...", e a expressao abaixo,
# que exige o "nao" colado no verbo ou no termo, deixa de casar. **Nao
# "simplifique" isto reusando `_normalizar`:** a unica coisa que distingue um
# pedido de uma recusa aqui e a pontuacao que ele apaga.
_NEGACAO_ANTES = re.compile(r"(?:^| )nao(?: (?:quero|queria|quis|preciso|precisa))? $")

# Token de pausa. Fora de `[a-z ]`, entao `_normalizar` o apagaria -- e e por
# isso que ele so existe na normalizacao paralela. Nenhum termo das listas
# acima o contem, entao a presenca dele nunca quebra um casamento por
# substring: ela so o EMPURRA para longe do "nao", que e o efeito desejado.
_PAUSA = "|"
_PONTUACAO_DE_PAUSA = re.compile(r"[,.;:!?]+")
_SO_LETRAS_ESPACO_E_PAUSA = re.compile(r"[^a-z |]+")


def _sem_acento(texto: str) -> str:
    """Minusculas e sem acento, com a pontuacao ainda no lugar.

    Extraido de `_normalizar` para `_normalizar_com_pausa` nao repetir a
    decomposicao NFKD -- e para as duas normalizacoes nao poderem divergir no
    que consideram "a mesma letra".
    """
    decomposto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    Mesmo normalizador do opt-out, e pela mesma razao: "ATENDENTE!" e
    "atendente" sao a forma que um lead irritado escreve, e a faixa estrita
    compara a mensagem inteira.
    """
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", _sem_acento(texto))).strip()


def _normalizar_com_pausa(texto: str) -> str:
    """Igual a `_normalizar`, mas a pontuacao vira `_PAUSA` em vez de sumir.

    Existe so para a guarda de negacao, e o comentario de `_NEGACAO_ANTES`
    explica por que ela nao pode ler a outra: "nao, quero falar com atendente"
    e um pedido e "nao quero falar com atendente" e uma recusa, e depois de
    `_normalizar` as duas sao a mesma string.

    **Os deslocamentos das duas NAO batem**, porque a pausa ocupa lugar. Por
    isso quem casa termo trabalha sobre esta aqui do comeco ao fim, em vez de
    achar o indice numa e ler o prefixo na outra -- ver `_dispara`.
    """
    marcado = _PONTUACAO_DE_PAUSA.sub(f" {_PAUSA} ", _sem_acento(texto))
    return _ESPACOS.sub(" ", _SO_LETRAS_ESPACO_E_PAUSA.sub(" ", marcado)).strip()


def _casa_sem_negacao(com_pausa: str, termo: str) -> bool:
    """Se `termo` aparece ao menos uma vez sem negacao imediatamente antes.

    Percorre TODAS as ocorrencias, e nao so a primeira: "nao quero falar com
    atendente agora, mas amanha quero falar com atendente" tem duas, e basta
    uma limpa para o pedido valer. Parar na primeira transformaria a guarda de
    negacao numa guarda de ordem das frases.

    Le a normalizacao COM PAUSA, nunca a outra -- ver `_NEGACAO_ANTES`.
    """
    inicio = com_pausa.find(termo)
    while inicio != -1:
        if _NEGACAO_ANTES.search(com_pausa[:inicio]) is None:
            return True
        inicio = com_pausa.find(termo, inicio + 1)
    return False


def _dispara(normalizado: str, com_pausa: str, termo: str) -> bool:
    """Se `termo` conta como pedido nesta mensagem.

    Quem decide se o termo ESTA na mensagem e a string normalizada de sempre;
    quem decide se ele esta NEGADO e a string com pausa. Sao duas perguntas e
    duas strings, porque os deslocamentos de uma nao valem na outra.

    O caso do meio e a pontuacao DENTRO do termo ("falar com uma, pessoa"):
    ela existe na normalizada e parte o termo na com pausa. A guarda nao tem
    como julgar negacao de um termo que ela nao acha, e o lado barato e
    disparar -- falso negativo aqui e o lead pedindo uma pessoa e continuando
    no loop de robo.
    """
    if termo not in normalizado:
        return False
    if termo not in com_pausa:
        return True
    return _casa_sem_negacao(com_pausa, termo)


def pediu_humano(texto: str) -> bool:
    """O lead pediu explicitamente para ser atendido por uma pessoa."""
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    if normalizado in _TERMOS_AMBIGUOS:
        return True
    com_pausa = _normalizar_com_pausa(texto)
    return any(_dispara(normalizado, com_pausa, termo) for termo in _TERMOS_INEQUIVOCOS)


def dentro_da_janela_de_atendimento(agora: datetime) -> bool:
    """Se `agora` cai dentro da janela local em que existe gente para atender.

    RN-16.1 (TEC-143). Le `atendimento_horario_inicio`/`_fim` e `followup_fuso`
    de `get_settings()` -- o comentario deles em `config.py` explica por que a
    janela e da imobiliaria e nao do corretor designado, e por que reaproveita
    o fuso do follow-up em vez de um campo proprio.

    **A aritmetica e delegada a `horario_permite_envio` (`domain/outbound/horario.py`)
    de proposito, para nao existir uma segunda formula da mesma conta de
    borda.** O docstring daquela funcao registra que a TEC-146 gastou uma
    card inteira consertando exatamente esse defeito de duas fontes -- e o
    plano desta card repetiu o erro, mandando escrever esta funcao do zero em
    vez de mandar procurar a existente. `horario_permite_envio` e nome de
    outro dominio (envio automatico, RN-13.3) e nao descreve o uso daqui;
    isso e aceito e nao corrigido por renomear -- a funcao pertence aquela
    card, e testada la, e trocar o nome dela por causa deste uso e que criaria
    o acoplamento errado.

    **Isto NAO funde as duas perguntas.** `horario_permite_envio` decide se um
    envio AUTOMATICO pode comecar; esta funcao decide se existe gente para
    ATENDER um pedido explicito do lead -- e as duas leem configuracao
    separada de proposito (`atendimento_horario_*` contra `followup_horario_*`).
    Hoje as duas contas coincidem -- mesma borda inclusiva de minuto, mesmo
    fuso -- e e so essa coincidencia que faz delegar funcionar. **Se as duas
    um dia divergirem, e esta funcao que para de delegar e ganha aritmetica
    propria; `horario_permite_envio` nao ganha um parametro para as duas.**

    `agora` precisa ser aware pela mesma razao que `horario_permite_envio`
    exige -- ver o docstring dela; a excecao de `tzinfo` ausente vem de la.
    """
    settings = get_settings()
    return horario_permite_envio(
        momento=agora,
        inicio=settings.atendimento_horario_inicio,
        fim=settings.atendimento_horario_fim,
        fuso=ZoneInfo(settings.followup_fuso),
    )


# Mora aqui, e nao em `turno.py`, pelo mesmo motivo que
# `TEXTO_DA_CONFIRMACAO_DE_OPTOUT` mora no modulo de opt-out: o texto pertence
# ao assunto, nao ao orquestrador que o entrega.
#
# COM acento: e texto que chega ao lead (TEC-267).
#
# **Nenhum dos dois afirma que alguem foi avisado, e a proibicao e por escrito.**
# Criar handoff nao notifica ninguem hoje: os dois adaptadores de
# `notificacao/canais.py` REGISTRAM e NAO ENTREGAM -- o e-mail nao tem provedor
# configurado neste projeto e o WhatsApp ao corretor exige template aprovado
# pela Meta que nao existe. A primeira versao desta card escreveu
# "Ja avisei nossa equipe" nas duas constantes, e essa e a TERCEIRA aparicao da
# mesma frase no repo: a TEC-174 escreveu "ja avisei um corretor" e teve de
# reescrever o texto inteiro depois; o comentario de `TEXTO_DA_JANELA_HUMANA`
# (`notificacao/envio.py`) registrou "Nao reintroduza a promessa"; e o plano
# desta card a reintroduziu assim mesmo. A forma aceita e a que
# `TEXTO_DO_LIMITE_DE_PERGUNTAS` e `TEXTO_DA_JANELA_HUMANA` ja usam: falar do
# ENCAMINHAMENTO e do HORARIO, nunca do aviso.
#
# **Sobreposicao declarada com `TEXTO_DA_JANELA_HUMANA` (TEC-177).** Aquele
# texto tambem diz um horario ao lead, e com as horas do CORRETOR
# (`corretores.horario_inicio`/`horario_fim`, resolvidas no job de notificacao);
# o daqui diz as horas da IMOBILIARIA (`Settings.atendimento_horario_*`, a D5
# do desenho). Um mesmo lead pode receber os dois na mesma conversa, com
# numeros diferentes. Nao e consertado aqui de proposito: as duas janelas
# respondem perguntas diferentes -- "quando ha gente na imobiliaria" contra "a
# jornada de quem vai te atender" -- e unifica-las e decisao de produto, nao de
# codigo. Ver as lacunas declaradas do desenho.
TEXTO_DO_PEDIDO_DE_HUMANO = (
    "Claro! Já estou passando esta conversa para um corretor da nossa equipe. "
    "Pode continuar escrevendo que fica tudo registrado."
)

# `{inicio}` e `{fim}` sao preenchidos com as horas locais da janela.
TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO = (
    "Claro! Já estou passando esta conversa para um corretor da nossa equipe. "
    "Nosso atendimento é das {inicio}h às {fim}h, "
    "então a resposta pode demorar até o próximo horário. "
    "Pode continuar escrevendo que fica tudo registrado."
)

# Kind proprio pela mesma razao do kind da confirmacao de opt-out: a reserva em
# `outbound_dispatches` nao pode colidir com a resposta que este turno nao vai
# mandar.
KIND_DO_PEDIDO_DE_HUMANO = "pedido_de_humano"

SUBAGENTE_PEDIDO_DE_HUMANO = "pedido_de_humano"
