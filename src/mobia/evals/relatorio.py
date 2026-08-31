from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao
from mobia.evals.metricas import (
    DISPERSAO_MEDIDA,
    MAX_CARACTERES_DA_RESPOSTA,
    MAX_PERGUNTAS_POR_TURNO,
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    DecomposicaoDaExtracao,
    Discrepancia,
    FalhaDeInfraestrutura,
    ResultadoDaMetrica,
    ResumoDaExtracaoEfetiva,
    ResumoDeConfianca,
    ResumoDeNegativos,
    ResumoDoFormato,
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
        # Indentado sob a falha, e nao concatenado nela: a mensagem do provedor
        # pode ter 300 caracteres, e a lista continua legivel de relance.
        if falha.motivo:
            linhas.append(f"    {falha.motivo}")
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


def _valores_de(discrepancia: Discrepancia) -> str:
    """O que cada lado tinha, para `divergiu` nao precisar de outra execucao paga.

    Endereco sozinho basta para `faltou` e `extra` -- quem for anotar abre o
    YAML e ve. Nao basta para `divergiu`: os dois lados existem, e sem os
    valores nao da para saber se o modelo errou o campo ou se as duas formas so
    nao casaram. A baseline de 30/08/2026 (TEC-247) morreu nessa distincao,
    com sete `divergiu` em `regiao` e nenhum valor guardado.

    Usa `!r` de proposito. Este texto e lido por quem esta cacando defeito de
    comparacao, e `repr` e o que torna visiveis exatamente as diferencas que
    `str` esconde: acento, espaco sobrando, `600000` contra
    `Decimal('600000.00')`, `"2"` contra `2`.
    """
    partes = []
    if discrepancia.esperado is not None:
        partes.append(f"anotado {discrepancia.esperado!r}")
    if discrepancia.obtido is not None:
        partes.append(f"obtido {discrepancia.obtido!r}")
    return f" -- {', '.join(partes)}" if partes else ""


def _secao_de_formato(resumo: ResumoDoFormato) -> list[str]:
    """O formato da resposta, aberto por regra. So diagnostico.

    Quem bloqueia e `aderencia ao tom`; esta secao diz **o que fazer** com
    aquele numero: violacao de tamanho e violacao de numero de perguntas pedem
    consertos diferentes, e um total unico esconderia qual dos dois esta
    acontecendo.

    A contagem de emoji nao entra na metrica de proposito. A regra do card e
    "a informacao essencial nunca depende de emoji", e isso exige entender o
    que a frase afirma -- se a figurinha substitui uma palavra ou so decora.
    Nenhuma contagem responde isso. O numero fica aqui como pista para quem
    for ler as respostas, com a limitacao dita.
    """
    por_regra: dict[str, int] = defaultdict(int)
    for violacao in resumo.violacoes:
        por_regra[violacao.regra] += 1

    linhas = [
        "",
        "## Formato da resposta (diagnostico)",
        "",
        f"- {resumo.respostas} respostas do agente medidas",
        f"- acima de {MAX_CARACTERES_DA_RESPOSTA} caracteres: {por_regra['comprimento']}",
        f"- com mais de {MAX_PERGUNTAS_POR_TURNO} pergunta: {por_regra['perguntas']}",
        f"- com emoji: {resumo.com_emoji} ({resumo.emojis} no total)",
        "",
        '  A contagem de emoji **nao** entra na metrica. A regra e "a',
        '  informacao essencial nunca depende de emoji", e decidir isso exige',
        "  entender o que a frase afirma -- nenhuma contagem responde. O numero",
        "  fica como pista para quem for ler as respostas.",
        "",
        "  Contar `?` e proxy, como o de reperguntas: erra nas duas direcoes.",
    ]
    if resumo.violacoes:
        linhas += ["", "Onde:", ""]
        for violacao in resumo.violacoes:
            linhas.append(
                f"  - {violacao.conversa_id} turno {violacao.indice}: "
                f"{violacao.regra} -- {violacao.medido}"
            )
    return linhas


def _secao_da_extracao_efetiva(resumo: ResumoDaExtracaoEfetiva) -> list[str]:
    """A extracao medida como producao a experimenta -- estado final da
    conversa, e nao turno a turno.

    Espelha o que `acuracia_efetiva` faz para a intencao. `None` nao apaga
    (ver `campos_a_gravar`), entao um campo que o modelo deixou de reemitir
    num turno posterior continua gravado, e a metrica turno a turno conta um
    erro que o lead nunca experimenta.

    Diagnostico: nao entra em `bloqueia`. Promove-la a metrica que trava
    pediria piso proprio e medido -- o de `precisao_da_extracao` foi calibrado
    contra outra conta.
    """
    taxa = resumo.taxa
    medida = (
        "sem campo para comparar"
        if taxa is None
        else f"{resumo.acertos}/{resumo.total} ({taxa:.1%})"
    )
    linhas = [
        "",
        "## Extracao efetiva: o estado que a conversa deixou (diagnostico)",
        "",
        f"- {resumo.conversas} conversas, estado final contra anotacao acumulada",
        f"- campos corretos no estado: {medida}",
        "",
        "  Compare com a precisao turno a turno acima. A diferenca entre as",
        "  duas nao e erro de nenhuma: `None` nao apaga, entao um campo que o",
        "  modelo deixou de reemitir num turno posterior continua gravado. A",
        "  metrica turno a turno cobra a reemissao; o lead experimenta o",
        "  estado. Onde as duas discordam, e a de cima que mede o modelo e",
        "  esta que mede o produto.",
    ]
    if resumo.divergencias:
        linhas += ["", "Campos errados no estado final:", ""]
        for d in resumo.divergencias:
            valores = ""
            if d.tipo == "faltou":
                valores = f" -- anotado {d.esperado!r}"
            elif d.tipo == "extra":
                valores = f" -- obtido {d.obtido!r}"
            else:
                valores = f" -- anotado {d.esperado!r}, obtido {d.obtido!r}"
            linhas.append(f"  - {d.conversa_id}: {d.campo} ({d.tipo}){valores}")
    return linhas


def _secao_da_conta_da_extracao(decomposicao: DecomposicaoDaExtracao) -> list[str]:
    """A conta da metrica que trava, aberta -- e o aviso de quanto ela resolve.

    Existe porque o numero de manchete e o pior lugar para comparar duas
    execucoes, e ate a TEC-253 nada dizia isso a quem lia o relatorio. A
    TEC-250 atribuiu um ganho de 8,1 pontos chamando-o de "cinco vezes maior
    que o ruido" contra uma dispersao de 1,7 medida num par de execucoes; um
    segundo par deu 5,7, e a frase caiu.

    Esta secao vem **antes** da lista de discrepancias de proposito: quem abre
    o relatorio para comparar com a execucao anterior precisa esbarrar no poder
    de resolucao antes de formar opiniao, nao depois.
    """
    taxa = decomposicao.taxa_sobre_base_fixa
    sobre_base = "sem campo anotado" if taxa is None else f"{taxa:.1%} da base fixa"
    return [
        "",
        "## Extracao: a conta aberta, e quanto ela resolve (diagnostico)",
        "",
        f"- campos anotados no corpus (base fixa): {decomposicao.anotados}",
        f"- acertos: {decomposicao.acertos} -- {sobre_base}",
        f"- faltou: {decomposicao.faltou} | divergiu: {decomposicao.divergiu} "
        f"| inventados (extra): {decomposicao.extra}",
        "",
        "  A metrica que trava usa denominador de uniao (esperado | obtido), e",
        "  e assim de proposito: sem contar o inventado, um modelo que acerta o",
        "  anotado e inventa mais quatro tiraria 100%. O preco e que ela soma",
        "  numa razao so duas coisas que se movem diferente -- `faltou` e",
        "  `divergiu` medem o defeito e sao estaveis; `extra` oscila, e cada",
        "  campo inventado desconta duas vezes, deixando de ser acerto e",
        "  inflando o denominador.",
        "",
        f"  **Poder de resolucao (medido em {DISPERSAO_MEDIDA.data}, TEC-253):** duas",
        f"  execucoes do MESMO codigo ja diferiram {DISPERSAO_MEDIDA.uniao_pp:.1f} pontos na",
        f"  metrica de uniao e {DISPERSAO_MEDIDA.base_fixa_pp:.1f} na base fixa. Nao atribua a",
        "  uma mudanca um efeito dessa ordem a partir de uma execucao so --",
        "  compare `faltou` e `divergiu`, que sao a parte estavel, e trate",
        "  `extra` como quantidade que precisa de varias execucoes.",
        "",
        "  Duas execucoes nao sao distribuicao: e a maior diferenca observada,",
        "  nao a dispersao real.",
    ]


def _secao_de_extracao(
    discrepancias: Sequence[Discrepancia], negativos: ResumoDeNegativos | None
) -> list[str]:
    """Onde a extracao nao casou, agregado e por turno. So diagnostico.

    Nenhum numero aqui tem faixa, pelo mesmo motivo de `_secao_de_confianca` e
    `_secao_de_reperguntas`. Quem bloqueia e `precisao_da_extracao`; esta secao
    existe para dizer **o que fazer** com aquele numero.

    A leitura importa: `extra` acusa a medicao antes de acusar o modelo. Com o
    denominador de uniao, um campo que o modelo extraiu certo e que ninguem
    anotou desconta exatamente como uma invencao. Campo com muitos `extra` e
    nenhuma anotacao no corpus e forte candidato a lacuna de anotacao, nao a
    defeito do modelo.

    A lista por turno vem depois do agregado de proposito: o agregado diz onde
    esta o problema, e o endereco (conversa e turno) e o que evita gastar outra
    execucao paga so para achar onde anotar.

    `negativos` muda essa leitura quando existe: num turno negativo o corpus
    esta anotado por completo, e o completo e vazio, entao `extra` ali deixa
    de ser ambiguo e vira invencao sem discussao possivel.
    """
    por_campo: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in discrepancias:
        por_campo[d.campo][d.tipo] += 1

    linhas = [
        "",
        "## Extracao: campos que nao casaram (diagnostico)",
        "",
        f"- total de discrepancias: {len(discrepancias)}",
    ]
    if negativos is not None:
        unidade_campo = "campo" if negativos.campos_inventados == 1 else "campos"
        linhas += [
            f"- {negativos.turnos} turnos negativos medidos, "
            f"{negativos.com_invencao} com invencao "
            f"({negativos.campos_inventados} {unidade_campo})",
            "",
            "  Num turno negativo, `extra` e invencao sem ambiguidade: o turno",
            "  esta anotado por completo, e o completo e vazio.",
            "",
        ]
    for campo, tipos in sorted(por_campo.items(), key=lambda par: (-sum(par[1].values()), par[0])):
        detalhe = ", ".join(f"{tipo}: {quantos}" for tipo, quantos in sorted(tipos.items()))
        linhas.append(f"  - {campo} -- {detalhe}")

    if discrepancias:
        linhas += ["", "Onde, para quem for anotar:", ""]
        for d in discrepancias:
            linhas.append(
                f"  - {d.conversa_id} turno {d.indice}: {d.campo} ({d.tipo}){_valores_de(d)}"
            )
    return linhas


def render(
    metricas: Sequence[ResultadoDaMetrica],
    confusao: dict[Intencao, dict[Intencao, int]],
    *,
    confianca: ResumoDeConfianca | None = None,
    erradas: Sequence[Classificacao] = (),
    infraestrutura: Sequence[FalhaDeInfraestrutura] = (),
    reperguntas: Sequence[tuple[str, int, str]] = (),
    discrepancias: Sequence[Discrepancia] = (),
    negativos: ResumoDeNegativos | None = None,
    decomposicao: DecomposicaoDaExtracao | None = None,
    efetiva: ResumoDaExtracaoEfetiva | None = None,
    formato: ResumoDoFormato | None = None,
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

    if decomposicao is not None:
        linhas += _secao_da_conta_da_extracao(decomposicao)

    if efetiva is not None:
        linhas += _secao_da_extracao_efetiva(efetiva)

    if formato is not None:
        linhas += _secao_de_formato(formato)

    if discrepancias or negativos is not None:
        linhas += _secao_de_extracao(discrepancias, negativos)

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


# Onde o relatorio de uma execucao paga fica quando ninguem escolhe o caminho.
# Relativo ao repositorio, e commitado: e a diferenca entre "a medicao existe"
# e "alguem viu a medicao passar num terminal". A execucao de 28/08/2026
# aconteceu, custou dinheiro, e o percentual e a faixa dela nao existem em
# lugar nenhum -- so a decomposicao por campo, porque alguem a copiou para a
# descricao da TEC-241 antes do terminal fechar.
DIRETORIO_DE_RELATORIOS = Path("evals/relatorios")


def preservar(texto: str, destino: Path) -> Path:
    """Grava o relatorio em disco, criando o diretorio se preciso.

    Existe separada de `render` porque as duas falham de jeitos diferentes e
    so uma delas pode derrubar a execucao. `render` e pura e roda sempre;
    esta toca o sistema de arquivos, e quem a chama tem de poder decidir o que
    fazer quando o disco recusa -- num runner pago, a resposta certa e
    imprimir o relatorio e seguir, nunca perder a medicao junto com o arquivo.

    Nao dateia nem versiona o nome: quem chama escolhe o caminho, porque o
    nome carrega a data e o commit do corpus, e essas duas coisas o modulo de
    render nao tem como saber.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    return destino
