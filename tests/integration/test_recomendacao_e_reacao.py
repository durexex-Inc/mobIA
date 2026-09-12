"""A recomendacao e a reacao do lead, contra o banco.

TEC-163. Os quatro cenarios do Gherkin da card, mais o que o desenho decidiu.
Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.repositorio import gravar_recomendacoes
from mobia.domain.agente.schemas import CategoriaDescarte, ReacaoLead
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


async def test_candidato_sem_score_fica_de_fora_e_nao_vira_zero(
    session: Any, session_factory: Any
) -> None:
    """Um candidato ausente de `scores` e descartado, nunca gravado com 0.0.

    `0.0` tornaria `score_match` decorativa e derrubaria a premissa do D4 --
    ver o docstring de `gravar_recomendacoes`. O outro candidato da mesma
    chamada, que TEM score, grava normalmente.
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

    linhas = (await session.execute(select(Recomendacao))).scalars().all()
    assert {linha.imovel_id for linha in linhas} == {com_score}


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
