"""Sonda: um turno SUPORTE_CONTRATO que cita dinheiro vira orcamento? (TEC-287)

Diagnostico, nao gate. A card TEC-287 manda, com todas as letras, medir antes
de decidir: *"vale conferir no corpus de evals com que frequencia um turno
`SUPORTE_CONTRATO` de fato carrega valor monetario. Se for raro a ponto de nao
aparecer, a card pode nao valer o risco de mexer no filtro de gravacao -- e
essa conclusao tambem e um resultado."*

**O corpus nao responde essa pergunta, e por isso esta sonda existe.** Os sete
turnos `SUPORTE_CONTRATO` de `evals/corpus/` tem todos `campos: {}`, mas o
corpus e escrito a mao: a ausencia mede o que o autor pensou em escrever, nao
o que o extrator faz quando o lead de fato cita um valor. Zero de sete, ali, e
evidencia fraca na direcao errada -- nenhuma das sete falas cita dinheiro,
entao elas nao tiveram a chance de vazar.

O que esta sonda mede e o elo que falta: dadas falas de suporte de contrato
que CITAM um valor, com que frequencia o modelo devolve `SUPORTE_CONTRATO`
**e** preenche a faixa de preco. Se ele quase nunca preencher, o vazamento e
teorico e a card se fecha sem codigo. Se preencher com frequencia, a card e
real e o conserto no filtro de gravacao se justifica.

**Replica o metodo das sondas da TEC-139/TEC-272:** chama `classificar` direto
com `SISTEMA_DO_AGENTE`, cada fala sendo o unico turno da sua propria
conversa, sem estado acumulado. Nao passa por `executar_turno`. Medir o modelo
cru e o que a pergunta pede -- o vazamento da card comeca no primeiro turno de
uma conversa que ainda nao tinha orcamento nenhum.

**Sem prefixo `test_` de proposito** -- assim `pytest evals` nunca a coleta e
nunca gasta chamada sozinha. Importar tambem nao gasta: a primeira chamada sai
dentro de `main()`.

**A saida vai para arquivo UTF-8, nunca para o console.** A sondagem da TEC-139
perdeu uma chamada paga para um `UnicodeEncodeError` num emoji da resposta, no
console `cp1252` do Windows, antes de o texto ser gravado em qualquer lugar.

Rode de proposito:

    ./.venv/Scripts/python.exe evals/sonda_valor_sob_suporte_contrato.py
"""

import asyncio
import sys
from pathlib import Path

from mobia.app.config import get_settings
from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE, ClassificadorAnthropic
from mobia.domain.agente.schemas import Extracao, Intencao
from mobia.domain.context.repositorio import campos_a_gravar
from mobia.domain.messages.enums import MessageRole
from mobia.evals.contexto import contexto_do_historico

REPETICOES = 3

DESTINO = Path(__file__).resolve().parent / "relatorios" / "_sonda-tec-287-bruto.md"

# Doze falas de suporte de contrato que CITAM um valor. A variacao e
# deliberada em tres eixos, porque cada um pode mover a resposta do modelo:
#
#   - a forma do numero ("2.800", "dois mil e oitocentos", "2,8 mil", "R$ 3500")
#   - o papel do valor na frase (o que ele paga hoje, o que passaria a pagar,
#     uma multa, um saldo devedor)
#   - haver ou nao uma segunda leitura de compra/aluguel na mesma fala
#
# O ultimo eixo importa mais do que parece: "hoje pago 2.800" e um fato sobre
# um contrato existente, nao um orcamento, e e exatamente essa distincao que a
# card afirma que o sistema nao faz. Se o modelo ja a fizer sozinho, o
# vazamento e teorico.
FALAS: tuple[str, ...] = (
    "queria entender o reajuste do meu contrato, hoje pago 2.800",
    "meu aluguel foi de 3.500 pra 3.900 e queria saber se pode isso",
    "sou inquilino e pago dois mil e oitocentos, o igpm subiu muito esse ano",
    "tem multa se eu sair antes? meu contrato e de R$ 4200 por mes",
    "a taxa de administracao no meu boleto ta 350, isso e normal?",
    "paguei 1.900 de caucao e queria saber quando recebo de volta",
    "meu contrato vence mes que vem, hoje eu pago 2,8 mil, como faco pra renovar",
    "queria revisar o valor do aluguel, ta em 5 mil e ficou fora da realidade",
    "cobraram 780 de multa no meu boleto e eu nao entendi o motivo",
    "sou locatario ha tres anos pagando 3.200, da pra negociar o reajuste?",
    "o condominio subiu pra 1.100 e eu queria entender se isso entra no meu contrato",
    "meu deposito foi de 7.000 e o contrato acabou, com quem eu falo sobre isso",
)


