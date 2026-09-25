"""Os fatos do lead, montados do banco e so do banco.

TEC-175, RN-15.1 e RN-15.3. Modulo sem I/O de proposito, no molde de
`vocabulario.py` e de `context/auditoria.py`: quem le do banco e o
repositorio; aqui so se decide o que vira texto.

**O modelo nunca ve o banco -- ele ve o que sai daqui.** A RN-15.3 manda todo
dado factual vir do estado estruturado, e este modulo e essa regra em forma
de arquitetura em vez de instrucao no prompt: o que nao entra no dossie o
modelo nao tem como citar. Instruir o modelo a nao inventar dependeria de ele
obedecer; isto nao depende.

O bloco (e) da RN-15.1 sai daqui mais magro que a regra promete, e e a emenda
E-01 dela que registra o porque: nao ha entidade Objecao neste sistema, entao
o bloco se monta de campos recusados, perguntas sem resposta e motivos de
descarte -- que sao pontos de atencao verdadeiros, mas nao sao a objecao que
o lead argumentou.
"""

from dataclasses import dataclass
from datetime import datetime

from mobia.domain.agente.delimitacao import delimitar

# O que se escreve onde o banco nao tem valor. Uma string so, e nao "" ou
# "None" espalhados: e ela que impede o modelo de ler a ausencia como zero --
# um lead sem score nunca teve score 0, do mesmo jeito que `lead_score_audit`
# guarda `total_anterior` nulo e nao zero no primeiro calculo.
AUSENTE = "nao informado"


@dataclass(frozen=True)
class ImovelApresentado:
    """Uma linha de `recomendacoes`, reduzida ao que o corretor precisa ver."""

    codigo: str
    preco_centavos: int
    # "venda" ou "aluguel": qual preco `preco_centavos` e. `Imovel` pode ter
    # os dois precos preenchidos ao mesmo tempo, e escolher um em silencio
    # poria um preco de VENDA no resumo de um lead que quer ALUGAR --
    # exatamente o numero errado na frase que a RN-15.3 promete vir do
    # banco. Rotular e mais barato que casar o preco com a intencao do lead:
    # isso exigiria saber qual operacao aquela `Recomendacao` buscou, dado
    # que a tabela nao guarda hoje.
    tipo_de_preco: str
    reacao: str | None
    motivo_descarte: str | None


@dataclass(frozen=True)
class Dossie:
    """Tudo o que o modelo vai ver, e nada alem disso."""

    # (a) quem e o lead e como chegou. Sem nome: nenhuma tabela deste sistema
    # guarda um -- ver a emenda E-02 da RN-15.1 e a L1 do desenho.
    canal: str
    conversa: str
    primeira_mensagem_em: datetime | None
    mensagens_do_lead: int

    # (b) o que procura.
    intencao: str | None
    faixa_min_centavos: int | None
    faixa_max_centavos: int | None
    regiao: str | None
    tipo_imovel: str | None
    quartos: int | None
    vagas: int | None
    urgencia: str | None
    forma_pagamento: str | None
    tem_imovel_para_vender: bool | None

    # (c) score, temperatura e justificativa.
    score_total: int | None
    score_fatores: tuple[tuple[str, int], ...]
    score_causas: tuple[str, ...]
    temperatura: str | None
    temperatura_forcada_motivos: tuple[str, ...]

    # (d) imoveis apresentados e reacoes.
    imoveis: tuple[ImovelApresentado, ...]

    # (e) pontos de atencao. Ver o cabecalho do modulo.
    campos_recusados: tuple[str, ...]
    perguntados_sem_resposta: tuple[str, ...]

    # (f) proxima acao: o que o gatilho e a prioridade ja dizem.
    gatilho: str
    etiqueta: str
    prioridade: str
    criado_em: datetime


