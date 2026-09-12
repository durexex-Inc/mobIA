"""A busca hibrida do catalogo: filtro estruturado antes da similaridade.

TEC-158. RN-09.1 (as duas fases), RN-09.2 (o teto de 10), RN-09.6 (a
ordenacao) e RN-08.4 (o que nao esta DISPONIVEL fica fora).

**As duas fases sao uma instrucao, e a garantia e a semantica do SQL.** O
Postgres avalia o WHERE antes de qualquer expressao do ORDER BY, entao o
"antes" da RN-09.1 sai de graca -- nao precisa de CTE nem de duas viagens ao
banco. Duas viagens dobrariam a latencia sem mudar o resultado; trazer o
subconjunto para calcular cosseno em Python transferiria 1536 floats por
linha, que numa faixa larga de preco e o catalogo inteiro pela rede.

**A consulta e montada com o Core, e nao com `text()` cru** -- e aqui este
modulo DIVERGE do molde das varreduras (`sweep_stalled`,
`indexar_catalogo`). Aquelas tem UMA forma fixa; esta tem seis filtros
independentemente opcionais. Em `text()` isso obriga a
`(:preco_max IS NULL OR preco_venda <= :preco_max)` em cada clausula, e esse
predicado entrega ao planejador uma condicao que ele nao pode podar: o plano
generico considera a coluna filtrada mesmo quando o parametro e nulo. Isso e
ruim justamente na TEC-159, que mede p95. Com o Core, so as condicoes
presentes entram no WHERE.

**A aderencia mora AQUI e em nenhum outro lugar, como expressao SQL.** O
score tem de estar no ORDER BY para o LIMIT significar algo, entao o calculo
e do banco. Uma funcao Python gemea que devolvesse o mesmo numero seria uma
segunda definicao da mesma regra -- a divergencia entre as duas apareceria
como ordem que ninguem consegue explicar. E o mesmo criterio da D3 da
TEC-157, que recusou o hash em SQL para nao duplicar a lista de campos.
"""

from collections.abc import Sequence
from typing import Any

import structlog
from sqlalchemy import Numeric, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel, Zona
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import (
    COLUNA_DE_PRECO,
    Candidato,
    Embedador,
    FiltroDeBusca,
    ResultadoDaBusca,
)
from mobia.domain.texto import dobrar

log = structlog.get_logger(__name__)

# RN-09.6. Constantes de modulo e nao `Settings`: pesos configuraveis sao
# RF-19, e antecipa-los aqui criaria configuracao que ninguem sabe calibrar
# sobre uma formula cuja metade a emenda E-01 acabou de definir. Ver D11.
PESO_SIMILARIDADE = 0.6
PESO_ADERENCIA = 0.4

# RN-09.2. O teto do que volta ao agente; os 3 que chegam ao lead sao a
# TEC-162.
MAX_CANDIDATOS = 10

# RN-09.3. A folga que o segundo passe da TEC-160 aplica as duas pontas da
# faixa. Pontos percentuais inteiros de proposito: `* 1.10` em float produz
# tetos que variam no ultimo centavo, e num catalogo de precos densos isso
# vira desempate invisivel numa suite que ja flakeia sob carga.
MARGEM_DO_RELAXAMENTO_PCT = 10

# O vocabulario que faz "zona sul" virar `Zona.SUL`. Cada zona entra com o
# nome nu e com o prefixo `zona `, porque o lead diz os dois -- e
# `normalizar_regiao` deixa `zona` passar de proposito: o comentario de
# `_PREFIXOS_DE_REFERENCIA` registra que "`zona leste`, `zona sul` e `zona
# oeste` sao o nome, nao ruido".
_ZONA_POR_TEXTO: dict[str, Zona] = {
    **{dobrar(zona.value): zona for zona in Zona},
    **{f"zona {dobrar(zona.value)}": zona for zona in Zona},
}


