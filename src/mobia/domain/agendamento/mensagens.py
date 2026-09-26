"""O que o lead e o corretor leem sobre o agendamento. TEC-170 e TEC-371.

Dois momentos, no mesmo lugar porque o vocabulario e um so. **Depois** que o
agendamento existe: a confirmacao ao lead, o aviso ao corretor e o do
cancelamento (TEC-170 e TEC-172), carregados por `confirmacao.py` e por
`ciclo.py`. **Durante** a conversa que o cria: a oferta de janelas, a
pergunta de confirmacao e as duas reofertas (TEC-371), montadas por
`conversa.py`.

Puro: nao toca banco nem rede. Ver
docs/superpowers/specs/2026-09-24-tec-170-confirmar-agendamento-design.md e
docs/superpowers/specs/2026-09-25-tec-371-agendar-pela-conversa-design.md.
"""

from collections.abc import Sequence
from datetime import datetime

from mobia.domain.agendamento.data_falada import data_e_hora_absolutas
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.catalogo.models import Imovel
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho, Prioridade
from mobia.domain.notificacao.mensagem import Aviso

# Texto ao lead: com acento (TEC-267). Nenhum dos tres diz que o corretor "foi
# avisado": o e-mail aceito pelo servidor nao e o e-mail lido (TEC-286).
TEXTO_DA_CONFIRMACAO_DE_VISITA = (
    "Sua visita está confirmada para {quando}, em {endereco}. Quem vai te receber é {corretor}."
)
# Visita com `imovel_id` nulo: o schema permite, e um endereco inventado seria
# pior que nenhum.
TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL = (
    "Sua visita está confirmada para {quando}. Quem vai te receber é {corretor}."
)
TEXTO_DA_CONFIRMACAO_DE_REUNIAO = (
    "Sua reunião remota está confirmada para {quando}, com {corretor}."
)


def descrever_lead(channel: str, telefone: str | None) -> str:
    """A linha "Lead:" do e-mail ao corretor e do evento na agenda. TEC-203:
    o telefone revelado, porque o corretor precisa dele para a visita; o par
    ja nao o carrega."""
    return f"{channel} +{telefone}" if telefone else f"{channel} (sem telefone informado)"


def endereco_de(imovel: Imovel) -> str:
    """O endereco que o catalogo permite dar. D4 do desenho.

    `Imovel` nao tem logradouro, numero nem CEP: titulo e codigo identificam o
    imovel, e bairro, cidade e UF o situam. O numero exato o corretor passa.
    """
    return f"{imovel.titulo} (cód. {imovel.codigo}) — {imovel.bairro}, {imovel.cidade}/{imovel.uf}"


def texto_ao_lead(*, tipo: str, inicio: datetime, corretor: str, imovel: Imovel | None) -> str:
    quando = data_e_hora_absolutas(inicio)
    if tipo == TipoDeCompromisso.REUNIAO_REMOTA:
        return TEXTO_DA_CONFIRMACAO_DE_REUNIAO.format(quando=quando, corretor=corretor)
    if imovel is None:
        return TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL.format(quando=quando, corretor=corretor)
    return TEXTO_DA_CONFIRMACAO_DE_VISITA.format(
        quando=quando, endereco=endereco_de(imovel), corretor=corretor
    )


# TEC-172, RN-12.3. A etiqueta e a prioridade do aviso de cancelamento sao
# literais daqui, e **nao** saem de `ETIQUETA_DE`/`PRIORIDADE_DE`, como as do
# aviso de confirmacao logo abaixo. Duas razoes:
#
# - Nao ha `Gatilho` de cancelamento, e nao vai haver: a docstring daquele
#   enum registra que ele nasceu completo e que acrescentar valor custa
#   migration. Este aviso nao abre handoff nenhum.
# - Reusar `ETIQUETA_DE[AGENDAMENTO_CONFIRMADO]` mandaria um e-mail de
#   CANCELAMENTO etiquetado "agendamento-confirmado" -- uma citacao que nao
#   bate com o produto, no campo que o corretor usa para triar a caixa.
ETIQUETA_DO_CANCELAMENTO = "agendamento-cancelado"


def aviso_de_cancelamento(
    *,
    tipo: str,
    inicio: datetime,
    corretor: str,
    imovel: Imovel | None,
    lead: str,
    link: str,
) -> Aviso:
    """O e-mail que diz ao corretor que o horario dele voltou a ficar livre.

    Mesma forma de `aviso_ao_corretor` -- os dados do compromisso mais a
    identificacao do lead --, porque o corretor precisa reconhecer QUAL
    compromisso caiu, e a data e a hora sao como ele o reconhece na agenda.
    """
    quando = data_e_hora_absolutas(inicio)
    remota = tipo == TipoDeCompromisso.REUNIAO_REMOTA
    assunto = f"{'Reunião remota' if remota else 'Visita'} cancelada: {quando}"
    linhas = [
        f"Quando era: {quando}",
        f"Tipo: {'Reunião remota' if remota else 'Visita presencial'}",
        f"Corretor: {corretor}",
    ]
    if not remota and imovel is not None:
        linhas.append(f"Imóvel: {endereco_de(imovel)}")
    linhas.append(f"Lead: {lead}")
    linhas.append("O horário já voltou a ficar disponível na sua agenda.")
    linhas.append(f"Conversa completa: {link}")
    return Aviso(
        assunto=assunto,
        corpo="\n".join(linhas),
        etiqueta=ETIQUETA_DO_CANCELAMENTO,
        prioridade=str(Prioridade.NORMAL),
        link=link,
    )


