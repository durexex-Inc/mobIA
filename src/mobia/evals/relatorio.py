from collections.abc import Sequence

from mobia.domain.agente.schemas import Intencao
from mobia.evals.metricas import ResultadoDaMetrica


def render(
    metricas: Sequence[ResultadoDaMetrica],
    confusao: dict[Intencao, dict[Intencao, int]],
) -> str:
    linhas = ["# Avaliacao da classificacao de intencao", ""]

    for metrica in metricas:
        linhas.append(f"- **{metrica.nome}**: {metrica.faixa.value} -- {metrica.detalhe}")

    if confusao:
        linhas += ["", "## Matriz de confusao", "", "esperada -> obtida (contagem)", ""]
        for esperada in sorted(confusao, key=lambda i: i.value):
            for obtida, quantas in sorted(confusao[esperada].items(), key=lambda par: -par[1]):
                marca = "" if esperada is obtida else "  <-- erro"
                linhas.append(f"- {esperada.value} -> {obtida.value}: {quantas}{marca}")

    return "\n".join(linhas) + "\n"
