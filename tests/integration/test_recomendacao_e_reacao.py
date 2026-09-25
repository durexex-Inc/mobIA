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

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
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
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message, MessageTelemetry
from mobia.domain.texto import dobrar
from mobia.infra.crypto import aad_de, decrypt

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

    E o que um modelo de verdade devolveria na retentativa: a mensagem
    reprocessada e a MESMA de antes -- o pedido que originou a busca --, e ela
    nao fala de imovel nenhum.

    Com o conserto da TEC-275 a continuacao nao chama `reagir`, e `reagir`
    definido aqui e o que torna isso VERIFICAVEL: `apresentados_recebidos`
    continua `None`, e varios testes abaixo assertam exatamente isso. A base
    nao define `reagir` porque nos testes dela nunca ha pendente quando o turno
    chega la; numa regressao em que a passada 2 voltasse a rodar o turno
    inteiro ha, e um `AttributeError` cairia no `except Exception` amplo de
    `turno.py` -- a regressao passaria calada e o teste mediria o duble em vez
    do sistema.
    """

    def __init__(self, filtro: dict[str, object]) -> None:
        super().__init__(filtro)
        self.apresentados_recebidos: list[str] | None = None

    async def reagir(self, contexto: Any, *, apresentados: list[str]) -> ReacoesDoTurno:
        self.apresentados_recebidos = apresentados
        return ReacoesDoTurno(reacoes=(), modelo="claude-opus-5")


async def test_retentativa_de_apresentacao_parcial_mantem_a_lista_do_lead(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275. Depois da retentativa o lead viu as tres fichas E ainda tem lista.

    Passada 1: a ficha 2 levanta `EnvioRetentavel`. As tres linhas ja estao
    gravadas com um `agora` unico (a L1 da TEC-162 grava o lote ANTES do laco),
    o lead recebeu so a ficha 1, e a excecao propaga antes da conciliacao --
    nenhuma das tres e fechada nem apagada.

    Passada 2, a MESMA mensagem: o turno NAO reentra pelo topo. O desvio da
    TEC-275 (D1) ve que ha um lote com este `message_id` e que parte dele ja
    tem reserva, e devolve `_continuar_entrega` antes de montar contexto --
    entao a passada 2 nao rebusca, nao chama o classificador e nao chama
    `reagir`. Ela entrega as fichas 2 e 3 que faltavam e concilia com o
    `apresentado_em` PERSISTIDO do lote.

    O fim e o que o lead precisa: ele viu as tres fichas E as tres seguem
    pendentes, entao "gostei do segundo" no turno seguinte tem contra o que
    resolver o ordinal.

    Antes da correcao a passada 2 rodava o turno inteiro: `ler_pendentes`
    devolvia as tres, `reagir` era chamado sobre elas com a mensagem original
    do lead (que nao e reacao a nada), e `gravar_reacoes` fechava como NEUTRO
    toda pendente nao mencionada -- as tres, antes de qualquer ficha ser
    reenviada; o lead acabava com as fichas e sem lista. Era o primeiro dos
    dois caminhos; o outro (o `< agora` de `conciliar_apresentacao` fechando
    como SEM_RESPOSTA) esta no teste seguinte.
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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
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

    assert len(segunda.entregues) == 2, (
        "a passada 2 entrega as fichas 2 e 3 -- as duas que faltavam. A asserta final "
        "desta funcao olha so para as pendentes, e as tres continuariam pendentes mesmo "
        "se a continuacao tivesse entregue UMA ficha: o lead ficaria sem a terceira e "
        "nada aqui acusaria. Neste lote o kind por posicao coincide com o persistido "
        "(tres linhas, nenhuma apagada), entao quem pega a reconstrucao posicional e "
        "`test_continuacao_usa_o_kind_persistido_e_nao_a_posicao`, com o lote furado"
    )

    assert classificador_2.apresentados_recebidos is None, (
        "a retentativa NAO pode ter chamado `reagir`, e isso e o conserto (D1), nao "
        "regressao: a continuacao retorna antes da passagem de reacao. Se `reagir` "
        "rodasse aqui, receberia a mensagem ORIGINAL do lead -- o pedido que originou a "
        "busca, que nao e reacao a ficha nenhuma -- e `gravar_reacoes` fecharia como "
        "NEUTRO toda pendente nao mencionada, ou seja, as tres, deixando o lead com as "
        "fichas e sem lista contra a qual resolver o ordinal. Esta linha nasceu afirmando "
        "o oposto (a4e1a2d), como DIAGNOSTICO de qual caminho rodava no sistema quebrado"
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


async def test_retentativa_com_reagir_falhando_mantem_as_linhas_pelo_outro_caminho(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275. As linhas sobrevivem tambem ao caminho de `conciliar_apresentacao`.

    Identico ao teste acima, e a unica diferenca e o duble: aqui o
    classificador da passada 2 estoura em `reagir`. Hoje isso nao muda nada,
    porque a passada 2 nao chega a chamar `reagir` -- o desvio da TEC-275
    devolve `_continuar_entrega` antes --, e e justamente esse "nao muda nada"
    que o teste afirma.

    O duble existe por causa do mundo ANTERIOR ao conserto, em que a passada 2
    rodava o turno inteiro: `reagir` levantava, caia no `except Exception`
    amplo de `turno.py`, `gravar_reacoes` nao rodava e as tres linhas seguiam
    `NULL` -- e ai quem as fechava era o outro caminho, o `apresentado_em <
    agora` de `conciliar_apresentacao`, porque `gravar_recomendacoes` nao
    inseria nada (`ON CONFLICT DO NOTHING` sobre as tres que ja existiam) e
    elas mantinham o carimbo da passada 1.

    Existe para provar que eram DOIS caminhos para o mesmo defeito: um
    conserto que so distinguisse as apresentacoes dentro de
    `conciliar_apresentacao` faz este teste passar e deixa o de cima
    reprovando.
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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
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
        "a passada 2 e continuacao e concilia com o carimbo do PROPRIO lote, entao nada "
        "tem o que fechar. Se as tres vierem fechadas, ela voltou a rodar o turno "
        "inteiro: `reagir` estourou, `gravar_reacoes` nao rodou, e quem fechou foi o "
        f"`apresentado_em < agora` de `conciliar_apresentacao`. Reacoes gravadas: {fechadas}"
    )


async def test_ficha_recusada_some_mesmo_quando_o_turno_morre_depois(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275, D8. A delecao da linha recusada nao pode depender do fim do laco.

    Ficha 1 recusada (permanente, a reserva FICA), ficha 3 retentavel -- o
    turno morre antes da conciliacao. Sem a delecao antecipada a linha da
    ficha 1 sobrevive, e ela e um imovel que o lead nunca viu ocupando um
    ordinal.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9A{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RecusaAPrimeiraEFalhaNaTerceira(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[0]:
                raise EnvioRecusado("http 400 codigo 131053")
            if kind == KINDS_DAS_FICHAS[2]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=_RecusaAPrimeiraEFalhaNaTerceira(get_sessionmaker()),
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    assert classificador.resultado is not None
    recusado = uuid.UUID(classificador.resultado.candidatos[0]["imovel_id"])
    gravados = {
        registro.imovel_id
        for registro in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert recusado not in gravados, (
        "a linha da ficha recusada tem de sumir na hora da recusa -- esperar o fim "
        "do laco perde a limpeza quando o turno morre no meio"
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


# ---------------------------------------------------------------------------
# Task 4 da TEC-275: os dois leitores -- o lote de uma mensagem, e as reservas
# dela. Juntos respondem "esta mensagem ja apresentou um lote, e quais fichas
# dele ainda nao sairam?" -- a pergunta que a Task 6 (continuacao) precisa.
# ---------------------------------------------------------------------------


async def test_ler_apresentacao_da_mensagem_devolve_o_lote_na_ordem_apresentada(
    session: Any, session_factory: Any
) -> None:
    """TEC-275, D5. Mesma ordenacao de `ler_pendentes`, escopo por mensagem.

    A ordem e o ordinal, e reusar a regra de `ler_pendentes` em vez de
    escrever uma segunda e o ponto: duas copias podem divergir, e o preco da
    divergencia e a reacao do lead grudando no imovel errado.

    Ao contrario de `ler_pendentes`, NAO filtra por `reacao_lead IS NULL`: a
    continuacao precisa do lote inteiro para mapear kind, inclusive linha que
    ja tenha reacao.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.agente.repositorio import ler_apresentacao_da_mensagem

    linha_da_mensagem = await _entrada_do_lead(session, texto="quero tres quartos")
    agora = datetime.now(UTC)
    esperados = []
    for posicao, (codigo, score) in enumerate(
        (("AP-9B0", "0.900"), ("AP-9B1", "0.800"), ("AP-9B2", "0.700"))
    ):
        imovel = await _imovel(session, codigo)
        esperados.append(imovel)
        session.add(
            Recomendacao(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=CONVERSA,
                imovel_id=imovel,
                score_match=Decimal(score),
                motivo_match="3 quartos",
                apresentado_em=agora,
                message_id=linha_da_mensagem.id,
                preco_centavos=30000000 + posicao,
                kind=f"ficha_{posicao + 1}",
            )
        )
    # Linha de OUTRA mensagem, na mesma conversa: nao pode entrar no lote.
    outra = await _imovel(session, "AP-9B9")
    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            imovel_id=outra,
            score_match=Decimal("0.950"),
            motivo_match="3 quartos",
            apresentado_em=agora - timedelta(hours=1),
            message_id=None,
            preco_centavos=1,
            kind="ficha_1",
        )
    )
    await session.commit()

    lote = await ler_apresentacao_da_mensagem(session_factory, message_id=linha_da_mensagem.id)
    assert [linha.imovel_id for linha in lote] == esperados
    assert [linha.kind for linha in lote] == ["ficha_1", "ficha_2", "ficha_3"]
    assert [linha.preco_centavos for linha in lote] == [30000000, 30000001, 30000002]
    assert all(linha.apresentado_em == agora for linha in lote)


