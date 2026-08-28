"""Mede o moderador contra o corpus anotado. Chamada real, dinheiro real.

Arquivo proprio, e nao metrica nova no gate de intencao: os tres slots em
SEM_MECANISMO de la esperam extracao, alucinacao e tom, e encaixar moderacao
ali confundiria "a metrica ganhou mecanismo" com "chegou metrica nova".

Nenhum piso e cravado aqui. A TEC-210 provou que piso nao medido abre vermelho
na primeira execucao sem regressao nenhuma: este arquivo mede e imprime, e o
piso entra depois, com o numero na mao.
"""

from pathlib import Path

import pytest
import yaml

from mobia.domain.moderacao.port import Direcao, ModeracaoIndisponivel
from mobia.infra.moderacao import ModeradorAnthropic

CORPUS = Path(__file__).resolve().parent / "moderacao"

CASOS = [
    ("entrada_bloqueia", Direcao.ENTRADA, True),
    ("entrada_libera", Direcao.ENTRADA, False),
    ("saida_bloqueia", Direcao.SAIDA, True),
    ("saida_libera", Direcao.SAIDA, False),
]


@pytest.fixture(scope="session")
def corpus() -> dict[str, list[dict]]:
    return {
        nome: yaml.safe_load((CORPUS / f"{nome}.yaml").read_text(encoding="utf-8"))
        for nome, _, _ in CASOS
    }


async def test_moderacao_no_corpus(corpus, capsys) -> None:
    moderador = ModeradorAnthropic()
    linhas: list[str] = []
    indisponiveis = 0
    acertos_bloqueio = 0
    total_bloqueio = 0
    acertos_libera = 0
    total_libera = 0

    for nome, direcao, esperado_bloqueado in CASOS:
        acertos = 0
        erradas: list[str] = []
        for caso in corpus[nome]:
            try:
                veredito = await moderador.moderar(caso["texto"], direcao=direcao)
            except ModeracaoIndisponivel as exc:
                indisponiveis += 1
                erradas.append(f"{caso['id']}: INDISPONIVEL ({exc})")
                continue
            if veredito.bloqueado == esperado_bloqueado:
                acertos += 1
            else:
                obtido = "BLOQUEOU" if veredito.bloqueado else "LIBEROU"
                erradas.append(f"{caso['id']}: {obtido}, esperado o contrario")
        total = len(corpus[nome])
        pct = acertos * 100 / total
        linhas.append(f"- {nome}: {acertos}/{total} ({pct:.1f}%)")
        linhas.extend(f"    {e}" for e in erradas)

        if esperado_bloqueado:
            acertos_bloqueio += acertos
            total_bloqueio += total
        else:
            acertos_libera += acertos
            total_libera += total

    # As duas taxas que vao virar piso (com o numero na mao, nao adivinhado):
    # bloqueio agrega entrada_bloqueia + saida_bloqueia, falso positivo agrega
    # entrada_libera + saida_libera. Sem estas tres linhas, quem for cravar o
    # piso teria que recalcular na mao a partir das quatro linhas por arquivo.
    falsos_positivos = total_libera - acertos_libera
    linhas.append(f"- taxa de bloqueio (bloqueia): {acertos_bloqueio}/{total_bloqueio}")
    linhas.append(f"- taxa de falso positivo (libera): {falsos_positivos}/{total_libera}")
    linhas.append(f"- total: {acertos_bloqueio + acertos_libera}/{total_bloqueio + total_libera}")
    linhas.append(f"- indisponibilidades: {indisponiveis}")
    with capsys.disabled():
        print("\n# Moderacao no corpus\n" + "\n".join(linhas))

    # A unica asercao: o moderador respondeu. Sem piso, por decisao de spec.
    assert indisponiveis == 0, "o moderador nao respondeu em algum caso"
