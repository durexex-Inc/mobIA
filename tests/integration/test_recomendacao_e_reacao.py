"""A recomendacao e a reacao do lead, contra o banco.

TEC-163. Os quatro cenarios do Gherkin da card, mais o que o desenho decidiu.
Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.agente.ferramenta_de_busca import porta_de_busca
from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.recomendacao import DescartePorBairro
from mobia.domain.agente.repositorio import (
    _TABELA_IMOVEIS,
    gravar_reacoes,
    gravar_recomendacoes,
    ler_descartes_por_distancia,
    ler_pendentes,
)
from mobia.domain.agente.schemas import (
    CategoriaDescarte,
    Extracao,
    Intencao,
    PerguntaDeDesambiguacao,
    ReacaoDoImovel,
    ReacaoLead,
    ReacoesDoTurno,
    RespostaDoAgente,
)
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import ResultadoDaBusca
from mobia.domain.texto import dobrar

CANAL = "whatsapp"
CONVERSA = "5548999990000"


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Um imovel completo e valido, com sobrescrita por campo.

    Molde do `_imovel` de `tests/integration/test_relaxamento_busca.py`.
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


async def _recomendar(session: Any, imovel_id: uuid.UUID, **sobrescritas: object) -> None:
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "imovel_id": imovel_id,
        "score_match": 0.870,
        "motivo_match": "3 quartos, Trindade, dentro do teto",
        "apresentado_em": datetime.now(UTC),
    }
    campos.update(sobrescritas)
    session.add(Recomendacao(**campos))
    await session.commit()


async def test_a_recomendacao_nasce_sem_reacao(session: Any) -> None:
    """D8: linha pendente e o gatilho da chamada de reacao."""
    imovel = await _imovel(session, "AP-401")

    await _recomendar(session, imovel)

    linha = (await session.execute(select(Recomendacao))).scalars().one()
    assert linha.reacao_lead is None
    assert linha.motivo_descarte is None


async def test_o_mesmo_imovel_nao_entra_duas_vezes_na_conversa(session: Any) -> None:
    """D3: o cenario 4 do Gherkin vira garantia de schema.

    "Os ja apresentados nao sao repetidos" deixa de depender de disciplina de
    consulta -- o banco recusa.
    """
    imovel = await _imovel(session, "AP-402")
    await _recomendar(session, imovel)

    with pytest.raises(IntegrityError):
        await _recomendar(session, imovel)


async def test_o_mesmo_imovel_entra_em_conversas_diferentes(session: Any) -> None:
    """O UNIQUE e por conversa: outro lead pode ver o mesmo imovel."""
    imovel = await _imovel(session, "AP-403")
    await _recomendar(session, imovel)

    await _recomendar(session, imovel, conversation_key="5548999991111")

    linhas = (await session.execute(select(Recomendacao))).scalars().all()
    assert len(linhas) == 2


async def test_a_reacao_e_a_categoria_gravam(session: Any) -> None:
    """D13: `motivo_descarte` guarda a CATEGORIA, nao a frase do lead."""
    imovel = await _imovel(session, "AP-404")

    await _recomendar(
        session,
        imovel,
        reacao_lead=ReacaoLead.DESCARTE.value,
        motivo_descarte=CategoriaDescarte.DISTANCIA.value,
    )

    linha = (await session.execute(select(Recomendacao))).scalars().one()
    assert linha.reacao_lead == "DESCARTE"
    assert linha.motivo_descarte == "DISTANCIA"


async def test_cenario_2_a_recomendacao_registra_motivo_e_momento(
    session: Any, session_factory: Any
) -> None:
    """Cenario 2 do Gherkin: "ela registra o motivo do match e o momento"."""
    imovel = await _imovel(session, "AP-410")
    agora = datetime.now(UTC)

    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=[{"imovel_id": str(imovel)}],
        scores={imovel: 0.87},
        criterios=["3 quartos", "Trindade"],
        agora=agora,
    )

    linha = (await session.execute(select(Recomendacao))).scalars().one()
    assert linha.motivo_match == "3 quartos, Trindade"
    assert linha.apresentado_em == agora
    assert float(linha.score_match) == 0.87


async def test_gravar_duas_vezes_o_mesmo_imovel_nao_levanta(
    session: Any, session_factory: Any
) -> None:
    """A reapresentacao acontece: o lead pede "mostra de novo aquele".

    O UNIQUE existe para impedir DUPLICATA, nao para derrubar o turno. Gravar
    de novo e no-op -- a linha original, com a reacao que ja tiver, sobrevive.
    """
    imovel = await _imovel(session, "AP-411")
    candidatos = [{"imovel_id": str(imovel)}]
    scores = {imovel: 0.87}

    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=candidatos,
        scores=scores,
        criterios=["Trindade"],
        agora=datetime.now(UTC),
    )
    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=candidatos,
        scores=scores,
        criterios=["Trindade"],
        agora=datetime.now(UTC),
    )

    linhas = (await session.execute(select(Recomendacao))).scalars().all()
    assert len(linhas) == 1


async def test_candidato_sem_score_ainda_grava_linha_com_zero(
    session: Any, session_factory: Any
) -> None:
    """RN-10.3 nao tem clausula de excecao: toda apresentacao vira linha.

    Ruling do round 1 de review: um candidato ausente de `scores` NAO fica de
    fora -- a linha faltando quebraria o UNIQUE (cenario 4 do Gherkin), o
    gatilho `reacao_lead IS NULL` da Task 5 e a medida de conversao. `0.0` e
    gravado como marca de bug (nunca deveria acontecer, ver docstring de
    `gravar_recomendacoes`), alto o bastante para saltar aos olhos em
    qualquer consulta -- ao contrario da linha que faltava antes. O outro
    candidato da mesma chamada, que TEM score, grava com o score real.
    """
    com_score = await _imovel(session, "AP-412")
    sem_score = await _imovel(session, "AP-413")

    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=[{"imovel_id": str(com_score)}, {"imovel_id": str(sem_score)}],
        scores={com_score: 0.5},
        criterios=["Trindade"],
        agora=datetime.now(UTC),
    )

    linhas = {
        linha.imovel_id: linha
        for linha in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert linhas.keys() == {com_score, sem_score}
    assert float(linhas[com_score].score_match) == 0.5
    assert float(linhas[sem_score].score_match) == 0.0


async def test_lista_de_candidatos_vazia_nao_grava_nada(session: Any, session_factory: Any) -> None:
    """Sem candidato nenhum, `gravar_recomendacoes` e no-op -- nao ha o que gravar."""
    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=[],
        scores={},
        criterios=[],
        agora=datetime.now(UTC),
    )

    linhas = (await session.execute(select(Recomendacao))).scalars().all()
    assert linhas == []


async def test_ler_pendentes_devolve_so_as_sem_reacao_desta_conversa(
    session: Any, session_factory: Any
) -> None:
    """`ler_pendentes` filtra por `reacao_lead IS NULL` E pelo par (channel, conversa).

    Tres linhas plantadas, tres motivos de exclusao diferentes: uma ja tem
    reacao, outra e de OUTRA conversa. So a pendente desta conversa volta.
    """
    pendente = await _imovel(session, "AP-530", titulo="Casa Pendente", bairro="Centro")
    ja_reagida = await _imovel(session, "AP-531")
    de_outra_conversa = await _imovel(session, "AP-532")

    await _recomendar(session, pendente)
    await _recomendar(session, ja_reagida, reacao_lead=ReacaoLead.INTERESSE.value)
    await _recomendar(session, de_outra_conversa, conversation_key="5548999992222")

    resultado = await ler_pendentes(session_factory, channel=CANAL, conversation_key=CONVERSA)

    assert [linha.imovel_id for linha in resultado] == [pendente]
    assert resultado[0].titulo == "Casa Pendente"
    assert resultado[0].bairro == "Centro"


async def test_ler_pendentes_ordena_por_apresentado_em(session: Any, session_factory: Any) -> None:
    """A ordem devolvida e a ordem de apresentacao, nao a ordem de insercao.

    D7: "o segundo" e o segundo APRESENTADO. Os tres sao gravados fora de
    ordem cronologica de proposito, para a asssercao nao passar por acidente
    de ordem de insercao coincidir com `apresentado_em`.
    """
    agora = datetime.now(UTC)
    primeiro = await _imovel(session, "AP-540")
    segundo = await _imovel(session, "AP-541")
    terceiro = await _imovel(session, "AP-542")

    await _recomendar(session, terceiro, apresentado_em=agora + timedelta(seconds=2))
    await _recomendar(session, primeiro, apresentado_em=agora)
    await _recomendar(session, segundo, apresentado_em=agora + timedelta(seconds=1))

    resultado = await ler_pendentes(session_factory, channel=CANAL, conversation_key=CONVERSA)

    assert [linha.imovel_id for linha in resultado] == [primeiro, segundo, terceiro]


async def test_ler_pendentes_desempata_por_score_quando_apresentado_em_empata(
    session: Any, session_factory: Any
) -> None:
    """Duas linhas da MESMA apresentacao empatam em `apresentado_em` por construcao.

    `gravar_recomendacoes` grava o lote inteiro com um unico `agora` -- ver o
    docstring de `ler_pendentes`. O desempate e `score_match DESC`, a mesma
    ordem que `buscar` usa para gerar a lista de candidatos, entao o de score
    mais alto tem de voltar primeiro mesmo tendo sido gravado depois.
    """
    mesmo_instante = datetime.now(UTC)
    score_baixo = await _imovel(session, "AP-550")
    score_alto = await _imovel(session, "AP-551")

    await _recomendar(session, score_baixo, apresentado_em=mesmo_instante, score_match=0.500)
    await _recomendar(session, score_alto, apresentado_em=mesmo_instante, score_match=0.900)

    resultado = await ler_pendentes(session_factory, channel=CANAL, conversation_key=CONVERSA)

    assert [linha.imovel_id for linha in resultado] == [score_alto, score_baixo]


async def test_gravar_reacoes_grava_reacao_e_categoria(session: Any, session_factory: Any) -> None:
    """A reacao e a categoria de cada imovel resolvido gravam na linha certa."""
    interessou = await _imovel(session, "AP-560")
    descartou = await _imovel(session, "AP-561")
    await _recomendar(session, interessou)
    await _recomendar(session, descartou)

    resolvidas = (
        (interessou, ReacaoDoImovel(ordinal=1, reacao=ReacaoLead.INTERESSE)),
        (
            descartou,
            ReacaoDoImovel(
                ordinal=2, reacao=ReacaoLead.DESCARTE, categoria=CategoriaDescarte.PRECO
            ),
        ),
    )
    await gravar_reacoes(
        session_factory, channel=CANAL, conversation_key=CONVERSA, resolvidas=resolvidas
    )

    linhas = {
        linha.imovel_id: linha
        for linha in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert linhas[interessou].reacao_lead == "INTERESSE"
    assert linhas[interessou].motivo_descarte is None
    assert linhas[descartou].reacao_lead == "DESCARTE"
    assert linhas[descartou].motivo_descarte == "PRECO"


async def test_gravar_reacoes_fecha_pendentes_nao_mencionadas_como_neutro(
    session: Any, session_factory: Any
) -> None:
    """D8: a pendente que o lead nao mencionou fecha como NEUTRO, nunca fica NULL.

    Sem isto, a proxima mensagem do lead ainda encontraria linha com
    `reacao_lead IS NULL` e pagaria uma chamada de reacao de novo pelo MESMO
    imovel -- a garantia de "no maximo uma chamada por apresentacao" depende
    disto.
    """
    mencionado = await _imovel(session, "AP-570")
    esquecido = await _imovel(session, "AP-571")
    await _recomendar(session, mencionado)
    await _recomendar(session, esquecido)

    resolvidas = ((mencionado, ReacaoDoImovel(ordinal=1, reacao=ReacaoLead.INTERESSE)),)
    await gravar_reacoes(
        session_factory, channel=CANAL, conversation_key=CONVERSA, resolvidas=resolvidas
    )

    linhas = {
        linha.imovel_id: linha
        for linha in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert linhas[mencionado].reacao_lead == "INTERESSE"
    assert linhas[esquecido].reacao_lead == "NEUTRO"


def test_a_tabela_sombra_ainda_bate_com_as_colunas_de_imovel() -> None:
    """`_TABELA_IMOVEIS` e uma SEGUNDA definicao do formato de `imoveis`, de proposito.

    `repositorio.py` declara essa Core table em vez de importar `Imovel`
    porque `ferramenta_de_busca.py` reserva para si ser "o unico arquivo em
    que domain/agente toca domain/catalogo" -- um import aqui tornaria essa
    frase falsa. O preco desse desvio e nao ter mais uma unica fonte para o
    formato de `imoveis`: se alguem renomear `id`, `titulo`, `bairro` ou
    `bairro_busca` em `Imovel`, nada falha em import nem em mypy, porque
    `_TABELA_IMOVEIS` nao referencia `Imovel` nenhum -- o JOIN de
    `ler_pendentes` ou `ler_descartes_por_distancia` so quebraria em tempo de
    consulta, em producao. E o mesmo risco que `COLUNA_DE_PRECO`
    (`catalogo/schemas.py`) existe para fechar do lado do preco; aqui, este
    teste e a guarda: ele roda no arquivo de teste, que ja importa `Imovel`
    porque a fronteira de `ferramenta_de_busca.py` e sobre `src/`, nao sobre
    `tests/`.
    """
    colunas_de_imovel = Imovel.__table__.columns
    for nome in ("id", "titulo", "bairro", "bairro_busca"):
        assert nome in colunas_de_imovel, (
            f"'{nome}' sumiu de Imovel.__table__.columns -- _TABELA_IMOVEIS em "
            "repositorio.py ainda a nomeia, e a consulta que a usa quebraria em consulta"
        )
    assert set(_TABELA_IMOVEIS.columns.keys()) == {"id", "titulo", "bairro", "bairro_busca"}


# ---------------------------------------------------------------------------
# Task 9: a consulta de exclusao, ligada ao filtro. RN-10.4, D11-D14.
# ---------------------------------------------------------------------------


async def test_ler_descartes_por_distancia_le_bairro_dobrado_e_categoria(
    session: Any, session_factory: Any
) -> None:
    """A consulta le TODO descarte da conversa -- de qualquer categoria,
    inclusive sem nenhuma -- e devolve o bairro na forma dobrada que
    `FiltroDeBusca.bairros_excluidos` compara. Quem filtra por DISTANCIA e
    `bairros_a_excluir`, nao esta consulta."""
    com_categoria = await _imovel(session, "AP-730", bairro="Trindade")
    sem_categoria = await _imovel(session, "AP-731", bairro="Itacorubi")
    nao_descartado = await _imovel(session, "AP-732", bairro="Centro")
    de_outra_conversa = await _imovel(session, "AP-733", bairro="Campeche")

    await _recomendar(
        session,
        com_categoria,
        reacao_lead=ReacaoLead.DESCARTE.value,
        motivo_descarte=CategoriaDescarte.DISTANCIA.value,
    )
    await _recomendar(session, sem_categoria, reacao_lead=ReacaoLead.DESCARTE.value)
    await _recomendar(session, nao_descartado, reacao_lead=ReacaoLead.INTERESSE.value)
    await _recomendar(
        session,
        de_outra_conversa,
        conversation_key="5548999993333",
        reacao_lead=ReacaoLead.DESCARTE.value,
        motivo_descarte=CategoriaDescarte.DISTANCIA.value,
    )

    resultado = await ler_descartes_por_distancia(
        session_factory, channel=CANAL, conversation_key=CONVERSA
    )

    assert set(resultado) == {
        DescartePorBairro(bairro="trindade", categoria=CategoriaDescarte.DISTANCIA),
        DescartePorBairro(bairro="itacorubi", categoria=None),
    }


class _BuscaEspia:
    """Substitui `buscar`: guarda o filtro recebido, sem candidato nenhum.

    Molde de `_BuscaEspia` de `tests/unit/test_ferramenta_de_busca.py` -- o
    assunto aqui e o QUE ENTRA no filtro (`bairros_excluidos`), nao o que a
    busca devolve.
    """

    def __init__(self) -> None:
        self.filtros: list[Any] = []

    async def __call__(
        self, session: Any, filtro: Any, consulta_texto: str | None = None, **_: object
    ) -> ResultadoDaBusca:
        self.filtros.append(filtro)
        return ResultadoDaBusca(candidatos=(), total_candidatos=0, consulta_vetorizada=False)


async def test_um_descarte_nao_exclui_da_busca_seguinte(session: Any, session_factory: Any) -> None:
    """A ligacao inteira (porta_de_busca -> ler_descartes_por_distancia ->
    bairros_a_excluir -> FiltroDeBusca) com um descarte so: abaixo do limiar,
    nada entra em `bairros_excluidos`."""
    imovel = await _imovel(session, "AP-740", bairro="Campeche")
    await _recomendar(
        session,
        imovel,
        reacao_lead=ReacaoLead.DESCARTE.value,
        motivo_descarte=CategoriaDescarte.DISTANCIA.value,
    )

    espia = _BuscaEspia()
    porta = porta_de_busca(session_factory, buscar=espia, channel=CANAL, conversation_key=CONVERSA)

    await porta({"operacao": "VENDA"})

    assert espia.filtros[0].bairros_excluidos == ()


async def test_dois_descartes_por_distancia_excluem_bairro_da_busca_seguinte(
    session: Any, session_factory: Any
) -> None:
    """`ferramenta_de_busca.py` e o UNICO lugar que consulta a recomendacao e
    poe o resultado no filtro (D11-D13) -- a busca continua sem saber que
    recomendacao existe."""
    primeiro = await _imovel(session, "AP-741", bairro="Campeche")
    segundo = await _imovel(session, "AP-742", bairro="Campeche")
    for imovel in (primeiro, segundo):
        await _recomendar(
            session,
            imovel,
            reacao_lead=ReacaoLead.DESCARTE.value,
            motivo_descarte=CategoriaDescarte.DISTANCIA.value,
        )

    espia = _BuscaEspia()
    porta = porta_de_busca(session_factory, buscar=espia, channel=CANAL, conversation_key=CONVERSA)

    await porta({"operacao": "VENDA"})

    assert espia.filtros[0].bairros_excluidos == ("campeche",)


async def test_conversa_sem_identidade_nao_ativa_a_exclusao(
    session: Any, session_factory: Any
) -> None:
    """`channel`/`conversation_key` default `None` -- quem chama `porta_de_busca`
    sem conversa (como os testes de `test_ferramenta_de_busca.py`) continua
    tendo a busca de sempre, sem exclusao nenhuma."""
    primeiro = await _imovel(session, "AP-743", bairro="Campeche")
    segundo = await _imovel(session, "AP-744", bairro="Campeche")
    for imovel in (primeiro, segundo):
        await _recomendar(
            session,
            imovel,
            reacao_lead=ReacaoLead.DESCARTE.value,
            motivo_descarte=CategoriaDescarte.DISTANCIA.value,
        )

    espia = _BuscaEspia()
    porta = porta_de_busca(session_factory, buscar=espia)

    await porta({"operacao": "VENDA"})

    assert espia.filtros[0].bairros_excluidos == ()


async def test_lead_nomeia_bairro_excluido_tira_da_exclusao_neste_turno(
    session: Any, session_factory: Any
) -> None:
    """D14: nomear vence inferir. Exclusao e inferencia nossa (duas
    rejeicoes); o lead dizendo o nome do bairro NESTE turno e declaracao, e
    declaracao vence.

    `"CORREGO GRANDE"` cru, maiusculo -- o caminho de um lead de verdade, e
    nao um literal ja dobrado --, tem de bater contra o excluido que
    `ler_descartes_por_distancia` devolve dobrado. Comparar um lado dobrado
    contra o outro cru foi o defeito exato que a TEC-160 pagou com um
    Critical.
    """
    primeiro = await _imovel(session, "AP-745", bairro="Corrego Grande")
    segundo = await _imovel(session, "AP-746", bairro="Corrego Grande")
    for imovel in (primeiro, segundo):
        await _recomendar(
            session,
            imovel,
            reacao_lead=ReacaoLead.DESCARTE.value,
            motivo_descarte=CategoriaDescarte.DISTANCIA.value,
        )

    espia = _BuscaEspia()
    porta = porta_de_busca(session_factory, buscar=espia, channel=CANAL, conversation_key=CONVERSA)

    await porta({"operacao": "VENDA", "regioes": ["CORREGO GRANDE"]})

    assert espia.filtros[0].bairros_excluidos == ()
    # A regiao nomeada ainda entra no filtro normalmente -- D14 tira SO da
    # exclusao, a busca por aquele bairro continua acontecendo.
    assert espia.filtros[0].regioes == ("CORREGO GRANDE",)


# ---------------------------------------------------------------------------
# Task 7: a reacao ligada no turno, antes da busca. D9.
# ---------------------------------------------------------------------------


def _conversa_do_turno() -> str:
    """A conversation_key que `rodar_turno`/`_entrada_do_lead` de fato usa.

    Distinta de `CONVERSA` (a constante deste arquivo, usada pelos testes
    acima que escrevem `Recomendacao` direto): os testes que rodam o TURNO
    inteiro semeiam a mensagem do lead com `_entrada_do_lead`
    (`tests/conftest.py`), que fixa `conversation_key=CONVERSA_AGENTE` --
    um valor diferente do `CONVERSA` deste modulo. As `Recomendacao` que
    estes testes plantam tem de usar a MESMA chave que o turno vai usar, ou
    `ler_pendentes` nao encontra nenhuma pendente e `reagir` nunca e chamado.
    """
    from conftest import CONVERSA_AGENTE  # type: ignore[import-not-found]

    return CONVERSA_AGENTE


async def _conversa_ja_existe(session: Any) -> None:
    """Semeia uma entrada anterior para `e_conversa_nova` ver a conversa como
    NAO nova. Copia de `test_apresentacao_no_turno.py`: identificacao tem
    arquivo proprio, e sem isto a mensagem extra de identificacao
    contaminaria a comparacao do texto entregue nestes testes, que nao sao
    sobre ela.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


