"""O vocabulario de kinds de saida, e quais deles formam uma resposta so.

TEC-273. Mora aqui, e nao dentro de `port.py`, pelo padrao que
`KIND_DA_CONFIRMACAO_DE_OPTOUT` ja estabelece: o kind vive no modulo que
possui o comportamento, e o port importa de la.

E nao pode continuar em `domain/agente/turno.py`, de onde veio: `port.py`
precisa dele agora, e `domain/outbound` nao pode importar de `domain/agente`
-- a dependencia ja corre no sentido contrario.
"""

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