# TEC-262, D2. Os tipos do catalogo que um pedido de tipo casa, alem dele
# mesmo. UMA entrada, e um `.get` com default de identidade -- a forma e a
# mensagem: existe uma regra assimetrica e todo o resto e ele mesmo.
#
# Um dicionario com as seis chaves preenchidas convidaria o proximo leitor a
# completar a simetria (`CASA: (CASA,)`, `TERRENO: (TERRENO,)`) e, tendo
# completado, a "consertar" a linha que nao e simetrica. A assimetria e o
# ponto, e nao um esquecimento.
#
# **Por que a seta aponta num sentido so.** Nao existe pedido de `COBERTURA`
# vindo do lead: o enum do agente nao tem o membro, e a D1 da TEC-242 garante
# que nao tera. Um chamador HTTP pode pedir cobertura -- a secao 6.3 aceita o
# enum do catalogo -- e ali a igualdade pura e a resposta certa: quem pede
# cobertura explicitamente quer cobertura. E quem pede `CASA` nao deve ver
# apartamento, que seria a generalizacao errada da mesma ideia.
_INCLUSOES: dict[TipoImovel, tuple[TipoImovel, ...]] = {
    TipoImovel.APARTAMENTO: (TipoImovel.APARTAMENTO, TipoImovel.COBERTURA),
}


def _inclusoes_de(tipo: TipoImovel) -> tuple[TipoImovel, ...]:
    """Os tipos que este pedido casa. Identidade, menos onde a D2 diz o contrario.

    Para a fala do lead, cobertura e uma especie de apartamento -- a D1 da
    TEC-242 ja decidiu isso ao anotar os tres turnos de `compra-06` que dizem
    "cobertura" como `APARTAMENTO`. Deixar a cobertura fora do resultado faria
    o filtro contradizer a anotacao do corpus, e na base simulada esconderia
    8% do catalogo do pedido mais comum.
    """
    return _INCLUSOES.get(tipo, (tipo,))


def zonas_de(regioes: Sequence[str]) -> tuple[Zona, ...]:
    """As zonas que o vocabulario reconhece nas regioes dadas.

    **Isto NAO e classificacao.** A regiao que casa uma zona continua sendo
    comparada contra `bairro_busca` tambem -- o filtro e um OR (D4). "centro"
    e nome de zona E de bairro em quase toda cidade brasileira: perguntar "e
    zona ou e bairro?" obriga a escolher, e a escolha erra metade das vezes
    devolvendo resultados plausiveis do lado errado.

    Ordenado por valor para que a consulta gerada seja estavel entre
    execucoes -- `set` nao tem ordem, e um IN que muda de ordem muda o SQL e
    invalida plano em cache sem motivo.
    """
    encontradas = {_ZONA_POR_TEXTO[regiao] for regiao in regioes if regiao in _ZONA_POR_TEXTO}
    return tuple(sorted(encontradas, key=lambda zona: zona.value))


def _aderencia(preco: ColumnElement[Any], teto: int | None) -> ColumnElement[Any]:
    """A aderencia ao teto de preco, em [0, 1]. RN-09.6, emenda E-01.

    A regra da o peso (0,4) e **nunca diz o que se mede**. O primeiro fato e
    que aderencia nao pode ser "respeita a faixa": o filtro e DURO, entao
    todo candidato ja esta dentro dela e o termo valeria 1 para todos -- 40%
    do peso zerado, e a ordenacao sendo similaridade pura com um nome errado.

    A ancora e o TETO, e nao o centro da faixa. Tres razoes: nao precisa do
    piso, que o lead frequentemente nao diz; o teto e o que o SRS trata como
    significativo (a RN-09.3 relaxa a faixa em ate 10% e a CA-09.1 cobra so o
    teto -- o piso nao aparece em regra nenhuma da RF-09); e o relaxamento da
    TEC-160 decai sozinho, porque 10% acima do teto sai com 0,9 sem clausula
    extra. No teto da 1,0; na metade do orcamento, 0,5.

    Sem teto informado devolve a constante 1: o termo PARA de discriminar, em
    vez de discriminar por acidente.

    **Efeito colateral declarado:** favorece sistematicamente o imovel mais
    caro que cabe no orcamento. E o comportamento de um corretor competente,
    e e tambem a direcao em que um erro de calibragem viraria upsell -- quem
    for medir precisao@3 na TEC-159 tem aqui o que olhar primeiro.
    """
    if teto is None:
        return literal(1.0)
    # `func.greatest(0.0, ...)` e nao um CASE: e a mesma poda, mais curta, e
    # e a forma que o `_similaridade` usa logo abaixo pelo mesmo motivo.
    return func.greatest(0.0, 1.0 - func.abs(preco - teto) / float(teto))


