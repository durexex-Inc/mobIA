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

    **Tres membros desde a TEC-130**, e foi essa extensao -- membros novos em
    vez de uma segunda tabela ou uma segunda coluna -- que justificou isto ser
    enum desde a TEC-138.

    **Nenhum dos dois motivos novos herda a janela de silencio dos 30 dias.**
    Ela e politica da RN-03.5 e `SituacaoDaConversa.silencia_o_agente`
    (`repositorio.py`) a condiciona a `FORA_DE_ESCOPO`. Para `INATIVIDADE` e o
    ponto inteiro da RN-02.3: a conversa fechada por silencio tem de ser
    respondida na mensagem seguinte, senao o reengajamento morre. Para
    `OPTOUT` o silencio ja existe e vem de `esta_em_optout`, cujo portao roda
    antes da reabertura em `turno.py` -- duplica-lo aqui criaria duas fontes
    para o mesmo fato.

    **`FORA_DE_ESCOPO` e igual, byte a byte, a `Intencao.FORA_DE_ESCOPO`
    (`domain/agente/schemas.py`), e isso e coincidencia, nao a mesma coisa.**
    Um e motivo de encerramento de conversa; o outro e classificacao de turno.
    Ja divergiram: `INATIVIDADE` e `OPTOUT` nao tem equivalente em `Intencao`.
    """

    FORA_DE_ESCOPO = "FORA_DE_ESCOPO"
    INATIVIDADE = "INATIVIDADE"
    OPTOUT = "OPTOUT"
