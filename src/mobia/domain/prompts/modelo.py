"""O que uma versao de prompt pode ser, sem I/O. TEC-199, D1 a D3 do desenho.

Modulo sem banco, no molde de `configuracao/vigente.py`: as regras de
publicacao sao testadas em `tests/unit/` sem Postgres de pe. Quem le e grava
as tabelas e `repositorio.py`, ao lado.

**O texto dos modelos padrao mora em `agente/classificador.py`**, ao lado dos
comentarios que explicam cada frase dele e do ritual do orcamento, e e
importado tarde: `classificador` importa `context.montagem`, que importa o
repositorio deste pacote, que importa este modulo. Mesmo recurso de
`configuracao/vigente.py::_cadencia_padrao`.
"""

import difflib
import re
from enum import StrEnum


class AgenteDoPrompt(StrEnum):
    """Os prompts versionados (D1, decisao do Eduardo, 26/09/2026).

    A card fala em "qualificador" e "consultor", que nao existem com esses
    nomes: os dois `system` que conversam com o lead sao o do turno principal
    e o do subagente investidor (TEC-153). Cada um tem historico proprio, e
    reverter um nao toca o outro.
    """

    AGENTE = "AGENTE"
    INVESTIDOR = "INVESTIDOR"


# Qualquer `{palavra}` no texto. Os dois conhecidos sao obrigatorios; o resto
# e recusado, porque quem escreve `{nome}` achando que e marcador mandaria a
# palavra literal para o modelo sem sintoma nenhum.
_MARCADOR = re.compile(r"\{([A-Za-z_]+)\}")


class ModeloInvalido(ValueError):
    """Versao recusada. Vira 422, e nada e gravado."""


def modelo_padrao(agente: AgenteDoPrompt) -> str:
    """A "versao 0": o texto escrito no codigo do deploy corrente."""
    from mobia.domain.agente.classificador import MODELO_DO_AGENTE, MODELO_DO_INVESTIDOR

    return MODELO_DO_AGENTE if agente is AgenteDoPrompt.AGENTE else MODELO_DO_INVESTIDOR


def _pior_caso(modelo: str) -> int:
    """O tamanho do `system` renderizado no pior caso da identidade: nome no
    teto de caracteres e o tom de frase mais longa -- o mesmo pior caso que
    `test_config.py::_PIOR_IDENTIDADE` mede para o orcamento."""
    from mobia.domain.agente.classificador import renderizar
    from mobia.domain.configuracao.vigente import TETO_DO_NOME, Tom

    return max(len(renderizar(modelo, nome="x" * TETO_DO_NOME, tom=tom)) for tom in Tom)


def teto_de_caracteres(agente: AgenteDoPrompt) -> int:
    """O maior modelo aceito, em caracteres do MODELO (D3).

    A regra e "renderizado no pior caso, nao passa do padrao renderizado no
    pior caso". Como a renderizacao so troca os marcadores, isso equivale a um
    teto no proprio modelo -- desde que o modelo tenha cada marcador uma vez so,
    que e o caso do padrao. Serve so para a tela mostrar um numero; quem decide
    e `validar_modelo`, que mede o renderizado e por isso conta tambem um
    marcador repetido.
    """
    padrao = modelo_padrao(agente)
    return len(padrao)


def validar_modelo(agente: AgenteDoPrompt, texto: str) -> str:
    """Levanta `ModeloInvalido` com TODAS as regras violadas juntas.

    Juntas, pelo argumento de `configuracao/vigente.py::validar`: quem corrige
    duas coisas numa rodada so nao quer descobrir a segunda depois.
    """
    erros: list[str] = []
    if not texto.strip():
        erros.append("o texto do prompt esta vazio")

    achados = set(_MARCADOR.findall(texto))
    for marcador in ("assistente", "tom"):
        if marcador not in achados:
            erros.append(
                f"falta o marcador {{{marcador}}}: e por ele que a configuracao do "
                "agente entra no prompt"
            )
    desconhecidos = sorted(achados - {"assistente", "tom"})
    if desconhecidos:
        lista = ", ".join("{" + m + "}" for m in desconhecidos)
        erros.append(f"marcador desconhecido: {lista}; so existem {{assistente}} e {{tom}}")

    # D3. Medido RENDERIZADO, e nao no modelo cru: um marcador repetido custa
    # a frase dele de novo, e e o renderizado que vai para a API.
    excesso = _pior_caso(texto) - _pior_caso(modelo_padrao(agente))
    if excesso > 0:
        erros.append(
            f"o prompt passa {excesso} caracteres do tamanho do padrao; a folga do "
            "orcamento de contexto e reservada, e crescer o prompt e mudanca de codigo"
        )

    if erros:
        raise ModeloInvalido("; ".join(erros))
    return texto


def diff_entre(anterior: str, novo: str, *, de: str, para: str) -> str:
    """Unified diff por linha. Gravado na publicacao (D4), e nao na leitura.

    `lineterm=""` e junta por `\\n`: com `keepends`, a ultima linha de um texto
    sem quebra final grudaria na linha seguinte do diff.
    """
    return "\n".join(
        difflib.unified_diff(
            anterior.splitlines(), novo.splitlines(), fromfile=de, tofile=para, lineterm=""
        )
    )
