"""Regras puras do ciclo de vida da conversa. RN-02.3, RN-03.5, TEC-138 e TEC-130.

Pura de proposito, no molde de `context/qualificacao.py`: sem I/O, sem banco,
sem chamada ao modelo. Quem grava e o repositorio; aqui so se decide.

Duas regras moram aqui: quando a conversa fora de escopo acaba
(`deve_encerrar`, RN-03.5) e por quanto tempo qualquer conversa fica em
silencio (`DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA`, RN-02.3).
"""

# RN-03.5. O unico lugar em que este numero esta escrito, como o
# TETO_DE_PERGUNTAS da RN-05.5.
TETO_DE_FORA_DE_ESCOPO = 3


def deve_encerrar(seguidas: int) -> bool:
    """Esta contagem de mensagens fora de escopo seguidas encerra a conversa?

    `>=` e nao `==`: dois turnos concorrentes da mesma conversa podem passar do
    teto entre a contagem de um e a decisao do outro, e encerrar uma conversa
    ja encerrada e idempotente. Parar de encerrar acima do teto perderia o
    caso em silencio.
    """
    return seguidas >= TETO_DE_FORA_DE_ESCOPO


# RN-02.3 e RN-03.5. **Tres leitores compartilham este numero de proposito**:
# `e_conversa_nova` (`agente/identificacao.py`) mede o silencio que abre
# conversa nova, `situacao_da_conversa` (`repositorio.py`) mede a janela do
# encerramento, e `encerrar_inativas` (`repositorio.py`) varre o que passou
# dela. Dois numeros iguais escritos em lugares diferentes divergem na
# primeira vez que alguem mexe em um -- e divergir aqui significa o turno
# tratar como conversa nova o que a varredura ainda considera ativa, ou o
# contrario.
#
# Estava em `agente/identificacao.py` ate a TEC-130. Saiu de la porque dois
# dos tres leitores nao sao do modulo do agente, e um deles e uma varredura
# de worker.
DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA = 30
