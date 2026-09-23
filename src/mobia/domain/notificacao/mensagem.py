"""O texto que o corretor recebe. TEC-177, RN-16.2.

Desde a TEC-281 devolve um `Aviso` e nao uma tupla -- ver o docstring dele.

Modulo sem I/O, no molde de `handoff/dossie.py` e de `handoff/vocabulario.py`.
"""

from dataclasses import dataclass

# O que entra no lugar do resumo quando ele nao existe. Desde a TEC-176
# (RN-15.4), so o dossie ausente ainda deixa `handoffs.resumo` nulo -- toda
# falha do redator (resposta invalida ou excecao do provedor) agora grava o
# template deterministico de `handoff/contingencia.py` em vez de nada. Este
# texto so aparece nesse caso raro que sobrou. A notificacao sai mesmo assim:
# a card diz que "o handoff que ninguem ve nao existe", e um corretor com
# aviso magro ainda atende o lead. Ver a D2.
#
# O link que este texto manda abrir nao resolve: `link_da_transcricao`
# (`handoff/resumo.py`) documenta em negrito que o destino e a E8, que nao
# existe. Desde a TEC-280 o e-mail CHEGA ao corretor, entao o dano deixou de
# ser hipotetico: ele recebe "Conversa completa: <link>" e o link nao abre
# nada. A card decidiu entregar assim mesmo -- corretor avisado com link
# quebrado ainda atende o lead, corretor nao avisado nao --, e registrou a
# lacuna. Ela fecha quando a E8 existir.
TEXTO_SEM_RESUMO = (
    "O resumo automatico nao pode ser gerado para este lead. "
    "Abra o link abaixo para ler a conversa inteira."
)


@dataclass(frozen=True)
class Aviso:
    """O que o corretor precisa saber, em prosa E em campos. TEC-281.

    Ate a TEC-281 isto era uma tupla `(assunto, corpo)`, e bastava: o unico
    canal que entregava era o e-mail, que manda prosa. O WhatsApp nao pode --
    a Meta so aceita template aprovado, e template recebe PARAMETROS
    POSICIONAIS, nao um paragrafo.

    Os tres campos estruturados ja existiam no sitio de chamada e eram
    jogados fora na hora em que `montar` os concatenava. A alternativa era o
    canal de WhatsApp extrair o link de volta do `corpo` por regex -- parsear
    prosa que nos mesmos acabamos de montar, um acoplamento textual que
    nenhum teste de `montar` protegeria.

    **`corpo` carrega o resumo; os outros quatro campos nao.** E por isso que
    o WhatsApp pode usar `etiqueta`, `prioridade` e `link` sem tocar em nada
    que a Meta revisaria humano por humano.
    """

    assunto: str
    corpo: str
    etiqueta: str
    prioridade: str
    link: str
    # O template aprovado que serve a ESTE aviso, ou `None` quando ainda nao
    # ha um. Fica na mensagem, e nao no canal, por uma razao concreta:
    # `notificar` (aviso de lead ao corretor) e `escalar_vencidos` (handoff
    # vencido ao gerente) leem o MESMO `ctx["canais_de_notificacao"]`, entao
    # uma instancia de canal serve duas mensagens diferentes. Um template
    # preso ao canal mandaria "lead pronto" ao gerente que esperava "handoff
    # vencido".
    #
    # `None` nao e omissao a corrigir: e a afirmacao de que este aviso nao tem
    # template aprovado, e o canal deve falhar alto em vez de inventar um.
    template: str | None = None


def montar(
    *, resumo: str | None, link: str, etiqueta: str, prioridade: str, template: str | None = None
) -> Aviso:
    """Devolve o `Aviso` completo.

    Tudo keyword-only: `etiqueta` e `prioridade` sao dois `str` adjacentes, e
    troca-los nao levanta, nao da erro de tipo e o mypy nao ve -- mesma razao
    dos dois `int` de `horario_permite_envio`. Do lado de fora o risco
    diminuiu desde a TEC-281: quem consome recebe campos nomeados no `Aviso`
    em vez de uma tupla posicional, entao trocar passa a ser visivel na
    leitura.

    O link fica no corpo e NAO no assunto: assunto e o que o corretor le na
    notificacao do celular, e uma URL longa ali empurra a etiqueta para fora
    da tela, que e justamente o que ele precisa ver para decidir se abre.
    """
    return Aviso(
        assunto=f"Lead pronto [{etiqueta}] prioridade {prioridade}",
        corpo="\n\n".join((resumo or TEXTO_SEM_RESUMO, f"Conversa completa: {link}")),
        etiqueta=etiqueta,
        prioridade=prioridade,
        link=link,
        template=template,
    )
