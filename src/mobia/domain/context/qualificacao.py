"""A regra que decide se o lead atingiu o minimo de qualificacao.

TEC-147, RN-05.3. Pura de proposito: sem I/O, sem banco, sem chamada ao
modelo. Nao ha coluna `status` -- "qualificado" e funcao dos campos, e uma
segunda fonte para o mesmo fato divergiria da primeira. Ver D1 do desenho.
"""

from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.models import LeadQualification

# O nome logico do orcamento, e o prefixo que todos os outros nomes dele
# compartilham. Ver `_canonico`.
CAMPO_DO_ORCAMENTO = "faixa_preco"

# Os quatro da RN-05.3. `faixa_preco` e um nome logico, nao uma coluna: sao
# duas colunas (`_min_centavos` e `_max_centavos`) e qualquer uma delas basta.
CAMPOS_OBRIGATORIOS: tuple[str, ...] = ("intencao", CAMPO_DO_ORCAMENTO, "regiao", "urgencia")

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

    Os nomes de `recusados` passam por `_canonico` antes de qualquer
    comparacao: o orcamento tem cinco nomes neste repo e a TEC-148 nao tem
    como saber qual deles esta lista usa.
    """
    if estado is None:
        return False

    negados = {_canonico(nome) for nome in recusados}
    for campo in CAMPOS_OBRIGATORIOS:
        if campo in negados:
            return False
        if not _preenchido(estado, campo):
            return False
    return True


def _canonico(nome: str) -> str:
    """O nome logico do campo que `nome` designa.

    Existe por causa do orcamento, que e o unico campo com mais de um nome, e
    que ja custou uma card inteira a este projeto: a TEC-146 gastou a dela
    num bug silencioso causado por dois lugares guardando o mesmo fato sob
    nomes diferentes (ver `_MARCA_DO_ORCAMENTO`, em `repositorio.py`).

    Sao cinco nomes hoje -- `faixa_preco_expressao` (o que o modelo diz),
    `faixa_preco_min_centavos`/`faixa_preco_max_centavos` (as colunas),
    `faixa_preco_min`/`faixa_preco_max` (o que o prompt renderiza, e sob o
    qual a marca da TEC-257 e gravada) -- e `CAMPOS_OBRIGATORIOS` usa um
    sexto, `faixa_preco`, que nao e nenhum deles. Sem esta traducao, a
    TEC-148 passando `recusados={"faixa_preco_max"}` -- a escolha obvia, e a
    unica que o vocabulario da marca oferece -- seria ignorada em silencio:
    a string nao esta em `CAMPOS_OBRIGATORIOS`, o laco nunca a ve, e um lead
    que recusou falar de orcamento qualificaria assim mesmo, sobre um preco
    velho. Teste verde nas duas cards.

    A traducao e por prefixo, e nao por tabela, de proposito: todos os seis
    nomes comecam por `faixa_preco`, e o proximo tambem vai comecar. Uma
    tabela precisaria ser lembrada; o prefixo nao. O preco disso e que um
    campo futuro que fale de preco sem ser o orcamento do lead (digamos,
    `faixa_preco_do_vendedor`) cairia aqui por engano -- e recusa larga de
    mais, que nega qualificacao, e o erro menos caro dos dois.
    """
    return CAMPO_DO_ORCAMENTO if nome.startswith(CAMPO_DO_ORCAMENTO) else nome


def _preenchido(estado: LeadQualification, campo: str) -> bool:
    if campo == "intencao":
        return estado.intencao in INTENCOES_QUALIFICAVEIS
    if campo == CAMPO_DO_ORCAMENTO:
        # Qualquer um dos extremos basta. Exigir os dois contradiz a RN-05.6,
        # que manda "ate 500 mil" virar max preenchido e min nulo.
        return (
            estado.faixa_preco_min_centavos is not None
            or estado.faixa_preco_max_centavos is not None
        )
    return getattr(estado, campo) is not None
