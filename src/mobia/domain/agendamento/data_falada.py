"""A data que o lead fala, resolvida para janelas do motor. TEC-167, RN-11.3.

Puro de proposito, no molde de `domain/agente/dinheiro.py`: sem I/O, sem
banco, sem chamada ao modelo, e `agora` entra como parametro. A gramatica e
lista fixa e erra por falta -- e a falta vira pergunta, nunca chute, porque
chute aqui e visita no dia errado (RT-10). Estende-la e decisao de card.

**`resolver` nao levanta para texto do lead.** Qualquer sequencia de
caracteres e entrada valida, e uma excecao aqui derrubaria o turno inteiro --
o argumento e o mesmo da docstring de `dinheiro.py`. So `agora` sem fuso
levanta: e erro de programacao, nao de fala.

Este modulo e a ponte entre a data falada e o motor (`propor_janelas`): a
unica peca que conhece ambos. Nenhum codigo de producao chama este modulo
ainda: ver o desenho,
docs/superpowers/specs/2026-09-24-tec-167-data-em-linguagem-natural-design.md.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from mobia.app.config import get_settings
from mobia.domain.agendamento.janelas import (
    DURACAO,
    Intervalo,
    TipoDeCompromisso,
    propor_janelas,
)
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
    # None -- como ate a I5 -- busca a semana inteira. Com periodo ("semana
    # que vem a tarde"), `janelas_para` busca dia a dia, de segunda a
    # sabado, so naquele periodo.
    periodo: PeriodoDoDia | None = None


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
TEXTO_DO_FIM_DE_SEMANA = "Aos domingos não há atendimento. Pode ser {dia}?"
TEXTO_DO_DOMINGO = "Aos domingos não há atendimento. Que outro dia fica bom para você?"
TEXTO_DE_HOJE_OU_DA_PROXIMA = "Você quer dizer hoje, {hoje}, ou {proxima}?"
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

# Formas sem acento de MESES, na mesma ordem -- o mesmo papel que _NOMES tem
# para DIAS_DA_SEMANA. "marco" e o que `dobrar("março")` devolve (cedilha
# tambem sai na normalizacao NFD).
_MES_NOMES = (
    "janeiro",
    "fevereiro",
    "marco",
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
# `º`/`o` opcional depois do numero: "1º/9", "dia 1º" -- o proprio modulo
# escreve "1º" em `data_absoluta`, e o lead pode ecoar do jeito que le.
_DIA_E_MES = re.compile(r"\b(\d{1,2})(?:º|o)?/(\d{1,2})(?:/(\d{4}|\d{2}))?\b")
# "dia" opcional, "de <mes por extenso>" obrigatorio, "de <ano>" opcional --
# e o que distingue esta forma de `_DIA_DO_MES` (que nunca leva mes) e de
# `_DIA_E_MES` (que nunca leva mes por extenso). Precisa rodar ANTES de
# `_DIA_DO_MES`: "dia 3 de outubro" contem "dia 3", que `_DIA_DO_MES` casaria
# sozinho e deixaria "de outubro" sobrando sem dono. O ano, quando vem, entra
# no MESMO match -- `_apagar` some com ele junto, e ele nunca sobra para ser
# lido como hora depois.
_DIA_DE_MES_EXTENSO = re.compile(
    r"\b(?:dia )?(\d{1,2})(?:º|o)? de (" + "|".join(_MES_NOMES) + r")(?: de (\d{4}|\d{2}))?\b"
)
_DIA_DO_MES = re.compile(r"\bdia (\d{1,2})(?:º|o)?\b")
_NOITE = re.compile(r"\bnoite\b")
_MANHA = re.compile(r"\bmanha\b")
_TARDE = re.compile(r"\btarde\b")
_MEIO_DIA = re.compile(r"\bmeio[- ]dia\b")
_HORA_E_MINUTO = re.compile(r"\b(\d{1,2})[h:](\d{2})\b")
# "horas?" opcional entre o numero e "da manha/tarde": "1 hora da tarde", "2
# horas da tarde" -- sem quebrar a forma mais curta, "10 da manha".
_HORA_COM_PERIODO = re.compile(r"\b(\d{1,2}) (?:horas?\s+)?da (manha|tarde)\b")
_HORA_COM_H = re.compile(r"\b(\d{1,2}) ?h\b")
_HORA_APOS_AS = re.compile(r"\bas (\d{1,2})\b")
# Uma hora logo depois de um qualificador de faixa ou limite nao e uma hora
# que o lead afirmou sozinha -- "entre 14 e 16h", "ate as 18", "a partir das
# 16h", "antes das 10". Sem `\b` no fim: nao importa o que vem depois do
# numero (h, minuto, nada), so que ele exista logo ali.
_HORA_QUALIFICADA = re.compile(
    r"\b(?:entre|ate|antes d[ae]s?|depois d[ae]s?|a partir d[ae]s?)\s+(?:as\s+)?\d{1,2}"
)

_NOMES = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
# Todo padrao que reconhece uma mencao de hora, para contar QUANTAS a frase
# tem -- I4: duas horas na mesma frase tambem descartam a hora, junto com o
# qualificador acima.
_PADROES_DE_HORA: tuple[re.Pattern[str], ...] = (
    _MEIO_DIA,
    _HORA_E_MINUTO,
    _HORA_COM_PERIODO,
    _HORA_COM_H,
    _HORA_APOS_AS,
)


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


def _ano_por_mes(hoje: date, mes: int) -> int:
    """O ano quando so o mes foi dito, sem ano falado. C1.

    Mes ANTERIOR ao corrente e o mesmo mes do ano que vem -- "5/1" dito em
    dezembro e janeiro que vem, nao um 5/1 que ja passou. Mes corrente ou
    posterior fica no ano corrente. Isto so decide o ANO: se o dia dentro do
    mes corrente ja tiver passado, quem chama compara a data resolvida com
    `hoje` e devolve TEXTO_DO_PASSADO -- esta funcao nao sabe o dia.
    """
    return hoje.year + 1 if mes < hoje.month else hoje.year


def _contar_mencoes_de_hora(texto: str) -> int:
    """Quantas mencoes de hora existem na frase, sem contar a mesma mencao
    duas vezes so porque duas formas diferentes casam pedacos sobrepostos
    dela. I4.

    "amanha as 15:30" tem UMA hora, mas `_HORA_APOS_AS` sozinho casaria "as
    15" (o prefixo) e `_HORA_E_MINUTO` casaria "15:30" (o todo) -- duas
    posicoes de match para a mesma mencao, se contadas independentes. Este
    laco consome na MESMA ordem de prioridade da extracao real (a mais
    especifica primeiro) e apaga o que casou antes de tentar a proxima
    forma na MESMA passada, para que a forma menos especifica nunca ache de
    novo o que a mais especifica ja resolveu.
    """
    restante = texto
    contagem = 0
    mudou = True
    while mudou:
        mudou = False
        for padrao in _PADROES_DE_HORA:
            casamento = padrao.search(restante)
            if casamento:
                restante = _apagar(restante, casamento)
                contagem += 1
                mudou = True
    return contagem


def resolver(texto: str, *, agora: datetime) -> Resolucao:
    if agora.tzinfo is None or agora.utcoffset() is None:
        raise ValueError(f"`agora` sem fuso: {agora!r}")
    fuso = get_settings().fuso_de_envio
    local = agora.astimezone(fuso)
    hoje = local.date()
    falado = dobrar(texto)[:_TAMANHO_MAXIMO]

    if _FIM_DE_SEMANA.search(falado):
        sabado = hoje + timedelta(days=(5 - hoje.weekday()) % 7)
        if sabado == hoje and local.hour >= 18:
            # As 18h de sabado so restam 60 minutos de atendimento (fecha as
            # 19h) -- perto demais para valer como oferta de "hoje", ainda
            # mais com as 3h de antecedencia que o motor exige por baixo.
            # Oferece o sabado seguinte, nao o de hoje. M11.
            sabado += timedelta(days=7)
        return Ambigua(TEXTO_DO_FIM_DE_SEMANA.format(dia=data_absoluta(sabado)))

    # Dias achados, com a posicao na frase: a posicao ordena a pergunta de
    # "dois dias" na ordem em que o lead os disse.
    dias: list[tuple[int, date]] = []

    for casa in _DIA_E_MES.finditer(falado):
        falado = _apagar(falado, casa)
        dia_num, mes_num = int(casa.group(1)), int(casa.group(2))
        ano_falado = casa.group(3)
        # C1: ano falado ("03/09/2027", "3/9/27") manda; sem ele, o mes
        # decide o ano (`_ano_por_mes`) -- e a comparacao com `hoje` abaixo,
        # a mesma dos dois ramos, pega tanto o dia que ja passou no mes
        # corrente quanto o ano falado que ja passou.
        ano = (
            (int(ano_falado) if len(ano_falado) == 4 else 2000 + int(ano_falado))
            if ano_falado is not None
            else _ano_por_mes(hoje, mes_num)
        )
        dia = _data(ano, mes_num, dia_num)
        if dia is None:
            return Ambigua(TEXTO_DA_DATA_INEXISTENTE)
        if dia < hoje:
            return Ambigua(TEXTO_DO_PASSADO)
        dias.append((casa.start(), dia))

    # "dia 3 de outubro", "3 de setembro", "3 de outubro de 2027": mes por
    # extenso, ano opcional -- o mesmo tratamento de ano do laco de
    # `_DIA_E_MES` acima (falado manda; sem ele, `_ano_por_mes`). Roda ANTES
    # de `_DIA_DO_MES`: ver o comentario do proprio regex, acima.
    for casa in _DIA_DE_MES_EXTENSO.finditer(falado):
        falado = _apagar(falado, casa)
        dia_num = int(casa.group(1))
        mes_num = _MES_NOMES.index(casa.group(2)) + 1
        ano_falado = casa.group(3)
        ano = (
            (int(ano_falado) if len(ano_falado) == 4 else 2000 + int(ano_falado))
            if ano_falado is not None
            else _ano_por_mes(hoje, mes_num)
        )
        dia = _data(ano, mes_num, dia_num)
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

    # Este laco nao tem return dentro dele: um segundo dia na mesma frase --
    # "segunda ou terca", "sabado ou domingo" -- nao pode ser descartado por
    # um return precoce achando o primeiro. Existem returns ANTES deste
    # ponto -- seis ao todo: o de "fim de semana", mais cinco dentro dos tres
    # lacos de data explicita acima (dois no de dia/mes, dois no de mes por
    # extenso, um no de dia do mes, para data impossivel ou passada) -- mas
    # nenhum deles esta NESTE laco. Toda decisao sobre o dia da semana (dois
    # dias? domingo? hoje ou proxima?) fica para depois de juntar TODAS as
    # mencoes.
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
    # Snapshot ANTES de qualquer apagar: I4 precisa ver todas as mencoes de
    # hora e o qualificador na frase inteira, nao no que sobrar depois que a
    # primeira ja foi consumida.
    falado_antes_da_hora = falado
    hora: int | None = None
    minuto = 0
    periodo_da_hora: str | None = None
    casa_hora: re.Match[str] | None = None
    if casa_meio_dia := _MEIO_DIA.search(falado):
        # M10: "meio-dia"/"meio dia" e 12h, sem digito nenhum para casar.
        falado = _apagar(falado, casa_meio_dia)
        hora = 12
    else:
        casa_hora = _HORA_E_MINUTO.search(falado)
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

    # I4: uma hora logo depois de "entre"/"ate"/"antes das"/"depois das"/"a
    # partir das", ou duas horas na mesma frase, nunca viram Instante --
    # comprometer uma hora que o lead nao afirmou sozinho e o mesmo chute que
    # a RN-11.3 proibe para dia. A frase resolve sem hora (dia, periodo, ou
    # NaoReconhecida); a janela proposta depois e a confirmacao absoluta
    # fecham o resto.
    if (
        _HORA_QUALIFICADA.search(falado_antes_da_hora)
        or _contar_mencoes_de_hora(falado_antes_da_hora) > 1
    ):
        hora = None
        minuto = 0
        periodo_da_hora = None

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
    # hora <12, ou hora nua de 1 a 6) -- fora deles, o numero que o lead
    # disse e o que vale.
    if hora is not None and periodo_da_hora is None:
        if periodo is PeriodoDoDia.TARDE and hora < 12:
            hora += 12
        elif periodo is None and 1 <= hora <= 6:
            # 3h ou 15h? Ninguem visita imovel as 3h, mas a regra e perguntar,
            # nao supor: supor aqui e o chute que a RN-11.3 proibe. So ate 6:
            # de 7 em diante (19h) ja e a borda do atendimento (I3), e o
            # texto so oferece a hora da tarde -- 7 vira Instante direto, sem
            # pergunta nem soma.
            return Ambigua(TEXTO_DA_HORA_AMBIGUA.format(hora=hora + 12))

    if semana_que_vem and dia_falado is None:
        # I5: periodo ou hora ditos junto de "semana que vem" viram o
        # periodo da Semana -- a hora exata cai, pelo mesmo argumento do I4
        # (nao comprometer o que o lead nao afirmou tao precisamente).
        periodo_da_semana = periodo
        if periodo_da_semana is None and hora is not None:
            periodo_da_semana = PeriodoDoDia.MANHA if hora < 12 else PeriodoDoDia.TARDE
        return Semana(proxima_segunda, periodo_da_semana)
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


def janelas_para(
    resolucao: Resolucao,
    *,
    agora: datetime,
    jornada_inicio: int,
    jornada_fim: int,
    ocupados: Sequence[Intervalo],
    tipo: TipoDeCompromisso,
) -> list[Intervalo] | Ambigua | NaoReconhecida:
    """As janelas que a data falada pede, ou a resolucao que pede pergunta.

    `Ambigua` e `NaoReconhecida` voltam como vieram, sem chamar o motor:
    quem chama faz a pergunta. As outras viram um `[de, ate]` para
    `propor_janelas`. Um `Instante` que nao cabe -- ocupado, fora da grade,
    fora do atendimento -- cai nas janelas do mesmo dia.

    `[]` e um resultado real deste retorno, nao falta de alternativa: "hoje
    as 18h" dito as 16h, por exemplo, nao tem janela nenhuma com as 3h de
    antecedencia dentro do mesmo dia. Quem chama (TEC-168) e quem transforma
    lista vazia em pergunta -- este modulo so devolve o que ha.
    """
    fuso = get_settings().fuso_de_envio

    def buscar(de: datetime, ate: datetime) -> list[Intervalo]:
        return propor_janelas(
            agora=agora,
            de=de,
            ate=ate,
            jornada_inicio=jornada_inicio,
            jornada_fim=jornada_fim,
            ocupados=ocupados,
            tipo=tipo,
        )

    def meia_noite(dia: date) -> datetime:
        return datetime(dia.year, dia.month, dia.day, tzinfo=fuso)

    match resolucao:
        case Instante(momento=momento):
            exata = buscar(momento, momento + DURACAO[tipo])
            if exata and exata[0].inicio == momento:
                return exata[:1]
            dia = momento.astimezone(fuso).date()
            return buscar(meia_noite(dia), meia_noite(dia + timedelta(days=1)))
        case Periodo(dia=dia, periodo=periodo):
            inicio, fim = LIMITES_DO_PERIODO[periodo]
            base = meia_noite(dia)
            return buscar(base + timedelta(hours=inicio), base + timedelta(hours=fim))
        case Dia(dia=dia):
            return buscar(meia_noite(dia), meia_noite(dia + timedelta(days=1)))
        case Semana(segunda=segunda, periodo=periodo):
            if periodo is None:
                return buscar(meia_noite(segunda), meia_noite(segunda + timedelta(days=7)))
            # I5: com periodo, um dia de cada vez -- segunda a sabado, nunca
            # domingo -- e so a PRIMEIRA janela daquele periodo naquele dia.
            # Ate 3, como o resto do modulo; para de olhar dias assim que
            # achar as 3, igual ao motor.
            inicio, fim = LIMITES_DO_PERIODO[periodo]
            janelas: list[Intervalo] = []
            for deslocamento in range(6):
                base = meia_noite(segunda + timedelta(days=deslocamento))
                do_dia = buscar(base + timedelta(hours=inicio), base + timedelta(hours=fim))
                if do_dia:
                    janelas.append(do_dia[0])
                if len(janelas) >= 3:
                    break
            return janelas
        case Ambigua() | NaoReconhecida():
            return resolucao
