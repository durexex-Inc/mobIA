"""O relaxamento da RN-09.3 contra o banco.

TEC-160. Os quatro cenarios do Gherkin da card, mais METADE da divida que a
TEC-158 deixou nomeada.

A metade paga e o decaimento para 0,9, que so e alcancavel quando o filtro
deixa de ser duro -- `test_a_ancora_da_ordenacao_nao_se_move_com_o_where`. A
outra metade, o clamp em 0 da aderencia, continua sem teste porque continua
inalcancavel por este caminho: `_aderencia` so zera em `preco >= 2 x teto`, e
o `WHERE` do passe relaxado para em `1,10 x teto` -- nenhuma linha que a busca
devolve chega la. Paga-la exige exercitar `_aderencia` por fora da busca, e
isso nao esta nesta card.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from sqlalchemy import select

from mobia.domain.catalogo import busca as modulo_de_busca
from mobia.domain.catalogo.busca import buscar
from mobia.domain.catalogo.enums import EstadoDoRelaxamento, Operacao
from mobia.domain.catalogo.models import BairroAdjacente, Imovel
from mobia.domain.catalogo.relaxamento import buscar_com_relaxamento
from mobia.domain.catalogo.schemas import FiltroDeBusca
from mobia.domain.texto import dobrar

TETO = 40000000  # R$ 400.000,00 em centavos -- o numero do cenario 1 da card


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Um imovel completo e valido, com sobrescrita por campo.

    Molde do `_imovel` de `test_busca_hibrida.py`.
    """
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Trindade",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 35000000,
        "bairro": "Trindade",
        "cidade": "Florianopolis",
        "uf": "SC",
        "zona": "CENTRO",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    campos.setdefault("bairro_busca", dobrar(str(campos["bairro"])))
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_o_filtro_relaxado_admite_dez_por_cento_acima_do_teto(session: Any) -> None:
    """D3. O `WHERE` cede; e o numero do cenario 1 da card (400 -> 440 mil)."""
    acima = await _imovel(session, "AP-201", preco_venda=44000000)

    duro = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO))
    relaxado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, relaxado=True),
    )

    assert duro.candidatos == ()
    assert [candidato.imovel_id for candidato in relaxado.candidatos] == [acima]


async def test_a_ancora_da_ordenacao_nao_se_move_com_o_where(session: Any) -> None:
    """D2, e a divida que o plano da TEC-158 deixou para esta card.

    A emenda E-01 da RN-09.6 promete que "10% acima do teto sai com 0,9". Isso
    so vale se `_aderencia` continuar ancorada no teto ORIGINAL. Se a ancora
    viajasse junto com o `WHERE`, este imovel sairia com 1,0 -- e a ordenacao
    passaria a favorecer o mais caro do conjunto AMPLIADO, que e a direcao em
    que um erro de calibragem vira upsell.

    Sem vetor de consulta a similaridade vale 0 para todos, entao o score e
    `0,4 * aderencia` -- e 0,4 * 0,9 = 0,36.
    """
    await _imovel(session, "AP-202", preco_venda=44000000)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, relaxado=True),
    )

    assert resultado.candidatos[0].score == 0.36


async def test_o_piso_tambem_cede_no_passe_relaxado(session: Any) -> None:
    """D3: "faixa de preco em ate 10%" e sobre o intervalo, nao so o teto."""
    abaixo = await _imovel(session, "AP-203", preco_venda=19000000)

    duro = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, preco_min_centavos=20000000)
    )
    relaxado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_min_centavos=20000000, relaxado=True),
    )

    assert duro.candidatos == ()
    assert [candidato.imovel_id for candidato in relaxado.candidatos] == [abaixo]


async def test_relaxado_sem_teto_nem_piso_nao_muda_nada(session: Any) -> None:
    """A folga se aplica ao que existe; `None` continua sendo "sem essa ponta"."""
    dentro = await _imovel(session, "AP-204")

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA, relaxado=True))

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [dentro]


