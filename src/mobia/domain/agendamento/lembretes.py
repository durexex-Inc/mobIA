"""Quando um lembrete e devido, e o que o lead le nele. TEC-171, RN-12.2.

Puro: nao toca banco nem rede, no molde de `mensagens.py` e de
`followup/cadencia.py`. Quem consulta, decide o canal e entrega e
`workers/jobs/sweep_lembretes.py`. Ver
docs/superpowers/specs/2026-09-25-tec-171-lembretes-de-agendamento-design.md.

**O vocabulario dos dois lembretes mora num `Lembrete` so** -- antecedencia,
marco seguinte, prefixo do kind, nome do template e os tres textos juntos.
Quatro listas paralelas indexadas por "24h" ou "2h" divergiriam na primeira
card que acrescentasse um terceiro lembrete, e o sintoma seria o texto de um
sair com o kind do outro.

**Nada le a resposta do lead a estes textos.** O de 24 horas oferece
confirmar, remarcar e cancelar, porque e o que a RN-12.2 manda, e nenhuma das
tres e lida: `domain/agente/turno.py` nao importa nada de
`domain/agendamento/`, e as duas ultimas sao a TEC-172. Por isso os textos
CONVIDAM ("e so responder aqui") e nao prometem ("eu remarco para voce") --
a licao que a TEC-174 pagou.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from mobia.domain.agendamento.data_falada import data_e_hora_absolutas
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.mensagens import endereco_de
from mobia.domain.catalogo.models import Imovel

# Texto ao lead: portugues COM acento (TEC-267). Os seis estao registrados em
# `tests/unit/literais_ao_lead.py` -- e entrar naquela lista que os poe sob a
# guarda de acento e sob a de promessa (TEC-286).
#
# Nenhum diz que o corretor "foi avisado" ou "esta a caminho", pela mesma
# razao das tres constantes da TEC-170: um canal aceitar nao e entrega.
TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA = (
    "Passando para lembrar: sua visita é {quando}, em {endereco}. "
    "Quem vai te receber é {corretor}. Se precisar remarcar ou cancelar, é só responder aqui."
)
TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA_SEM_IMOVEL = (
    "Passando para lembrar: sua visita é {quando}. "
    "Quem vai te receber é {corretor}. Se precisar remarcar ou cancelar, é só responder aqui."
)
TEXTO_DO_LEMBRETE_DE_24H_DE_REUNIAO = (
    "Passando para lembrar: sua reunião remota é {quando}, com {corretor}. "
    "Se precisar remarcar ou cancelar, é só responder aqui."
)

# Faltando duas horas, o que serve e a hora e o endereco -- nao ha tempo util
# para remarcar, e perguntar seria oferecer o que nao cabe mais.
TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA = (
    "Sua visita é daqui a pouco, {quando}, em {endereco}. {corretor} te espera lá."
)
TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA_SEM_IMOVEL = (
    "Sua visita é daqui a pouco, {quando}. {corretor} te espera lá."
)
TEXTO_DO_LEMBRETE_DE_2H_DE_REUNIAO = "Sua reunião remota é daqui a pouco, {quando}, com {corretor}."


@dataclass(frozen=True, slots=True)
class Lembrete:
    """Um dos dois lembretes da RN-12.2, com tudo o que muda entre eles.

    `antecedencia` e o piso da faixa em que ele e devido; `proximo_marco` e o
    teto, exclusivo. Ver `lembrete_devido`, que e quem os usa, e a D2 do
    desenho, que e quem os justifica.

    `prefixo_do_kind` tem doze caracteres nos dois, de proposito: com os vinte
    primeiros do hex do id do agendamento eles fecham os trinta e dois de
    `outbound_dispatches.kind`, e uma aritmetica so vale para os dois. E a
    mesma conta de `kind_da_confirmacao` (`confirmacao.py`), que a explica por
    extenso.
    """

    chave: str
    antecedencia: timedelta
    proximo_marco: timedelta
    prefixo_do_kind: str
    template: str
    texto_de_visita: str
    texto_de_visita_sem_imovel: str
    texto_de_reuniao: str


LEMBRETE_DE_24H = Lembrete(
    chave="24h",
    antecedencia=timedelta(hours=24),
    # O marco seguinte e o lembrete de 2 horas: passado ele, o de 24 horas
    # deixou de fazer sentido e nao sai mais.
    proximo_marco=timedelta(hours=2),
    prefixo_do_kind="lembrete_24_",
    template="lembrete_visita_24h",
    texto_de_visita=TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA,
    texto_de_visita_sem_imovel=TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA_SEM_IMOVEL,
    texto_de_reuniao=TEXTO_DO_LEMBRETE_DE_24H_DE_REUNIAO,
)

LEMBRETE_DE_2H = Lembrete(
    chave="2h",
    antecedencia=timedelta(hours=2),
    # Zero, e nao um marco: depois do inicio do compromisso nao ha lembrete
    # nenhum a dar.
    proximo_marco=timedelta(0),
    # `_02_` e nao `_2_`, para que os dois prefixos tenham o mesmo tamanho e a
    # conta dos 32 caracteres seja uma so.
    prefixo_do_kind="lembrete_02_",
    template="lembrete_visita_2h",
    texto_de_visita=TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA,
    texto_de_visita_sem_imovel=TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA_SEM_IMOVEL,
    texto_de_reuniao=TEXTO_DO_LEMBRETE_DE_2H_DE_REUNIAO,
)

# Na ordem em que vencem. A varredura itera sobre esta tupla.
LEMBRETES: tuple[Lembrete, ...] = (LEMBRETE_DE_24H, LEMBRETE_DE_2H)


def _exigir_fuso(nome: str, momento: datetime) -> None:
    # Mesma recusa e mesma razao de `horario_permite_envio`: comparar um naive
    # com um aware levanta `TypeError` no meio da varredura, e aceitar o naive
    # com `astimezone` assumiria o fuso do sistema, que difere entre esta
    # maquina (UTC-3) e o runner do CI (UTC).
    if momento.tzinfo is None:
        raise ValueError(f"{nome} sem tzinfo: passe um datetime aware.")


def lembrete_devido(
    lembrete: Lembrete,
    *,
    inicio: datetime,
    confirmado_em: datetime | None,
    agora: datetime,
) -> bool:
    """Se `lembrete` e devido agora para um compromisso que comeca em `inicio`.

    A faixa e `[inicio - antecedencia, inicio - proximo_marco)`. D2 do
    desenho, e cada ponta tem uma razao diferente:

    **O piso e a CA-12.1** -- "quando o relogio chega a 24 h antes, entao o
    lembrete e enviado". Com o cron de cinco em cinco minutos, "chega a" e a
    primeira passagem em que `agora >= inicio - antecedencia`.

    **O teto e o que impede a regra de mentir.** Sem ele, um worker parado por
    tres horas faria a passagem seguinte mandar o lembrete de 24 horas JUNTO
    com o de 2 horas -- e "voce consegue ir? da para remarcar" noventa minutos
    antes da visita e outra mensagem, nao a mesma atrasada. O teto de cada
    faixa e o marco do lembrete seguinte, o que da vinte e duas horas de folga
    ao de 24h e duas ao de 2h: cabe qualquer indisponibilidade plausivel, e a
    mensagem nunca sai depois de ter deixado de fazer sentido.

    **E `confirmado_em` e a terceira condicao, que e o caso do agendamento
    confirmado em cima da hora.** Um confirmado tres horas antes da visita tem
    `agora >= inicio - 24h` verdadeiro no instante em que nasce: sem esta
    condicao o lead receberia a confirmacao da TEC-170 e, minutos depois, um
    "lembrete de 24 horas" repetindo a mesma data, a mesma hora e o mesmo
    endereco. Um lembrete cujo momento ja tinha passado quando o agendamento
    foi confirmado nunca existiu.

    `confirmado_em` nulo nao autoriza envio. A coluna e nulavel e `confirmar`
    sempre a preenche, entao nulo com status CONFIRMADO e uma linha que nenhum
    caminho do codigo produz; trata-la como "confirmado ha muito tempo"
    mandaria mensagem por causa de um estado adulterado a mao.

    Tudo keyword-only depois do lembrete: `inicio`, `confirmado_em` e `agora`
    sao tres `datetime` adjacentes, e trocar dois deles devolveria o resultado
    errado em silencio, sem erro de tipo -- mesma razao de `dentro_da_janela`
    e de `horario_permite_envio`.
    """
    _exigir_fuso("inicio", inicio)
    _exigir_fuso("agora", agora)
    if confirmado_em is None:
        return False
    _exigir_fuso("confirmado_em", confirmado_em)
    momento = inicio - lembrete.antecedencia
    if confirmado_em >= momento:
        return False
    return momento <= agora < inicio - lembrete.proximo_marco


def kind_do_lembrete(lembrete: Lembrete, agendamento_id: uuid.UUID) -> str:
    """O `kind` do envio: um por lembrete E por agendamento.

    A reserva de `outbound_dispatches` e UNIQUE (message_id, kind), e a ancora
    e a ultima mensagem DO LEAD. Dois agendamentos do mesmo lead caem na mesma
    linha de `messages`, entao um kind fixo por lembrete faria o segundo ser
    suprimido como reentrega -- para sempre. O pedaco do id separa os dois; o
    mesmo agendamento continua repetindo o mesmo kind, que e o que torna a
    reexecucao segura. O raciocinio inteiro esta em `kind_da_confirmacao`
    (`confirmacao.py`), e nao se repete aqui.

    **Nenhum destes kinds entra em `_GRUPOS`** (`outbound/kinds.py`), pela
    mesma razao que `KIND_DO_FOLLOWUP` nao entra: cada lembrete e uma mensagem
    propria, e liberar a reserva do de 24 horas porque o de 2 falhou reabriria
    o envio de algo que o lead recebeu no dia anterior.
    """
    return f"{lembrete.prefixo_do_kind}{agendamento_id.hex[:20]}"


def texto_do_lembrete(
    lembrete: Lembrete,
    *,
    tipo: str,
    inicio: datetime,
    corretor: str,
    imovel: Imovel | None,
) -> str:
    """O texto ao lead, na mesma divisao em tres de `texto_ao_lead` (TEC-170).

    `endereco_de` e `data_e_hora_absolutas` vem emprestados, e nao remontados:
    "como um compromisso e mostrado ao lead" tem uma fonte so, e a confirmacao
    e o lembrete falam do mesmo compromisso.
    """
    quando = data_e_hora_absolutas(inicio)
    if tipo == TipoDeCompromisso.REUNIAO_REMOTA:
        return lembrete.texto_de_reuniao.format(quando=quando, corretor=corretor)
    if imovel is None:
        return lembrete.texto_de_visita_sem_imovel.format(quando=quando, corretor=corretor)
    return lembrete.texto_de_visita.format(
        quando=quando, endereco=endereco_de(imovel), corretor=corretor
    )


def escolher_template_do_lembrete(lembrete: Lembrete, *, aprovados: frozenset[str]) -> str | None:
    """O template deste lembrete, SE a Meta o aprovou. `None` quando nao.

    **Catalogo proprio, e nao uma categoria nova no `TEMPLATES` do follow-up**
    (`followup/template.py`): as tres categorias de la sao contextos de
    reengajamento, escolhidos por `categoria_da_novidade` a partir do par
    `(ficha, queda)` que um lembrete nao tem. O que os dois compartilham e a
    JANELA (`outbound/janela.py`) e a fonte da aprovacao
    (`Settings.templates_aprovados`), que e o mesmo fato externo do RT-03.

    Com `aprovados` vazio -- o default, e a realidade do RT-03 -- devolve
    `None` para os dois, e todo lembrete fora da janela de 24h deixa de sair.
    E a lacuna maior desta card, declarada na D4 do desenho: um lead que marcou
    visita ontem provavelmente nao escreveu desde entao, e vinte e quatro horas
    e exatamente a antecedencia do primeiro lembrete.
    """
    return lembrete.template if lembrete.template in aprovados else None
