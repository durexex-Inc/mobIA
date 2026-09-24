"""A data que o lead fala, resolvida para o calendario. TEC-167, RN-11.3.

Puro de proposito, no molde de `domain/agente/dinheiro.py`: sem I/O, sem
banco, sem chamada ao modelo, e `agora` entra como parametro. A gramatica e
lista fixa e erra por falta -- e a falta vira pergunta, nunca chute, porque
chute aqui e visita no dia errado (RT-10). Estende-la e decisao de card.

**`resolver` nao levanta para texto do lead.** Qualquer sequencia de
caracteres e entrada valida, e uma excecao aqui derrubaria o turno inteiro --
o argumento e o mesmo da docstring de `dinheiro.py`. So `agora` sem fuso
levanta: e erro de programacao, nao de fala.

Nenhum codigo de producao chama este modulo ainda: ver o desenho,
docs/superpowers/specs/2026-09-24-tec-167-data-em-linguagem-natural-design.md.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from mobia.app.config import get_settings
from mobia.domain.texto import dobrar


class PeriodoDoDia(StrEnum):
    MANHA = "MANHA"
    TARDE = "TARDE"


# 19 e literal, nao lido de `Settings`: a D3 do desenho fixa o periodo da
# tarde em 12h-19h, gramatica fixa igual ao resto deste modulo (D1). Hoje
# esse numero coincide com o padrao de `atendimento_horario_fim`, mas e
# coincidencia de valor, nao acoplamento de codigo -- mudar aquele setting
# NAO move este limite nem o "19h" escrito em `TEXTO_DA_NOITE`.
LIMITES_DO_PERIODO: dict[PeriodoDoDia, tuple[int, int]] = {
    PeriodoDoDia.MANHA: (9, 12),
    PeriodoDoDia.TARDE: (12, 19),
}


@dataclass(frozen=True)
class Instante:
    momento: datetime


@dataclass(frozen=True)
class Periodo:
    dia: date
    periodo: PeriodoDoDia


@dataclass(frozen=True)
class Dia:
    dia: date


@dataclass(frozen=True)
class Semana:
    segunda: date


@dataclass(frozen=True)
class Ambigua:
    # Texto pronto para o lead: uma das constantes `TEXTO_...` abaixo, ja com
    # as datas preenchidas.
    pergunta: str


@dataclass(frozen=True)
class NaoReconhecida:
    pass


Resolucao = Instante | Periodo | Dia | Semana | Ambigua | NaoReconhecida

# O texto que o lead le: portugues com acento (TEC-267). Registrados em
# `tests/unit/literais_ao_lead.py`, para as guardas de acento e de promessa.
TEXTO_DO_FIM_DE_SEMANA = "Aos domingos não há atendimento. Pode ser no {dia}?"
TEXTO_DO_DOMINGO = "Aos domingos não há atendimento. Que outro dia fica bom para você?"
TEXTO_DE_HOJE_OU_DA_PROXIMA = "Você quer dizer hoje, {hoje}, ou a próxima, {proxima}?"
TEXTO_DA_HORA_AMBIGUA = "Você quer dizer às {hora}h?"
TEXTO_DO_PASSADO = "Esse horário já passou. Que outro dia e horário ficam bons para você?"
TEXTO_DE_DOIS_DIAS = "Qual dos dois fica melhor para você: {primeiro} ou {segundo}?"
TEXTO_DA_NOITE = "O atendimento vai até as 19h. Pode ser no fim da tarde?"
TEXTO_DA_DATA_INEXISTENTE = (
    "Não encontrei essa data no calendário. Que outro dia fica bom para você?"
)

DIAS_DA_SEMANA = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MESES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_DOMINGO = 6

# Teto do texto examinado. A fala do lead e curta; o teto existe para que uma
# colagem de 10 mil caracteres custe o mesmo que uma frase.
_TAMANHO_MAXIMO = 300

# Sobre o texto ja dobrado (sem acento, caixa dobrada). `\b` em toda palavra:
# sem ele "amanha" conteria "manha" e todo "amanha" viraria periodo da manha.
_FIM_DE_SEMANA = re.compile(r"\b(?:fim|final) de semana\b")
_SEMANA_QUE_VEM = re.compile(r"\b(?:semana que vem|proxima semana)\b")
_DEPOIS_DE_AMANHA = re.compile(r"\bdepois de amanha\b")
_AMANHA = re.compile(r"\bamanha\b")
_HOJE = re.compile(r"\bhoje\b")
_DIA_DA_SEMANA = re.compile(r"\b(segunda|terca|quarta|quinta|sexta|sabado|domingo)(?:[- ]feira)?\b")
_DIA_E_MES = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
_DIA_DO_MES = re.compile(r"\bdia (\d{1,2})\b")
_NOITE = re.compile(r"\bnoite\b")
_MANHA = re.compile(r"\bmanha\b")
_TARDE = re.compile(r"\btarde\b")
_HORA_E_MINUTO = re.compile(r"\b(\d{1,2})[h:](\d{2})\b")
_HORA_COM_PERIODO = re.compile(r"\b(\d{1,2}) da (manha|tarde)\b")
_HORA_COM_H = re.compile(r"\b(\d{1,2}) ?h\b")
_HORA_APOS_AS = re.compile(r"\bas (\d{1,2})\b")

_NOMES = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")


def data_absoluta(dia: date) -> str:
    """ "quinta-feira, 27 de agosto" -- o ordinal no dia primeiro ("1º")."""
    numero = "1º" if dia.day == 1 else str(dia.day)
    return f"{DIAS_DA_SEMANA[dia.weekday()]}, {numero} de {MESES[dia.month - 1]}"


def data_e_hora_absolutas(momento: datetime) -> str:
    """ "quinta-feira, 27 de agosto, as 15h" -- sempre no fuso de Sao Paulo.

    As tres coisas que a RN-11.3 exige na confirmacao: dia da semana, dia do
    mes e horario. Qualquer que seja o fuso de `momento`, o que o lead le e a
    hora local dele.
    """
    local = momento.astimezone(get_settings().fuso_de_envio)
    hora = f"{local.hour}h" if local.minute == 0 else f"{local.hour}h{local.minute:02d}"
    return f"{data_absoluta(local.date())}, às {hora}"


def _apagar(texto: str, casa: re.Match[str]) -> str:
    # Troca o trecho casado por espacos do mesmo tamanho: as posicoes dos
    # outros achados continuam valendo, e "3/9" nao sobra para virar hora.
    return texto[: casa.start()] + " " * (casa.end() - casa.start()) + texto[casa.end() :]


def _data(ano: int, mes: int, dia: int) -> date | None:
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def resolver(texto: str, *, agora: datetime) -> Resolucao:
    if agora.tzinfo is None or agora.utcoffset() is None:
        raise ValueError(f"`agora` sem fuso: {agora!r}")
    fuso = get_settings().fuso_de_envio
    local = agora.astimezone(fuso)
    hoje = local.date()
    falado = dobrar(texto)[:_TAMANHO_MAXIMO]

    if _FIM_DE_SEMANA.search(falado):
        sabado = hoje + timedelta(days=(5 - hoje.weekday()) % 7)
        return Ambigua(TEXTO_DO_FIM_DE_SEMANA.format(dia=data_absoluta(sabado)))

    # Dias achados, com a posicao na frase: a posicao ordena a pergunta de
    # "dois dias" na ordem em que o lead os disse.
    dias: list[tuple[int, date]] = []

    for casa in _DIA_E_MES.finditer(falado):
        falado = _apagar(falado, casa)
        dia = _data(hoje.year, int(casa.group(2)), int(casa.group(1)))
        if dia is None:
            return Ambigua(TEXTO_DA_DATA_INEXISTENTE)
        if dia < hoje:
            return Ambigua(TEXTO_DO_PASSADO)
        dias.append((casa.start(), dia))

    for casa in _DIA_DO_MES.finditer(falado):
        falado = _apagar(falado, casa)
        numero = int(casa.group(1))
        # Estritamente no futuro: "dia 25" dito no dia 25 e o do mes que vem --
        # quem quer hoje diz "hoje".
        if numero > hoje.day:
            dia = _data(hoje.year, hoje.month, numero)
        else:
            ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
            dia = _data(ano, mes, numero)
        if dia is None:
            return Ambigua(TEXTO_DA_DATA_INEXISTENTE)
        dias.append((casa.start(), dia))

    semana_que_vem = _SEMANA_QUE_VEM.search(falado)
    proxima_segunda = hoje + timedelta(days=7 - hoje.weekday())

    for padrao, deslocamento in ((_DEPOIS_DE_AMANHA, 2), (_AMANHA, 1), (_HOJE, 0)):
        for casa in padrao.finditer(falado):
            falado = _apagar(falado, casa)
            dias.append((casa.start(), hoje + timedelta(days=deslocamento)))

    # Nenhum return aqui dentro (fora dos dois ja existentes acima, para data
    # explicita impossivel ou passada): um segundo dia na mesma frase --
    # "segunda ou terca", "sabado ou domingo" -- nao pode ser descartado por
    # um return precoce achando o primeiro. Toda decisao (dois dias? domingo?
    # hoje ou proxima?) fica para depois de juntar TODAS as mencoes.
    veio_de_semana_atual = False
    for casa in _DIA_DA_SEMANA.finditer(falado):
        falado = _apagar(falado, casa)
        alvo = _NOMES.index(casa.group(1))
        if semana_que_vem:
            dias.append((casa.start(), proxima_segunda + timedelta(days=alvo)))
            continue
        delta = (alvo - hoje.weekday()) % 7
        if delta == 0 and alvo != _DOMINGO:
            # O nome do dia da semana bate com o de hoje ("terca" numa
            # terca): esta mencao vale como "hoje" na lista de dias abaixo.
            # Se ela sobreviver como a UNICA mencao depois do descarte de
            # domingo, e so ai que vira a pergunta "hoje ou a proxima" --
            # nao aqui, porque um segundo dia na mesma frase tem prioridade
            # (RN-11.3: a falta vira pergunta, mas uma pergunta so).
            veio_de_semana_atual = True
        dias.append((casa.start(), hoje + timedelta(days=delta)))

    distintos = sorted({dia for _, dia in dias}, key=lambda d: min(p for p, x in dias if x == d))
    # Domingo nunca sobra como "o dia falado" -- nem quando o lead disse a
    # palavra, nem quando um dia relativo caiu nele por coincidencia
    # ("amanha" dito num sabado, "dia 20" que cai num domingo em 2026). As
    # duas fontes convergem aqui: qualquer data da lista que caia num domingo
    # sai do conjunto de dias validos e vira a marca `domingo_mencionado`.
    domingo_mencionado = any(dia.weekday() == _DOMINGO for dia in distintos)
    sem_domingo = [dia for dia in distintos if dia.weekday() != _DOMINGO]

    if len(sem_domingo) > 1:
        return Ambigua(
            TEXTO_DE_DOIS_DIAS.format(
                primeiro=data_absoluta(sem_domingo[0]), segundo=data_absoluta(sem_domingo[1])
            )
        )
    if domingo_mencionado and len(sem_domingo) == 1:
        # Domingo E outro dia na mesma frase ("sabado ou domingo"): o outro
        # dia e a oferta natural, e o texto do fim de semana ja serve para
        # qualquer dia, nao so sabado.
        return Ambigua(TEXTO_DO_FIM_DE_SEMANA.format(dia=data_absoluta(sem_domingo[0])))
    if domingo_mencionado:
        return Ambigua(TEXTO_DO_DOMINGO)
    dia_falado = sem_domingo[0] if sem_domingo else None
    if dia_falado is not None and dia_falado == hoje and veio_de_semana_atual:
        return Ambigua(
            TEXTO_DE_HOJE_OU_DA_PROXIMA.format(
                hoje=data_absoluta(hoje),
                proxima=data_absoluta(hoje + timedelta(days=7)),
            )
        )

    # Hora. As formas mais especificas primeiro, e cada uma apaga o que casou.
    hora: int | None = None
    minuto = 0
    periodo_da_hora: str | None = None
    casa_hora: re.Match[str] | None = _HORA_E_MINUTO.search(falado)
    if casa_hora:
        falado = _apagar(falado, casa_hora)
        h, m = int(casa_hora.group(1)), int(casa_hora.group(2))
        if h <= 23 and m <= 59:
            hora, minuto = h, m
    else:
        casa_hora = _HORA_COM_PERIODO.search(falado)
        if casa_hora:
            falado = _apagar(falado, casa_hora)
            h, periodo_da_hora = int(casa_hora.group(1)), casa_hora.group(2)
            if h <= 23:
                hora = h + 12 if periodo_da_hora == "tarde" and h < 12 else h
        else:
            casa_hora = _HORA_COM_H.search(falado) or _HORA_APOS_AS.search(falado)
            if casa_hora:
                falado = _apagar(falado, casa_hora)
                h = int(casa_hora.group(1))
                if h <= 23:
                    hora = h

    if _NOITE.search(falado):
        return Ambigua(TEXTO_DA_NOITE)
    periodo: PeriodoDoDia | None = None
    if _MANHA.search(falado):
        periodo = PeriodoDoDia.MANHA
    elif _TARDE.search(falado):
        periodo = PeriodoDoDia.TARDE

    # Hora explicita vence periodo contraditorio, de proposito: "quinta 15h
    # de manha" fica 15h, nao vira pergunta nem 3h. Os dois ramos abaixo so
    # ajustam a hora nos casos em que ela PRECISA de complemento (TARDE com
    # hora <12, ou hora nua de 1 a 7) -- fora deles, o numero que o lead
    # disse e o que vale.
    if hora is not None and periodo_da_hora is None:
        if periodo is PeriodoDoDia.TARDE and hora < 12:
            hora += 12
        elif periodo is None and 1 <= hora <= 7:
            # 3h ou 15h? Ninguem visita imovel as 3h, mas a regra e perguntar,
            # nao supor: supor aqui e o chute que a RN-11.3 proibe.
            return Ambigua(TEXTO_DA_HORA_AMBIGUA.format(hora=hora + 12))

    if semana_que_vem and dia_falado is None:
        return Semana(proxima_segunda)
    if dia_falado is None and hora is None and periodo is None:
        return NaoReconhecida()
    dia = dia_falado if dia_falado is not None else hoje

    if hora is not None:
        momento = datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=fuso)
        if momento < local:
            return Ambigua(TEXTO_DO_PASSADO)
        return Instante(momento)
    if periodo is not None:
        fim = datetime(dia.year, dia.month, dia.day, LIMITES_DO_PERIODO[periodo][1], tzinfo=fuso)
        if fim <= local:
            return Ambigua(TEXTO_DO_PASSADO)
        return Periodo(dia, periodo)
    return Dia(dia)