async def test_vetor_pronto_dispensa_o_embedador(session: Any) -> None:
    """D9. Com o vetor na mao, `buscar` nao chama o provedor.

    O embedador injetado aqui EXPLODE se chamado: o teste falha por excecao,
    e nao por assercao sobre contagem, porque o que importa e que a segunda
    chamada nao aconteca -- nao que ela aconteca N vezes.
    """
    await _imovel(session, "AP-205")

    async def embedador_proibido(textos: list[str]) -> list[list[float]]:
        raise AssertionError("o embedador nao devia ser chamado com vetor pronto")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        vetor=[0.0] * 1536,
        embedador=embedador_proibido,
    )

    assert resultado.consulta_vetorizada is True


async def test_a_adjacencia_e_simetrica(session: Any) -> None:
    """D8. As duas direcoes sao gravadas, e a simetria e teste e nao convencao.

    Sem isto, a consulta seria um OR sobre duas colunas -- e o caminho e
    quente, com o p95 de 400 ms da TEC-159 a cumprir.
    """
    linhas = (await session.execute(select(BairroAdjacente))).scalars().all()
    pares = {(linha.bairro_busca, linha.adjacente_busca) for linha in linhas}

    assert pares, "a migration 0021 devia ter semeado a tabela"
    faltando = {(b, a) for (a, b) in pares if (b, a) not in pares}
    assert faltando == set()


async def test_todo_nome_da_adjacencia_existe_no_catalogo_seed(session: Any) -> None:
    """D8. Sem FK -- nao existe entidade de bairro para referenciar --, entao a
    integridade e este teste. Nome errado na tabela falharia em silencio: o
    bairro nunca ampliaria, e ninguem veria erro nenhum.

    Os nomes esperados sao os 12 bairros do catalogo simulado
    (`data/seed/imoveis.csv`), na forma dobrada.
    """
    esperados = {
        dobrar(nome)
        for nome in (
            "Agronomica",
            "Balneario",
            "Campeche",
            "Canasvieiras",
            "Centro",
            "Coqueiros",
            "Estreito",
            "Itacorubi",
            "Jurere",
            "Lagoa da Conceicao",
            "Santo Antonio de Lisboa",
            "Trindade",
        )
    }

    linhas = (await session.execute(select(BairroAdjacente))).scalars().all()
    nomes = {linha.bairro_busca for linha in linhas} | {linha.adjacente_busca for linha in linhas}

    assert nomes <= esperados


async def test_a_adjacencia_guarda_os_quinze_pares(session: Any) -> None:
    """30 linhas: 15 pares nao ordenados, cada um nas duas direcoes."""
    linhas = (await session.execute(select(BairroAdjacente))).scalars().all()

    assert len(linhas) == 30


async def test_cenario_1_amplia_faixa_e_bairro_quando_nao_ha_resultado(session: Any) -> None:
    """Cenario 1 do Gherkin, com os numeros da card.

    "Dado o filtro de 3 quartos ate R$ 400.000 na Trindade, sem nenhum
    resultado, quando o relaxamento e aplicado, entao a busca e refeita com
    preco ate R$ 440.000 e bairros adjacentes."
    """
    vizinho = await _imovel(
        session, "AP-301", preco_venda=43000000, bairro="Agronomica", zona="CENTRO"
    )

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            preco_max_centavos=TETO,
            quartos_min=3,
            regioes=("trindade",),
        ),
    )

    assert resultado.relaxamento is EstadoDoRelaxamento.APLICADO
    assert [candidato.imovel_id for candidato in resultado.candidatos] == [vizinho]
    # As duas dimensoes cederam: o aviso vai ser a variante que diz as duas.
    assert (resultado.relaxou_preco, resultado.relaxou_bairro) == (True, True)