def reais(centavos: int | None) -> str:
    """Centavos em moeda brasileira, sem centavos na saida.

    **Byte a byte igual a `reais_de` (`agente/apresentacao.py`)** -- revisao
    final da TEC-176, Minor 7. Nao e coincidencia: os dois formatam o mesmo
    fato, so que para consumidores diferentes (o resumo do corretor aqui, a
    ficha que o agente apresenta ao lead la), e a duplicacao precede esta
    branch. Nao unificar agora e decisao deliberada -- e um refactor fora do
    escopo desta card, entre dois modulos de dominios diferentes -- mas fica
    registrada aqui para uma card futura consolidar, em vez de a proxima
    pessoa redescobrir a duplicacao do zero.

    Sem casas decimais porque preco de imovel nao as tem na pratica e elas so
    gastariam caracteres do orcamento de 1.500 da RN-15.2.
    """
    if centavos is None:
        return AUSENTE
    return f"R$ {centavos // 100:,}".replace(",", ".")


def sim_nao(valor: bool | None) -> str:
    if valor is None:
        return AUSENTE
    return "sim" if valor else "nao"


def ou_ausente(valor: object | None) -> str:
    return AUSENTE if valor is None else str(valor)


def isoformat_ou_none(valor: datetime | None) -> str | None:
    """`.isoformat()` so roda quando ha data -- sem handoff sem mensagem do
    lead, `primeira_mensagem_em` e `None`, e `None.isoformat()` estouraria."""
    return None if valor is None else valor.isoformat()


def truncado(valor: str, teto: int | None) -> str:
    """Corta `valor` para no maximo `teto` caracteres, sem reticencias.

    TEC-176, revisao final (Critical 1a). Ate aqui so as LISTAS (`imoveis`,
    `campos_recusados`, `perguntados_sem_resposta`) tinham teto -- um campo
    de valor unico como `regiao` ia para o texto do tamanho que viesse do
    banco, sem corte nenhum. `regiao` e `String(120)` (`context/models.py`)
    e sozinho nao estoura os 1.500 da RN-15.2, mas somado a todo o resto do
    dossie no maximo que cada coluna aceita, estourava -- ver o comentario
    de `contingencia.montar`. Sem reticencias porque cada caractere de "..."
    e orcamento gasto tambem, e o cabecalho do bloco ja avisa que o campo
    pode ter sido cortado.

    `teto=None` devolve `valor` sem tocar -- e o caminho de `renderizar`, que
    nao corta nada porque o modelo recebe o dossie inteiro.
    """
    if teto is None or len(valor) <= teto:
        return valor
    return valor[:teto]


def faixa(dossie: Dossie) -> str:
    """A faixa como o lead a declarou, e nao um intervalo inventado.

    Minimo ausente com maximo presente e o caso comum ("ate 600 mil"), e
    escrever "de R$ 0 ate R$ 600.000" pareceria um piso que o lead nunca deu.
    """
    minimo, maximo = dossie.faixa_min_centavos, dossie.faixa_max_centavos
    if minimo is None and maximo is None:
        return AUSENTE
    if minimo is None:
        return f"ate {reais(maximo)}"
    if maximo is None:
        return f"a partir de {reais(minimo)}"
    return f"de {reais(minimo)} ate {reais(maximo)}"


def _aviso_de_corte(rotulo: str, total: int, teto: int, ordem: str) -> str:
    """ "rotulo (N no total, ORDEM T)": o UNICO texto para "esta lista foi
    cortada" no modulo (TEC-176, revisao final, Minor 5).

    Antes existiam dois: `imoveis()` escrevia "N imoveis apresentados,
    mostrando os primeiros T:" e `_lista_com_teto` escrevia "rotulo (N no
    total, primeiros T): ...". Mesmo conceito, mesmo arquivo, mesmo
    consumidor (o corretor lendo o resumo de contingencia) -- so a forma
    divergia.

    `ordem` diz COMO os T mostrados foram escolhidos, e por isso nao e fixo:
    `imoveis()` corta pelos "mais recentes" (ver `imoveis`, D6 do desenho);
    `campos_recusados` e `perguntados_sem_resposta` nao tem nocao de tempo
    nenhuma -- so ordem de insercao no banco --, entao continuam
    "primeiros".
    """
    return f"{rotulo} ({total} no total, {ordem} {teto})"


