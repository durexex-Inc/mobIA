from collections.abc import Sequence

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao
from mobia.evals.metricas import Classificacao, ResultadoDaMetrica, ResumoDeConfianca


def _marca_de(errada: Classificacao) -> str:
    """Por que este turno entrou na lista, quando a linha nao deixa obvio.

    Os tres casos nao pedem a mesma acao. Palpite certo e rebaixado e
    calibragem; palpite errado que o rebaixamento salva explica a acuracia
    efetiva estar acima da crua; palpite errado e rebaixado erra duas vezes.
    Sem a marca, a primeira linha ainda pareceria um bug do relatorio -- ela
    mostra `esperada -> obtida` iguais.
    """
    if errada.certa:
        return "  <-- certa, rebaixada para INDEFINIDA"
    if errada.certa_na_efetiva:
        return "  <-- errada, mas o rebaixamento acerta o rotulo"
    if errada.desambiguaria:
        return "  <-- errada, e rebaixada para INDEFINIDA"
    return ""


def _secao_de_erradas(erradas: Sequence[Classificacao]) -> list[str]:
    """Nomeia turno por turno, porque agregado nao da para investigar.

    A matriz diz que INVESTIMENTO virou COMPRA sete vezes; ela nao diz quais
    sete. Sem estas linhas, descobrir isso custa outra execucao paga -- e o
    relatorio vive em log efemero de CI, entao ou esta aqui ou nao existe.
    Sem teto de linhas de proposito: no pior caso e um turno por linha, e uma
    lista truncada devolve o leitor exatamente ao problema que ela resolve.
    """
    linhas = [
        "",
        "## Classificacoes erradas",
        "",
        "conversa_id[indice]: esperada -> obtida (confianca)",
        "",
    ]
    for errada in erradas:
        linhas.append(
            f"- {errada.conversa_id}[{errada.indice}]: "
            f"{errada.esperada.value} -> {errada.obtida.value} "
            f"({errada.confianca}){_marca_de(errada)}"
        )
    return linhas


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
    erradas: Sequence[Classificacao] = (),
) -> str:
    linhas = ["# Avaliacao da classificacao de intencao", ""]

    for metrica in metricas:
        linhas.append(f"- **{metrica.nome}**: {metrica.faixa.value} -- {metrica.detalhe}")

    if confianca is not None:
        linhas += _secao_de_confianca(confianca)

    if erradas:
        linhas += _secao_de_erradas(erradas)

    if confusao:
        linhas += ["", "## Matriz de confusao", "", "esperada -> obtida (contagem)", ""]
        for esperada in sorted(confusao, key=lambda i: i.value):
            for obtida, quantas in sorted(
                confusao[esperada].items(), key=lambda par: (-par[1], par[0].value)
            ):
                marca = "" if esperada is obtida else "  <-- erro"
                linhas.append(f"- {esperada.value} -> {obtida.value}: {quantas}{marca}")

    return "\n".join(linhas) + "\n"
