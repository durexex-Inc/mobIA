"""A politica de zero-resultado da RN-09.3: relaxar uma vez, e so uma.

TEC-160. **Modulo proprio, e nao dentro de `busca.py`**, por duas razoes (D1).
A docstring de `busca.py` afirma que "nao precisa de CTE nem de duas viagens ao
banco" e deriva dali a garantia de latencia; uma funcao que faz duas viagens
sob esse texto o torna falso, e este repo trata comentario desatualizado como
defeito. E montar a consulta e decidir a politica de zero-resultado sao
responsabilidades diferentes -- separa-las da a RN-09.3 um nome proprio nos
testes.

A seta aponta num sentido so: este modulo importa `busca`, nunca o contrario.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.catalogo.busca import MAX_CANDIDATOS, vetor_da_consulta
from mobia.domain.catalogo.busca import buscar as buscar_de_verdade
from mobia.domain.catalogo.enums import EstadoDoRelaxamento
from mobia.domain.catalogo.models import BairroAdjacente
from mobia.domain.catalogo.schemas import Embedador, FiltroDeBusca, ResultadoDaBusca
from mobia.domain.texto import dobrar

log = structlog.get_logger(__name__)


def e_relaxavel(filtro: FiltroDeBusca) -> bool:
    """Se ha alguma dimensao que a RN-09.3 saiba relaxar. D5.

    Sem teto, sem piso e sem regiao, o zero veio de tipo, quartos ou vagas --
    e a regra nao relaxa nenhum dos tres. A segunda consulta seria byte a byte
    igual a primeira: paga-se latencia contra o p95 de 400 ms da TEC-159 para
    receber o mesmo zero.

    E tambem a lacuna que o desenho da TEC-262 nomeou -- "relaxaria preco e
    bairro de uma busca que nunca teve chance". Ela fechou o caso do tipo;
    quartos e vagas seguem abertos (L3).

    **Condicao necessaria, nao suficiente, e barata de proposito.** Regiao sem
    teto nem piso passa por aqui, mas so ha o que alargar se a tabela de
    adjacencia devolver bairro que o lead ja nao tinha pedido -- e descobrir
    isso custa uma consulta. Esta funcao evita pagar ate essa consulta quando
    nem ela poderia ajudar; quem de fato decide fazer o segundo passe e
    `buscar_com_relaxamento`, depois de olhar o que `alargar` mudou.
    """
    return (
        filtro.preco_max_centavos is not None
        or filtro.preco_min_centavos is not None
        or bool(filtro.regioes)
    )


def alargar(filtro: FiltroDeBusca, adjacentes: Sequence[str]) -> FiltroDeBusca:
    """O filtro do segundo passe: regioes UNIAO adjacentes, e `relaxado=True`.

    **O teto e o piso NAO se mexem aqui, de proposito.** A folga de preco e do
    `WHERE`, e mora dentro de `buscar` (D2 e D3). Escrever
    `preco_max_centavos = teto * 1,10` neste ponto faria a ancora de
    `_aderencia` viajar junto, e a promessa da emenda E-01 da RN-09.6 -- "10%
    acima do teto sai com 0,9" -- viraria falsa em silencio, com a ordenacao
    passando a favorecer o mais caro do conjunto AMPLIADO.

    **Uniao, e nao substituicao.** O cenario 4 do Gherkin diz "apenas bairros
    marcados como adjacentes a Trindade entram na busca"; ao pe da letra isso
    excluiria a propria Trindade, e esconderia o imovel que o preco relaxado
    acabou de tornar elegivel nela. "Apenas" limita de onde vem os novos, nao
    quem sai -- e o cenario 1 confirma ao dizer "preco ate R$ 440.000 E
    bairros adjacentes", nao "em vez de".

    Ordenado para que o `IN` gerado seja estavel entre execucoes: `set` nao tem
    ordem, e um IN que muda de ordem muda o SQL e invalida plano em cache sem
    motivo. E o mesmo argumento de `zonas_de`, em `busca.py`.
    """
    # TEC-163, D12. Nao e redundancia do NOT IN da busca: sem esta subtracao,
    # `relaxou_bairro` sairia True num relaxamento cujo unico bairro novo era
    # um excluido -- que o WHERE descarta em seguida --, e o lead ouviria
    # "incluí bairros vizinhos" tendo recebido zero bairro novo.
    #
    # O WHERE garante que o imovel excluido NAO VOLTA; esta linha garante que
    # o AVISO NAO MENTE. Um protege o lead do resultado, o outro da frase.
    adjacentes_validos = set(adjacentes) - set(filtro.bairros_excluidos)
    return replace(
        filtro,
        relaxado=True,
        regioes=tuple(sorted(set(filtro.regioes) | adjacentes_validos)),
    )


async def adjacentes_de(session: AsyncSession, regioes: Sequence[str]) -> tuple[str, ...]:
    """Os bairros vizinhos dos que o lead pediu, na forma dobrada. D8.

    **`regioes` tem de chegar JA DOBRADA.** A tabela guarda nome dobrado (a
    migration grava `dobrar(...)`), e esta funcao nao dobra: `IN ('Trindade')`
    contra `bairro_busca = 'trindade'` nao casa linha nenhuma e devolve vazio
    -- indistinguivel do caso legitimo da L2 abaixo. `buscar_com_relaxamento`
    dobra antes de chamar; quem chamar de outro lugar tem a mesma obrigacao.

    Um `IN` simples sobre a PK: a tabela guarda as duas direcoes justamente
    para que esta consulta nao precise ser um OR sobre duas colunas com uniao.

    Regiao que nao e nome de bairro -- "zona sul", por exemplo -- simplesmente
    nao casa linha nenhuma, e o resultado e vazio. Nao e erro: e a L2, e o
    passe relaxa so o preco.
    """
    if not regioes:
        return ()

    linhas = await session.execute(
        select(BairroAdjacente.adjacente_busca).where(
            BairroAdjacente.bairro_busca.in_(tuple(regioes))
        )
    )
    return tuple(sorted({linha[0] for linha in linhas}))


async def buscar_com_relaxamento(
    session: AsyncSession,
    filtro: FiltroDeBusca,
    *,
    consulta_texto: str | None = None,
    limite: int = MAX_CANDIDATOS,
    embedador: Embedador | None = None,
    buscar: Any = None,
) -> ResultadoDaBusca:
    """A busca da RN-09.1 com a politica de zero-resultado da RN-09.3.

    **Um passe a mais, no maximo, e nunca uma cascata.** A regra poe "um" em
    negrito e a card repete: "nunca uma cascata de tentativas". Uma escada
    (relaxa preco, se ainda zero amplia bairro) devolveria resultado mais
    proximo do pedido, mas custaria ate tres consultas contra o p95 de 400 ms
    que a TEC-159 mede. Ver D4.

    `buscar` e injetavel para o teste contar chamadas sem banco falso -- mesmo
    molde do `buscar` injetavel de `porta_de_busca`.
    """
    executar = buscar or buscar_de_verdade

    # D9: UMA vez, e o mesmo vetor vai para os dois passes. Sem isto, o passe 2
    # recebe `consulta_texto` de novo e chama o embedador outra vez -- segunda
    # chamada paga ao provedor e segunda latencia, para o mesmo texto, em todo
    # turno relaxado.
    vetor = await vetor_da_consulta(consulta_texto, embedador)

    resultado = await executar(session, filtro, vetor=vetor, limite=limite)
    if resultado.candidatos or not e_relaxavel(filtro):
        return resultado

    # As regioes dobradas UMA vez, aqui, e e a forma que segue para os tres
    # usos. `buscar` dobra por dentro, mas `adjacentes_de` nao: a tabela guarda
    # nome dobrado e o `IN` com o cru que a `porta_de_busca` monta ("Trindade")
    # nao casa linha nenhuma. Sem esta linha a metade de bairro da RN-09.3
    # morre em silencio -- so o preco alarga, e todo teste continua verde
    # porque todo teste escreve a regiao ja dobrada. `dobrar` e idempotente,
    # entao passar a forma dobrada adiante nao muda o que a busca enxerga -- e
    # e o que deixa a comparacao de `relaxou_bairro` abaixo ser entre iguais.
    dobradas = tuple(dobrar(regiao) for regiao in filtro.regioes if regiao.strip())

    # D13: falha aqui derruba a DIMENSAO, nao a busca -- e o molde de
    # `vetor_da_consulta` e da D6 da TEC-265. `Exception` ampla de proposito:
    # timeout, conexao caida e resposta malformada tem a mesma consequencia
    # aqui, e distinguir a causa nao muda o que o relaxamento faz.
    try:
        adjacentes = await adjacentes_de(session, dobradas)
    except Exception as erro:
        log.warning(
            "busca.adjacencia_indisponivel",
            tipo=type(erro).__name__,
            detalhe="o relaxamento segue so na faixa de preco",
        )
        adjacentes = ()

    alargado = alargar(replace(filtro, regioes=dobradas), adjacentes)

    # D11: o aviso tem tres variantes e escolhe por estes dois. As duas sao
    # medidas do que MUDOU, e nao do que se tentou: `bool(adjacentes)` diria
    # "incluí bairros vizinhos" tambem para o lead que nomeou um agrupamento
    # ja fechado ("Centro, Trindade, Agronomica, Itacorubi"), onde todo
    # adjacente que a tabela devolve ja estava no pedido e o `IN` do segundo
    # passe e o mesmo do primeiro. E exatamente a mentira que as tres
    # variantes existem para impedir.
    relaxou_preco = filtro.preco_max_centavos is not None or filtro.preco_min_centavos is not None
    # Contra `dobradas`, NUNCA contra `filtro.regioes`: comparar o alargado
    # (dobrado) com o cru daria True sempre que o lead escreveu com maiuscula
    # ou acento, e a mentira acima voltaria com outra roupa.
    relaxou_bairro = set(alargado.regioes) != set(dobradas)

    if not (relaxou_preco or relaxou_bairro):
        # Nada mudou: o `WHERE` do segundo passe seria byte a byte o do
        # primeiro, que ja voltou vazio. Pagariamos uma consulta contra o p95
        # de 400 ms da TEC-159 para carimbar `SEM_RESULTADO` no mesmo zero, e
        # o turno diria ao lead que "procurou tambem um pouco alem" de um
        # criterio que nao se mexeu. Depois do try/except de proposito:
        # adjacencia indisponivel sem teto nem piso e um dos jeitos de chegar
        # aqui.
        return resultado

    relaxado = await executar(session, alargado, vetor=vetor, limite=limite)

    # D6: `APLICADO` significa "o que voce esta vendo veio do passe relaxado".
    # Relaxou e continuou zero e `SEM_RESULTADO`, e nao `APLICADO` com lista
    # vazia -- senao o aviso ao lead anunciaria "ampliei o criterio" seguido de
    # nada, e o turno nao teria como oferecer o desfecho que a regra 4 da card
    # exige.
    return replace(
        relaxado,
        relaxamento=(
            EstadoDoRelaxamento.APLICADO
            if relaxado.candidatos
            else EstadoDoRelaxamento.SEM_RESULTADO
        ),
        relaxou_preco=relaxou_preco,
        relaxou_bairro=relaxou_bairro,
    )
