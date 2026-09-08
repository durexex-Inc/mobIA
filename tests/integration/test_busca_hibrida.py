"""A busca hibrida: filtro estruturado antes da similaridade.

TEC-158. Os quatro cenarios do Gherkin da card, mais o que o desenho
decidiu. Basename distinto de tudo em `tests/unit/`.

**A aderencia e afirmada AQUI, e nao em unitario.** Ela existe uma vez, como
expressao SQL -- estes testes medem o `score` que a consulta devolve, que e o
numero que de fato ordena.
"""

import uuid
from typing import Any

from conftest import EmbedadorFake

from mobia.domain.catalogo.busca import buscar
from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import FiltroDeBusca
from mobia.domain.texto import dobrar

TETO = 60000000  # R$ 600.000,00 em centavos


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Um imovel completo e valido, com sobrescrita por campo.

    Molde do `_imovel` de `test_indexacao_do_catalogo.py`, mais
    `bairro_busca`, que a `0019` tornou NOT NULL.
    """
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Vila Mariana",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 50000000,
        "bairro": "Vila Mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "zona": "SUL",
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
    # Derivada, como no repositorio: o teste nao pode inventar uma dobra
    # diferente da que o codigo de producao grava.
    campos.setdefault("bairro_busca", dobrar(str(campos["bairro"])))
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def test_o_filtro_estruturado_e_respeitado_a_risca(session: Any) -> None:
    """Cenario 1 do Gherkin, e a CA-09.1.

    Tres imoveis que NAO deveriam voltar, um por dimensao: preco acima do
    teto, quartos abaixo do minimo, zona errada.
    """
    dentro = await _imovel(session, "AP-001", preco_venda=55000000, quartos=2, zona="SUL")
    await _imovel(session, "AP-002", preco_venda=70000000, quartos=2, zona="SUL")
    await _imovel(session, "AP-003", preco_venda=55000000, quartos=1, zona="SUL")
    await _imovel(
        session, "AP-004", preco_venda=55000000, quartos=2, zona="NORTE", bairro="Santana"
    )

    resultado = await buscar(
        session,
        FiltroDeBusca(
            operacao=Operacao.VENDA,
            preco_max_centavos=TETO,
            quartos_min=2,
            regioes=("zona sul",),
        ),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [dentro]
    for candidato in resultado.candidatos:
        assert candidato.preco_centavos <= TETO
        assert candidato.quartos >= 2


async def test_imovel_vendido_nao_aparece_e_continua_no_banco(session: Any) -> None:
    """Cenario 2 do Gherkin, RN-08.4 e CA-08.2.

    As DUAS assercoes, porque a regra tem duas metades e um DELETE passaria
    na primeira: "excluido dos resultados de busca, mas mantido no banco para
    historico".
    """
    vendido = await _imovel(session, "AP-010", status=StatusImovel.VENDIDO.value)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert resultado.candidatos == ()
    assert await session.get(Imovel, vendido) is not None


async def test_no_maximo_dez_candidatos_e_o_total_conta_antes_do_teto(session: Any) -> None:
    """Cenario 3 do Gherkin e RN-09.2.

    Quarenta imoveis que casam. O `total_candidatos` dizer 40 e o que prova
    que a contagem e antes do LIMIT -- com um COUNT depois do teto ele diria
    10, e o agente nunca saberia que havia mais.
    """
    for numero in range(40):
        await _imovel(session, f"AP-{numero:03d}")

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert len(resultado.candidatos) == 10
    assert resultado.total_candidatos == 40


async def test_o_candidato_traz_identificador_e_preco_do_banco(session: Any) -> None:
    """Cenario 4 do Gherkin e RN-09.4."""
    identificador = await _imovel(session, "AP-020", preco_venda=58000000)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert len(resultado.candidatos) == 1
    candidato = resultado.candidatos[0]
    assert candidato.imovel_id == identificador
    assert candidato.preco_centavos == 58000000
    assert candidato.codigo == "AP-020"


async def test_imovel_de_ambas_as_operacoes_entra_na_busca_de_venda(session: Any) -> None:
    """`IN (operacao, 'AMBOS')`, e nao igualdade crua. D2."""
    ambos = await _imovel(session, "AP-030", operacao=Operacao.AMBOS.value, preco_aluguel=300000)
    await _imovel(
        session, "AP-031", operacao=Operacao.ALUGUEL.value, preco_venda=None, preco_aluguel=300000
    )

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [ambos]


async def test_a_busca_de_aluguel_compara_o_preco_de_aluguel(session: Any) -> None:
    """A falha que a D2 recusou, virada teste.

    O mesmo imovel: R$ 580.000 de venda e R$ 3.000 de aluguel. Numa faixa de
    "ate R$ 4.000" de aluguel ele entra; numa de "ate R$ 600.000" de aluguel
    ele tambem entraria por acidente se a comparacao fosse contra o preco de
    venda -- por isso a assercao de baixo usa um teto de aluguel APERTADO, que
    so o preco certo satisfaz.
    """
    await _imovel(
        session, "AP-040", operacao=Operacao.AMBOS.value, preco_venda=58000000, preco_aluguel=300000
    )

    cabe = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.ALUGUEL, preco_max_centavos=400000),
    )
    assert len(cabe.candidatos) == 1
    assert cabe.candidatos[0].preco_centavos == 300000

    nao_cabe = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.ALUGUEL, preco_max_centavos=200000),
    )
    assert nao_cabe.candidatos == ()


async def test_centro_casa_a_zona_e_o_bairro(session: Any) -> None:
    """O caso que fez a D4 recusar classificacao.

    Duas linhas: uma na zona CENTRO com outro bairro, outra no bairro
    "Centro" com outra zona. O OR devolve as duas -- classificar o texto
    devolveria uma e erraria a outra, em silencio.
    """
    por_zona = await _imovel(session, "AP-050", zona="CENTRO", bairro="Se")
    por_bairro = await _imovel(session, "AP-051", zona="OESTE", bairro="Centro")

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA, regioes=("centro",)))

    assert {candidato.imovel_id for candidato in resultado.candidatos} == {
        por_zona,
        por_bairro,
    }


async def test_bairro_acentuado_casa_a_fala_dobrada_do_lead(session: Any) -> None:
    """D5. O lead digita "aclimacao"; o arquivo trouxe "Aclimacao" com til."""
    identificador = await _imovel(session, "AP-060", bairro="Aclimação", zona=None)

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, regioes=("aclimacao",))
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [identificador]


async def test_a_aderencia_vale_um_no_teto_e_meio_na_metade(session: Any) -> None:
    """Os valores da D7, medidos no `score` que a consulta devolve.

    Sem vetor de consulta a similaridade vale 0 para todos, entao o score e
    exatamente `0,4 x aderencia` -- o que torna a aderencia observavel sem
    uma funcao Python gemea que a duplicasse.
    """
    no_teto = await _imovel(session, "AP-070", preco_venda=TETO)
    na_metade = await _imovel(session, "AP-071", preco_venda=TETO // 2)

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=TETO)
    )

    por_id = {candidato.imovel_id: candidato.score for candidato in resultado.candidatos}
    assert por_id[no_teto] == 0.4
    assert por_id[na_metade] == 0.2
    # E a ordem que a D7 declara: o mais caro que cabe vem primeiro.
    assert resultado.candidatos[0].imovel_id == no_teto


async def test_sem_teto_de_preco_a_aderencia_para_de_discriminar(session: Any) -> None:
    """D7. O termo vira a constante 1, e o score de todos e o mesmo."""
    await _imovel(session, "AP-080", preco_venda=10000000)
    await _imovel(session, "AP-081", preco_venda=90000000)

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert {candidato.score for candidato in resultado.candidatos} == {0.4}


async def test_a_ordem_entre_scores_empatados_e_estavel(session: Any) -> None:
    """D1. Sem o desempate por `id` isto seria flake plantado a mao."""
    for numero in range(5):
        await _imovel(session, f"AP-09{numero}", preco_venda=50000000)

    primeira = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))
    segunda = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA))

    assert [candidato.imovel_id for candidato in primeira.candidatos] == [
        candidato.imovel_id for candidato in segunda.candidatos
    ]


async def test_o_filtro_de_tipo_e_o_de_vagas(session: Any) -> None:
    """As duas dimensoes da RN-09.1 que os cenarios do Gherkin nao exercitam."""
    casa_com_duas = await _imovel(session, "CA-001", tipo=TipoImovel.CASA.value, vagas=2)
    await _imovel(session, "CA-002", tipo=TipoImovel.CASA.value, vagas=1)
    await _imovel(session, "AP-100", tipo=TipoImovel.APARTAMENTO.value, vagas=2)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA, tipo=TipoImovel.CASA, vagas_min=2),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [casa_com_duas]


async def test_limite_acima_do_teto_e_preso_em_dez(session: Any) -> None:
    """RN-09.2 e D10: quem chama por dentro nao escapa do teto."""
    for numero in range(12):
        await _imovel(session, f"AP-11{numero}")

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA), limite=50)

    assert len(resultado.candidatos) == 10


async def test_zero_resultados_devolve_vazio_e_nao_levanta(session: Any) -> None:
    """A porta que a TEC-160 vai abrir. Vazio nao e erro."""
    await _imovel(session, "AP-120", preco_venda=90000000)

    resultado = await buscar(
        session, FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=1000000)
    )

    assert resultado.candidatos == ()
    assert resultado.total_candidatos == 0


async def test_imovel_sem_vetor_entra_e_ordena_atras(session: Any) -> None:
    """D8. Falta de vetor nunca exclui ninguem.

    A alternativa literal -- so imovel com vetor e candidato -- foi recusada
    porque o proprio aviso da TEC-157 descreve o desfecho: "o catalogo fica
    sem vetor e a busca semantica devolve vazio". Um ambiente sem chave
    responderia "nao ha imoveis" para um catalogo de 500.

    Os dois imoveis tem o MESMO preco, entao a aderencia empata e a ordem sai
    inteira da similaridade.
    """
    com_vetor = await _imovel(session, "AP-200", embedding=[0.1] * 1536)
    sem_vetor = await _imovel(session, "AP-201")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        embedador=EmbedadorFake(),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [
        com_vetor,
        sem_vetor,
    ]
    assert resultado.consulta_vetorizada is True
    assert resultado.candidatos_sem_vetor == 1


async def test_provedor_caido_devolve_candidatos_filtrados_e_nao_erro(session: Any) -> None:
    """A assercao que a D9 tornou necessaria.

    A TEC-157 derivava de TOPOLOGIA a regra "falha de embedding nao bloqueia
    o atendimento" -- nao havia caminho em que o turno chamasse o provedor.
    Esta card criou o caminho, entao a regra passou a precisar de teste. Sem
    esta assercao, um `raise` no lugar do `except` de `_vetor_da_consulta`
    deixaria a suite verde e o atendimento parado.
    """
    identificador = await _imovel(session, "AP-210")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        embedador=EmbedadorFake(falhar=True),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [identificador]
    assert resultado.consulta_vetorizada is False


async def test_busca_sem_texto_nao_chama_o_provedor(session: Any) -> None:
    """D8. Criterio estruturado sozinho nao paga uma requisicao.

    A assercao e sobre a CHAMADA e nao sobre o desfecho: um embedador chamado
    e descartado devolveria os mesmos candidatos, gastando dinheiro e
    latencia em todo turno.
    """
    await _imovel(session, "AP-220")
    embedador = EmbedadorFake()

    resultado = await buscar(session, FiltroDeBusca(operacao=Operacao.VENDA), embedador=embedador)

    assert embedador.chamadas == []
    assert resultado.consulta_vetorizada is False
    assert len(resultado.candidatos) == 1


async def test_sem_embedador_injetado_a_busca_segue(session: Any) -> None:
    """O default do parametro nao pode ser um caminho que levanta."""
    await _imovel(session, "AP-230")

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
    )

    assert len(resultado.candidatos) == 1
    assert resultado.consulta_vetorizada is False


async def test_sem_teto_a_ordem_e_a_similaridade_pura(session: Any) -> None:
    """D7, a outra metade: sem teto o termo de aderencia empata em 1.

    Os dois imoveis tem precos muito diferentes -- R$ 100 mil e R$ 900 mil --,
    e a ordem NAO os segue: o barato vem primeiro porque o vetor dele casa a
    consulta. E o que prova que 0,6 da ordenacao e da similaridade, e nao um
    termo decorativo ao lado do preco.

    O vetor de soma zero da similaridade exatamente 0 contra o vetor constante
    do falso; o constante da exatamente 1. Ver a nota do Step 1.
    """
    parecido = await _imovel(session, "AP-240", preco_venda=10000000, embedding=[0.1] * 1536)
    diferente = await _imovel(session, "AP-241", preco_venda=90000000, embedding=[0.1, -0.1] * 768)

    resultado = await buscar(
        session,
        FiltroDeBusca(operacao=Operacao.VENDA),
        consulta_texto="apartamento com varanda",
        embedador=EmbedadorFake(),
    )

    assert [candidato.imovel_id for candidato in resultado.candidatos] == [
        parecido,
        diferente,
    ]
    por_id = {candidato.imovel_id: candidato.score for candidato in resultado.candidatos}
    assert por_id[parecido] == 1.0
    assert por_id[diferente] == 0.4
