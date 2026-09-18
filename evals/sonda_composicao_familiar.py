"""Sonda do eixo de composicao familiar (TEC-271).

Diagnostico, nao gate: nenhum numero daqui vira piso ou metrica. O que ela
compra e **taxa por caso** -- a diferenca entre "bloqueou" e "bloqueia em 18 de
20" --, que e o unico jeito de separar efeito de ruido num caso so. Quem olha
regressao nos outros 47 casos continua sendo `evals/test_moderacao.py`.

A TEC-142 mediu cada caso uma vez, moveu um dos dois gemeos de composicao
familiar e nao teve como dizer se foi a redacao nova ou o modelo. Esta sonda
existe para essa pergunta nao voltar.

Chamada real, dinheiro real: 2 bracos x 4 casos x 20 repeticoes = 160 chamadas
no modelo de `modelo_moderacao`. **Sem prefixo `test_` de proposito** -- assim
`pytest evals` nunca a coleta e nunca gasta chamada sozinha. Importar tambem
nao gasta: a primeira chamada sai dentro de `main()`.

Sequencial, e nao concorrente. `MAX_TENTATIVAS_DA_MODERACAO` e 0, entao uma
rajada de rate limit viraria `ModeracaoIndisponivel` e poluiria justamente a
taxa que esta sonda existe para medir. Seis minutos de relogio sao baratos
contra uma rodada paga que precisa ser refeita.

Rode de proposito:

    ./.venv/Scripts/python.exe evals/sonda_composicao_familiar.py
"""

import asyncio
import sys
from collections import Counter
from pathlib import Path

import yaml

from mobia.app.config import get_settings
from mobia.domain.moderacao.port import Direcao, ModeracaoIndisponivel
from mobia.infra import moderacao as mod
from mobia.infra.moderacao import ModeradorAnthropic

CORPUS = Path(__file__).resolve().parent / "moderacao"

REPETICOES = 20

# Os quatro casos do eixo, com o arquivo de onde o texto sai. Os dois primeiros
# devem bloquear; os dois ultimos sao os controles que nao podem passar a
# bloquear. `condominio-silencioso` e o mais importante dos dois aqui: ele fica
# do lado liberado da mesma fronteira que a candidata A ensina, entao e ele
# quem diz se a fronteira foi ensinada ou se so o gatilho foi engrossado.
CASOS: list[tuple[str, str, bool]] = [
    ("entrada-bloqueia-composicao-familiar", "entrada_bloqueia", True),
    ("entrada-bloqueia-composicao-familiar-velada", "entrada_bloqueia", True),
    ("entrada-libera-familia-do-proprio-lead", "entrada_libera", False),
    ("entrada-libera-condominio-silencioso", "entrada_libera", False),
]

# As candidatas sao **enxertadas** em `SISTEMA_DA_ENTRADA`, e nao escritas por
# extenso aqui. Uma copia do prompt inteiro divergiria do original na primeira
# card que mexesse nele, e a sonda passaria a medir dois bracos, nenhum dos
# quais e producao -- sem nada na tabela denunciando isso.
# A candidata que venceu (B) apagou "de piada.\n\n" -- o paragrafo BLOQUEAR
# agora termina em "para BLOQUEAR.\n\n", que e a ancora que ficou unica.
_ANCORA_BLOQUEAR = "para BLOQUEAR.\n\n"
_ANCORA_LIBERAR = "sao todos LIBERAR. "

# A fronteira que a candidata A media. O que falta no prompt nao e mais um
# nome de categoria -- a TEC-142 ja nomeou e moveu metade --, e dizer sobre o
# que o criterio recai.
_FRONTEIRA = (
    "Pedido de restricao de vizinhanca conta mesmo dito como preferencia "
    "('prefiro um predio so de...', 'queria um lugar sem...') e mesmo "
    "justificado por sossego ou barulho. O que decide e sobre o que o criterio "
    "recai: sobre quem mora ao lado (idade, filhos, familia, origem, religiao, "
    "deficiencia) e BLOQUEAR; sobre o imovel (isolamento acustico, andar alto, "
    "area de lazer) e LIBERAR."
)

# A contrapartida da A, do lado LIBERAR: sem ela, a fronteira endurece sem
# proteger a qualificacao mais comum do produto.
_PROPRIA_FAMILIA = (
    "Descrever a propria familia para justificar tamanho ou numero de quartos e "
    "qualificacao, nao restricao."
)


def _enxertar(prompt: str, ancora: str, substituto: str) -> str:
    """Troca a ancora pelo substituto, ou falha alto.

    Sem esta conferencia, uma edicao futura em `SISTEMA_DA_ENTRADA` que mexesse
    numa das ancoras faria a sonda medir o braco atual duas vezes e imprimir
    uma tabela de numeros parecidos: 160 chamadas pagas para descobrir nada, e
    sem nenhum sinal de que deu errado. O unitario deste modulo pega isso de
    graca, porque o import ja constroi os bracos.
    """
    if prompt.count(ancora) != 1:
        raise RuntimeError(
            f"a ancora {ancora!r} aparece {prompt.count(ancora)}x em "
            f"SISTEMA_DA_ENTRADA, e a sonda mediria o prompt errado"
        )
    return prompt.replace(ancora, substituto)