def _similaridade(vetor: list[float] | None) -> ColumnElement[Any]:
    """A similaridade de cosseno com a consulta, em [0, 1]. D8.

    `<=>` do pgvector e DISTANCIA de cosseno em [0, 2], entao `1 - distancia`
    vive em [-1, 1]. Similaridade negativa e rara em texto real, e sem o
    `greatest` ela entraria com peso 0,6 e poderia empurrar um candidato para
    tras de um sem vetor nenhum -- que e ordem sem significado.

    **O `coalesce` esta explicito de proposito.** `GREATEST` do Postgres
    IGNORA NULL, entao `GREATEST(0, 1 - NULL)` ja devolve 0 e os dois casos
    degenerados (imovel sem embedding, consulta sem vetor) funcionariam
    sozinhos. A regra da D8 tem de valer por decisao, e nao por uma
    peculiaridade da funcao que o proximo leitor nao conhece.
    """
    if vetor is None:
        return literal(0.0)
    return func.coalesce(func.greatest(0.0, 1.0 - Imovel.embedding.cosine_distance(vetor)), 0.0)


def _com_folga(valor: int, sinal: int) -> int:
    """O limite de preco do passe relaxado. `sinal` e +1 para o teto, -1 para o piso.

    Aritmetica inteira sobre centavos, sem ponto flutuante entrando no SQL.
    """
    return valor * (100 + sinal * MARGEM_DO_RELAXAMENTO_PCT) // 100


