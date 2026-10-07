"""Gatilho, etiqueta, prioridade e status do handoff, e quais status aceitam.

Modulo sem I/O de proposito: e o que deixa a regra ser testada em
`tests/unit/`, sem Postgres de pe.
"""

from enum import StrEnum


class Gatilho(StrEnum):
    """Os gatilhos da RN-16.1.

    **Nasceu completo, com fiacao para tres, e a TEC-169 acrescentou o
    setimo.** Ate ela este docstring dizia que acrescentar valor a este enum
    "custa migration", e isso era falso: `handoffs.gatilho` e `String(32)`
    CRU -- a `0023_handoffs.py` poe `CheckConstraint` em `prioridade` e em
    `status`, e em nenhum dos dois casos no gatilho. O parentesco que a frase
    antiga nomeava (o `IN` do CHECK em `handoffs.status`) e real, so que e
    sobre o `status`: e ELE que custa migration, nao este enum. O preco de um
    gatilho novo sao as duas entradas em `ETIQUETA_DE` e `PRIORIDADE_DE`
    abaixo, que `tests/unit/test_handoff_vocabulario.py` exige.

    Acrescentar um CHAMADOR tambem nao custa nada, e esse era o outro ponto
    da frase antiga. TEC-143 e TEC-149 chegaram e so chamaram
    `registrar_handoff` com o gatilho que ja existia.
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
    # TEC-169, RN-11.5. O lead pediu visita, nao havia janela nas proximas 72
    # horas e ele aceitou a lista de espera. Gatilho proprio e nao
    # PEDIDO_DE_HUMANO: aquele e o unico ALTA da RN-16.1 e significa que o
    # lead pediu uma pessoa, e aqui ele pediu um HORARIO. A etiqueta e o
    # filtro do corretor no dashboard (TEC-192) e nao muda depois de criada,
    # entao reusar a de outra fila a tornaria mentirosa para sempre.
    SEM_DISPONIBILIDADE = "SEM_DISPONIBILIDADE"
    # TEC-389. O cliente pediu contato sobre um imovel pelo portal, sem
    # nenhuma conversa -- nao e LEAD_QUENTE (aquele vem de score/temperatura
    # calculados sobre qualificacao conversacional, que este pedido nao tem) e
    # nao e PEDIDO_DE_HUMANO (o lead nao pediu uma pessoa, pediu um imovel).
    INTERESSE_PORTAL = "INTERESSE_PORTAL"


class Prioridade(StrEnum):
    ALTA = "ALTA"
    NORMAL = "NORMAL"


class Status(StrEnum):
    """CONCLUIDO ganhou escritor na TEC-278 -- `devolver` em `conversas.py`. Ver o modelo."""

    PENDENTE = "PENDENTE"
    ACEITO = "ACEITO"
    ESCALADO = "ESCALADO"
    CONCLUIDO = "CONCLUIDO"


# Estados que o aceite pode transformar em ACEITO. ESCALADO entra por decisao
# da Task 6 (TEC-178): aceitar depois da escalada e o caso real -- o gerente
# cobrou e alguem pegou -- e recusar penalizaria justamente o comportamento
# que a card quer provocar. Ver a Emenda E-01 da secao 6.5 do SRS: o 410
# "escalado por SLA" que o texto original previa nunca e levantado.
#
# **Dois leitores, e eles TEM DE andar juntos:** a rota de aceite
# (`api/routes/handoffs.py`) e a tomada da conversa pelo corretor
# (`atendimento/tomada.py`, D6 da TEC-179), que aceita junto o handoff aberto.
# As duas decidem a mesma pergunta -- "isto ainda pode virar ACEITO?". Morava
# na rota ate a TEC-194, que precisou dela no dominio.
ACEITAVEIS = (Status.PENDENTE.value, Status.ESCALADO.value)


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
    Gatilho.SEM_DISPONIBILIDADE: "sem-disponibilidade",
    Gatilho.INTERESSE_PORTAL: "interesse-portal",
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
    Gatilho.SEM_DISPONIBILIDADE: Prioridade.NORMAL,
    Gatilho.INTERESSE_PORTAL: Prioridade.NORMAL,
}


# A escalada da emenda E-01 -- prioridade de handoff aberto sobe e nunca desce --
# NAO mora aqui. Ela e um `CASE` dentro do `ON CONFLICT DO UPDATE` de
# `repositorio.py`, porque quem decide precisa ver a linha existente, e o Python
# nao a ve naquele caminho. Uma gemea em Python seria segunda implementacao da
# mesma regra, livre para divergir em silencio da que roda de verdade.
