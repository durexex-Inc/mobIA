"""Os kinds da resposta de texto, e quais deles formam uma resposta so.

TEC-273. NAO e o vocabulario inteiro de kinds de saida do sistema -- e o da
resposta de texto (`reply`, `reply_2`), mais os dois que nao tem outro lar
que `port.py` possa importar: o do follow-up (TEC-184) e o da fala do corretor
(TEC-194), que a guarda de atendimento humano precisa reconhecer. `KINDS_DAS_FICHAS`,
`KIND_DO_CRITERIO_AMPLIADO` e `KIND_DO_FILTRO_AJUSTADO` moram em
`domain/agente/turno.py`; `KIND_DA_CONFIRMACAO_DE_OPTOUT`,
`KIND_DA_JANELA_HUMANA` e `KIND_DO_AVISO_DE_ERRO` moram cada um no modulo do
proprio comportamento. Este modulo existe pelo mesmo padrao que aqueles tres
ja seguem: o kind vive no modulo que possui o comportamento, e quem precisa
dele importa de la.

`reply`/`reply_2` nao tem um modulo de comportamento proprio para morar --
sao produzidos dentro de `executar_turno`, em `domain/agente/turno.py` -- e
por isso precisaram de um lar novo: `port.py` passou a precisar do
agrupamento (D1, `grupo_de`) para liberar as reservas do grupo inteiro numa
falha retentavel, e `domain/outbound` nao pode importar de `domain/agente`,
que ja importa dele -- a dependencia so corre num sentido.
"""

import uuid

KIND_DA_RESPOSTA = "reply"

# Dois kinds e nao um repetido, pelo mesmo motivo de `KINDS_DAS_FICHAS`: a
# `UNIQUE (message_id, kind)` de `outbound_dispatches` e o que torna o
# reprocessamento seguro, e duas mensagens com o mesmo kind fariam a segunda
# ser suprimida como reentrega -- o lead receberia metade da resposta em
# silencio.
#
# O primeiro continua sendo `KIND_DA_RESPOSTA` e nao um nome novo: ha linhas
# gravadas com "reply" e testes que afirmam `_kinds_reservados() == ["reply"]`.
#
# A reserva por kind faz a parte ja entregue ser suprimida de novo numa
# retentativa -- e isso NAO quer dizer "a retentativa completa a mesma
# resposta". `sweep_stalled` reenfileira a MENSAGEM, e o turno roda inteiro de
# novo, com uma chamada NOVA ao classificador: texto diferente do da tentativa
# anterior. A parte com reserva devolve False de novo e e suprimida; a parte
# sem reserva sai, mas com o texto da chamada NOVA -- nao com a continuacao do
# texto antigo, e o lead acaba com a primeira metade de uma resposta seguida da
# segunda metade de outra. Fix review final (TEC-140): este comentario prometia
# "reentrega SO ela", que e falso -- a parte que falta reentrega, mas o texto ao
# redor dela mudou.
#
# **E e por isso que os grupos abaixo existem.** Ate a TEC-273 o paragrafo
# acima terminava dizendo que o log do laco de entrega "so torna isso visivel,
# sem evitar"; agora a falha RETENTAVEL (e o cancelamento) evita: antes de
# propagar, `GuardedOutbound.send` libera as reservas do grupo inteiro (ver
# `_liberar`, em `port.py`), a retentativa nao encontra reserva nenhuma e
# entrega as DUAS partes da geracao nova. O lead le uma duplicata visivel, que
# e o lado que TEC-134/TEC-227 ja escolheram, e nao duas metades costuradas.
#
# A costura sobrevive so onde a reserva fica viva sem passar por aquela guarda
# -- queda do worker, excecao depois do `send`, ou o proprio delete da
# liberacao falhando (`outbound.liberacao_falhou`). Ai o laco de entrega de
# `executar_turno` marca entrega parcial, grava so o que saiu e alarma em
# `turno.entrega_parcial_da_resposta`: continua sem ser evitado, mas ja nao
# passa em silencio.
KINDS_DA_RESPOSTA = (KIND_DA_RESPOSTA, "reply_2")

