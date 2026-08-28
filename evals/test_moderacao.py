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
        fora_do_ar = 0
        erradas: list[str] = []
        for caso in corpus[nome]:
            try:
                veredito = await moderador.moderar(caso["texto"], direcao=direcao)
            except ModeracaoIndisponivel as exc:
                # Fora do denominador, e nao contado como erro: um caso que o
                # moderador nao respondeu nao diz nada sobre o criterio dele.
                # Somado como erro, uma indisponibilidade viraria "falso
                # positivo" numa linha e "bloqueio perdido" na outra, e as duas
                # taxas que vao virar piso sairiam deflacionadas por um
                # problema de infraestrutura. A contagem nao some: aparece na
                # propria linha do arquivo e na linha de indisponibilidades.
                fora_do_ar += 1
                indisponiveis += 1
                erradas.append(f"{caso['id']}: INDISPONIVEL ({exc})")
                continue
            if veredito.bloqueado == esperado_bloqueado:
                acertos += 1
            else:
                obtido = "BLOQUEOU" if veredito.bloqueado else "LIBEROU"
                erradas.append(f"{caso['id']}: {obtido}, esperado o contrario")
        medidos = len(corpus[nome]) - fora_do_ar
        pct = f"{acertos * 100 / medidos:.1f}%" if medidos else "sem medida"
        sufixo = f", {fora_do_ar} fora do denominador" if fora_do_ar else ""
        linhas.append(f"- {nome}: {acertos}/{medidos} ({pct}{sufixo})")
        linhas.extend(f"    {e}" for e in erradas)

        if esperado_bloqueado:
            acertos_bloqueio += acertos
            total_bloqueio += medidos
        else:
            acertos_libera += acertos
            total_libera += medidos

    # As duas taxas que vao virar piso (com o numero na mao, nao adivinhado):
    # bloqueio agrega entrada_bloqueia + saida_bloqueia, falso positivo agrega
    # entrada_libera + saida_libera. Sem estas tres linhas, quem for cravar o
    # piso teria que recalcular na mao a partir das quatro linhas por arquivo.
    falsos_positivos = total_libera - acertos_libera

    def _linha(rotulo: str, parte: int, todo: int) -> str:
        """Fracao **e** porcentagem, na mesma unidade das linhas por arquivo.

        As linhas por arquivo sempre imprimiram porcentagem; estas imprimiam so
        a fracao, e a diferenca de unidade dentro do mesmo relatorio e um
        convite a comparar 0,9 com 90,0 -- justo nas linhas de onde o piso vai
        ser lido.
        """
        pct = f"{parte * 100 / todo:.1f}%" if todo else "sem medida"
        return f"- {rotulo}: {parte}/{todo} ({pct})"

    linhas.append(_linha("taxa de bloqueio (bloqueia)", acertos_bloqueio, total_bloqueio))
    linhas.append(_linha("taxa de falso positivo (libera)", falsos_positivos, total_libera))
    linhas.append(_linha("total", acertos_bloqueio + acertos_libera, total_bloqueio + total_libera))
    linhas.append(f"- indisponibilidades: {indisponiveis} (fora de todos os denominadores)")
    with capsys.disabled():
        print("\n# Moderacao no corpus\n" + "\n".join(linhas))

    # A unica asercao: o moderador respondeu. Sem piso, por decisao de spec.
    assert indisponiveis == 0, "o moderador nao respondeu em algum caso"