async def buscar(
    session: AsyncSession,
    filtro: FiltroDeBusca,
    consulta_texto: str | None = None,
    limite: int = MAX_CANDIDATOS,
    embedador: Embedador | None = None,
    vetor: list[float] | None = None,
) -> ResultadoDaBusca:
    """Os candidatos que atendem ao filtro, ordenados pela relevancia da RN-09.6.

    `limite` e preso entre 1 e `MAX_CANDIDATOS` mesmo quando o chamador pede
    algo fora da faixa: a RN-09.2 e sobre o que a busca DEVOLVE, e nao sobre
    o que o endpoint aceita. O endpoint recusa `limite > 10` com 422 e exige
    `ge=1` para informar o cliente; este clamp garante a regra nos dois
    sentidos para quem chama por dentro -- sem ele, `0` devolveria uma busca
    vazia sem motivo e `-1` faria o `LIMIT` do Postgres levantar. Ver D10.

    `vetor` presente manda, e `consulta_texto`/`embedador` sao ignorados.
    Ausente (ou `None`), deriva como sempre. Nao precisa de sentinela porque
    "passei None" e "nao passei" querem a mesma coisa: derive se puder. Quem
    usa isto e `buscar_com_relaxamento`, que vetoriza UMA vez e entrega o
    mesmo vetor aos dois passes -- sem isso, todo turno relaxado pagaria duas
    chamadas ao provedor pelo mesmo texto. Ver D9.
    """
    teto_de_candidatos = max(1, min(limite, MAX_CANDIDATOS))

    # Dobra o que recebeu: o chamador pode passar "Zona Sul" ou "zona sul" e o
    # resultado e o mesmo, porque `dobrar` e idempotente. O lead chega pela
    # `normalizar_regiao`, que ja dobrou -- dobrar de novo nao custa nada e
    # tira do chamador HTTP a obrigacao de saber disso.
    regioes = tuple(dobrar(regiao) for regiao in filtro.regioes if regiao.strip())
    zonas = zonas_de(regioes)

    vetor = vetor if vetor is not None else await vetor_da_consulta(consulta_texto, embedador)

    preco = getattr(Imovel, COLUNA_DE_PRECO[filtro.operacao])

    condicoes: list[ColumnElement[Any]] = [
        # Literal, e nao parametro: ver D3.
        Imovel.status == StatusImovel.DISPONIVEL.value,
        # `in_` e nao `==`: igualdade crua excluiria todo imovel anunciado
        # para venda E locacao, que e caso comum de catalogo real e sairia da
        # busca em silencio.
        Imovel.operacao.in_([filtro.operacao.value, Operacao.AMBOS.value]),
        # O CHECK da tabela so garante que UM dos dois precos existe.
        preco.is_not(None),
    ]

    # TEC-160, D2 e D3. O `WHERE` cede quando este e o passe relaxado; a
    # ANCORA de `_aderencia`, mais abaixo, NAO -- ela continua recebendo
    # `filtro.preco_max_centavos` cru. Os dois fatos estao nesta funcao de
    # proposito: separa-los faria a promessa da emenda E-01 da RN-09.6 ("10%
    # acima do teto sai com 0,9") depender de dois campos coincidirem.
    if filtro.preco_max_centavos is not None:
        teto = filtro.preco_max_centavos
        condicoes.append(preco <= (_com_folga(teto, +1) if filtro.relaxado else teto))
    if filtro.preco_min_centavos is not None:
        piso = filtro.preco_min_centavos
        condicoes.append(preco >= (_com_folga(piso, -1) if filtro.relaxado else piso))
    if filtro.tipo is not None:
        condicoes.append(Imovel.tipo.in_([tipo.value for tipo in _inclusoes_de(filtro.tipo)]))
    if filtro.quartos_min is not None:
        # `>=`, porque a card diz "nenhum resultado tem menos de 2 quartos" e
        # o contrato do SRS chama o campo de `quartosMin`.
        condicoes.append(Imovel.quartos >= filtro.quartos_min)
    if filtro.vagas_min is not None:
        condicoes.append(Imovel.vagas >= filtro.vagas_min)
    if regioes:
        # O OR da D4. `IN ()` e erro de sintaxe no Postgres -- o SQLAlchemy
        # nunca o emite. Para `zonas` vazia, `in_([])` compila para
        # `zona IN (NULL) AND (1 != 1)`: a estrategia de empty-IN do proprio
        # SQLAlchemy. A clausula fica falsa porque `AND` tem precedencia sobre
        # `OR`, entao o WHERE le como `bairro_busca IN (...) OR (zona IN
        # (NULL) AND (1 != 1))` -- o lado da zona nunca contribui, mesmo para
        # `zona` NULL, e nao envenena o OR.
        condicoes.append(
            or_(
                Imovel.bairro_busca.in_(regioes),
                Imovel.zona.in_([zona.value for zona in zonas]),
            )
        )
    if filtro.bairros_excluidos:
        # TEC-163, D12. Excluido e excluido, relaxado ou nao. Necessario mesmo
        # sem relaxamento: se o lead pediu "zona sul" e o Campeche foi
        # excluido, o filtro de zona o casa pelo outro lado do OR de regiao --
        # so esta condicao, em AND, o segura.
        condicoes.append(Imovel.bairro_busca.not_in(filtro.bairros_excluidos))

    # `round` do Postgres com duas casas exige `numeric`: sobre `double
    # precision` ele so aceita um argumento. As tres casas vem do
    # `score_match numeric(4,3)` da tabela Recomendacao do SRS; o TIPO nao --
    # a entrada e uma distancia de cosseno em ponto flutuante, e `Decimal`
    # afirmaria uma exatidao que o vetor nao tem. Ver D11.
    score = func.round(
        cast(
            PESO_SIMILARIDADE * _similaridade(vetor)
            + PESO_ADERENCIA * _aderencia(preco, filtro.preco_max_centavos),
            Numeric,
        ),
        3,
    ).label("score")

    consulta = (
        select(
            Imovel.id,
            Imovel.codigo,
            Imovel.titulo,
            Imovel.bairro,
            preco.label("preco"),
            Imovel.quartos,
            Imovel.vagas,
            Imovel.area_util_m2,
            Imovel.embedding.is_not(None).label("tem_vetor"),
            score,
            # A contagem ANTES do teto, na mesma passagem: funcao de janela e
            # avaliada depois do WHERE e antes do LIMIT. Um COUNT separado
            # pagaria o filtro duas vezes para devolver um inteiro.
            func.count().over().label("total_candidatos"),
        )
        .where(*condicoes)
        # O desempate por `id` e OBRIGATORIO: sem ele a ordem entre scores
        # empatados e a que o executor entregar, e ela varia entre execucoes.
        # Numa suite cujos testes de integracao ja flakeiam sob carga, isso
        # seria flake plantado a mao.
        #
        # `score` aqui e o `Label` do SELECT, e nao a expressao crua: o
        # SQLAlchemy referencia o alias (`ORDER BY score DESC`) em vez de
        # recompilar o `round(CAST(... greatest ...))` inteiro uma segunda
        # vez -- o Postgres computa o score uma vez por linha, nao duas.
        .order_by(score.desc(), Imovel.id)
        .limit(teto_de_candidatos)
    )

    linhas = list(await session.execute(consulta))

    candidatos = tuple(
        Candidato(
            imovel_id=linha.id,
            codigo=linha.codigo,
            titulo=linha.titulo,
            bairro=linha.bairro,
            preco_centavos=linha.preco,
            quartos=linha.quartos,
            vagas=linha.vagas,
            area_util_m2=linha.area_util_m2,
            # `float` na borda: o `round` devolveu `Decimal` porque o cast
            # pediu `numeric`, e o dominio expoe `float` (D11).
            score=float(linha.score),
            tem_vetor=linha.tem_vetor,
        )
        for linha in linhas
    )

    return ResultadoDaBusca(
        candidatos=candidatos,
        total_candidatos=linhas[0].total_candidatos if linhas else 0,
        consulta_vetorizada=vetor is not None,
    )