class _ClassificadorDeReacao:
    """Fake minimo para a Task 7: separa a reacao (chamada 3) da classificacao
    (chamada 1) do turno, sem candidato nenhum.

    Molde de `_ClassificadorComCandidatos`
    (`tests/integration/test_apresentacao_no_turno.py`), reduzido ao que estes
    testes precisam -- o assunto aqui e a ORDEM entre `reagir` e a busca deste
    turno, nao a apresentacao das fichas, entao `classificar` nunca devolve
    candidato.
    """

    def __init__(
        self,
        reacoes: tuple[ReacaoDoImovel, ...] = (),
        *,
        erro_ao_reagir: Exception | None = None,
        resposta: str = "Beleza, deixa eu ver.",
    ) -> None:
        self.reacoes = reacoes
        self.erro_ao_reagir = erro_ao_reagir
        self.resposta = resposta
        # Capturado para o cenario 1 conferir o que `reagir` de fato recebeu
        # -- a prova de que `apresentados` e os ids resolvidos vem da mesma
        # ordem.
        self.apresentados_recebidos: list[str] | None = None

    async def classificar(self, contexto: Any, *, porta: Any = None) -> RespostaDoAgente:
        return RespostaDoAgente(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            resposta=self.resposta,
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=Extracao(),
        )

    async def desambiguar(self, contexto: Any) -> PerguntaDeDesambiguacao:
        raise AssertionError("confianca alta o bastante para nao desambiguar")

    async def reagir(self, contexto: Any, *, apresentados: list[str]) -> ReacoesDoTurno:
        self.apresentados_recebidos = apresentados
        if self.erro_ao_reagir is not None:
            raise self.erro_ao_reagir
        return ReacoesDoTurno(reacoes=self.reacoes, modelo="claude-opus-5")


