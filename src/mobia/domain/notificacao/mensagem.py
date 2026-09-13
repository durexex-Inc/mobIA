"""O texto que o corretor recebe. TEC-177, RN-16.2.

Modulo sem I/O, no molde de `handoff/dossie.py` e de `handoff/vocabulario.py`.
"""

# O que entra no lugar do resumo quando ele nao existe. Desde a TEC-176
# (RN-15.4), so o dossie ausente ainda deixa `handoffs.resumo` nulo -- toda
# falha do redator (resposta invalida ou excecao do provedor) agora grava o
# template deterministico de `handoff/contingencia.py` em vez de nada. Este
# texto so aparece nesse caso raro que sobrou. A notificacao sai mesmo assim:
# a card diz que "o handoff que ninguem ve nao existe", e um corretor com
# aviso magro ainda atende o lead. Ver a D2.
#
# O link que este texto manda abrir nao resolve ainda: `link_da_transcricao`
# (`handoff/resumo.py`) documenta em negrito que o destino e a E8, que nao
# existe. Sem dano hoje -- nenhum canal entrega nada a corretor nenhum (D4) --
# mas o dia em que um adaptador real existir, a E8 tem de existir junto.
TEXTO_SEM_RESUMO = (
    "O resumo automatico nao pode ser gerado para este lead. "
    "Abra o link abaixo para ler a conversa inteira."
)


def montar(*, resumo: str | None, link: str, etiqueta: str, prioridade: str) -> tuple[str, str]:
    """Devolve (assunto, corpo).

    Tudo keyword-only: `etiqueta` e `prioridade` sao dois `str` adjacentes, e
    troca-los nao levanta, nao da erro de tipo e o mypy nao ve -- mesma razao
    dos dois `int` de `horario_permite_envio`.

    O link fica no corpo e NAO no assunto: assunto e o que o corretor le na
    notificacao do celular, e uma URL longa ali empurra a etiqueta para fora
    da tela, que e justamente o que ele precisa ver para decidir se abre.
    """
    assunto = f"Lead pronto [{etiqueta}] prioridade {prioridade}"
    corpo = "\n\n".join((resumo or TEXTO_SEM_RESUMO, f"Conversa completa: {link}"))
    return assunto, corpo
