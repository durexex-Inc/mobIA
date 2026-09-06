"""O maximo absoluto de mensagens automaticas sem resposta. TEC-188, RN-13.7.

Pura de proposito, no molde de `horario.py`, `cadencia.py` e `score.py`: sem
I/O, sem banco, sem chamada ao modelo. Quem conta e o repositorio; aqui so se
compara.

**Mora em `outbound/` e nao em `followup/`**, ao lado de `horario.py` e pela
mesma razao: a RN-13.7 diz que, atingido o maximo, nenhuma automacao envia
mais nada a esse lead, e a card enumera -- nem follow-up, nem lembrete, nem
reengajamento. Sob `followup/` a TEC-171 nao acharia esta funcao e escreveria
a segunda, que e a forma do defeito que a TEC-146 gastou uma card inteira
consertando.

**E NAO mora em `GuardedOutbound.send`**, pela mesma razao que a janela da
TEC-185 nao mora: aquele caminho carrega a resposta ao lead, e o maximo e
sobre mensagem AUTOMATICA. Um lead no maximo que escreve continua sendo
respondido -- e essa resposta dele, por mover a ancora, e justamente o que
zera o contador.
"""

# A RN-13.7, literal. **Escrito a mao, e nao derivado de `CADENCIA`** -- ao
# contrario de `INTERVALO_MINIMO` e dos tetos por temperatura da consulta, que
# sao derivados de proposito para nao virarem segunda fonte.
#
# Aqui derivar seria o erro: o maximo ficaria igual ao teto da cadencia por
# construcao, e a regra "o teto prevalece sobre a configuracao de cadencia --
# mesmo que alguem configure 6 tentativas, o envio para na quarta" viraria
# tautologia. O sentido da RN-13.7 e ser um numero INDEPENDENTE que sobrevive
# a alguem alongar a cadencia.
#
# E nao vai para `Settings`, ao contrario da janela da TEC-185: a card daquela
# pedia janela ajustavel sem deploy, e esta pede o contrario na letra --
# "maximo absoluto". Um maximo ajustavel por variavel de ambiente e um maximo
# que a proxima pessoa com pressa aumenta, e o bloqueio do numero na Meta nao
# volta atras.
MAXIMO_SEM_RESPOSTA = 4


def antispam_permite_envio(*, ja_enviadas: int) -> bool:
    """Se ainda cabe uma mensagem automatica para este lead. RN-13.7.

    `ja_enviadas` e a CONTAGEM de mensagens automaticas que sairam desde a
    ultima fala do lead -- e nao o numero da ultima tentativa. A diferenca e o
    centro desta card: a regua da cadencia devolve a MAIOR tentativa vencida e
    pula as intermediarias, entao um lead calado ha dez dias tem uma linha so,
    com `tentativa_numero = 4`. Contar pela posicao cortaria da automacao um
    lead que recebeu uma unica mensagem, e nada denunciaria o corte -- ele
    simplesmente pararia de receber follow-up.

    A comparacao e `<` e nao `!=`: com igualdade estrita, uma contagem que
    passasse do maximo por qualquer motivo voltaria a permitir envio.

    Keyword-only por consistencia com `horario_permite_envio` e com o resto do
    dominio puro. Aqui o argumento da troca silenciosa nao se aplica (ha um
    parametro so), mas a simetria e o que faz a lista de guardas da varredura
    se ler como uma lista.
    """
    return ja_enviadas < MAXIMO_SEM_RESPOSTA
