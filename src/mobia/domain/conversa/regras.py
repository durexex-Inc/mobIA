"""A regra de quando a conversa fora de escopo acaba. RN-03.5, TEC-138.

Pura de proposito, no molde de `context/qualificacao.py`: sem I/O, sem banco,
sem chamada ao modelo. Quem grava e o repositorio; aqui so se decide.
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
