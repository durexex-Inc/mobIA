"""A lista de espera de quem pediu visita sem horario livre. TEC-169, RN-11.5.

Puro: nao toca banco nem rede, no molde de `remarcacao.py` e `lembretes.py`.
Quem consulta, decide o canal e entrega e
`workers/jobs/sweep_lista_de_espera.py`; quem oferece e aceita e
`agendamento/conversa.py`.

**O horizonte de 72 horas NAO mora aqui** -- ele e `conversa.py::HORIZONTE`,
porque e a conversa que decide quando a lista e oferecida, e `janelas.py`
ja declara que "`ate` vem de quem chama". O que mora aqui e o horizonte
ESTENDIDO, que so existe depois de o lead recusar a fila.
"""

import uuid
from datetime import timedelta

# Quando o lead recusa a fila e pede datas mais para frente (quarto cenario da
# card), a grade passa a ser buscada neste horizonte em vez das 72 horas.
#
# Catorze dias, e nao um numero medido: e o intervalo em que a agenda do
# corretor ainda e informacao -- mais longe que isso, a grade muda antes de a
# visita chegar. Mesmo argumento e mesma honestidade do `VALIDADE_DO_CONVITE`
# de `remarcacao.py`, que declara ser um numero escolhido. Quem medir corrige.
#
# **Nao substitui as 72 horas.** Aquelas continuam decidindo a lista de
# espera, que e a regra do SRS; este e a resposta a um pedido explicito e so
# existe depois dele.
HORIZONTE_ESTENDIDO = timedelta(days=14)

# Doze caracteres, como `remarcacao__`, `confirmacao_` e `lembrete_24_`: com
# os vinte primeiros do hex do id fecham os trinta e dois de
# `outbound_dispatches.kind`. A conta por extenso esta em `kind_da_confirmacao`.
PREFIXO_DO_KIND = "espera_slot_"

# O nome do template aprovado, para o aviso que sai fora da janela de 24h da
# Meta. A aprovacao e fato EXTERNO (RT-03) e entra por
# `Settings.templates_aprovados`, nunca daqui.
TEMPLATE_DO_AVISO = "espera_slot_liberado"
IDIOMA_DO_TEMPLATE = "pt_BR"

# Os tres textos ao lead: portugues COM acento (TEC-267), registrados em
# `tests/unit/literais_ao_lead.py` -- e esse registro e o que os poe sob a
# guarda de `test_promessa_ao_lead.py`, nao a boa intencao de quem escreve.
#
# **O que eles podem afirmar.** Que a conversa entrou na fila de um corretor:
# isso e verdade, o handoff e criado na mesma transacao do aceite. O que
# nenhum deles pode e dizer que alguem viu o aviso ou que vai procurar o lead
# -- as duas frases que a TEC-174 e a TEC-286 proibiram, e que a Emenda E-01
# da RN-11.5 nomeia como a razao de esta regra ter ficado sem texto ate aqui.
TEXTO_DA_LISTA_DE_ESPERA = (
    "Não tenho horário livre nos próximos três dias. Posso te colocar na fila "
    "de um corretor para propor um horário, ou te mostrar datas mais para "
    "frente. O que prefere?"
)

# "eu te mostro aqui" e sobre ESTA conversa, que e o que o sweep de fato faz.
# Nao e uma pessoa que ligaria.
TEXTO_DA_ESPERA_ACEITA = (
    "Pronto, você está na fila desde agora. Se abrir um horário antes, eu te mostro aqui."
)

# Nao nomeia o horario liberado, e isso e deliberado (D7): a fila e por
# "quero visitar" e nao por slot, e prometer AQUELE horario criaria uma
# reserva que ninguem segura. Quem responder cai em `_oferecer`, que
# recalcula a grade de agora.
TEXTO_DO_SLOT_LIBERADO = (
    "Abriu horário para visita nos próximos dias. Quer que eu te mostre as opções?"
)


def kind_do_aviso(espera_id: uuid.UUID) -> str:
    """Um `kind` por linha da fila, e nao um fixo.

    Mesmo raciocinio de `kind_do_convite` e de `kind_do_lembrete`: a reserva
    de `outbound_dispatches` e UNIQUE (message_id, kind) e a ancora e a ultima
    mensagem DO LEAD, entao duas passagens pela fila do mesmo lead cairiam na
    mesma linha de `messages` e o segundo aviso seria suprimido como
    reentrega -- para sempre.
    """
    return f"{PREFIXO_DO_KIND}{espera_id.hex[:20]}"


def template_do_aviso(*, aprovados: frozenset[str]) -> str | None:
    """O template, SE a Meta o aprovou. `None` quando nao.

    Com `aprovados` vazio -- o default, e a realidade do RT-03 -- devolve
    `None`, e todo aviso fora da janela de 24h deixa de sair. E a mesma lacuna
    que a TEC-171 e a TEC-172 declararam, e aqui ela morde pelo mesmo motivo
    da remarcacao: quem esta na fila ha dias e, por construcao, alguem que
    parou de falar com o agente.

    **A fila nao trava por causa disto**: `avisada_em` e carimbada mesmo
    quando o envio nao sai, senao o proximo slot ficaria preso atras de um
    lead que nao pode ser avisado. Ver a D7 do desenho.
    """
    return TEMPLATE_DO_AVISO if TEMPLATE_DO_AVISO in aprovados else None