async def vetor_da_consulta(
    consulta_texto: str | None, embedador: Embedador | None
) -> list[float] | None:
    """O vetor da consulta, ou None -- e None nunca e erro. D8 e D9.

    Tres caminhos levam a None, e nenhum deles bloqueia a busca: nao ha texto
    de consulta (o lead so deu criterios estruturados), nao ha embedador
    injetado, ou o provedor falhou. Em todos, a similaridade vale 0 para todo
    candidato e a ordem passa a ser a aderencia de preco.

    **Isto e o que substitui a garantia de topologia da TEC-157.** A docstring
    de `indexar_catalogo` dizia que nenhum caminho chama o provedor de
    embedding dentro do turno, e derivava DISSO a regra de que falha de
    embedding nao bloqueia o atendimento. A metade que sobrevive e a que
    importa -- o embedding do CATALOGO continua nascendo so no cron --, e a
    metade nova precisa deste `except` e do teste que o cobre.

    `Exception` ampla de proposito: timeout, conexao recusada, 429 e resposta
    malformada tem todos a mesma consequencia aqui, e distinguir a causa nao
    muda o que a busca faz. `motivo_do_provedor` nao e usado para nao
    importar `infra.embeddings` neste modulo de dominio -- o tipo da excecao e
    o sinal, e o motivo detalhado do provedor ja e logado pela varredura.
    """
    if not consulta_texto or not consulta_texto.strip():
        return None
    if embedador is None:
        return None

    try:
        vetores = await embedador([consulta_texto])
    except Exception as erro:
        log.warning(
            "busca.consulta_nao_vetorizada",
            tipo=type(erro).__name__,
            detalhe="a busca segue com filtro estruturado e ordem por aderencia de preco",
        )
        return None

    return vetores[0] if vetores else None