async def test_cenario_1_gostei_do_segundo_marca_o_imovel_certo_como_interesse(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
) -> None:
    """Cenario 1 do Gherkin: tres imoveis apresentados, "gostei do segundo"
    marca o CORRETO -- pela posicao, nao pelo id.

    Titulo e bairro distintos por imovel, de proposito: se o ordinal casasse
    com o imovel errado, esta asserta pegaria mesmo sem olhar para
    `apresentados_recebidos`.
    """
    conversa = _conversa_do_turno()
    agora = datetime.now(UTC)
    primeiro = await _imovel(session, "AP-601", titulo="Apto Um", bairro="Centro")
    segundo = await _imovel(session, "AP-602", titulo="Apto Dois", bairro="Trindade")
    terceiro = await _imovel(session, "AP-603", titulo="Apto Tres", bairro="Itacorubi")
    await _recomendar(session, primeiro, conversation_key=conversa, apresentado_em=agora)
    await _recomendar(
        session, segundo, conversation_key=conversa, apresentado_em=agora + timedelta(seconds=1)
    )
    await _recomendar(
        session, terceiro, conversation_key=conversa, apresentado_em=agora + timedelta(seconds=2)
    )

    classificador = _ClassificadorDeReacao(
        reacoes=(ReacaoDoImovel(ordinal=2, reacao=ReacaoLead.INTERESSE),)
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="gostei do segundo",
    )

    assert resultado == "respondido"
    # A prova de que `apresentados` e `ids` vieram da MESMA ordem: a linha
    # numerada com "Apto Dois -- Trindade" e a que o classificador de fato viu
    # na posicao 2, e a reacao de ordinal 2 gruda no imovel que
    # `_recomendar` gravou naquela mesma posicao.
    assert classificador.apresentados_recebidos == [
        "1. Apto Um -- Centro",
        "2. Apto Dois -- Trindade",
        "3. Apto Tres -- Itacorubi",
    ]
    reacoes = {
        linha.imovel_id: linha.reacao_lead
        for linha in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert reacoes[segundo] == "INTERESSE"
    # D8: as duas nao mencionadas fecham NEUTRO, nunca ficam NULL -- senao a
    # proxima mensagem do lead pagaria `reagir` de novo pelos mesmos imoveis.
    assert reacoes[primeiro] == "NEUTRO"
    assert reacoes[terceiro] == "NEUTRO"


async def test_cenario_4_tem_mais_alguma_coisa_nao_marca_descarte_em_ninguem(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
) -> None:
    """Cenario 4 do Gherkin: perguntar por mais opcoes nao e opiniao sobre os
    ja mostrados. Ninguem vira DESCARTE -- as pendentes so fecham NEUTRO,
    porque nao houve reacao nenhuma, so uma pergunta por mais."""
    conversa = _conversa_do_turno()
    primeiro = await _imovel(session, "AP-610")
    segundo = await _imovel(session, "AP-611")
    await _recomendar(session, primeiro, conversation_key=conversa)
    await _recomendar(
        session,
        segundo,
        conversation_key=conversa,
        apresentado_em=datetime.now(UTC) + timedelta(seconds=1),
    )

    classificador = _ClassificadorDeReacao(reacoes=())
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor_fake(),
        contador_fake(),
        texto="tem mais alguma coisa?",
    )

    assert resultado == "respondido"
    reacoes = {
        linha.imovel_id: linha.reacao_lead
        for linha in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert reacoes == {primeiro: "NEUTRO", segundo: "NEUTRO"}


async def test_falha_de_reagir_nao_derruba_o_turno_e_deixa_pendente(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D9/D6 da TEC-265: derrubar a DIMENSAO, nao o turno.

    Provedor fora na chamada de reacao nao pode custar a resposta do lead --
    a linha continua pendente, o filtro deste turno nao se ajusta, e o lead
    recebe a mensagem normal do classificador.
    """
    # `_conversa_ja_existe` evita a identificacao ("Oi! Sou o assistente...")
    # entrar como prefixo do texto -- ela e de um subsistema diferente
    # (`identificacao.py`) e so atrapalharia a comparacao abaixo.
    await _conversa_ja_existe(session)
    conversa = _conversa_do_turno()
    imovel = await _imovel(session, "AP-620")
    await _recomendar(session, imovel, conversation_key=conversa)

    classificador = _ClassificadorDeReacao(erro_ao_reagir=TimeoutError("provedor fora"))
    outbound = outbound_fake()

    with caplog.at_level("WARNING"):
        resultado = await rodar_turno(
            session, classificador, outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "respondido"
    assert outbound.entregues == [classificador.resposta]
    linha = (await session.execute(select(Recomendacao))).scalars().one()
    assert linha.reacao_lead is None
    assert "turno.reacao_nao_capturada" in caplog.text


# ---------------------------------------------------------------------------
# Task 10: a exclusao ligada de verdade -- pelo TURNO, nao pela porta chamada
# direto. RN-10.4.
# ---------------------------------------------------------------------------


class _ClassificadorQueBuscaSemFiltroExtra:
    """Pede a ferramenta com o filtro dado e devolve os candidatos que a porta
    real trouxe.

    Molde de `_ClassificadorQuePedeAFerramenta`
    (`tests/integration/test_busca_no_turno.py`), copiado e nao importado --
    arquivos de integracao deste repo sao autocontidos. Existe para provar que
    a exclusao da RN-10.4 atravessa `executar_turno` de ponta a ponta: os
    testes de cima (`test_dois_descartes_por_distancia_excluem_bairro_da_
    busca_seguinte` etc.) chamam `porta_de_busca` DIRETO, com `channel`/
    `conversation_key` passados a mao -- e nunca teriam pego o defeito real
    (`executar_turno` montando a porta sem os dois).
    """

    def __init__(self, filtro: dict[str, object]) -> None:
        self.filtro = filtro
        self.resultado: RespostaDoAgente | None = None

    async def classificar(self, contexto: Any, *, porta: Any = None) -> RespostaDoAgente:
        assert porta is not None, "o turno tem de montar e passar a porta (D3)"
        saida = await porta(self.filtro)
        self.resultado = RespostaDoAgente(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.90"),
            resposta="Encontrei uma opcao que pode te interessar.",
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=Extracao(),
            candidatos=saida.get("candidatos", []),
            criterios=saida.get("criterios", []),
        )
        return self.resultado

    async def desambiguar(self, contexto: Any) -> PerguntaDeDesambiguacao:
        raise AssertionError("confianca alta o bastante para nao desambiguar neste teste")


async def test_a_exclusao_de_bairro_atravessa_um_turno_de_verdade(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TEC-163, Task 10. A lacuna que este teste fecha: ate esta task,
    `executar_turno` montava `porta_de_busca` SEM `channel`/`conversation_key`,
    e `_bairros_excluidos_desta_busca` desliga a exclusao inteira sem os
    dois -- a feature inteira das Tasks 7-9 (limiar, categoria, dobra, o lift
    de D14) rodava so em teste de porta direta e NUNCA num turno de verdade.

    Dois descartes por distancia no Campeche, ja registrados (de "turnos
    anteriores" desta mesma conversa) excluem o bairro; o imovel que a busca
    DESTE turno encontraria, se a exclusao nao valesse, tambem esta no
    Campeche e nao pode aparecer entre os candidatos que o TURNO devolveu.
    """
    conversa = _conversa_do_turno()
    for codigo in ("AP-900", "AP-901"):
        descartado = await _imovel(session, codigo, bairro="Campeche")
        await _recomendar(
            session,
            descartado,
            conversation_key=conversa,
            reacao_lead=ReacaoLead.DESCARTE.value,
            motivo_descarte=CategoriaDescarte.DISTANCIA.value,
        )
    procurado = await _imovel(session, "AP-902", bairro="Campeche")

    classificador = _ClassificadorQueBuscaSemFiltroExtra({"operacao": "VENDA"})
    outbound = outbound_fake()

    with caplog.at_level("INFO"):
        resultado = await rodar_turno(
            session, classificador, outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "respondido"
    assert classificador.resultado is not None
    ids_encontrados = {c["imovel_id"] for c in classificador.resultado.candidatos}
    assert str(procurado) not in ids_encontrados, (
        "o Campeche tinha de sair da busca deste turno -- se este imovel aparece, "
        "a exclusao da RN-10.4 nao esta ligada de verdade no turno"
    )
    assert "recomendacao.exclusao_desligada_sem_identidade" not in caplog.text, (
        "este log e o sinal de que o turno nao passou identidade de conversa para "
        "porta_de_busca -- ele nao pode aparecer num turno normal"
    )
