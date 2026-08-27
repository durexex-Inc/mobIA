from collections.abc import Sequence

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao
from mobia.evals.metricas import ResultadoDaMetrica, ResumoDeConfianca


def _secao_de_confianca(resumo: ResumoDeConfianca) -> list[str]:
    """A calibragem em numeros, para quem for recalibrar o limiar.

    Existe separada das metricas porque nao carrega faixa: nenhum destes
    numeros bloqueia por si -- quem bloqueia e a acuracia efetiva. O que eles
    fazem e explicar a diferenca entre as duas acuracias quando ela aparece, e
    dar ao TEC-210 a contagem que nenhuma outra execucao produz.
    """
    pct = resumo.abaixo_do_limiar * 100 / resumo.turnos if resumo.turnos else 0.0
    return [
        "",
        "## Confianca",
        "",
        f"- limiar de desambiguacao: {LIMIAR_DE_DESAMBIGUACAO}",
        f"- turnos abaixo do limiar: {resumo.abaixo_do_limiar}/{resumo.turnos} ({pct:.1f}%)",
        f"- acertos rebaixados para INDEFINIDA: {resumo.acertos_rebaixados}",
        f"- erros que o rebaixamento acertou: {resumo.acertos_recuperados}",
    ]


def render(
    metricas: Sequence[ResultadoDaMetrica],
    confusao: dict[Intencao, dict[Intencao, int]],
    *,
    confianca: ResumoDeConfianca | None = None,
) -> str:
    linhas = ["# Avaliacao da classificacao de intencao", ""]

    for metrica in metricas:
        linhas.append(f"- **{metrica.nome}**: {metrica.faixa.value} -- {metrica.detalhe}")

    if confianca is not None:
        linhas += _secao_de_confianca(confianca)

    if confusao:
        linhas += ["", "## Matriz de confusao", "", "esperada -> obtida (contagem)", ""]
        for esperada in sorted(confusao, key=lambda i: i.value):
            for obtida, quantas in sorted(
                confusao[esperada].items(), key=lambda par: (-par[1], par[0].value)
            ):
                marca = "" if esperada is obtida else "  <-- erro"
                linhas.append(f"- {esperada.value} -> {obtida.value}: {quantas}{marca}")

    return "\n".join(linhas) + "\n"
