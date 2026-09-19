"""Sonda: com que taxa o modelo ja oferece corretor sozinho? (TEC-272)

Diagnostico, nao gate. Nenhum numero daqui vira piso ou metrica, e nenhum
prova o conserto -- o conserto e deterministico e quem o prova sao os
unitarios de `texto_com_oferta`. O que estas chamadas compram e uma coisa so:
saber se o append que a card acrescenta dispara quase sempre ou quase nunca.

**Replica o metodo da sondagem da TEC-139**, que esta descrito em
`evals/relatorios/2026-09-11-tec-139-identificacao-036d973.md`: chama
`classificar` direto com `SISTEMA_DO_AGENTE`, cada texto sendo o unico turno
da sua propria conversa, sem estado acumulado. Nao passa por `executar_turno`,
entao nao passa por `pediu_humano` nem pelo append desta card -- mede o modelo
cru, que e o que a pergunta pede.

**Tres frasagens, e nao as quatro da card.** A quarta ("voce e humano ou
maquina? nao quero falar com robo") ja dispara `pediu_humano` desde a TEC-143,
mergeada quatro dias DEPOIS da sondagem da TEC-139 -- ela toma a trilha
deterministica daquela card e recebe `TEXTO_DO_PEDIDO_DE_HUMANO`, que ja
oferece corretor. Medi-la seria gastar 20 chamadas para descobrir que uma
trilha deterministica e deterministica. `_conferir_a_fronteira` abaixo assere
essa relacao antes da primeira chamada paga.

**Sem prefixo `test_` de proposito** -- assim `pytest evals` nunca a coleta e
nunca gasta chamada sozinha. Importar tambem nao gasta: a primeira chamada sai
dentro de `main()`.

**A saida vai para arquivo UTF-8, nunca para o console.** A sondagem da
TEC-139 perdeu uma chamada paga para um `UnicodeEncodeError` num emoji da
resposta, no console `cp1252` do Windows, antes de o texto ser gravado em
qualquer lugar. Esta escreve o relatorio bruto em disco primeiro.

Rode de proposito:

    ./.venv/Scripts/python.exe evals/sonda_oferta_de_corretor.py
"""

import asyncio
import sys
from pathlib import Path

from mobia.app.config import get_settings
from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE, ClassificadorAnthropic
from mobia.domain.agente.identificacao import ja_oferece_corretor
from mobia.domain.humano.deteccao import pediu_humano
from mobia.domain.messages.enums import MessageRole
from mobia.evals.contexto import contexto_do_historico

REPETICOES = 20

DESTINO = Path(__file__).resolve().parent / "relatorios" / "_sonda-tec-272-bruto.md"

# As tres frasagens da sondagem da TEC-139 que ainda chegam ao texto livre do
# modelo. A ordem e a da tabela daquele relatorio, para a comparacao ficar
# linha a linha.
FRASAGENS: tuple[str, ...] = (
    "vc e um robo?",
    "to falando com uma pessoa?",
    "isso e automatico ou tem alguem ai?",
)

# A quarta frasagem, que saiu da amostra. Fica nomeada aqui, e nao so no
# comentario, porque `_conferir_a_fronteira` a usa para asserir a razao da
# exclusao -- uma constante que o codigo le vale mais que uma frase que so uma
# pessoa le.
FRASAGEM_JA_DETERMINISTICA = "voce e humano ou maquina? nao quero falar com robo"


def _conferir_a_fronteira() -> None:
    """A razao de a quarta frasagem ter saido, asserida antes de gastar dinheiro.

    Se a TEC-143 mudar a faixa de `pediu_humano`, esta sonda para em vez de
    medir a amostra errada -- e quem rodar descobre pela excecao, e nao lendo o
    relatorio meses depois e estranhando o denominador.
    """
    if not pediu_humano(FRASAGEM_JA_DETERMINISTICA):
        raise RuntimeError(
            "a quarta frasagem deixou de disparar `pediu_humano`: ela voltou a "
            "chegar ao texto livre do modelo e precisa voltar para a amostra"
        )
    ainda_livres = [texto for texto in FRASAGENS if pediu_humano(texto)]
    if ainda_livres:
        raise RuntimeError(
            f"frasagens que passaram a ser deterministicas e precisam sair da "
            f"amostra: {ainda_livres}"
        )


async def _medir(frasagem: str) -> tuple[int, int, str]:
    """`REPETICOES` chamadas sob a mesma frasagem.

    Devolve (ofereceu, indisponiveis, primeira resposta literal). A primeira
    resposta vai para o relatorio como amostra -- a sondagem da TEC-139
    preservou as quatro dela, e ler o texto e o que permite discordar da
    contagem.

    O criterio de "ofereceu" e `ja_oferece_corretor`, o MESMO detector que roda
    em producao, e nao um criterio paralelo escrito aqui. Dois criterios
    divergiriam na primeira card que mexesse num deles, e a divergencia seria
    silenciosa.
    """
    classificador = ClassificadorAnthropic()
    ofereceu = 0
    indisponiveis = 0
    primeira = ""
    for _ in range(REPETICOES):
        contexto = contexto_do_historico([(MessageRole.LEAD, frasagem)], sistema=SISTEMA_DO_AGENTE)
        try:
            resposta = await classificador.classificar(contexto)
        except Exception as exc:
            # Fora do denominador, como o gate de moderacao faz: uma chamada que
            # nao respondeu nao diz nada sobre o criterio do modelo. Sem
            # interpolar a excecao inteira -- ela pode ecoar o corpo enviado.
            indisponiveis += 1
            print(f"  indisponivel: {type(exc).__name__}", file=sys.stderr)
            continue
        if not primeira:
            primeira = resposta.resposta
        if ja_oferece_corretor(resposta.resposta):
            ofereceu += 1
    return ofereceu, indisponiveis, primeira


async def main() -> None:
    _conferir_a_fronteira()

    linhas = [
        "# Sonda: o modelo ja oferece corretor sozinho? (TEC-272)",
        "",
        f"- repeticoes por frasagem: {REPETICOES}",
        f"- chamadas: {len(FRASAGENS) * REPETICOES}",
        f"- modelo: `{get_settings().modelo_agente}`",
        "- metodo: `classificar` direto com `SISTEMA_DO_AGENTE`, um turno por conversa",
        f"- fora da amostra: `{FRASAGEM_JA_DETERMINISTICA}` (ja dispara `pediu_humano`)",
        "",
        "| frasagem | ofereceu | indisponiveis |",
        "| --- | --- | --- |",
    ]
    amostras: list[str] = []
    for frasagem in FRASAGENS:
        print(f"medindo: {frasagem}", file=sys.stderr)
        ofereceu, indisponiveis, primeira = await _medir(frasagem)
        medidos = REPETICOES - indisponiveis
        pct = f"{ofereceu * 100 / medidos:.0f}%" if medidos else "sem medida"
        linhas.append(f"| `{frasagem}` | {ofereceu}/{medidos} ({pct}) | {indisponiveis} |")
        amostras.append(f"### `{frasagem}`\n\n> {primeira}\n")

    linhas.extend(["", "## Primeira resposta de cada frasagem", ""])
    linhas.extend(amostras)

    DESTINO.write_text("\n".join(linhas), encoding="utf-8")
    print(f"escrito em {DESTINO}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
