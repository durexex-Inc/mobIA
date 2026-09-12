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
    primeira_mensagem_em: datetime
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

    O repo nao tinha formatador: `dinheiro.py` so parseia o que o lead
    escreve. Este e o caminho de volta, e vive aqui porque so o dossie
    precisa dele.

    Sem casas decimais porque preco de imovel nao as tem na pratica e elas so
    gastariam caracteres do orcamento de 1.500 da RN-15.2.
    """
    if centavos is None:
        return AUSENTE
    return f"R$ {centavos // 100:,}".replace(",", ".")


def _sim_nao(valor: bool | None) -> str:
    if valor is None:
        return AUSENTE
    return "sim" if valor else "nao"


def _ou_ausente(valor: object | None) -> str:
    return AUSENTE if valor is None else str(valor)


def _faixa(dossie: Dossie) -> str:
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


def _imoveis(dossie: Dossie) -> str:
    if not dossie.imoveis:
        return "nenhum imovel apresentado ainda"

    linhas = [f"{len(dossie.imoveis)} imoveis apresentados:"]
    for imovel in dossie.imoveis:
        reacao = imovel.reacao or "sem reacao ate agora"
        descarte = f", motivo {imovel.motivo_descarte}" if imovel.motivo_descarte else ""
        linhas.append(
            f"- {imovel.codigo}, {reais(imovel.preco_centavos)} ({imovel.tipo_de_preco}): "
            f"{reacao}{descarte}"
        )
    return "\n".join(linhas)


def _pontos_de_atencao(dossie: Dossie) -> str:
    """O bloco (e), montado do que existe. Ver o cabecalho do modulo."""
    partes = []
    if dossie.campos_recusados:
        partes.append(f"recusou informar: {', '.join(dossie.campos_recusados)}")
    if dossie.perguntados_sem_resposta:
        partes.append(f"perguntado e sem resposta: {', '.join(dossie.perguntados_sem_resposta)}")

    descartes = sorted({i.motivo_descarte for i in dossie.imoveis if i.motivo_descarte})
    if descartes:
        partes.append(f"motivos de descarte de imovel: {', '.join(descartes)}")

    if not partes:
        return "nenhum ponto de atencao registrado"
    return "\n".join(f"- {parte}" for parte in partes)


def _fatores(dossie: Dossie) -> str:
    if not dossie.score_fatores:
        return AUSENTE
    return ", ".join(f"{nome} {valor}" for nome, valor in dossie.score_fatores)


def renderizar(dossie: Dossie) -> str:
    """O dossie em texto, que e tudo o que o modelo recebe.

    Rotulado campo a campo e nao em prosa: o modelo precisa distinguir um
    valor ausente de um valor zero, e prosa corrida apaga essa diferenca --
    que e exatamente o erro que a RN-15.3 existe para impedir.
    """
    forcada = (
        f" (forcada por {', '.join(dossie.temperatura_forcada_motivos)})"
        if dossie.temperatura_forcada_motivos
        else ""
    )
    return "\n".join(
        (
            "ORIGEM",
            f"canal: {dossie.canal}",
            f"chave da conversa: {dossie.conversa}",
            f"primeira mensagem: {dossie.primeira_mensagem_em.isoformat()}",
            f"mensagens do lead: {dossie.mensagens_do_lead}",
            "",
            "CRITERIOS",
            f"intencao: {_ou_ausente(dossie.intencao)}",
            f"faixa de preco: {_faixa(dossie)}",
            f"regiao: {_ou_ausente(dossie.regiao)}",
            f"tipo de imovel: {_ou_ausente(dossie.tipo_imovel)}",
            f"quartos: {_ou_ausente(dossie.quartos)}",
            f"vagas: {_ou_ausente(dossie.vagas)}",
            f"urgencia: {_ou_ausente(dossie.urgencia)}",
            f"forma de pagamento: {_ou_ausente(dossie.forma_pagamento)}",
            f"tem imovel para vender: {_sim_nao(dossie.tem_imovel_para_vender)}",
            "",
            "SCORE",
            f"total: {_ou_ausente(dossie.score_total)}",
            f"fatores: {_fatores(dossie)}",
            f"ultimo recalculo por: {', '.join(dossie.score_causas) or AUSENTE}",
            f"temperatura: {_ou_ausente(dossie.temperatura)}{forcada}",
            "",
            "IMOVEIS",
            _imoveis(dossie),
            "",
            "PONTOS DE ATENCAO",
            _pontos_de_atencao(dossie),
            "",
            "HANDOFF",
            f"gatilho: {dossie.gatilho}",
            f"etiqueta: {dossie.etiqueta}",
            f"prioridade: {dossie.prioridade}",
            f"criado em: {dossie.criado_em.isoformat()}",
        )
    )