async def test_kinds_reservados_devolve_o_que_ja_tem_reserva(session: Any) -> None:
    """TEC-275, D4. A reserva e o que diz se aquela ficha ja saiu.

    Reserva committada ANTES do efeito externo, liberada so em
    `EnvioRetentavel`/cancelamento -- entao presenca significa "esta posicao
    esta encerrada, nao reenviamos", que e o contrato que a continuacao usa.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.outbound.models import OutboundDispatch
    from mobia.domain.outbound.repositorio import kinds_reservados
    from mobia.infra.db import get_sessionmaker

    linha_da_mensagem = await _entrada_do_lead(session, texto="quero tres quartos")
    session.add(OutboundDispatch(id=uuid.uuid4(), message_id=linha_da_mensagem.id, kind="ficha_1"))
    await session.commit()

    assert await kinds_reservados(get_sessionmaker(), message_id=linha_da_mensagem.id) == frozenset(
        {"ficha_1"}
    )


# ---------------------------------------------------------------------------
# Task 7 da TEC-275: os casos de borda da continuacao.
#
# Os dois testes de aceite acima cobrem o caminho inteiro e feliz da
# retentativa. O que segue sao as bordas dele -- o lote incompleto, o lote que
# nao da para continuar, o kind que a posicao erraria, a fala que a passada 2
# grava, a janela que fecha no meio e a linha que o lead ja reagiu.
# ---------------------------------------------------------------------------


async def _falas_do_agente(session: Any) -> list[tuple[str, str | None, str | None]]:
    """Cada fala do agente na linha do tempo como `(texto, model, subagent)`.

    `text_body` e bytea cifrado desde a TEC-126, entao `decrypt` com o AAD da
    propria linha -- mesmo molde de `_texto_gravado`
    (`test_apresentacao_no_turno.py`). Olhar aqui e diferente de olhar para
    `outbound.entregues`: o duble registra o que SAIU, e esta tabela registra
    o que ficou gravado, que e a fonte do contexto do turno seguinte.

    **`model` e `subagent` vem junto porque os comentarios que os escolhem em
    `_continuar_entrega` afirmam consequencia concreta** -- `""` abriria um
    `telemetry.unknown_model`, e um rotulo de subagente proprio partiria a
    MESMA apresentacao em dois valores para quem le a telemetria depois. Ate
    esta task nada na suite lia aquelas duas colunas, entao as duas
    afirmacoes eram promessa sem fiador, que e o que este repo trata como
    defeito.

    `outerjoin` e nao `join`: a telemetria e gravada num commit proprio,
    depois do da mensagem, e `_registrar_telemetria` engole a falha dela. Com
    `join`, uma fala sem telemetria sumiria desta lista e o teste culparia a
    gravacao da fala; com `outerjoin` ela aparece com `None` nos dois campos,
    e a asserta que compara contra `MODELO_SEM_CHAMADA` acusa o que de fato
    faltou.
    """
    linhas = (
        await session.execute(
            select(Message, MessageTelemetry.model, MessageTelemetry.subagent)
            .outerjoin(MessageTelemetry, MessageTelemetry.message_id == Message.id)
            .where(Message.role == MessageRole.AGENTE)
            .order_by(Message.created_at)
        )
    ).all()
    return [
        (decrypt(linha.text_body, aad_de(linha.id, "text_body")), model, subagent)
        for linha, model, subagent in linhas
    ]


async def test_continuacao_entrega_o_que_restou_quando_uma_linha_do_lote_sumiu(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275. Lote incompleto: a linha que a D8 apagou nao volta na passada 2.

    A rota real para o lote chegar incompleto na passada 2 e a D8: a ficha 2 e
    recusada e a linha dela e apagada NA HORA, ainda dentro da passada 1 -- a
    conciliacao, que e a outra rota de delecao, nao chega a rodar quando o laco
    morre numa ficha seguinte.

    Nao e o imovel que sai do catalogo: `recomendacoes.imovel_id` tem FK para
    `imoveis` SEM `ON DELETE`, entao imovel referenciado por linha do lote nao
    pode ser apagado. E por isso que o ramo `sumiram` de `_continuar_entrega` e
    defensivo e hoje inalcancavel -- o comentario dele diz isso --, e por isso
    que um teste que apagasse a linha antes do imovel provaria nada: sem a
    linha, o imovel nem entra no lote e o ramo ficaria vazio de qualquer jeito.

    O que tem de valer: a continuacao entrega SO a ficha que faltava, o imovel
    recusado nao ressuscita como pendente, e o ordinal dos outros dois nao se
    desloca. Reprova se a continuacao conciliar com um `now()` novo -- as duas
    linhas sobreviventes viram `apresentado_em < agora` e fecham como
    SEM_RESPOSTA, deixando o lead com as fichas e sem lista -- ou se ela
    deixar de pular o kind ja reservado, porque ai `send` devolve False, a
    ficha 1 entra em `nao_entregues` e a conciliacao apaga a linha do unico
    imovel que o lead viu nas duas passadas.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9C{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RecusaASegundaEFalhaNaTerceira(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[1]:
                raise EnvioRecusado("http 400 codigo 131053")
            if kind == KINDS_DAS_FICHAS[2]:
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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RecusaASegundaEFalhaNaTerceira(get_sessionmaker()), classificador)

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]
    assert len(apresentados) == 3
    gravados = {
        registro.imovel_id
        for registro in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert gravados == {apresentados[0], apresentados[2]}, (
        "premissa: a D8 apagou a linha da ficha recusada ainda na passada 1, entao o "
        "lote que a passada 2 le tem DUAS linhas e nao tres"
    )

    segunda = OutboundFake(get_sessionmaker())
    classificador_2 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, classificador_2) == "respondido"

    assert classificador_2.resultado is None, (
        "a continuacao nao rebusca e nao chama o classificador (D1)"
    )
    assert len(segunda.entregues) == 1, "so a ficha 3 faltava sair"
    assert await _pendentes_da_conversa(session_factory) == (apresentados[0], apresentados[2]), (
        "o recusado nao pode ressuscitar como pendente, e os dois que o lead viu tem de "
        "continuar na mesma ordem -- e essa ordem que o ordinal do proximo turno indexa"
    )


async def test_quando_nada_saiu_a_retentativa_roda_o_turno_inteiro(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275, D4. Ficha 1 falha retentavel: nada chegou, entao recomeca.

    Nao ha o que continuar -- nem fichas, nem a prosa, que viaja com a ficha 1
    e nao esta persistida em lugar nenhum se nao chegou a sair. E o ramo do
    meio do desvio: ha lote, mas nenhum kind dele tem reserva.

    Reprova se o desvio olhar so para a existencia do lote e entrar na
    continuacao -- e o que pega isso e a PROSA, nao a contagem de fichas: a
    continuacao entregaria as tres do mesmo jeito (nenhum kind esta
    reservado), so que mudas. A prosa viaja com a ficha 1 (D5 da TEC-162) e
    nao esta persistida em lugar nenhum, entao so um turno inteiro a regenera;
    sem ela o lead recebe tres fichas soltas e nunca sabe por que.

    E reprova tambem se as linhas orfas da passada 1 forem ignoradas em vez de
    APAGADAS: o `ON CONFLICT DO NOTHING` da gravacao nova preservaria o
    carimbo velho, e `reagir` deste turno receberia tres pendentes de uma
    apresentacao que nunca aconteceu.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9D{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RetentavelNaPrimeira(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[0]:
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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    primeiro = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaPrimeira(get_sessionmaker()), primeiro)

    segunda = OutboundFake(get_sessionmaker())
    segundo = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, segundo) == "respondido"

    assert len(segunda.entregues) == 3, (
        "nada tinha saido, entao a retentativa apresenta as tres do zero"
    )
    assert segundo.resultado is not None, (
        "este ramo roda o turno INTEIRO, e o classificador e quem prova isso"
    )
    assert segundo.resultado.resposta in segunda.entregues[0], (
        "a prosa vai na primeira ficha, e e ela que separa este ramo da continuacao: "
        "a continuacao entregaria as tres fichas tambem (nenhum kind tem reserva), so "
        "que sem prosa nenhuma -- a da passada 1 morreu com ela e nao esta persistida"
    )
    assert segundo.apresentados_recebidos is None, (
        "as linhas orfas da passada 1 foram apagadas, entao nao havia pendente "
        "para `reagir` receber"
    )
    assert len(await _pendentes_da_conversa(session_factory)) == 3


async def test_continuacao_usa_o_kind_persistido_e_nao_a_posicao(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275, D9. O caso que a reconstrucao posicional erra.

    Ficha 1 recusada (a linha dela some na hora, D8) e ficha 3 retentavel. Na
    continuacao o lote tem DUAS linhas, e a que falta e a de kind `ficha_3`.
    Reconstruindo o kind pela posicao dentro do lote, ela viraria `ficha_2` --
    que ja tem reserva --, `send` devolveria False, e a continuacao nao
    enviaria nada: o lead ficaria sem a terceira ficha e com uma pendente que
    nunca viu, que e o defeito de ordinal que esta card existe para fechar.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9E{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RecusaAPrimeiraEFalhaNaTerceira(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[0]:
                raise EnvioRecusado("http 400 codigo 131053")
            if kind == KINDS_DAS_FICHAS[2]:
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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RecusaAPrimeiraEFalhaNaTerceira(get_sessionmaker()), classificador)

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]

    segunda = OutboundFake(get_sessionmaker())
    classificador_2 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, classificador_2) == "respondido"

    assert classificador_2.resultado is None, (
        "a continuacao nao chama o classificador (D1); `resultado` preenchido aqui "
        "significa que o desvio nao foi tomado e o turno recomecou do zero"
    )
    assert len(segunda.entregues) == 1, "so a ficha 3 faltava sair"
    assert await _pendentes_da_conversa(session_factory) == (apresentados[1], apresentados[2]), (
        "a recusada nao pode estar na lista, e a terceira tem de estar -- se a "
        "continuacao reconstruiu o kind pela posicao, a terceira nunca saiu"
    )


async def test_continuacao_grava_so_as_legendas_que_ela_entregou(
    session: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275. A fala do agente que a passada 2 gravou e a dela, e so uma vez.

    A gravacao existe porque a protecao contra o turno SEGUINTE reapresentar
    estes mesmos imoveis e o TEXTO gravado (D16 da TEC-162), nao exclusao por
    id: sem ela o lead receberia as fichas 2 e 3 de novo no proximo turno.
    Sem esta asserta a chamada podia sumir inteira e os dois testes de aceite
    seguiriam verdes -- eles olham para pendentes, nao para a linha do tempo.

    Duas metades. Regravar as legendas da passada 1 duplicaria a fala do
    agente na linha do tempo (a ficha 1 ja saiu la, e a legenda dela chegaria
    ao contexto duas vezes), entao o titulo do primeiro imovel NAO pode estar
    no texto -- e o que `pular` garante ao deixar a ficha 1 fora de
    `legendas`. E uma passada que nao entrega nada nao grava nada: a terceira
    chamada e a varredura reprocessando uma linha cuja continuacao ja tinha
    sucedido (o turno morreu depois dela, antes de a linha virar PROCESSED);
    com os tres kinds reservados ela nao envia ficha nenhuma, e gravar ali
    seria fala fantasma -- texto na linha do tempo que o lead nunca recebeu.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.app.config import MODELO_SEM_CHAMADA
    from mobia.domain.agente.turno import (
        KINDS_DAS_FICHAS,
        SUBAGENTE_CLASSIFICADOR,
        executar_turno,
    )
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    # Titulo distinto por imovel: o `_imovel` deste arquivo da o mesmo titulo a
    # todos e os precos so diferem em centavos, que `reais_de` trunca -- as
    # tres legendas sairiam identicas e nenhuma asserta sobre o TEXTO gravado
    # conseguiria dizer de qual ficha ele veio.
    titulos = {}
    for n in range(3):
        titulo = f"Apartamento numero {n}"
        titulos[await _imovel(session, f"AP-9F{n}", quartos=3, titulo=titulo)] = titulo

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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaSegunda(get_sessionmaker()), classificador)

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]
    assert await _falas_do_agente(session) == [], (
        "premissa: a passada 1 morreu dentro do laco, antes de gravar coisa alguma"
    )

    segunda = OutboundFake(get_sessionmaker())
    classificador_2 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, classificador_2) == "respondido"

    assert classificador_2.resultado is None, (
        "a continuacao nao chama o classificador (D1); `resultado` preenchido aqui "
        "significa que o desvio nao foi tomado e o turno recomecou do zero"
    )

    ((fala, modelo, subagente),) = await _falas_do_agente(session)
    assert titulos[apresentados[1]] in fala
    assert titulos[apresentados[2]] in fala
    assert titulos[apresentados[0]] not in fala, (
        "a legenda da ficha 1 saiu na passada 1; regrava-la duplicaria a fala do agente"
    )
    assert modelo == MODELO_SEM_CHAMADA, (
        "nesta passada nao houve chamada ao modelo -- a prosa, a unica parte que veio "
        'dele, saiu com a ficha 1 na passada anterior. Com `""` a telemetria abriria '
        "um `telemetry.unknown_model` por continuacao"
    )
    assert subagente == SUBAGENTE_CLASSIFICADOR, (
        "estas fichas saem da busca que o classificador fez na passada anterior; um "
        "rotulo proprio partiria a MESMA apresentacao em dois valores de `subagent` "
        "para quem le a telemetria depois"
    )

    terceira = OutboundFake(get_sessionmaker())
    assert (
        await _rodar(terceira, _ClassificadorQueBuscaESemReacao({"operacao": "VENDA"}))
        == "reentrega_suprimida"
    )
    assert terceira.entregues == []
    assert await _falas_do_agente(session) == [(fala, modelo, subagente)], (
        "sem entrega nao ha o que gravar -- uma linha a mais aqui seria texto que o "
        "lead nunca recebeu entrando no contexto do proximo turno"
    )


async def test_janela_fechada_na_continuacao_devolve_expirado(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275. A janela de 24h fechando entre as passadas vira desfecho, nao crash.

    A retentativa e atrasada por construcao -- ela depende da varredura --,
    entao a janela fechar entre as duas passadas nao e hipotese remota. O
    desvio que chama `_continuar_entrega` fica FORA do `try` que o caminho
    normal usa: sem a clausula propria dentro dela, `EnvioForaDaJanela` sai
    crua de `executar_turno`, a linha vira FAILED, a varredura queima as
    tentativas restantes reentrando numa continuacao que nunca vai suceder, e
    o fim e handoff de erro para um corretor.

    Reprova de duas formas: se a clausula sumir, a excecao escapa e o teste
    estoura; se alguem trocar `EnvioForaDaJanela` por `EnvioRecusado` na
    captura de `_entregar_fichas`, a janela fechada seria engolida como "uma
    ficha ruim entre tres" e o desfecho viria "reentrega_suprimida" -- um
    desfecho que mente sobre por que o lead nao recebeu nada.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9G{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RetentavelNaSegunda(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[1]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    class _JanelaJaFechada(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            raise EnvioForaDaJanela("http 400 codigo 131047")

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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaSegunda(get_sessionmaker()), classificador)

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]

    segunda = _JanelaJaFechada(get_sessionmaker())
    classificador_2 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, classificador_2) == "expirado"

    assert classificador_2.resultado is None, (
        "a continuacao nao chama o classificador (D1); `resultado` preenchido aqui "
        "significa que o desvio nao foi tomado e o turno recomecou do zero"
    )
    assert segunda.entregues == []
    assert await _pendentes_da_conversa(session_factory) == tuple(apresentados), (
        "o desfecho sai antes da conciliacao, entao o lote continua inteiro: o lead viu "
        "a ficha 1 e as tres linhas seguem sendo a lista contra a qual ele responde"
    )


async def test_continuacao_le_o_lote_inteiro_mesmo_com_linha_ja_reagida(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-275, D5. `ler_apresentacao_da_mensagem` nao filtra `reacao_lead IS NULL`.

    A ausencia daquele filtro e deliberada e, sem este teste, o codigo passaria
    identico se alguem o acrescentasse por simetria com `ler_pendentes` -- que
    e de onde a ordenacao foi copiada.

    O caso e real: a retentativa depende da varredura, e nesse intervalo o
    lead pode reagir a ficha 1, que ELE JA RECEBEU, por outra mensagem. Com o
    filtro, a linha dela cai fora do lote; sobram os kinds `ficha_2` e
    `ficha_3`, nenhum dos dois reservado, e o desvio deixa de cair na
    continuacao -- cai no ramo do meio, que apaga o resto do lote e roda o
    turno INTEIRO. O classificador rebusca e monta uma apresentacao NOVA, com
    prosa nova, para um pedido que ja foi atendido pela metade, em vez de
    terminar a que ficou pendurada.

    A asserta que separa os dois ramos e a do classificador: so um deles o
    chama.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    titulos = {}
    for n in range(3):
        titulo = f"Apartamento numero {n}"
        titulos[await _imovel(session, f"AP-9H{n}", quartos=3, titulo=titulo)] = titulo

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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    classificador = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaSegunda(get_sessionmaker()), classificador)

    assert classificador.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador.resultado.candidatos]

    # O lead reagiu a ficha que JA recebeu, por outra mensagem, antes de a
    # varredura reprocessar esta.
    reagida = (
        (
            await session.execute(
                select(Recomendacao).where(Recomendacao.imovel_id == apresentados[0])
            )
        )
        .scalars()
        .one()
    )
    reagida.reacao_lead = ReacaoLead.INTERESSE.value
    await session.commit()

    segunda = OutboundFake(get_sessionmaker())
    classificador_2 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, classificador_2) == "respondido"

    assert classificador_2.resultado is None, (
        "com a linha reagida dentro do lote o desvio continua a entrega; se ela cair "
        "fora, o ramo do meio apaga o resto do lote e este classificador teria buscado"
    )
    assert len(segunda.entregues) == 2
    assert titulos[apresentados[1]] in segunda.entregues[0]
    assert titulos[apresentados[2]] in segunda.entregues[1]

    gravados = {
        registro.imovel_id
        for registro in (await session.execute(select(Recomendacao))).scalars().all()
    }
    assert gravados == set(apresentados), "a continuacao nao apaga linha nenhuma do lote"
    assert await _pendentes_da_conversa(session_factory) == (apresentados[1], apresentados[2]), (
        "a reagida sai da lista por ter reacao, e nao por ter sido apagada -- as duas "
        "que o lead acabou de receber continuam sendo a lista do proximo ordinal"
    )


async def test_continuacao_concilia_com_o_carimbo_mais_recente_do_message_id(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """Fix wave. Um `message_id` pode acabar com DOIS carimbos, e a continuacao
    tem de conciliar com o mais recente.

    `gravar_recomendacoes` grava o lote inteiro com um `agora` unico, e o resto
    da continuacao depende disso. Mas `apagar_apresentacao_da_mensagem` -- o
    ramo do meio -- carrega `reacao_lead IS NULL`: uma linha que um
    `gravar_reacoes` intercalado ja fechou NAO e apagada. Dai o turno inteiro
    roda de novo sobre a MESMA mensagem e grava linhas novas com o mesmo
    `message_id` e carimbo novo, e a mensagem fica com dois.

    A montagem abaixo produz exatamente isso em tres passadas:

    1. ficha 1 estoura retentavel -- nada sai, as tres linhas ficam com `t1`;
    2. o lead reage, por outra mensagem, a um imovel daquele lote; a
       retentativa cai no ramo do meio, apaga as duas sem reacao, a reagida
       fica, e o turno inteiro apresenta tres imoveis NOVOS com `t2`. A ficha 2
       estoura retentavel, entao a ficha 1 saiu e ficou reservada;
    3. a terceira passada e continuacao, e a ficha 3 dela e recusada em
       definitivo pela Meta.

    Com `lote[0].apresentado_em` a continuacao pega `t1`, o carimbo da linha
    SOBREVIVENTE. O recorte de `apagar_recomendacao_nao_entregue` e de
    `conciliar_apresentacao` e `apresentado_em == agora`, entao nenhum dos dois
    casa a linha da ficha recusada: ela sobrevive como pendente, e a lista
    volta a ter um imovel que o lead nunca viu -- o ordinal deslocado que e o
    defeito-alvo desta card.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRecusado, EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-9J{n}", quartos=3, preco_venda=30000000 + n)

    linha = await semear_entrada(session)

    class _RetentavelEm(OutboundFake):  # type: ignore[misc, valid-type]
        alvo = KINDS_DAS_FICHAS[0]

        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == self.alvo:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    class _RetentavelNaSegunda(_RetentavelEm):  # type: ignore[misc, valid-type]
        alvo = KINDS_DAS_FICHAS[1]

    class _RecusadaNaTerceira(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DAS_FICHAS[2]:
                raise EnvioRecusado("http 400 codigo 131053")
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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    primeiro = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelEm(get_sessionmaker()), primeiro)
    assert primeiro.resultado is not None
    antigos = [uuid.UUID(c["imovel_id"]) for c in primeiro.resultado.candidatos]
    assert len(antigos) == 3

    # O lead reage, por OUTRA mensagem, a um imovel deste lote. E a linha que
    # sobrevive ao ramo do meio, porque ele so apaga `reacao_lead IS NULL`.
    reagida = (
        (await session.execute(select(Recomendacao).where(Recomendacao.imovel_id == antigos[0])))
        .scalars()
        .one()
    )
    reagida.reacao_lead = ReacaoLead.INTERESSE.value
    await session.commit()

    # Imoveis que so a busca da passada 2 alcanca: sem eles o `ON CONFLICT DO
    # NOTHING` preservaria o carimbo antigo e a mensagem ficaria com um so.
    for n in range(3):
        await _imovel(session, f"AP-9K{n}", quartos=5, preco_venda=40000000 + n)

    segundo = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 5})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaSegunda(get_sessionmaker()), segundo)
    assert segundo.resultado is not None
    novos = [uuid.UUID(c["imovel_id"]) for c in segundo.resultado.candidatos]
    assert len(novos) == 3
    assert set(novos).isdisjoint(antigos), "a passada 2 tem de apresentar imoveis NOVOS"

    carimbos = {
        registro.apresentado_em
        for registro in (
            await session.execute(select(Recomendacao).where(Recomendacao.message_id == linha.id))
        )
        .scalars()
        .all()
    }
    assert len(carimbos) == 2, (
        "a montagem so exercita a defesa se a mensagem de fato ficou com dois "
        f"carimbos; veio {len(carimbos)}"
    )

    terceira = _RecusadaNaTerceira(get_sessionmaker())
    classificador_3 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 5})
    assert await _rodar(terceira, classificador_3) == "respondido"
    assert classificador_3.resultado is None, "a passada 3 e continuacao, e nao turno novo"

    assert await _pendentes_da_conversa(session_factory) == (novos[0], novos[1]), (
        "a ficha 3 foi recusada em definitivo e o lead nunca a viu, entao a linha dela "
        "tem de sumir. Com o carimbo da linha sobrevivente (o mais ANTIGO) nem "
        "`apagar_recomendacao_nao_entregue` nem `conciliar_apresentacao` casam o lote "
        "real, e ela fica na lista que o proximo ordinal numera"
    )