async def test_cenario_2_relaxamento_acontece_uma_unica_vez(session: Any) -> None:
    """Cenario 2: continua sem resultado depois de relaxar, e nao tenta de novo.

    A contagem de chamadas e a afirmacao: DUAS, nunca tres. A RN-09.3 poe "um"
    em negrito, e uma escada custaria ate tres consultas contra o p95 da
    TEC-159.
    """
    await _imovel(session, "AP-302", preco_venda=90000000, bairro="Jurere", zona="NORTE")

    chamadas = 0
    original = modulo_de_busca.buscar

    async def contando(*args: Any, **kwargs: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return await original(*args, **kwargs)

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
        buscar=contando,
    )

    assert chamadas == 2
    assert resultado.relaxamento is EstadoDoRelaxamento.SEM_RESULTADO
    assert resultado.candidatos == ()


async def test_cenario_3_busca_com_resultado_nao_e_relaxada(session: Any) -> None:
    """Cenario 3: quatro imoveis no filtro original, nenhum relaxamento."""
    for numero in range(4):
        await _imovel(session, f"AP-31{numero}", preco_venda=35000000)

    chamadas = 0
    original = modulo_de_busca.buscar

    async def contando(*args: Any, **kwargs: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return await original(*args, **kwargs)

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
        buscar=contando,
    )

    assert chamadas == 1
    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE
    assert len(resultado.candidatos) == 4


async def test_cenario_4_so_bairro_marcado_adjacente_entra(session: Any) -> None:
    """Cenario 4: a ampliacao se limita a tabela.

    Campeche NAO e adjacente a Trindade; Itacorubi e. O de Campeche fica fora
    mesmo cabendo no preco relaxado -- e o que separa "ampliar" de "desistir
    do filtro de regiao".
    """
    dentro = await _imovel(
        session, "AP-320", preco_venda=43000000, bairro="Itacorubi", zona="NORTE"
    )
    await _imovel(session, "AP-321", preco_venda=43000000, bairro="Campeche", zona="SUL")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [dentro]


async def test_o_bairro_pedido_continua_na_busca_relaxada(session: Any) -> None:
    """A leitura do "apenas" do cenario 4: uniao, nao substituicao.

    O imovel da Trindade nao cabia no teto duro e cabe no relaxado. Exclui-lo
    seria devolver o vizinho e esconder o bairro que o lead pediu.
    """
    na_trindade = await _imovel(session, "AP-322", preco_venda=43000000, bairro="Trindade")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [na_trindade]


async def test_nada_relaxavel_nao_faz_segunda_consulta(session: Any) -> None:
    """D5. Sem teto, sem piso e sem regiao, a segunda consulta seria identica."""
    await _imovel(session, "AP-330", quartos=2)

    chamadas = 0
    original = modulo_de_busca.buscar

    async def contando(*args: Any, **kwargs: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return await original(*args, **kwargs)

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, quartos_min=4),
        buscar=contando,
    )

    assert chamadas == 1
    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE


async def test_busca_por_zona_relaxa_preco_e_nao_amplia_bairro(session: Any) -> None:
    """L2. "zona sul" nao e nome de bairro e nao casa linha nenhuma da tabela.

    E a decisao correta -- a zona ja e o agregado de bairros --, mas e
    comportamento que alguem vai encontrar e achar que e bug.
    """
    no_sul = await _imovel(session, "AP-340", preco_venda=43000000, bairro="Campeche", zona="SUL")
    await _imovel(session, "AP-341", preco_venda=43000000, bairro="Centro", zona="CENTRO")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("zona sul",)),
    )

    assert resultado.relaxamento is EstadoDoRelaxamento.APLICADO
    assert [candidato.imovel_id for candidato in resultado.candidatos] == [no_sul]
    # So o preco cedeu -- e por isso o aviso nao pode ser uma constante fixa
    # que diga "inclui bairros vizinhos" (D11).
    assert (resultado.relaxou_preco, resultado.relaxou_bairro) == (True, False)