def imoveis(
    dossie: Dossie,
    teto: int | None = None,
    *,
    teto_codigo: int | None = None,
    teto_motivo_descarte: int | None = None,
) -> str:
    """A lista de imoveis apresentados, com corte opcional.

    `teto` existe para o resumo de contingencia (TEC-176): o dossie inteiro
    pode ter dezenas de imoveis, e o resumo tem o limite de 1.500 caracteres
    da RN-15.2. `renderizar` chama sem nenhum teto porque o modelo recebe o
    dossie inteiro -- ele e quem decide o que resumir.

    **Mostra os `teto` MAIS RECENTES, do mais novo para o mais antigo** --
    revisao final da TEC-176 (Important 3), corrigindo uma inversao: antes
    disto, `dossie.imoveis[:teto]` pegava os primeiros da lista, e
    `carregar_dossie` ordena por `apresentado_em` ASCENDENTE, entao o
    corretor via os imoveis mais VELHOS -- o oposto do exemplo literal da D6
    do desenho ("30 imoveis apresentados, os 5 mais recentes"). Escolhido
    mostrar do mais novo para o mais antigo (e nao em ordem cronologica) por
    ser exatamente o modo mais frio de contexto que este template serve: o
    ultimo imovel que o lead viu e o que tem mais a ver com onde a conversa
    parou, entao ele fica em primeiro, nao em ultimo.

    `teto_codigo` e `teto_motivo_descarte` cortam o COMPRIMENTO de cada
    campo (e nao a quantidade de imoveis mostrados) -- mesma logica de
    `truncado`, so que por item. `renderizar` nao passa nenhum dos dois: o
    modelo ve `codigo` e `motivo_descarte` inteiros.
    """
    if not dossie.imoveis:
        return "nenhum imovel apresentado ainda"

    quantidade = len(dossie.imoveis)
    substantivo = "imovel apresentado" if quantidade == 1 else "imoveis apresentados"
    if teto is None:
        mostrados = dossie.imoveis
        cabecalho = f"{quantidade} {substantivo}:"
    else:
        # Os ULTIMOS `teto` da lista (ascendente por `apresentado_em`) sao os
        # mais recentes; invertidos, o mais novo vem primeiro.
        mostrados = tuple(reversed(dossie.imoveis[-teto:])) if teto > 0 else ()
        if quantidade > teto:
            cabecalho = f"{_aviso_de_corte(substantivo, quantidade, teto, 'mais recentes')}:"
        else:
            cabecalho = f"{quantidade} {substantivo}:"
    linhas = [cabecalho]
    for imovel in mostrados:
        codigo = truncado(imovel.codigo, teto_codigo)
        reacao = imovel.reacao or "sem reacao ate agora"
        motivo = (
            truncado(imovel.motivo_descarte, teto_motivo_descarte)
            if imovel.motivo_descarte
            else None
        )
        descarte = f", motivo {motivo}" if motivo else ""
        linhas.append(
            f"- {codigo}, {reais(imovel.preco_centavos)} ({imovel.tipo_de_preco}): "
            f"{reacao}{descarte}"
        )
    return "\n".join(linhas)


def _lista_com_teto(rotulo: str, itens: tuple[str, ...], teto: int | None) -> str:
    """Uma lista rotulada, com corte opcional e o total dito por extenso.

    `campos_recusados` e `perguntados_sem_resposta` sao `ARRAY(String(32))`
    sem cardinalidade maxima (ver `context/models.py`) -- ao contrario de
    `motivo_descarte`, que vem de um enum pequeno (`CategoriaDescarte`) e por
    isso nunca precisou de teto. Sem corte, um lead com muitos campos
    recusados estouraria os 1.500 caracteres da RN-15.2 do mesmo jeito que a
    lista de imoveis estourava antes de `imoveis()` ganhar `teto`.
    """
    if teto is not None and len(itens) > teto:
        mostrados = ", ".join(itens[:teto])
        return f"{_aviso_de_corte(rotulo, len(itens), teto, 'primeiros')}: {mostrados}"
    return f"{rotulo}: {', '.join(itens)}"