def aviso_ao_corretor(
    *,
    tipo: str,
    inicio: datetime,
    corretor: str,
    imovel: Imovel | None,
    lead: str,
    link: str,
) -> Aviso:
    """O e-mail ao corretor: os dados do lead mais a identificacao dele. D3.

    Etiqueta e prioridade vem do vocabulario do handoff para este fato, que
    ja existe -- nenhum handoff e aberto (o desenho explica por que).
    """
    quando = data_e_hora_absolutas(inicio)
    remota = tipo == TipoDeCompromisso.REUNIAO_REMOTA
    assunto = f"{'Reunião remota' if remota else 'Visita'} confirmada: {quando}"
    linhas = [
        f"Quando: {quando}",
        f"Tipo: {'Reunião remota' if remota else 'Visita presencial'}",
        f"Corretor: {corretor}",
    ]
    if not remota and imovel is not None:
        linhas.append(f"Imóvel: {endereco_de(imovel)}")
    linhas.append(f"Lead: {lead}")
    linhas.append(f"Conversa completa: {link}")
    gatilho = Gatilho.AGENDAMENTO_CONFIRMADO
    return Aviso(
        assunto=assunto,
        corpo="\n".join(linhas),
        etiqueta=ETIQUETA_DE[gatilho],
        prioridade=str(PRIORIDADE_DE[gatilho]),
        link=link,
    )


# TEC-371, D11. O que o lead le nos tres turnos da conversa de agendamento.
# Com acento (TEC-267), e registrados em `tests/unit/literais_ao_lead.py` --
# sem o registro as guardas de acento e de promessa nao olham para eles.
#
# **Nenhum promete contato de ninguem** (TEC-286): o agente oferece, repete o
# que o lead escolheu e pergunta. Quem avisa o corretor e o job da RN-12.1,
# depois que existe agendamento.
TEXTO_DAS_JANELAS = "Tenho estes horários para a visita:\n{janelas}\nQual deles fica melhor?"
# O horario perdido para outro lead. **Nao diz "outro cliente"**: quem
# reservou pode ser o proprio corretor pela agenda dele, e afirmar o que nao
# se sabe e a mesma classe de erro que um endereco inventado.
TEXTO_DO_CONFLITO = (
    "Esse horário acabou de ser preenchido. Tenho estes:\n{janelas}\nAlgum deles serve?"
)
TEXTO_DA_RESERVA_VENCIDA = (
    "O horário ficou reservado por alguns minutos e a reserva expirou. "
    "Estes estão livres agora:\n{janelas}\nQual prefere?"
)
TEXTO_DE_OUTRO_HORARIO = "Sem problema. Tenho também:\n{janelas}\nAlgum destes fica bom?"
# A pergunta da RN-11.3: data e hora absolutas antes de gravar. **E aqui que a
# protecao do RT-10 acontece** -- se a escolha foi lida errado, e esta frase
# que o lead corrige, e por isso ela repete o horario por extenso em vez de
# dizer "esse horario".
TEXTO_DA_ESCOLHA = "Perfeito: {quando}, com {corretor}. Confirmo a visita?"


def linhas_das_janelas(janelas: Sequence[datetime]) -> str:
    """As janelas numeradas, uma por linha, cada uma com data e hora absolutas.

    **Numeradas porque o lead responde por posicao.** "a segunda" e "2" sao as
    respostas mais curtas possiveis, e `escolha.py::escolher` as le -- uma
    lista sem numero deixaria o ordinal sem ancora visivel.
    """
    return "\n".join(
        f"{ordinal}. {data_e_hora_absolutas(inicio)}" for ordinal, inicio in enumerate(janelas, 1)
    )


# TEC-372, RN-12.2 e RN-12.3. O que o lead le quando responde ao lembrete de
# 24 horas. Com acento (TEC-267) e registrados em `literais_ao_lead.py`.
#
# **Nenhum diz que o corretor "foi avisado"**, pela razao que os textos da
# TEC-170 logo acima ja registram: o e-mail aceito pelo servidor nao e o
# e-mail lido. O de cancelamento diz o que NOS fizemos -- a visita caiu --, e
# nada sobre quem soube disso.
TEXTO_DA_PRESENCA_CONFIRMADA = "Presença confirmada para {quando}. Até lá!"
TEXTO_DO_CANCELAMENTO_FEITO = "Pronto, cancelei a sua visita de {quando}."
TEXTO_DA_REMARCACAO = "Claro, vamos remarcar. Tenho estes horários:\n{janelas}\nQual prefere?"
