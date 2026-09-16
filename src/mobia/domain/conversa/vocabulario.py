"""Status da conversa e motivo do encerramento. TEC-138, RN-03.5 e RN-02.3.

Modulo sem I/O de proposito, no molde de `handoff/vocabulario.py`: e o que
deixa a regra ser testada em `tests/unit/`, sem Postgres de pe.
"""

from enum import StrEnum


class Status(StrEnum):
    """O ciclo de vida de `Conversa`. RN-03.5."""

    ATIVA = "ATIVA"
    ENCERRADA = "ENCERRADA"


class MotivoDoEncerramento(StrEnum):
    """Vocabulario e nao booleano de proposito.

    A regra da card pede que o motivo seja "proprio, separado do encerramento
    por inatividade", e uma booleana `encerrada` obrigaria quem precisasse de
    um segundo motivo a inventar onde guarda-lo.

    **Um unico membro por enquanto.** A TEC-130 acrescenta INATIVIDADE aqui --
    e e essa extensao futura, um membro novo em vez de uma segunda tabela ou
    uma segunda coluna, que justifica isto ser enum e nao uma constante solta.

    **O membro novo nao herda a janela de silencio dos 30 dias.** Ela e
    politica da RN-03.5 e `SituacaoDaConversa.silencia_o_agente`
    (`repositorio.py`) a condiciona a `FORA_DE_ESCOPO`; quem acrescentar um
    motivo aqui ganha o encerramento registrado e nada mais, ate acrescentar o
    motivo tambem la -- de proposito.

    **`FORA_DE_ESCOPO` e igual, byte a byte, a `Intencao.FORA_DE_ESCOPO`
    (`domain/agente/schemas.py`), e isso e coincidencia, nao a mesma coisa.**
    Um e motivo de encerramento de conversa; o outro e classificacao de turno.
    Vao divergir: a TEC-130 acrescenta INATIVIDADE aqui e nada equivalente
    entra em `Intencao` por causa disso.
    """

    FORA_DE_ESCOPO = "FORA_DE_ESCOPO"
