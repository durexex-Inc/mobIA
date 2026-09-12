"""A recomendacao e a reacao do lead, contra o banco.

TEC-163. Os quatro cenarios do Gherkin da card, mais o que o desenho decidiu.
Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.repositorio import (
    _TABELA_IMOVEIS,
    gravar_reacoes,
    gravar_recomendacoes,
    ler_pendentes,
)
from mobia.domain.agente.schemas import CategoriaDescarte, ReacaoDoImovel, ReacaoLead
from mobia.domain.catalogo.models import Imovel
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
    formato de `imoveis`: se alguem renomear `id`, `titulo` ou `bairro` em
    `Imovel`, nada falha em import nem em mypy, porque `_TABELA_IMOVEIS` nao
    referencia `Imovel` nenhum -- o JOIN de `ler_pendentes` so quebraria em
    tempo de consulta, em producao. E o mesmo risco que `COLUNA_DE_PRECO`
    (`catalogo/schemas.py`) existe para fechar do lado do preco; aqui, este
    teste e a guarda: ele roda no arquivo de teste, que ja importa `Imovel`
    porque a fronteira de `ferramenta_de_busca.py` e sobre `src/`, nao sobre
    `tests/`.
    """
    colunas_de_imovel = Imovel.__table__.columns
    for nome in ("id", "titulo", "bairro"):
        assert nome in colunas_de_imovel, (
            f"'{nome}' sumiu de Imovel.__table__.columns -- _TABELA_IMOVEIS em "
            "repositorio.py ainda a nomeia, e ler_pendentes quebraria em consulta"
        )
    assert set(_TABELA_IMOVEIS.columns.keys()) == {"id", "titulo", "bairro"}