async def test_o_vetor_e_calculado_uma_vez_para_os_dois_passes(session: Any) -> None:
    """D9. Sem isto, todo turno relaxado paga duas chamadas ao provedor."""
    await _imovel(session, "AP-350", preco_venda=43000000, bairro="Agronomica", zona="CENTRO")

    chamadas = 0

    async def embedador(textos: list[str]) -> list[list[float]]:
        nonlocal chamadas
        chamadas += 1
        return [[0.0] * 1536]

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO, regioes=("trindade",)),
        consulta_texto="apartamento com varanda",
        embedador=embedador,
    )

    assert chamadas == 1
    assert resultado.relaxamento is EstadoDoRelaxamento.APLICADO


async def test_regiao_com_acento_e_maiuscula_amplia_o_bairro(session: Any) -> None:
    """A forma que a `porta_de_busca` REALMENTE monta, e nao o literal dobrado
    que todo outro teste deste arquivo escreve.

    `porta_de_busca` faz `tuple(str(regiao) for regiao in ...)` -- sem
    normalizar --, entao o que chega aqui e o que o modelo escreveu:
    "Agronomica" com maiuscula, e com acento quando o lead usou. A tabela de
    adjacencia guarda a forma dobrada. Sem dobrar antes do `IN`, ele nao casa
    linha nenhuma, `adjacentes` volta vazia e a METADE DE BAIRRO da RN-09.3
    fica morta em producao -- com a suite inteira verde, porque a suite
    inteira escreve `("trindade",)`.

    O imovel cabe no teto ORIGINAL: se ele voltar, foi a regiao que cedeu, e
    nao o preco.
    """
    vizinho = await _imovel(session, "AP-360", preco_venda=35000000, bairro="Trindade")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            preco_max_centavos=TETO,
            regioes=("Agronômica",),
        ),
    )

    assert resultado.relaxamento is EstadoDoRelaxamento.APLICADO
    assert [candidato.imovel_id for candidato in resultado.candidatos] == [vizinho]
    assert resultado.relaxou_bairro is True


async def _fecho_da_adjacencia(session: Any) -> tuple[str, ...]:
    """Todos os bairros da tabela -- o unico conjunto FECHADO que o seed tem.

    O grafo dos 15 pares e conexo, entao qualquer subconjunto proprio vaza
    para fora quando se pedem seus adjacentes. Derivar do banco em vez de
    escrever os 12 nomes a mao mantem o teste correto quando o seed crescer.
    """
    linhas = (await session.execute(select(BairroAdjacente))).scalars().all()
    return tuple(
        {linha.bairro_busca for linha in linhas} | {linha.adjacente_busca for linha in linhas}
    )


async def test_adjacente_que_o_lead_ja_pediu_nao_conta_como_bairro_ampliado(
    session: Any,
) -> None:
    """`relaxou_bairro` mede o que MUDOU, e nao o que a tabela devolveu.

    Pedindo o fecho inteiro da adjacencia, a consulta traz linha para todo
    bairro -- mas todo adjacente ja estava no pedido, e o `IN` do segundo
    passe e identico ao do primeiro. Um `bool(adjacentes)` diria True aqui, e
    o lead ouviria "inclui bairros vizinhos" sobre uma busca que nao incluiu
    vizinho nenhum: a mentira que as tres variantes do aviso existem para
    impedir.

    O preco cedeu de verdade, entao o segundo passe acontece e o aviso sai --
    na variante de preco, que e a verdadeira.
    """
    acima = await _imovel(session, "AP-361", preco_venda=43000000, bairro="Trindade")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            preco_max_centavos=TETO,
            regioes=await _fecho_da_adjacencia(session),
        ),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [acima]
    assert (resultado.relaxou_preco, resultado.relaxou_bairro) == (True, False)