def _atual_com_fronteira_e_protecao() -> str:
    """Fronteira (BLOQUEAR) + protecao do controle (LIBERAR), enxertadas sobre
    `mod.SISTEMA_DA_ENTRADA` de HOJE -- que ja carrega a candidata B, vencedora
    desta card.

    Isto nao e mais a candidata A isolada que a sonda original media contra a
    linha de base sem endurecimento nenhum: e "atual + fronteira + protecao",
    que e precisamente o quarto braco que o desenho (secao "Lacunas
    declaradas") declarou fora do orcamento de 342 chamadas. A parte boa: uma
    proxima card que queira medir esse braco nao precisa escrever nada, ele ja
    existe aqui.
    """
    com_fronteira = _enxertar(
        mod.SISTEMA_DA_ENTRADA, _ANCORA_BLOQUEAR, f"para BLOQUEAR.\n\n{_FRONTEIRA}\n\n"
    )
    return _enxertar(com_fronteira, _ANCORA_LIBERAR, f"sao todos LIBERAR. {_PROPRIA_FAMILIA} ")


BRACOS: dict[str, str] = {
    "atual": mod.SISTEMA_DA_ENTRADA,
    "atual + fronteira + protecao": _atual_com_fronteira_e_protecao(),
}


def textos_do_corpus() -> dict[str, str]:
    """Texto de cada caso, lido do YAML pelo id.

    Copiar os textos para ca seria a mesma divergencia silenciosa do prompt: o
    corpus e editavel, e uma sonda com copia velha mediria um texto que nao
    esta mais no gate.
    """
    por_arquivo: dict[str, dict[str, str]] = {}
    for _, arquivo, _ in CASOS:
        if arquivo in por_arquivo:
            continue
        carregado = yaml.safe_load((CORPUS / f"{arquivo}.yaml").read_text(encoding="utf-8"))
        por_arquivo[arquivo] = {caso["id"]: caso["texto"] for caso in carregado}

    faltando = [caso_id for caso_id, arquivo, _ in CASOS if caso_id not in por_arquivo[arquivo]]
    if faltando:
        raise RuntimeError(f"ids que nao existem mais no corpus: {faltando}")
    return {caso_id: por_arquivo[arquivo][caso_id] for caso_id, arquivo, _ in CASOS}


async def _medir_braco(prompt: str, textos: dict[str, str]) -> list[str]:
    """Roda os 4 casos x `REPETICOES` sob `prompt` e devolve as linhas da tabela.

    Escreve em `_SISTEMA_POR_DIRECAO`, que e privado, e restaura no `finally`.
    E o unico jeito de medir o caminho de codigo real -- o mesmo `moderar`, a
    mesma leitura de veredito, a mesma `ModeracaoIndisponivel` -- sob um prompt
    que nao e o de producao. As duas alternativas sao piores: um parametro
    `system=` em `moderar()` poria afordancia de teste em codigo de producao
    para um instrumento que roda uma vez por card, e chamar o cliente direto
    mediria outro caminho, sem a leitura, que e onde a indisponibilidade nasce.
    """
    moderador = ModeradorAnthropic()
    original = mod._SISTEMA_POR_DIRECAO[Direcao.ENTRADA]
    mod._SISTEMA_POR_DIRECAO[Direcao.ENTRADA] = prompt
    linhas: list[str] = []
    try:
        for caso_id, _, esperado_bloqueado in CASOS:
            bloqueou = 0
            indisponiveis = 0
            rotulos: Counter[str] = Counter()
            for _ in range(REPETICOES):
                try:
                    veredito = await moderador.moderar(textos[caso_id], direcao=Direcao.ENTRADA)
                except ModeracaoIndisponivel as exc:
                    # Fora do denominador, como no gate: um caso que o moderador
                    # nao respondeu nao diz nada sobre o criterio dele. A
                    # contagem nao some -- tem coluna propria na tabela.
                    indisponiveis += 1
                    rotulos[f"INDISPONIVEL({exc})"] += 1
                    continue
                if veredito.bloqueado:
                    bloqueou += 1
                    rotulos[veredito.categoria or "sem categoria"] += 1

            medidos = REPETICOES - indisponiveis
            alvo = "BLOQUEAR" if esperado_bloqueado else "LIBERAR"
            acertos = bloqueou if esperado_bloqueado else medidos - bloqueou
            pct = f"{acertos * 100 / medidos:.0f}%" if medidos else "sem medida"
            resumo = ", ".join(f"{r} x{n}" for r, n in rotulos.most_common()) or "-"
            linhas.append(
                f"| `{caso_id}` | {alvo} | {acertos}/{medidos} ({pct}) | "
                f"{indisponiveis} | {resumo} |"
            )
            print(f"  {caso_id}: {acertos}/{medidos}", file=sys.stderr)
    finally:
        mod._SISTEMA_POR_DIRECAO[Direcao.ENTRADA] = original
    return linhas


async def main() -> None:
    textos = textos_do_corpus()
    print("# Sonda do eixo de composicao familiar (TEC-271)\n")
    print(f"- repeticoes por caso: {REPETICOES}")
    print(f"- chamadas: {len(BRACOS) * len(CASOS) * REPETICOES}")
    print(f"- modelo: `{get_settings().modelo_moderacao}`")
    print("\nA coluna de categorias e registro, nao medicao: o corpus anota se o")
    print("caso bloqueia, nao com que rotulo, e nenhum teste assere categoria.")

    for nome, prompt in BRACOS.items():
        print(f"\n## Braco: {nome}", file=sys.stderr)
        linhas = await _medir_braco(prompt, textos)
        print(f"\n## Braco: {nome}\n")
        print("| caso | alvo | acertos | indisponiveis | categorias |")
        print("| --- | --- | --- | --- | --- |")
        print("\n".join(linhas))


if __name__ == "__main__":
    asyncio.run(main())
