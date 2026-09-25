"""O que o lead e o corretor leem quando o agendamento e confirmado. TEC-170.

Puro: nao toca banco nem rede. `confirmacao.py` carrega o agendamento e chama
estas funcoes. Ver docs/superpowers/specs/2026-09-24-tec-170-confirmar-agendamento-design.md.
"""

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
    channel: str,
    conversation_key: str,
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
    linhas.append(f"Lead: {channel} {conversation_key}")
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
    channel: str,
    conversation_key: str,
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
    linhas.append(f"Lead: {channel} {conversation_key}")
    linhas.append(f"Conversa completa: {link}")
    gatilho = Gatilho.AGENDAMENTO_CONFIRMADO
    return Aviso(
        assunto=assunto,
        corpo="\n".join(linhas),
        etiqueta=ETIQUETA_DE[gatilho],
        prioridade=str(PRIORIDADE_DE[gatilho]),
        link=link,
    )
