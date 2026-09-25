"""O convite para remarcar, depois de um cancelamento. TEC-172, RN-12.3.

Puro: nao toca banco nem rede, no molde de `lembretes.py`. Quem consulta,
decide o canal e entrega e `workers/jobs/sweep_remarcacoes.py`.

**Um texto so, e nao tres.** `lembretes.py` tem seis constantes porque o
lembrete DESCREVE o compromisso -- e visita com imovel, visita sem imovel e
reuniao remota se descrevem diferente. O convite nao descreve compromisso
nenhum: ele convida a marcar outro. Repetir a data do que foi cancelado seria
lembrar o lead do que ele proprio desmarcou.

**Nada le a resposta**, como na TEC-171: o texto convida e nao promete que
alguem remarca. `domain/agente/turno.py` nao importa nada de
`domain/agendamento/`.
"""

import uuid
from datetime import datetime, timedelta

# RN-12.3: "agenda tentativa de remarcacao em 24 horas". Regra do SRS e nao
# configuracao, o mesmo argumento da D4 da TEC-285.
ANTECEDENCIA_DO_CONVITE = timedelta(hours=24)

# O teto da faixa, e ele resolve dois problemas de uma vez.
#
# O primeiro e o mesmo da TEC-171: um worker parado nao pode fazer o convite
# sair quando ele ja deixou de fazer sentido -- "voce cancelou ha tres meses,
# quer remarcar?" e outra mensagem, nao a mesma atrasada.
#
# O segundo e o backfill, e sem o teto ele morderia no primeiro deploy: TODO
# cancelamento anterior a esta card tem a coluna de resolvido nula, entao a
# primeira passagem convidaria a tabela inteira de uma vez. O teto os deixa de
# fora por construcao, sem que ninguem precise lembrar de uma data de corte.
#
# Sete dias, e nao um numero medido: e o intervalo em que um lead ainda
# reconhece o assunto. Quem medir corrige.
VALIDADE_DO_CONVITE = timedelta(days=7)

# Doze caracteres, como `confirmacao_`, `lembrete_24_` e `lembrete_02_`: com os
# vinte primeiros do hex do id fecham os trinta e dois de
# `outbound_dispatches.kind`. A conta por extenso esta em `kind_da_confirmacao`.
PREFIXO_DO_KIND = "remarcacao__"

# O nome do template aprovado, quando o cancelamento tirou o lead da janela de
# 24h da Meta. A aprovacao e fato EXTERNO (RT-03) e entra por
# `Settings.templates_aprovados`, nunca daqui.
TEMPLATE_DO_CONVITE = "remarcacao_convite"
IDIOMA_DO_TEMPLATE = "pt_BR"

# Texto ao lead: portugues COM acento (TEC-267), registrado em
# `tests/unit/literais_ao_lead.py`. Nao promete que alguem remarca -- nada le
# a resposta --, e nao diz que o corretor "esta esperando".
TEXTO_DO_CONVITE_DE_REMARCACAO = (
    "Vi que a sua visita foi cancelada. Se quiser remarcar, é só me dizer "
    "quando fica bom para você."
)


def convite_devido(*, cancelado_em: datetime | None, agora: datetime) -> bool:
    """Se o convite e devido agora, para quem cancelou em `cancelado_em`.

    A faixa e `[cancelado_em + 24h, cancelado_em + 24h + 7 dias)`. O piso e a
    RN-12.3; o teto e as duas razoes que `VALIDADE_DO_CONVITE` guarda.

    `cancelado_em` nulo nao autoriza envio: um agendamento CANCELADO sem
    carimbo e um estado que `cancelar` nao produz, e trata-lo como "cancelado
    ha muito tempo" mandaria mensagem por causa de uma linha adulterada a mao.
    Mesma recusa e mesma razao de `lembrete_devido`.

    Keyword-only: sao dois `datetime` adjacentes, e trocar a ordem devolveria
    o resultado errado em silencio.
    """
    if cancelado_em is None:
        return False
    for nome, momento in (("cancelado_em", cancelado_em), ("agora", agora)):
        if momento.tzinfo is None:
            raise ValueError(f"{nome} sem tzinfo: passe um datetime aware.")
    devido_em = cancelado_em + ANTECEDENCIA_DO_CONVITE
    return devido_em <= agora < devido_em + VALIDADE_DO_CONVITE


def kind_do_convite(agendamento_id: uuid.UUID) -> str:
    """Um `kind` por agendamento, e nao um fixo.

    Mesmo raciocinio de `kind_da_confirmacao` e de `kind_do_lembrete`: a
    reserva de `outbound_dispatches` e UNIQUE (message_id, kind) e a ancora e
    a ultima mensagem DO LEAD, entao dois cancelamentos do mesmo lead cairiam
    na mesma linha de `messages` e o segundo convite seria suprimido como
    reentrega -- para sempre.
    """
    return f"{PREFIXO_DO_KIND}{agendamento_id.hex[:20]}"


def template_do_convite(*, aprovados: frozenset[str]) -> str | None:
    """O template, SE a Meta o aprovou. `None` quando nao.

    Com `aprovados` vazio -- o default, e a realidade do RT-03 -- devolve
    `None`, e todo convite fora da janela de 24h deixa de sair. E a mesma
    lacuna que a TEC-171 declarou, e aqui ela morde ainda mais: o lead que
    cancelou e, por definicao, alguem que parou de falar com o agente.
    """
    return TEMPLATE_DO_CONVITE if TEMPLATE_DO_CONVITE in aprovados else None
