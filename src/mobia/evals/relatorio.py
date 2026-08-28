from collections import defaultdict
from collections.abc import Sequence

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao
from mobia.evals.metricas import (
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    FalhaDeInfraestrutura,
    ResultadoDaMetrica,
    ResumoDeConfianca,
)


def _secao_de_infraestrutura(falhas: Sequence[FalhaDeInfraestrutura]) -> list[str]:
    """As conversas que a rede levou, separadas dos erros de classificacao.

    Vem logo depois das metricas e antes de tudo o mais porque muda como se le
    o resto: vermelho por 429 pede re-rodar, vermelho por regressao pede
    investigar, e o relatorio tem de dizer qual dos dois e antes de mostrar os
    numeros que o leitor vai interpretar. Diz explicitamente que estes turnos
    nao entraram em metrica nenhuma -- e a frase que impede rede instavel de
    ser lida como prompt pior.
    """
    linhas = [
        "",
        "## Falhas de infraestrutura",
        "",
        f"{len(falhas)} conversa(s) abandonada(s), teto {TETO_DE_CONVERSAS_ABANDONADAS}.",
        "Nao sao erro de classificacao: nenhum turno destas conversas entrou nas metricas.",
        "",
    ]
    for falha in falhas:
        linhas.append(f"- {falha.conversa_id}[{falha.indice}]: {falha.erro}")
    return linhas


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


def _secao_de_reperguntas(reperguntas: Sequence[tuple[str, int, str]]) -> list[str]:
    """Contagem do proxy de repergunta, so diagnostico -- nunca bloqueia.

    Mesmo motivo de `_secao_de_confianca`: nenhum numero aqui tem faixa.
    `MARCADORES_DE_REPERGUNTA` (`evals/test_acuracia_de_intencao.py`) e lista de
    palavra-chave, e o total nao e cota inferior nem superior de reperguntas
    -- e um indicador aproximado, com erro nas duas direcoes. Falso negativo
    por construcao: uma repergunta com outras palavras escapa. Falso
    positivo tambem: o agente pode citar "apartamento" ou "vaga" ao descrever
    um imovel numa frase que, por outro motivo, termina com "?". Ver os
    testes de `_reperguntou` em `tests/unit/test_evals_reperguntas.py`.
    """
    por_campo: dict[str, int] = defaultdict(int)
    for _, _, campo in reperguntas:
        por_campo[campo] += 1
    linhas = [
        "",
        "## Reperguntas (proxy de palavra-chave, diagnostico)",
        "",
        f"- total detectado: {len(reperguntas)}",
    ]
    for campo, quantos in sorted(por_campo.items(), key=lambda par: (-par[1], par[0])):
        linhas.append(f"  - {campo}: {quantos}")
    return linhas


def render(
    metricas: Sequence[ResultadoDaMetrica],
    confusao: dict[Intencao, dict[Intencao, int]],
    *,
    confianca: ResumoDeConfianca | None = None,
    erradas: Sequence[Classificacao] = (),
    infraestrutura: Sequence[FalhaDeInfraestrutura] = (),
    reperguntas: Sequence[tuple[str, int, str]] = (),
) -> str:
    linhas = ["# Avaliacao da classificacao de intencao", ""]

    for metrica in metricas:
        linhas.append(f"- **{metrica.nome}**: {metrica.faixa.value} -- {metrica.detalhe}")

    if infraestrutura:
        linhas += _secao_de_infraestrutura(infraestrutura)

    if confianca is not None:
        linhas += _secao_de_confianca(confianca)

    if reperguntas:
        linhas += _secao_de_reperguntas(reperguntas)

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