def pontos_de_atencao(
    dossie: Dossie, teto: int | None = None, *, teto_motivo_descarte: int | None = None
) -> str:
    """O bloco (e), montado do que existe. Ver o cabecalho do modulo.

    `teto` corta `campos_recusados` e `perguntados_sem_resposta`, no mesmo
    papel que tem em `imoveis()`: `renderizar` chama sem `teto` porque o
    modelo recebe a lista inteira; o resumo de contingencia (TEC-176) chama
    com `teto` porque tem 1.500 caracteres de orcamento.

    `teto_motivo_descarte` corta o COMPRIMENTO de cada motivo antes de
    deduplicar (TEC-176, revisao final, Critical 1a): a coluna
    (`Recomendacao.motivo_descarte`, `agente/models.py`) e `String(80)`, bem
    mais larga que qualquer `CategoriaDescarte` real hoje (o maior membro,
    "DISTANCIA", tem 9); o teto usa o tamanho real do enum, e nao o da
    coluna, exatamente porque a aplicacao nunca escreve outra coisa ali --
    ver o comentario de `contingencia.montar` para a conta completa.
    """
    partes = []
    if dossie.campos_recusados:
        partes.append(_lista_com_teto("recusou informar", dossie.campos_recusados, teto))
    if dossie.perguntados_sem_resposta:
        partes.append(
            _lista_com_teto("perguntado e sem resposta", dossie.perguntados_sem_resposta, teto)
        )

    descartes = sorted(
        {
            truncado(i.motivo_descarte, teto_motivo_descarte)
            for i in dossie.imoveis
            if i.motivo_descarte
        }
    )
    if descartes:
        partes.append(f"motivos de descarte de imovel: {', '.join(descartes)}")

    if not partes:
        return "nenhum ponto de atencao registrado"
    return "\n".join(f"- {parte}" for parte in partes)


def fatores(dossie: Dossie) -> str:
    if not dossie.score_fatores:
        return AUSENTE
    return ", ".join(f"{nome} {valor}" for nome, valor in dossie.score_fatores)


def forcada_por(dossie: Dossie) -> str:
    """O sufixo "(forcada por ...)" da temperatura, ou vazio.

    Promovido de dentro de `renderizar` (TEC-176, revisao da Task 1): existia
    so ali ate o resumo de contingencia precisar do mesmo sufixo e reescreve-
    lo por conta propria -- exatamente o defeito que este modulo existe para
    evitar, e que a TEC-146 gastou uma card inteira consertando.
    """
    if not dossie.temperatura_forcada_motivos:
        return ""
    return f" (forcada por {', '.join(dossie.temperatura_forcada_motivos)})"


# As linhas abaixo (ate `linha_prioridade`) sao compartilhadas por
# `renderizar` e `contingencia.montar` -- TEC-176, revisao final (Minor 4).
# Ate aqui a duplicacao so tinha side resolvida no VALOR (os formatadores
# `faixa`, `sim_nao`, `ou_ausente` acima, e `forcada_por`); a LINHA continuava
# escrita duas vezes em cada funcao, e a divergencia ja tinha acontecido uma
# vez -- `score_causas` e `criado_em` existem so em `renderizar`, nao em
# `montar`, porque quem escreveu `montar` nao tinha as linhas de `renderizar`
# na frente para copiar.
#
# Cada helper que aceita `teto` corta o campo para o resumo de contingencia
# (Critical 1a da mesma revisao): `renderizar` sempre chama sem `teto`
# porque o modelo recebe o dossie inteiro; so `contingencia.montar` passa um
# valor, vindo do tamanho real da coluna ou do enum que a alimenta -- ver o
# comentario de `contingencia.montar` para a tabela completa.
def linha_canal(dossie: Dossie, teto: int | None = None) -> str:
    return f"canal: {truncado(dossie.canal, teto)}"


def linha_mensagens_do_lead(dossie: Dossie) -> str:
    return f"mensagens do lead: {dossie.mensagens_do_lead}"


def linha_primeira_mensagem(dossie: Dossie) -> str:
    return f"primeira mensagem: {ou_ausente(isoformat_ou_none(dossie.primeira_mensagem_em))}"


