"""Gatilho, etiqueta e prioridade do handoff.

Modulo sem I/O de proposito: e o que deixa a regra ser testada em
`tests/unit/`, sem Postgres de pe.
"""

from enum import StrEnum


class Gatilho(StrEnum):
    """Os gatilhos da RN-16.1.

    **Nasce completo, com fiacao para tres.** Acrescentar valor a este enum
    depois custa migration (o `IN` do CHECK em `handoffs.status` e irmao deste
    problema); acrescentar um CHAMADOR nao custa nada. TEC-143 e TEC-149
    chegaram e so chamaram `registrar_handoff` com o gatilho que ja existia.
    TEC-170 chegou e NAO chamou: o aviso do agendamento confirmado sai por
    e-mail direto ao corretor, sem abrir handoff (RN-16.1, decidido em
    conversa) -- AGENDAMENTO_CONFIRMADO segue sem chamador. **A TEC-371
    tampouco o chamou**, e e a card em que ele mais pareceria servir: ela e a
    primeira a confirmar agendamento por conversa de lead. A decisao da
    TEC-170 nao foi reaberta -- o e-mail continua sendo o caminho, e abrir
    handoff aqui poria na fila do corretor uma visita que ja esta marcada.

    A RN-16.1 junta VENDER_IMOVEL e SUPORTE_CONTRATO num item so, e aqui eles
    sao dois: o Gherkin da card so nomeia a etiqueta `venda-imovel`, e as duas
    intencoes viram filas diferentes para o corretor -- quem quer vender um
    imovel e quem tem duvida de contrato vigente nao sao o mesmo trabalho.
    """

    LEAD_QUENTE = "LEAD_QUENTE"
    AGENDAMENTO_CONFIRMADO = "AGENDAMENTO_CONFIRMADO"
    PEDIDO_DE_HUMANO = "PEDIDO_DE_HUMANO"
    VENDA_IMOVEL = "VENDA_IMOVEL"
    SUPORTE_CONTRATO = "SUPORTE_CONTRATO"
    LIMITE_DE_PERGUNTAS = "LIMITE_DE_PERGUNTAS"
    ERRO_DO_AGENTE = "ERRO_DO_AGENTE"


class Prioridade(StrEnum):
    ALTA = "ALTA"
    NORMAL = "NORMAL"


class Status(StrEnum):
    """CONCLUIDO ganhou escritor na TEC-278 -- `devolver` em `conversas.py`. Ver o modelo."""

    PENDENTE = "PENDENTE"
    ACEITO = "ACEITO"
    ESCALADO = "ESCALADO"
    CONCLUIDO = "CONCLUIDO"


# A etiqueta e o filtro do corretor no dashboard (TEC-192), e por isso ela e do
# gatilho que CRIOU o handoff e nao muda quando outro chega.
ETIQUETA_DE: dict[Gatilho, str] = {
    Gatilho.LEAD_QUENTE: "lead-quente",
    Gatilho.AGENDAMENTO_CONFIRMADO: "agendamento-confirmado",
    Gatilho.PEDIDO_DE_HUMANO: "pedido-humano",
    Gatilho.VENDA_IMOVEL: "venda-imovel",
    Gatilho.SUPORTE_CONTRATO: "suporte-contrato",
    Gatilho.LIMITE_DE_PERGUNTAS: "qualificacao-parcial",
    Gatilho.ERRO_DO_AGENTE: "erro-do-agente",
}

PRIORIDADE_DE: dict[Gatilho, Prioridade] = {
    Gatilho.LEAD_QUENTE: Prioridade.NORMAL,
    Gatilho.AGENDAMENTO_CONFIRMADO: Prioridade.NORMAL,
    # O unico ALTA da RN-16.1.
    Gatilho.PEDIDO_DE_HUMANO: Prioridade.ALTA,
    Gatilho.VENDA_IMOVEL: Prioridade.NORMAL,
    Gatilho.SUPORTE_CONTRATO: Prioridade.NORMAL,
    Gatilho.LIMITE_DE_PERGUNTAS: Prioridade.NORMAL,
    Gatilho.ERRO_DO_AGENTE: Prioridade.NORMAL,
}


# A escalada da emenda E-01 -- prioridade de handoff aberto sobe e nunca desce --
# NAO mora aqui. Ela e um `CASE` dentro do `ON CONFLICT DO UPDATE` de
# `repositorio.py`, porque quem decide precisa ver a linha existente, e o Python
# nao a ve naquele caminho. Uma gemea em Python seria segunda implementacao da
# mesma regra, livre para divergir em silencio da que roda de verdade.