# Os grupos: conjuntos de kinds que carregam UMA resposta regeneravel.
#
# **As fichas nao estao aqui, e e decisao.** A retentativa de uma apresentacao
# repete o lote persistido (TEC-275, D1) em vez de chamar o modelo de novo,
# entao nao ha duas geracoes para misturar -- e a reserva de cada ficha e
# justamente o sinal que diz "esta ja saiu, nao reenvie". Poe-las num grupo
# esvaziaria esse sinal e faria `_continuar_entrega` nunca ser tomada.
_GRUPOS: tuple[tuple[str, ...], ...] = (KINDS_DA_RESPOSTA,)


def grupo_de(kind: str) -> tuple[str, ...]:
    """Os kinds que saem e voltam JUNTOS com `kind`. TEC-273.

    Devolve `(kind,)` quando ele nao pertence a grupo nenhum, e nao `()`: o
    chamador fica uniforme, liberando sempre `grupo_de(kind)`. Com `()` o
    port teria de lembrar de somar o proprio kind, e esquecer disso deixaria
    presa exatamente a reserva que acabou de falhar.
    """
    for grupo in _GRUPOS:
        if kind in grupo:
            return grupo
    return (kind,)


# TEC-184. Um kind por tentativa, e nao um so repetido: a UNIQUE
# (message_id, kind) de `outbound_dispatches` e o que impede duas varreduras
# concorrentes de mandarem a mesma tentativa duas vezes, e com um kind unico a
# SEGUNDA tentativa do mesmo lead seria absorvida como se fosse repeticao da
# primeira -- o lead receberia so o primeiro follow-up da cadencia, em
# silencio.
#
# O teto e quatro porque a cadencia mais longa (QUENTE) tem quatro posicoes --
# ver `CADENCIA` em `domain/followup/cadencia.py`. Nao ha validacao do
# argumento aqui: quem o produz e `tentativa_devida`, que so devolve posicao
# existente na regua, e uma guarda nesta funcao seria uma segunda opiniao
# sobre o que aquela ja garante.
#
# **Nao entra em `_GRUPOS`.** Grupo e o conjunto de kinds que carregam UMA
# resposta regeneravel, e cada tentativa de follow-up e uma mensagem propria,
# de uma varredura propria: liberar a reserva da tentativa 1 porque a 2 falhou
# reabriria o envio de uma mensagem que o lead ja recebeu dias antes.
def KIND_DO_FOLLOWUP(tentativa: int) -> str:
    """O kind da n-esima tentativa de follow-up: `followup_1`..`followup_4`."""
    return f"followup_{tentativa}"


# TEC-194, D3. A fala que o corretor digita no dashboard. O unico kind que
# atravessa a guarda de atendimento humano de `GuardedOutbound.send` -- a
# guarda existe para o agente nao falar por cima do corretor, e quem fala aqui
# E o corretor. A de opt-out continua valendo para ele: o lead que pediu para
# parar nao recebe mensagem de ninguem.
#
# Um kind por FALA, e nao um so: a UNIQUE (message_id, kind) de
# `outbound_dispatches` suprimiria como reentrega a segunda fala ancorada na
# mesma mensagem do lead -- e o corretor que manda duas mensagens seguidas, sem
# o lead responder no meio, e o caso comum. Com o id da fala no kind, `False`
# da guarda so pode significar opt-out.
#
# Prefixo em vez de valor fixo, pela mesma razao de `KIND_DO_FOLLOWUP`, e fora
# de `_GRUPOS` pela mesma razao tambem: cada fala e uma mensagem propria.
PREFIXO_DA_FALA_DO_CORRETOR = "corretor:"


def kind_da_fala_do_corretor(fala_id: uuid.UUID) -> str:
    """O kind de uma fala do corretor: `corretor:` e 22 digitos do id.

    **22, e nao o UUID inteiro**, porque `outbound_dispatches.kind` e
    `String(32)` e o prefixo ja ocupa 9. A unicidade que importa e a da UNIQUE
    `(message_id, kind)`, isto e, entre as falas ancoradas na MESMA mensagem
    do lead -- e 88 bits de um UUIDv4 nao colidem entre meia duzia delas.
    """
    return f"{PREFIXO_DA_FALA_DO_CORRETOR}{fala_id.hex[:22]}"


def e_fala_do_corretor(kind: str) -> bool:
    return kind.startswith(PREFIXO_DA_FALA_DO_CORRETOR)