async def test_regiao_sem_preco_e_sem_bairro_novo_nao_faz_segunda_consulta(
    session: Any,
) -> None:
    """`e_relaxavel` diz "talvez"; quem diz "nao" e o que `alargar` mudou.

    "zona sul" nao e nome de bairro (L2) e nao casa linha da adjacencia, e sem
    teto nem piso nao ha faixa para ceder. O segundo passe seria byte a byte o
    primeiro: uma consulta a mais contra o p95 de 400 ms da TEC-159, e um
    `SEM_RESULTADO` que faria o turno dizer ao lead que procurou alem do
    pedido sem ter procurado.
    """
    await _imovel(session, "AP-362", bairro="Centro", zona="CENTRO")

    chamadas = 0
    original = modulo_de_busca.buscar

    async def contando(*args: Any, **kwargs: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return await original(*args, **kwargs)

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, regioes=("zona norte",)),
        buscar=contando,
    )

    assert chamadas == 1
    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE
    assert resultado.candidatos == ()


async def test_bairro_excluido_nao_volta_pela_zona(session: Any) -> None:
    """D12. O filtro de zona casa o bairro excluido pelo outro lado do OR;
    so a condicao de exclusao, em AND, o segura."""
    aceito = await _imovel(session, "AP-370", preco_venda=35000000, bairro="Praia Mole", zona="SUL")
    await _imovel(session, "AP-371", preco_venda=35000000, bairro="Campeche", zona="SUL")

    resultado = await buscar(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            regioes=("zona sul",),
            bairros_excluidos=(dobrar("Campeche"),),
        ),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [aceito]


async def test_bairro_excluido_nao_volta_pelo_relaxamento(session: Any) -> None:
    """**D12, metade 1.** O relaxamento amplia para adjacentes, e o vizinho do
    bairro excluido pode ser o proprio excluido por outro caminho. Iniciativa
    nossa nao anula pedido do lead.

    Lagoa da Conceicao (par 0021) e adjacente tanto a Itacorubi quanto a
    Campeche. Excluindo Campeche, o segundo passe alarga a partir de Lagoa da
    Conceicao e o unico imovel que deve voltar e o de Itacorubi.
    """
    aceito = await _imovel(
        session, "AP-372", preco_venda=43000000, bairro="Itacorubi", zona="NORTE"
    )
    await _imovel(session, "AP-373", preco_venda=43000000, bairro="Campeche", zona="SUL")

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            preco_max_centavos=TETO,
            regioes=("lagoa da conceicao",),
            bairros_excluidos=(dobrar("Campeche"),),
        ),
    )

    assert resultado.relaxamento is EstadoDoRelaxamento.APLICADO
    assert [candidato.imovel_id for candidato in resultado.candidatos] == [aceito]


async def test_relaxou_bairro_e_falso_quando_o_unico_adjacente_era_excluido(
    session: Any,
) -> None:
    """**D12, metade 2.** Sem a subtracao em `alargar`, `relaxou_bairro` sairia
    True e o lead ouviria "inclui bairros vizinhos" tendo recebido zero bairro
    novo -- a mesma classe de mentira que a revisao final da TEC-160 pegou em
    `relaxou_bairro=bool(adjacentes)`.

    Campeche tem um vizinho so na tabela (Lagoa da Conceicao). Excluindo-o, o
    unico adjacente que a consulta devolveria some na subtracao, e o segundo
    passe nao tem bairro novo nenhum para oferecer.

    A exclusao chega aqui na forma que um chamador real produziria -- dobrada
    a partir de texto com maiuscula e acento, e nao ja digitada dobrada como o
    resto deste arquivo faz.
    """
    await _imovel(session, "AP-374", preco_venda=35000000, bairro="Lagoa da Conceicao")

    chamadas = 0
    original = modulo_de_busca.buscar

    async def contando(*args: Any, **kwargs: Any) -> Any:
        nonlocal chamadas
        chamadas += 1
        return await original(*args, **kwargs)

    resultado = await buscar_com_relaxamento(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            regioes=("campeche",),
            bairros_excluidos=(dobrar("Lagoa da Conceição"),),
        ),
        buscar=contando,
    )

    assert chamadas == 1
    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE
    assert resultado.candidatos == ()
    assert resultado.relaxou_bairro is False