def linhas_de_criterios(
    dossie: Dossie, tetos: dict[str, int] | None = None, *, regiao_delimitada: bool = False
) -> tuple[str, ...]:
    """As nove linhas do bloco "o que procura" -- (b) na `Dossie`.

    `tetos` mapeia o NOME do campo (`"regiao"`, `"tipo_imovel"`,
    `"urgencia"`, `"forma_pagamento"`, `"intencao"`) ao teto de caracteres
    daquele campo. So `contingencia.montar` passa algo aqui.

    `regiao_delimitada` e so de `renderizar` (TEC-204): `regiao` e o unico
    texto livre do dossie que veio da fala do lead, e o modelo o recebe entre
    `<lead>` e `</lead>`. A contingencia e lida pelo corretor, e fica sem tag.
    """
    tetos = tetos or {}

    def campo(rotulo: str, chave: str, valor: str) -> str:
        return f"{rotulo}: {truncado(valor, tetos.get(chave))}"

    regiao = ou_ausente(dossie.regiao)
    if regiao_delimitada and dossie.regiao is not None:
        regiao = delimitar(dossie.regiao)

    return (
        campo("intencao", "intencao", ou_ausente(dossie.intencao)),
        f"faixa de preco: {faixa(dossie)}",
        campo("regiao", "regiao", regiao),
        campo("tipo de imovel", "tipo_imovel", ou_ausente(dossie.tipo_imovel)),
        f"quartos: {ou_ausente(dossie.quartos)}",
        f"vagas: {ou_ausente(dossie.vagas)}",
        campo("urgencia", "urgencia", ou_ausente(dossie.urgencia)),
        campo("forma de pagamento", "forma_pagamento", ou_ausente(dossie.forma_pagamento)),
        f"tem imovel para vender: {sim_nao(dossie.tem_imovel_para_vender)}",
    )


def linha_fatores(dossie: Dossie) -> str:
    return f"fatores: {fatores(dossie)}"


def linha_temperatura(dossie: Dossie) -> str:
    return f"temperatura: {ou_ausente(dossie.temperatura)}{forcada_por(dossie)}"


def linha_gatilho(dossie: Dossie, teto: int | None = None) -> str:
    return f"gatilho: {truncado(dossie.gatilho, teto)}"


def linha_etiqueta(dossie: Dossie, teto: int | None = None) -> str:
    return f"etiqueta: {truncado(dossie.etiqueta, teto)}"


def linha_prioridade(dossie: Dossie) -> str:
    return f"prioridade: {dossie.prioridade}"


def renderizar(dossie: Dossie) -> str:
    """O dossie em texto, que e tudo o que o modelo recebe.

    Rotulado campo a campo e nao em prosa: o modelo precisa distinguir um
    valor ausente de um valor zero, e prosa corrida apaga essa diferenca --
    que e exatamente o erro que a RN-15.3 existe para impedir.

    As linhas em comum com `contingencia.montar` vem dos helpers
    `linha_*`/`linhas_de_criterios` (TEC-176, revisao final, Minor 4);
    `canal`, `chave da conversa`, `total` e os rotulos de secao
    ("ORIGEM"/"CRITERIOS"/...) sao proprios desta funcao e nao entram nos
    helpers -- ver o comentario deles para o porque.

    A `regiao` vai delimitada (TEC-204): e texto que o lead disse.
    """
    return "\n".join(
        (
            "ORIGEM",
            linha_canal(dossie),
            f"chave da conversa: {dossie.conversa}",
            linha_primeira_mensagem(dossie),
            linha_mensagens_do_lead(dossie),
            "",
            "CRITERIOS",
            *linhas_de_criterios(dossie, regiao_delimitada=True),
            "",
            "SCORE",
            f"total: {ou_ausente(dossie.score_total)}",
            linha_fatores(dossie),
            f"ultimo recalculo por: {', '.join(dossie.score_causas) or AUSENTE}",
            linha_temperatura(dossie),
            "",
            "IMOVEIS",
            imoveis(dossie),
            "",
            "PONTOS DE ATENCAO",
            pontos_de_atencao(dossie),
            "",
            "HANDOFF",
            linha_gatilho(dossie),
            linha_etiqueta(dossie),
            linha_prioridade(dossie),
            f"criado em: {dossie.criado_em.isoformat()}",
        )
    )
