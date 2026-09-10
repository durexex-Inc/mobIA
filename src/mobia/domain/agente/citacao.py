"""A guarda anti-alucinacao sobre a prosa do modelo. TEC-161.

Puro de proposito: nenhum I/O, nenhum banco, nenhuma chamada ao modelo -- no
molde de `apresentacao.py` e `dinheiro.py`. Guarda que depende de rede e
guarda que falha quando mais precisa funcionar.

**O que esta em jogo.** Depois da TEC-162 a ficha inteira vem do banco, entao
a unica superficie invencavel que sobrou e a prosa: o prefixo da legenda da
ficha 1 nos turnos de apresentacao, e a mensagem inteira nos outros. Este
modulo olha so para ela, e so para duas coisas dentro dela -- cifra e codigo.

**Erra por falta, nao por excesso.** Parafrase sem numero ("tenho um bem
espacoso na praia") passa. Bloquear turno correto e o unico jeito de uma
guarda anti-alucinacao perder a confianca de quem opera, e um falso positivo
custa uma resposta boa que o lead nao recebe.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mobia.domain.agente.apresentacao import reais_de
from mobia.domain.agente.dinheiro import valores_em

# 10%, em decimos, para a comparacao ficar em inteiro. `abs(d) * 10 <= preco`
# e exatamente "d esta dentro de 10% de preco", sem float e sem Decimal.
#
# O numero NAO e derivado: e emprestado da RN-09.3, que relaxa a faixa de
# preco em ate 10%. As duas coisas sao semanticamente diferentes -- relaxar
# busca nao e tolerar citacao --, e a escolha e deliberada: inventar uma
# segunda constante de tolerancia obrigaria a defender um numero novo sem
# dado para calibra-lo. Ver D4 do desenho.
#
# A janela e real: num imovel de R$ 500 mil, 50 mil reais de erro na prosa
# passam. O que a torna aceitavel e que a ficha logo abaixo, na MESMA
# mensagem, mostra o preco do banco.
TOLERANCIA_EM_DECIMOS = 1

# O formato do catalogo: AP-1004, CA-1005, TE-1001. Maiusculas de proposito --
# a prosa em minusculas nao carrega codigo. A coluna e String(20) sem
# constraint de formato, entao codigo de outra forma nao e detectado; a lacuna
# esta travada por `test_codigo_de_outro_formato_nao_e_detectado`.
_CODIGO = re.compile(r"\b[A-Z]{2,3}-\d{3,6}\b")


@dataclass(frozen=True, slots=True)
class Divergencia:
    """Uma coisa que a prosa afirmou e o banco nao sustenta.

    `citado` ja vem formatado para o log -- preco via `reais_de`, e nao em
    centavos. Nao e cosmetica: `_mascarar_digitos` (app/logging.py) come
    corridas de 10 a 15 digitos, e um imovel de R$ 10 milhoes em centavos sao
    exatamente 10 digitos. O valor sairia mascarado do log justamente no caso
    caro. Com pontos de milhar nao ha corrida.

    Nao carrega a prosa. Registra-la criaria no log exatamente aquilo que a
    guarda impediu de sair -- a mesma regra da moderacao de saida.
    """

    tipo: Literal["preco", "codigo"]
    citado: str


def _cabe_em_algum(citado: int, precos: Sequence[int]) -> bool:
    """O valor esta a menos de 10% de algum candidato.

    "Algum" e nao "o certo": a prosa fala de um imovel entre ate dez, e nao ha
    como saber qual. Exigir o candidato correto pediria uma ligacao que a
    prosa nao tem.
    """
    for preco in precos:
        if preco <= 0:
            # Preco zero ou negativo nao sustenta citacao nenhuma, e dividir
            # por ele levantaria dentro da guarda.
            continue
        if abs(citado - preco) * 10 <= preco * TOLERANCIA_EM_DECIMOS:
            return True
    return False


def _na_faixa(citado: int, faixa: tuple[int | None, int | None]) -> bool:
    """O valor esta dentro do que o lead declarou.

    Faixa toda `None` nao e faixa aberta: e ausencia de declaracao, e devolve
    False. Tratar ausencia como "qualquer valor serve" desligaria a guarda
    para todo lead que ainda nao falou de dinheiro.
    """
    minimo, maximo = faixa
    if minimo is None and maximo is None:
        return False
    if minimo is not None and citado < minimo:
        return False
    if maximo is not None and citado > maximo:
        return False
    return True


def divergencias_de(
    prosa: str,
    *,
    candidatos: Sequence[Mapping[str, Any]],
    faixa: tuple[int | None, int | None],
) -> tuple[Divergencia, ...]:
    """O que a prosa afirmou e o turno nao sustenta. Vazio significa que passa.

    `candidatos` vazio nao e caso especial: nenhum valor casa, e so a faixa do
    lead passa. E o que a TEC-265 previu ao deixar o campo nao-opcional -- "nao
    buscou" e "buscou e nao achou" tomam a mesma decisao aqui.

    Devolve TODAS as divergencias numa passada, e nao a primeira: quem
    investiga um bloqueio quer saber se o modelo errou o preco, o codigo, ou
    os dois.
    """
    precos = [int(c["preco_centavos"]) for c in candidatos if "preco_centavos" in c]
    codigos = {str(c["codigo"]) for c in candidatos if c.get("codigo")}

    divergencias: list[Divergencia] = []
    for citado in valores_em(prosa):
        if _cabe_em_algum(citado, precos) or _na_faixa(citado, faixa):
            continue
        divergencias.append(Divergencia(tipo="preco", citado=reais_de(citado)))
    for codigo in _CODIGO.findall(prosa):
        if codigo not in codigos:
            divergencias.append(Divergencia(tipo="codigo", citado=codigo))
    return tuple(divergencias)