# ---------------------------------------------------------------------------
# TEC-273: a liberacao em grupo nao pode alcancar as fichas da TEC-275.
# ---------------------------------------------------------------------------


async def test_a_continuacao_sobrevive_a_liberacao_em_grupo_da_tec_273(
    session: Any,
    session_factory: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-273, fronteira. A liberacao de irmas nao alcanca as fichas.

    A TEC-275 le as reservas de ficha para saber o que ja saiu. Se a TEC-273
    liberasse por `message_id`, elas sumiriam numa falha retentavel, a
    intersecao ficaria vazia, e `_continuar_entrega` nunca seria tomada -- o
    turno inteiro rodaria de novo, com chamada paga ao modelo, e o lead
    receberia fichas de qualquer jeito. A regressao seria invisivel sem esta
    asserta.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DAS_FICHAS, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    await _conversa_ja_existe(session)
    for n in range(3):
        await _imovel(session, f"AP-8A{n}", quartos=3, preco_venda=30000000 + n)

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
            agendador_de_avisos=AgendadorDeAvisosNoop(),
        )

    classificador_1 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    with pytest.raises(EnvioRetentavel):
        await _rodar(_RetentavelNaSegunda(get_sessionmaker()), classificador_1)

    assert classificador_1.resultado is not None
    apresentados = [uuid.UUID(c["imovel_id"]) for c in classificador_1.resultado.candidatos]

    segunda = OutboundFake(get_sessionmaker())
    classificador_2 = _ClassificadorQueBuscaESemReacao({"operacao": "VENDA", "quartos_min": 3})
    assert await _rodar(segunda, classificador_2) == "respondido"

    assert classificador_2.resultado is None, (
        "a continuacao nao chama o classificador -- ver `resultado` preenchido significa "
        "que o desvio nao foi tomado, e a liberacao em grupo alcancou as fichas"
    )
    assert len(segunda.entregues) == 2, "so as fichas 2 e 3 faltavam sair"
    assert await _pendentes_da_conversa(session_factory) == tuple(apresentados)
