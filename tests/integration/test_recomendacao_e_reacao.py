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
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    imovel = await _imovel(session, "AP-410")
    mensagem = await _entrada_do_lead(session)
    agora = datetime.now(UTC)

    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=[{"imovel_id": str(imovel), "preco_centavos": 41000000}],
        scores={imovel: 0.87},
        criterios=["3 quartos", "Trindade"],
        message_id=mensagem.id,
        kinds=["ficha_1"],
        relaxou_preco=False,
        relaxou_bairro=False,
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
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    imovel = await _imovel(session, "AP-411")
    mensagem = await _entrada_do_lead(session)
    candidatos = [{"imovel_id": str(imovel), "preco_centavos": 41000000}]
    scores = {imovel: 0.87}

    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=candidatos,
        scores=scores,
        criterios=["Trindade"],
        message_id=mensagem.id,
        kinds=["ficha_1"],
        relaxou_preco=False,
        relaxou_bairro=False,
        agora=datetime.now(UTC),
    )
    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=candidatos,
        scores=scores,
        criterios=["Trindade"],
        message_id=mensagem.id,
        kinds=["ficha_1"],
        relaxou_preco=False,
        relaxou_bairro=False,
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
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    com_score = await _imovel(session, "AP-412")
    sem_score = await _imovel(session, "AP-413")
    mensagem = await _entrada_do_lead(session)

    await gravar_recomendacoes(
        session_factory,
        channel=CANAL,
        conversation_key=CONVERSA,
        candidatos=[
            {"imovel_id": str(com_score), "preco_centavos": 41200000},
            {"imovel_id": str(sem_score), "preco_centavos": 41300000},
        ],
        scores={com_score: 0.5},
        criterios=["Trindade"],
        message_id=mensagem.id,
        kinds=["ficha_1", "ficha_2"],
        relaxou_preco=False,
        relaxou_bairro=False,
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
        message_id=uuid.uuid4(),
        kinds=[],
        relaxou_preco=False,
        relaxou_bairro=False,
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
            # Fix wave. As mesmas quatro chaves que `_relaxamento_de`
            # (`classificador.py`) le do `tool_result` num turno de verdade --
            # copiadas aqui pelo mesmo motivo que `criterios` acima ja era: sem
            # elas, `gerada.relaxou_preco` chega False em todo teste que usa
            # este duble, e um turno relaxado passaria por aqui indistinguivel
            # de um turno normal.
            relaxou_e_achou=bool(saida.get("relaxamento_aplicado")),
            relaxou_sem_resultado=bool(saida.get("relaxamento_sem_resultado")),
            relaxou_preco=bool(saida.get("relaxamento_de_preco")),
            relaxou_bairro=bool(saida.get("relaxamento_de_bairro")),
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


# ---------------------------------------------------------------------------
# Fix wave: `ler_pendentes` devolve o que o lead VIU, e so isso.
#
# A posicao N daquela lista e o ordinal N da resposta do lead (D7). Duas
# rotas colocavam la linha que ele nunca viu -- uma pendente velha que
# `reagir` nao fechou, e a ficha que nao saiu --, e nas duas o ordinal dele
# gruda no imovel errado.
# ---------------------------------------------------------------------------


class _ClassificadorQueBuscaEFalhaAoReagir(_ClassificadorQueBuscaSemFiltroExtra):
    """`_ClassificadorQueBuscaSemFiltroExtra` com `reagir` estourando.

    E a combinacao que nenhum duble deste repo tinha: o turno que NAO consegue
    capturar a reacao (o `except Exception` amplo de `turno.py`, que esta
    certo em si) e mesmo assim busca e apresenta. E exatamente ai que as
    pendentes do turno anterior sobrevivem ate a lista numerada do turno
    seguinte.
    """

    async def reagir(self, contexto: Any, *, apresentados: list[str]) -> ReacoesDoTurno:
        raise TimeoutError("provedor fora")


async def _pendentes_da_conversa(session_factory: Any) -> tuple[uuid.UUID, ...]:
    """Os ids que o PROXIMO turno numeraria, na ordem em que os numeraria."""
    return tuple(
        pendente.imovel_id
        for pendente in await ler_pendentes(
            session_factory, channel=CANAL, conversation_key=_conversa_do_turno()
        )
    )


async def test_pendente_que_reagir_nao_fechou_nao_entra_na_lista_da_proxima_reacao(
    session: Any,
    session_factory: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D8/L5: a apresentacao nova supera a pendente antiga, que fecha `SEM_RESPOSTA`.

    O enum declara o valor, a D8 o especifica, `gravar_reacoes` documentava
    que marca-lo era "de quem apresenta de novo (`turno.py`)" -- e ninguem o
    escrevia. Sem isso: `reagir` estoura neste turno (provedor fora), as tres
    linhas do turno anterior continuam NULL, este turno apresenta outras tres,
    e no proximo `ler_pendentes` devolve SEIS numa lista so. "Gostei do
    segundo", dito sobre a lista de tres que ele acabou de ver, cairia no
    segundo da lista VELHA -- um imovel que ele ja tinha deixado para tras.

    `quartos=1` nos tres antigos os mantem fora da busca deste turno
    (`quartos_min=3`): sem isso a busca real os traria de volta entre os
    candidatos e a asserta nao separaria "pendente velha fechada" de
    "reapresentado".
    """
    await _conversa_ja_existe(session)
    conversa = _conversa_do_turno()
    antes = datetime.now(UTC) - timedelta(minutes=5)
    antigos = []
    for posicao, codigo in enumerate(("AP-940", "AP-941", "AP-942")):
        antigo = await _imovel(session, codigo, quartos=1)
        await _recomendar(
            session,
            antigo,
            conversation_key=conversa,
            apresentado_em=antes + timedelta(seconds=posicao),
        )
        antigos.append(antigo)

    novos = {await _imovel(session, f"AP-95{n}", quartos=3) for n in range(3)}
    classificador = _ClassificadorQueBuscaEFalhaAoReagir({"operacao": "VENDA", "quartos_min": 3})
    outbound = outbound_fake()

    with caplog.at_level("WARNING"):
        resultado = await rodar_turno(
            session, classificador, outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "respondido"
    assert "turno.reacao_nao_capturada" in caplog.text, (
        "o teste so vale se `reagir` de fato falhou -- e a falha que deixa a pendente aberta"
    )
    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]

    reacoes = {
        linha.imovel_id: linha.reacao_lead
        for linha in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert {reacoes[antigo] for antigo in antigos} == {"SEM_RESPOSTA"}, (
        "a apresentacao nova supera as tres antigas -- NEUTRO diria que o lead respondeu "
        "sobre elas, e NULL as deixaria na lista numerada do proximo turno"
    )
    assert await _pendentes_da_conversa(session_factory) == tuple(apresentados), (
        "a lista que o proximo turno numera tem de ser exatamente o que o lead acabou "
        "de ver, na ordem em que viu"
    )
    assert set(apresentados) == novos


async def test_o_ordinal_do_turno_seguinte_aponta_para_o_imovel_recem_visto(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
) -> None:
    """A mesma falha do teste acima, cobrada no lugar em que ela custa caro: o
    imovel que a opiniao do lead marca.

    Turno 1 apresenta tres e `reagir` estoura. Turno 2 apresenta outros tres.
    Turno 3 o lead diz "gostei do segundo" -- e o segundo e o segundo da
    lista que ele acabou de ver. Com as pendentes do turno 1 ainda abertas, o
    ordinal 2 cairia no segundo imovel do turno 1.
    """
    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-96{n}", quartos=3, preco_venda=30000000 + n)

    primeiro_turno = _ClassificadorQueBuscaEFalhaAoReagir({"operacao": "VENDA", "quartos_min": 3})
    outbound = outbound_fake()
    assert (
        await rodar_turno(session, primeiro_turno, outbound, resumidor_fake(), contador_fake())
        == "respondido"
    )

    # Imoveis novos para o turno 2, e os tres do turno 1 fora da busca dele:
    # `ON CONFLICT DO NOTHING` nao gera pendente nova para quem ja tem linha,
    # e um reapresentado no lote 2 confundiria a asserta.
    for n in range(3):
        await _imovel(session, f"AP-97{n}", quartos=4, preco_venda=30000000 + n)
    segundo_turno = _ClassificadorQueBuscaEFalhaAoReagir({"operacao": "VENDA", "quartos_min": 4})
    assert (
        await rodar_turno(session, segundo_turno, outbound, resumidor_fake(), contador_fake())
        == "respondido"
    )
    assert segundo_turno.resultado is not None
    vistos_por_ultimo = [uuid.UUID(c["imovel_id"]) for c in segundo_turno.resultado.candidatos]
    assert len(vistos_por_ultimo) == 3

    terceiro_turno = _ClassificadorDeReacao(
        reacoes=(ReacaoDoImovel(ordinal=2, reacao=ReacaoLead.INTERESSE),)
    )
    assert (
        await rodar_turno(
            session,
            terceiro_turno,
            outbound,
            resumidor_fake(),
            contador_fake(),
            texto="gostei do segundo",
        )
        == "respondido"
    )

    interessados = [
        linha.imovel_id
        for linha in (await session.execute(select(Recomendacao))).scalars().all()
        if linha.reacao_lead == "INTERESSE"
    ]
    assert interessados == [vistos_por_ultimo[1]], (
        "'o segundo' e o segundo da lista que o lead acabou de ver, e nao o segundo "
        "de uma apresentacao anterior que ficou aberta"
    )


async def test_ficha_recusada_nao_deixa_linha_de_imovel_que_o_lead_nunca_viu(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """RN-10.3 registra o que foi APRESENTADO, e ficha recusada nao e apresentacao.

    `gravar_recomendacoes` roda ANTES do laco de entrega -- de proposito, e a
    L1 da TEC-162 --, entao a linha da ficha 2 ja existe quando a Meta recusa
    a midia (D10: a recusa nao cala as outras duas). Sem a conciliacao, o
    proximo turno numera `["1. A", "2. B", "3. C"]` com o lead tendo visto so
    A e C: "o segundo" marcaria B, que ele nunca recebeu.

    A linha e APAGADA e nao fechada porque o UNIQUE (channel, conversa,
    imovel) e para sempre: fechada, ela bloquearia com `ON CONFLICT DO
    NOTHING` a apresentacao futura de B -- aquela que de fato sair -- de
    gerar pendente, e B ficaria inalcancavel pela reacao do lead pelo resto
    da conversa por causa de uma foto recusada uma vez.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS
    from mobia.domain.outbound.port import EnvioRecusado
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-98{n}", quartos=3, preco_venda=30000000 + n)

    class _RecusaASegunda(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[1]:
                raise EnvioRecusado("http 400 codigo 131053")
            await super()._deliver(message_id, kind, payload)

    outbound = _RecusaASegunda(get_sessionmaker())
    classificador = _ClassificadorQueBuscaSemFiltroExtra({"operacao": "VENDA", "quartos_min": 3})

    with caplog.at_level("ERROR"):
        resultado = await rodar_turno(
            session, classificador, outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "respondido"
    assert "apresentacao.ficha_recusada" in caplog.text, (
        "o teste so vale se a segunda ficha de fato foi recusada"
    )
    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]
    recusado = apresentados[1]

    gravados = {
        linha.imovel_id for linha in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert recusado not in gravados, "linha gravada para ficha que a Meta recusou"
    assert gravados == {apresentados[0], apresentados[2]}
    assert await _pendentes_da_conversa(session_factory) == (apresentados[0], apresentados[2]), (
        "a lista numerada do proximo turno tem de pular o imovel cuja ficha nao saiu -- "
        "senao 'o segundo' marca um imovel que o lead nunca recebeu"
    )


async def test_o_motivo_gravado_diz_quando_a_busca_precisou_ampliar(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
) -> None:
    """D5, segunda metade: "quais filtros bateram, E se houve relaxamento".

    O unico teste desta suite em que o relaxamento de VERDADE acontece dentro
    de um turno: os outros trocam `buscar_com_relaxamento` inteira por um
    duble, e com ela fora nenhum passe relaxado existe para ser descrito.
    Aqui a busca real roda contra o catalogo real -- um imovel de R$ 430.000
    com teto de R$ 400.000 so aparece porque o segundo passe cede 10% --, e a
    linha gravada tem de dizer isso. Sem as duas flags, `motivo_match` sairia
    "ate R$ 400.000": um criterio que este imovel nao satisfaz, gravado no
    banco como se fosse fato -- o dano que a D5 existe para impedir.
    """
    await _conversa_ja_existe(session)
    imovel = await _imovel(session, "AP-990", quartos=3, preco_venda=43000000)

    classificador = _ClassificadorQueBuscaSemFiltroExtra(
        {"operacao": "VENDA", "quartos_min": 3, "preco_max_centavos": 40000000}
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert classificador.resultado is not None
    assert classificador.resultado.relaxou_preco is True, (
        "sem relaxamento de verdade este teste nao exercita nada"
    )
    linha = (await session.execute(select(Recomendacao))).scalars().one()
    assert linha.imovel_id == imovel
    assert linha.motivo_match == "3 quartos, ate R$ 400.000 (criterio ampliado: preco)"


# ---------------------------------------------------------------------------
# TEC-275: a retentativa de uma apresentacao parcial.
#
# `EnvioRetentavel` no meio do laco propaga ANTES de `conciliar_apresentacao`
# (de proposito: conciliar no meio apagaria linha de ficha que a retentativa
# ainda vai entregar), o turno termina FAILED e `sweep_stalled` reenfileira a
# MESMA mensagem -- FAILED e reivindicavel (`CLAIMABLE_STATUSES`). O que a
# segunda passada faz com as linhas que a primeira deixou abertas e o assunto
# daqui.
# ---------------------------------------------------------------------------


class _ClassificadorQueBuscaESemReacao(_ClassificadorQueBuscaSemFiltroExtra):
    """`_ClassificadorQueBuscaSemFiltroExtra` com `reagir` que FUNCIONA e nao
    acha reacao nenhuma.

    E o que um modelo de verdade devolve na retentativa: a mensagem
    reprocessada e a MESMA de antes -- o pedido que originou a busca --, e ela
    nao fala de imovel nenhum. A base nao define `reagir` porque nos testes
    dela nunca ha pendente quando o turno chega la; aqui ha, e um
    `AttributeError` cairia no `except Exception` amplo de `turno.py` e o teste
    passaria a medir o duble em vez do sistema.
    """

    def __init__(self, filtro: dict[str, object]) -> None:
        super().__init__(filtro)
        self.apresentados_recebidos: list[str] | None = None

    async def reagir(self, contexto: Any, *, apresentados: list[str]) -> ReacoesDoTurno:
        self.apresentados_recebidos = apresentados
        return ReacoesDoTurno(reacoes=(), modelo="claude-opus-5")


async def test_retentativa_de_apresentacao_parcial_deixa_o_lead_sem_lista(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275. Depois da retentativa o lead viu as tres fichas e nao tem lista.

    Passada 1: a ficha 2 levanta `EnvioRetentavel`. As tres linhas ja estao
    gravadas com um `agora` unico (a L1 da TEC-162 grava o lote ANTES do laco),
    o lead recebeu so a ficha 1, e a excecao propaga antes da conciliacao --
    nenhuma das tres e fechada nem apagada.

    Passada 2, a MESMA mensagem: o turno reentra pelo topo. `ler_pendentes`
    devolve as tres, `reagir` e chamado sobre elas com a mensagem original do
    lead (que nao e reacao a nada), e `gravar_reacoes` fecha como NEUTRO toda
    pendente nao mencionada -- as tres, antes de qualquer ficha ser reenviada.

    O turno entao reentrega, e o turno SEGUINTE nao tem lista: o lead acabou
    de ver tres fichas e `ler_pendentes` devolve vazio. "Gostei do segundo"
    nao tem contra o que resolver o ordinal.

    Este teste afirma o comportamento CERTO e por isso reprova hoje. A
    mensagem da asserta que quebrar diz qual dos dois caminhos fechou as
    linhas -- NEUTRO (a passagem de reacao) ou SEM_RESPOSTA (o `< agora` de
    `conciliar_apresentacao`).
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-93{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RetentavelNaSegunda(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[1]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    async def _rodar(outbound: Any, classificador: Any) -> str:
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    primeira = _RetentavelNaSegunda(get_sessionmaker())
    classificador_1 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(primeira, classificador_1)

    assert len(primeira.entregues) == 1, (
        "o teste so vale se a primeira passada entregou UMA ficha e parou na segunda"
    )
    assert classificador_1.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador_1.resultado.candidatos]
    assert len(apresentados) == 3
    assert await _pendentes_da_conversa(session_factory) == tuple(apresentados), (
        "sem conciliacao, as tres linhas da passada 1 ficam abertas -- e a premissa "
        "de que o resto do teste depende"
    )

    segunda = OutboundFake(get_sessionmaker())
    classificador_2 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, classificador_2) == "respondido"

    assert classificador_2.apresentados_recebidos is not None, (
        "a retentativa tem de ter chamado `reagir` sobre as pendentes da passada 1 -- "
        "e isso que torna a passagem de reacao o primeiro caminho"
    )

    fechadas = {
        str(registro.imovel_id): registro.reacao_lead
        for registro in (await session.execute(select(Recomendacao))).scalars().all()
    }
    vistos_agora = sorted(str(i) for i in apresentados)
    assert await _pendentes_da_conversa(session_factory) == tuple(apresentados), (
        "o lead acabou de receber as tres fichas e nao tem lista contra a qual "
        f"responder 'gostei do segundo'. Reacoes gravadas: {fechadas}; "
        f"imoveis que ele viu: {vistos_agora}"
    )


async def test_retentativa_com_reagir_falhando_fecha_as_mesmas_linhas_pelo_outro_caminho(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275. O mesmo fim por `conciliar_apresentacao`, quando `reagir` estoura.

    Identico ao teste acima, com uma diferenca na passada 2: `reagir` levanta,
    cai no `except Exception` amplo de `turno.py`, e `gravar_reacoes` nao roda
    -- as tres linhas seguem `NULL`. A apresentacao reentrega; como
    `gravar_recomendacoes` nao insere nada (`ON CONFLICT DO NOTHING` sobre as
    tres que ja existem), elas mantem o `apresentado_em` da passada 1, e o
    `apresentado_em < agora` de `conciliar_apresentacao` casa as tres.

    Existe para provar que sao DOIS caminhos para o mesmo fim: um conserto
    que so distinga as apresentacoes dentro de `conciliar_apresentacao` faz
    este teste passar e deixa o de cima reprovando.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-92{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RetentavelNaSegunda(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[1]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    async def _rodar(outbound: Any, classificador: Any) -> str:
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    primeira = _RetentavelNaSegunda(get_sessionmaker())
    classificador_1 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(primeira, classificador_1)

    assert classificador_1.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador_1.resultado.candidatos]
    assert len(apresentados) == 3

    segunda = OutboundFake(get_sessionmaker())
    assert (
        await _rodar(
            segunda,
            _ClassificadorQueBuscaEFalhaAoReagir({"operacao": "VENDA", "quartos_min": 3}),
        )
        == "respondido"
    )

    fechadas = {
        str(registro.imovel_id): registro.reacao_lead
        for registro in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert await _pendentes_da_conversa(session_factory) == tuple(apresentados), (
        "com `reagir` estourando na retentativa quem fecha as tres e o "
        f"`apresentado_em < agora` de `conciliar_apresentacao`. Reacoes gravadas: {fechadas}"
    )


async def test_a_recomendacao_guarda_dono_preco_e_kind(session: Any) -> None:
    """TEC-275, D2. As tres colunas que tornam a apresentacao continuavel.

    Nullable as tres: linha anterior a esta card nao tem dono, e inventar um
    seria mentira (L2 do desenho).
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    linha_da_mensagem = await _entrada_do_lead(session, texto="quero tres quartos")
    imovel = await _imovel(session, "AP-910")

    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            imovel_id=imovel,
            score_match=Decimal("0.900"),
            motivo_match="3 quartos",
            apresentado_em=datetime.now(UTC),
            message_id=linha_da_mensagem.id,
            preco_centavos=30000000,
            kind="ficha_1",
        )
    )
    await session.commit()

    gravada = (await session.execute(select(Recomendacao))).scalars().one()
    assert gravada.message_id == linha_da_mensagem.id
    assert gravada.preco_centavos == 30000000
    assert gravada.kind == "ficha_1"


async def test_cada_linha_apresentada_guarda_o_kind_com_que_saiu(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
) -> None:
    """TEC-275, D9. O kind da linha e o kind com que a ficha saiu, na ordem.

    Trava o alinhamento entre a lista que `gravar_recomendacoes` recebe e a
    que o laco de entrega enumera: as duas saem de `escolhidos` filtrado por
    `encontrados`, na mesma ordem, entao o indice de uma e o da outra. Se
    alguem inserir um filtro ou uma reordenacao em so uma delas, o kind passa
    a apontar para a ficha errada e este teste cai.
    """
    from mobia.domain.agente.turno import KINDS_DAS_FICHAS

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-91{n}", quartos=3, preco_venda=30000000 + n)

    classificador = _ClassificadorQueBuscaSemFiltroExtra({"operacao": "VENDA", "quartos_min": 3})
    outbound = outbound_fake()
    assert (
        await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())
        == "respondido"
    )

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]
    linhas = {
        registro.imovel_id: registro
        for registro in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert len(linhas) == 3
    for posicao, imovel_id in enumerate(apresentados):
        assert linhas[imovel_id].kind == KINDS_DAS_FICHAS[posicao]
        assert linhas[imovel_id].message_id is not None
        # Nao "30000000 + posicao": a ordem de apresentacao vem do ranking
        # (score_match DESC), nao da ordem de criacao dos imoveis. A invariante
        # de verdade e a linha guardar o preco do candidato que esta NAQUELA
        # posicao, seja ele qual for.
        assert linhas[imovel_id].preco_centavos == int(
            classificador.resultado.candidatos[posicao]["preco_centavos"]
        )
