"""Qual das janelas oferecidas o lead escolheu. TEC-371, D5.

Puro de proposito, no molde de `data_falada.py`: sem I/O, sem banco, sem
chamada ao modelo, e `agora` entra como parametro. **Nunca levanta para texto
do lead** -- qualquer sequencia de caracteres e entrada valida, e uma excecao
aqui derrubaria o turno inteiro.

**`NaoEscolheu` nao produz texto, e quem chama cai fora.** Uma pergunta nossa
aqui ("nao entendi, qual dos tres?") competiria com a resposta que o modelo
daria: o lead que pergunta "quanto e o condominio?" no meio da escolha tem de
receber o valor do condominio, e nao uma repergunta sobre horario.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mobia.app.config import get_settings
from mobia.domain.agendamento.data_falada import (
    LIMITES_DO_PERIODO,
    Dia,
    Instante,
    Periodo,
    Semana,
    resolver,
)
from mobia.domain.agendamento.propostas import Proposta
from mobia.domain.texto import dobrar


@dataclass(frozen=True)
class Escolhida:
    proposta: Proposta


@dataclass(frozen=True)
class NaoEscolheu:
    pass


Resultado = Escolhida | NaoEscolheu


# **"segunda" e ordinal aqui, e nao dia da semana.** Numa lista de tres
# janelas a leitura ordinal e a que o lead quis, e o custo esta declarado na
# D5: quem responde "segunda" querendo o dia recebe a segunda janela -- e le
# a data absoluta na pergunta de confirmacao, que e a protecao que a RN-11.3
# existe para dar contra o RT-10.
#
# `(?! feira)` e o unico recorte: quem escreve "segunda-feira" por extenso
# nomeou o dia, nao a posicao, e ai a via da data resolve.
_ORDINAL_POR_PALAVRA = re.compile(r"\b(primeir[ao]|segund[ao](?! feira)|terceir[ao]|ultim[ao])\b")

_POSICAO_DA_PALAVRA = {"primeir": 1, "segund": 2, "terceir": 3}

# O digito so conta quando e a mensagem INTEIRA, com no maximo um artigo
# antes. Solto no meio da frase ele e hora ("as 3"), preco ou quantidade de
# quartos -- e "as 3" chega aqui como `Instante`, pela via da data.
_ORDINAL_POR_DIGITO = re.compile(r"^(?:a|o|na|no|opcao|numero)? ?([123])$")

_ESPACOS = re.compile(r"\s+")
_SO_LETRAS_ESPACO_E_DIGITO = re.compile(r"[^a-z0-9 ]+")


def _normalizar(texto: str) -> str:
    limpo = _SO_LETRAS_ESPACO_E_DIGITO.sub(" ", dobrar(texto))
    return _ESPACOS.sub(" ", limpo).strip()


def _por_ordinal(normalizado: str, propostas: list[Proposta]) -> Proposta | None:
    casa = _ORDINAL_POR_PALAVRA.search(normalizado)
    if casa is not None:
        palavra = casa.group(1)
        if palavra.startswith("ultim"):
            return propostas[-1]
        posicao = _POSICAO_DA_PALAVRA[palavra[:-1]]
        return propostas[posicao - 1] if posicao <= len(propostas) else None
    digito = _ORDINAL_POR_DIGITO.match(normalizado)
    if digito is None:
        return None
    posicao = int(digito.group(1))
    # `1 <= posicao <= len` e nao `try/except IndexError`, pelo motivo que
    # `agente/recomendacao.py::resolver_ordinais` ja escreve: `lista[-1]`
    # devolve o ULTIMO item em vez de levantar, e um ordinal fora da faixa
    # marcaria a janela errada em silencio.
    return propostas[posicao - 1] if 1 <= posicao <= len(propostas) else None


def _dia_inteiro(dia: date, fuso: ZoneInfo) -> tuple[datetime, datetime]:
    inicio = datetime.combine(dia, time(0), tzinfo=fuso)
    return inicio, inicio + timedelta(days=1)


def _unica_dentro(propostas: list[Proposta], de: datetime, ate: datetime) -> Proposta | None:
    """A unica proposta que cai em [de, ate), ou nada.

    **Duas dentro e `None`, e nao a primeira.** "quinta" com duas janelas na
    quinta nao escolheu nada, e chutar uma delas gravaria uma reserva que o
    lead nao pediu -- o horario errado sai da agenda do corretor e o lead le
    uma confirmacao que nao bate com o que ele disse.
    """
    dentro = [p for p in propostas if de <= p.janela.inicio < ate]
    return dentro[0] if len(dentro) == 1 else None


def _por_data(texto: str, propostas: list[Proposta], *, agora: datetime) -> Proposta | None:
    fuso = get_settings().fuso_de_envio
    match resolver(texto, agora=agora):
        case Instante(momento=momento):
            exatas = [p for p in propostas if p.janela.inicio == momento]
            return exatas[0] if len(exatas) == 1 else None
        case Periodo(dia=dia, periodo=periodo):
            comeco, _ = _dia_inteiro(dia, fuso)
            de_hora, ate_hora = LIMITES_DO_PERIODO[periodo]
            return _unica_dentro(
                propostas, comeco + timedelta(hours=de_hora), comeco + timedelta(hours=ate_hora)
            )
        case Dia(dia=dia):
            de, ate = _dia_inteiro(dia, fuso)
            return _unica_dentro(propostas, de, ate)
        case Semana(segunda=segunda):
            de, _ = _dia_inteiro(segunda, fuso)
            return _unica_dentro(propostas, de, de + timedelta(days=7))
        case _:
            # `Ambigua` e `NaoReconhecida`: a data falada nao decide nada, e
            # inventar uma escolha a partir dela e o RT-10 de volta.
            return None


# A hora dita sozinha, sem dia. **Nao sai de `resolver`, e a razao e que a
# pergunta e outra.** Aquele modulo responde "que data o lead esta PROPONDO",
# e por isso devolve `Ambigua` para hora que ja passou hoje -- "as 9h" ditas
# as 10h nao sao proposta de nada. Aqui a pergunta e "a qual das janelas que
# ja oferecemos o lead se refere", e todas elas sao futuras por construcao:
# o lead que le "quinta as 9h" e responde "9h" as 10h da manha escolheu, e
# tratar isso como horario vencido seria recusar a propria oferta.
#
# Os tres padroes sao os mesmos de `data_falada.py` -- hora com minuto, hora
# com `h`, hora depois de "as" --, de proposito: o lead escreve do mesmo jeito
# nos dois lugares, e uma quarta forma so aqui seria gramatica que so um dos
# dois entende.
_HORA_E_MINUTO = re.compile(r"\b(\d{1,2})[h:](\d{2})\b")
_HORA_COM_H = re.compile(r"\b(\d{1,2}) ?h\b")
_HORA_APOS_AS = re.compile(r"\bas (\d{1,2})\b")


def _por_hora(normalizado: str, propostas: list[Proposta]) -> Proposta | None:
    fuso = get_settings().fuso_de_envio
    casa_com_minuto = _HORA_E_MINUTO.search(normalizado)
    if casa_com_minuto is not None:
        hora, minuto = int(casa_com_minuto.group(1)), int(casa_com_minuto.group(2))
    else:
        casa = _HORA_COM_H.search(normalizado) or _HORA_APOS_AS.search(normalizado)
        if casa is None:
            return None
        hora, minuto = int(casa.group(1)), 0
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    alvo = time(hora, minuto)
    na_hora = [
        p for p in propostas if p.janela.inicio.astimezone(fuso).time().replace(second=0) == alvo
    ]
    return na_hora[0] if len(na_hora) == 1 else None


def escolher(texto: str, propostas: list[Proposta], *, agora: datetime) -> Resultado:
    """A janela que o lead escolheu entre as que leu, ou `NaoEscolheu`.

    **Ordinal antes de data, e a ordem e decisao.** "a segunda" e ambiguo
    entre posicao e dia da semana, e numa lista de tres a posicao e a leitura
    que o lead quis -- ver o comentario de `_ORDINAL_POR_PALAVRA`.
    """
    if not propostas:
        return NaoEscolheu()
    normalizado = _normalizar(texto)
    if not normalizado:
        return NaoEscolheu()
    escolhida = (
        _por_ordinal(normalizado, propostas)
        # A data vem antes da hora solta porque ela e mais especifica: "quinta
        # as 11h" tem de casar a janela daquela quinta, e nao ficar ambigua
        # com a outra janela das 11h de sexta.
        or _por_data(texto, propostas, agora=agora)
        or _por_hora(normalizado, propostas)
    )
    return Escolhida(escolhida) if escolhida is not None else NaoEscolheu()
