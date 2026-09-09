"""A ficha do imovel e a legenda que o lead recebe. TEC-162.

Puro de proposito: nenhum I/O e **nenhum import de `domain/catalogo`**. Quem
traduz `Imovel` em `Ficha` e `ferramenta_de_busca.fichas_do_catalogo`, que e
o unico arquivo em que `domain/agente` toca `domain/catalogo` -- a invariante
esta no docstring dele, e quebra-la aqui a tornaria invisivel.

Todo texto daqui sai para o lead e e ASCII, sem acento: `Condominio`, `m2`,
separador `-`. E a mesma disciplina de `TEXTO_DA_BUSCA_INCONCLUSIVA` em
`turno.py`, e a D12 do desenho explica por que a card a segue em vez de
consertar a politica.
"""

from collections.abc import Sequence
from dataclasses import dataclass

# RN-04.2. O mesmo numero de `evals/metricas.MAX_CARACTERES_DA_RESPOSTA`, que
# mede a regra nas evals; este e o primeiro lugar de `src/` que a respeita por
# construcao. Nao e limite da Meta -- a legenda dela cabe 1024.
MAX_CARACTERES_DA_LEGENDA = 600

# Duas e nao quatro porque cinco linhas de ficha e o limite do que se le numa
# legenda de foto.
CARACTERISTICAS_NO_DESTAQUE = 2

_SEPARADOR_DA_PROSA = "\n\n"
_RETICENCIA = "..."


@dataclass(frozen=True, slots=True)
class Ficha:
    """Os oito campos da RN-10.1, resolvidos e agnosticos de canal.

    Tres campos sao opcionais porque o catalogo os tem vazios de verdade --
    117 dos 520 imoveis do seed nao tem caracteristica nenhuma. Ausencia
    omite a linha e nunca esconde o imovel, que e a regra da propria RN-10.2
    sobre foto.
    """

    titulo: str
    bairro: str
    preco_centavos: int
    quartos: int
    vagas: int
    area_util_m2: int
    condominio_centavos: int | None
    diferencial: str | None
    foto: str | None


def reais_de(centavos: int) -> str:
    """`R$ 516.464` a partir de 51646430.

    Trunca os centavos para BAIXO e nunca arredonda: arredondar para cima
    cota ao lead um preco acima do real, e e essa a direcao que vira
    reclamacao na visita. O seed tem preco com centavos de verdade
    (`516464.30`), entao isto nao e hipotese.
    """
    return f"R$ {centavos // 100:,}".replace(",", ".")


def diferencial_de(caracteristicas: Sequence[str]) -> str | None:
    """As duas primeiras caracteristicas, na ordem em que o catalogo as guarda.

    Ordem armazenada e nao ranking: quem quiser priorizar muda o CSV. `None`
    quando nao ha nenhuma, e `legenda_de` omite a linha.
    """
    escolhidas = tuple(caracteristicas)[:CARACTERISTICAS_NO_DESTAQUE]
    if not escolhidas:
        return None
    return " e ".join(escolhidas)


def legenda_de(ficha: Ficha, *, prefixo: str | None = None) -> str:
    """A legenda de uma ficha, com a prosa do modelo opcionalmente na frente.

    Estourado o teto, o que se corta e o PREFIXO -- nunca a ficha. A ficha e
    o conteudo que a RN-10.1 exige e a prosa e ornamento, e essa ordem de
    prioridade e a D14 do desenho.
    """
    linhas = [
        ficha.titulo,
        f"{ficha.bairro} - {reais_de(ficha.preco_centavos)}",
        f"{ficha.quartos} quartos - {ficha.vagas} vagas - {ficha.area_util_m2} m2",
    ]
    if ficha.condominio_centavos is not None:
        linhas.append(f"Condominio {reais_de(ficha.condominio_centavos)}")
    if ficha.diferencial is not None:
        linhas.append(f"Destaque: {ficha.diferencial}")
    corpo = "\n".join(linhas)

    prosa = _prosa_que_cabe(prefixo, len(corpo)) if prefixo else ""
    if not prosa:
        return corpo
    return f"{prosa}{_SEPARADOR_DA_PROSA}{corpo}"


def _prosa_que_cabe(prefixo: str, tamanho_do_corpo: int) -> str:
    """O prefixo truncado na ultima fronteira de palavra que couber.

    Devolve string vazia quando nao sobra espaco nem para a reticencia --
    prosa cortada no meio de uma palavra sem marca nenhuma pareceria bug ao
    lead, e a ficha nunca cede espaco para evitar isso.
    """
    disponivel = MAX_CARACTERES_DA_LEGENDA - tamanho_do_corpo - len(_SEPARADOR_DA_PROSA)
    if len(prefixo) <= disponivel:
        return prefixo
    if disponivel <= len(_RETICENCIA):
        return ""
    return prefixo[: disponivel - len(_RETICENCIA)].rsplit(" ", 1)[0] + _RETICENCIA
