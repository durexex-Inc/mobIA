"""A regra que decide se o lead atingiu o minimo de qualificacao.

TEC-147, RN-05.3. Pura de proposito: sem I/O, sem banco, sem chamada ao
modelo. Nao ha coluna `status` -- "qualificado" e funcao dos campos, e uma
segunda fonte para o mesmo fato divergiria da primeira. Ver D1 do desenho.
"""

from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.models import LeadQualification

# Os quatro da RN-05.3. `faixa_preco` e um nome logico, nao uma coluna: sao
# duas colunas (`_min_centavos` e `_max_centavos`) e qualquer uma delas basta.
CAMPOS_OBRIGATORIOS: tuple[str, ...] = ("intencao", "faixa_preco", "regiao", "urgencia")

# RN-03.4: VENDER_IMOVEL e SUPORTE_CONTRATO vao direto para handoff, e o SDR
# nao os qualifica. INDEFINIDA e FORA_DE_ESCOPO ficam de fora por outro
# motivo: significam ausencia de intencao utilizavel, e a coluna nunca e nula
# depois do primeiro turno, entao "preenchida" precisa desta lista para
# significar alguma coisa.
INTENCOES_QUALIFICAVEIS = frozenset(
    {Intencao.COMPRA.value, Intencao.ALUGUEL.value, Intencao.INVESTIMENTO.value}
)


def esta_qualificado(
    estado: LeadQualification | None,
    recusados: frozenset[str] = frozenset(),
) -> bool:
    """O lead atingiu o minimo obrigatorio da RN-05.3.

    `recusados` entra por parametro e nao por coluna: quem grava recusa e a
    TEC-148, que ainda nao existe. O default vazio e o comportamento de hoje,
    e a assinatura documenta a dependencia em vez de esconde-la (D5).

    Campo recusado nao conta, mesmo com valor na coluna (D4).
    """
    if estado is None:
        return False

    for campo in CAMPOS_OBRIGATORIOS:
        if campo in recusados:
            return False
        if not _preenchido(estado, campo):
            return False
    return True


def _preenchido(estado: LeadQualification, campo: str) -> bool:
    if campo == "intencao":
        return estado.intencao in INTENCOES_QUALIFICAVEIS
    if campo == "faixa_preco":
        # Qualquer um dos extremos basta. Exigir os dois contradiz a RN-05.6,
        # que manda "ate 500 mil" virar max preenchido e min nulo.
        return (
            estado.faixa_preco_min_centavos is not None
            or estado.faixa_preco_max_centavos is not None
        )
    return getattr(estado, campo) is not None