def _conferir_a_fronteira() -> None:
    """A premissa da card, asserida antes de gastar dinheiro.

    A card afirma que o conserto e no filtro de gravacao, e que hoje ele
    deixa passar. Se `campos_a_gravar` ja barrasse a faixa de preco sob
    `SUPORTE_CONTRATO`, o vazamento nao existiria mais e esta sonda estaria
    medindo uma pergunta ja respondida -- gastando chamadas paga para isso.

    Assere a relacao, nao o texto: se alguem consertar o filtro antes desta
    card, a sonda para com a razao escrita em vez de produzir um relatorio que
    ninguem sabe interpretar.
    """
    com_faixa = Extracao(faixa_preco_min_centavos=None, faixa_preco_max_centavos=280_000)
    gravados = campos_a_gravar(Intencao.SUPORTE_CONTRATO, com_faixa)

    if "faixa_preco_max_centavos" not in gravados:
        raise RuntimeError(
            "`campos_a_gravar` ja barra a faixa de preco sob SUPORTE_CONTRATO: "
            "o vazamento que a TEC-287 mede deixou de existir, e esta sonda "
            "nao tem mais o que medir"
        )


def _tem_faixa(resposta: object) -> bool:
    extracao = resposta.extracao  # type: ignore[attr-defined]
    return (
        extracao.faixa_preco_min_centavos is not None
        or extracao.faixa_preco_max_centavos is not None
    )


async def _medir(fala: str) -> tuple[int, int, int, str]:
    """`REPETICOES` chamadas sob a mesma fala.

    Devolve (vazou, fora_de_suporte, indisponiveis, amostra).

    "Vazou" e a conjuncao das duas condicoes, e nao so a faixa preenchida: o
    vazamento da card exige que a intencao seja `SUPORTE_CONTRATO` (que grava)
    E que a faixa venha junto. Uma fala classificada ALUGUEL com faixa
    preenchida nao e este defeito -- ali a banda valida o numero.
    """
    classificador = ClassificadorAnthropic()
    vazou = 0
    fora_de_suporte = 0
    indisponiveis = 0
    amostra = ""
    for _ in range(REPETICOES):
        contexto = contexto_do_historico([(MessageRole.LEAD, fala)], sistema=SISTEMA_DO_AGENTE)
        try:
            resposta = await classificador.classificar(contexto)
        except Exception as exc:
            # Fora do denominador, como as sondas anteriores fazem: uma chamada
            # que nao respondeu nao diz nada sobre o criterio do modelo. Sem
            # interpolar a excecao inteira -- ela pode ecoar o corpo enviado.
            indisponiveis += 1
            print(f"  indisponivel: {type(exc).__name__}", file=sys.stderr)
            continue
        if not amostra:
            amostra = (
                f"intencao={resposta.intencao.value} "
                f"min={resposta.extracao.faixa_preco_min_centavos} "
                f"max={resposta.extracao.faixa_preco_max_centavos}"
            )
        if resposta.intencao is not Intencao.SUPORTE_CONTRATO:
            fora_de_suporte += 1
            continue
        if _tem_faixa(resposta):
            vazou += 1
    return vazou, fora_de_suporte, indisponiveis, amostra


async def main() -> None:
    _conferir_a_fronteira()

    linhas = [
        "# Sonda: valor citado sob SUPORTE_CONTRATO vira orcamento? (TEC-287)",
        "",
        f"- repeticoes por fala: {REPETICOES}",
        f"- chamadas: {len(FALAS) * REPETICOES}",
        f"- modelo: `{get_settings().modelo_agente}`",
        "- metodo: `classificar` direto com `SISTEMA_DO_AGENTE`, um turno por conversa",
        "- criterio de vazamento: intencao SUPORTE_CONTRATO **e** faixa de preco preenchida",
        "",
        "| fala | vazou | fora de SUPORTE | indisponiveis | primeira resposta |",
        "| --- | --- | --- | --- | --- |",
    ]
    total_vazou = 0
    total_medido = 0
    for fala in FALAS:
        print(f"medindo: {fala[:50]}", file=sys.stderr)
        vazou, fora, indisponiveis, amostra = await _medir(fala)
        medidos = REPETICOES - indisponiveis
        total_vazou += vazou
        total_medido += medidos
        linhas.append(f"| `{fala}` | {vazou}/{medidos} | {fora} | {indisponiveis} | {amostra} |")

    pct = f"{total_vazou * 100 / total_medido:.0f}%" if total_medido else "sem medida"
    linhas.extend(["", f"**Total: {total_vazou}/{total_medido} ({pct}) vazaram.**", ""])

    DESTINO.write_text("\n".join(linhas), encoding="utf-8")
    print(f"escrito em {DESTINO}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
