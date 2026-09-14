"""A queda de preco: a primeira e mais forte fonte de novidade do follow-up.

TEC-184. Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from mobia.domain.agente.models import Recomendacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.models import LeadQualification
from mobia.domain.followup.repositorio import imovel_novo_compativel, queda_de_preco
from mobia.domain.texto import dobrar

CANAL = "whatsapp"
CONVERSA = "5548999990000"


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos. Molde de `tests/integration/test_fichas_do_catalogo.py`."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Trindade",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 59_000_000,
        "bairro": "Trindade",
        "cidade": "Florianopolis",
        "uf": "SC",
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
        "score_match": Decimal("0.870"),
        "motivo_match": "3 quartos, Trindade, dentro do teto",
        "apresentado_em": datetime.now(UTC),
    }
    campos.update(sobrescritas)
    session.add(Recomendacao(**campos))
    await session.commit()


async def test_detecta_a_queda_contra_o_preco_apresentado(session: Any) -> None:
    """D2: a referencia e `recomendacoes.preco_centavos` -- o numero que o lead
    VIU --, e nao o `preco_venda` de hoje dos dois lados.

    O comentario daquela coluna (TEC-275, D3) ja diz que ela e fato historico
    e continua certa depois de o preco do imovel mudar. E por isso que esta
    card nao precisa de tabela de historico.
    """
    imovel = await _imovel(session, "AP-401", preco_venda=59_000_000)
    await _recomendar(session, imovel, preco_centavos=62_000_000)

    queda = await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA)

    assert queda is not None
    assert queda.imovel_id == imovel
    assert queda.preco_antes_centavos == 62_000_000
    assert queda.preco_agora_centavos == 59_000_000


async def test_aumento_de_preco_nao_e_queda(session: Any) -> None:
    """O Gherkin da card diz "reducao"; a regra de negocio diz "mudanca". Vale
    o Gherkin: aumento nao reengaja -- e um motivo a mais para o lead sumir."""
    imovel = await _imovel(session, "AP-402", preco_venda=62_000_000)
    await _recomendar(session, imovel, preco_centavos=59_000_000)

    assert await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA) is None


async def test_preco_igual_nao_e_queda(session: Any) -> None:
    imovel = await _imovel(session, "AP-403", preco_venda=59_000_000)
    await _recomendar(session, imovel, preco_centavos=59_000_000)

    assert await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA) is None


async def test_a_maior_queda_vence(session: Any) -> None:
    """Uma informacao nova por mensagem (D2): com duas quedas, a maior ganha."""
    imovel_a = await _imovel(session, "AP-404", preco_venda=59_000_000)
    await _recomendar(session, imovel_a, preco_centavos=62_000_000)
    imovel_b = await _imovel(session, "AP-405", preco_venda=70_000_000)
    await _recomendar(session, imovel_b, preco_centavos=80_000_000)

    queda = await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA)

    assert queda is not None
    assert queda.imovel_id == imovel_b
    assert queda.preco_agora_centavos == 70_000_000


async def test_sem_recomendacao_nao_ha_referencia(session: Any) -> None:
    """L3 do desenho: lead que nunca recebeu ficha nao tem esta fonte."""
    await _imovel(session, "AP-406", preco_venda=59_000_000)

    assert await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA) is None


async def test_recomendacao_sem_preco_e_ignorada(session: Any) -> None:
    """`Recomendacao.preco_centavos` e nulavel: linha anterior a TEC-275 nao
    tem o numero. Sem referencia, nao ha queda -- e nao um erro."""
    imovel = await _imovel(session, "AP-407", preco_venda=59_000_000)
    await _recomendar(session, imovel, preco_centavos=None)

    assert await queda_de_preco(session, channel=CANAL, conversation_key=CONVERSA) is None


ANCORA = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


async def _qualificar(session: Any, **sobrescritas: object) -> None:
    campos: dict[str, object] = {"channel": CANAL, "conversation_key": CONVERSA}
    campos.update(sobrescritas)
    session.add(LeadQualification(**campos))
    await session.commit()


async def test_imovel_criado_depois_da_ancora_e_novidade(session: Any) -> None:
    """`regiao` chega crua do lead ("sao francisco", sem acento) e compara
    contra `bairro_busca`, que guarda o bairro DOBRADO ("Sao Francisco" com
    cedilha e til). So casam porque os dois lados passam por `dobrar` -- e a
    TEC-160 pagou um Critical justamente por comparar um lado dobrado contra
    o outro cru."""
    await _qualificar(session, regiao="sao francisco", tipo_imovel="APARTAMENTO", quartos=3)
    imovel = await _imovel(
        session,
        "AP-501",
        bairro="São Francisco",
        tipo="APARTAMENTO",
        quartos=3,
        created_at=ANCORA + timedelta(days=1),
    )

    achado = await imovel_novo_compativel(
        session, channel=CANAL, conversation_key=CONVERSA, desde=ANCORA
    )

    assert achado == imovel


async def test_imovel_anterior_a_ancora_nao_e_novidade(session: Any) -> None:
    """ "Novo" e relativo a ultima fala do lead: o que ja existia quando ele
    falou nao e novidade para ele."""
    await _qualificar(session, regiao="sao francisco", tipo_imovel="APARTAMENTO", quartos=3)
    await _imovel(
        session,
        "AP-502",
        bairro="São Francisco",
        tipo="APARTAMENTO",
        quartos=3,
        created_at=ANCORA - timedelta(days=1),
    )

    achado = await imovel_novo_compativel(
        session, channel=CANAL, conversation_key=CONVERSA, desde=ANCORA
    )

    assert achado is None


async def test_imovel_ja_apresentado_nao_e_novidade(session: Any) -> None:
    """Reapresentar o que o lead ja viu e exatamente o "robo carente" que a
    historia da card quer evitar."""
    await _qualificar(session)
    imovel = await _imovel(session, "AP-503", created_at=ANCORA + timedelta(days=1))
    await _recomendar(session, imovel)

    achado = await imovel_novo_compativel(
        session, channel=CANAL, conversation_key=CONVERSA, desde=ANCORA
    )

    assert achado is None


async def test_imovel_fora_dos_criterios_nao_e_novidade(session: Any) -> None:
    await _qualificar(session, regiao="Centro", quartos=3)
    await _imovel(
        session,
        "AP-504",
        bairro="Centro",
        quartos=1,
        created_at=ANCORA + timedelta(days=1),
    )

    achado = await imovel_novo_compativel(
        session, channel=CANAL, conversation_key=CONVERSA, desde=ANCORA
    )

    assert achado is None


async def test_lead_sem_criterio_nenhum_aceita_qualquer_imovel_novo(session: Any) -> None:
    """Todo criterio e nulavel, e nulo significa "o lead nao disse" -- nao
    "nenhum imovel serve". Filtrar por campo ausente devolveria sempre vazio e
    mataria a fonte para quem mal comecou a conversar."""
    await _qualificar(session)
    imovel = await _imovel(session, "AP-505", created_at=ANCORA + timedelta(days=1))

    achado = await imovel_novo_compativel(
        session, channel=CANAL, conversation_key=CONVERSA, desde=ANCORA
    )

    assert achado == imovel


async def test_imovel_indisponivel_nao_e_novidade(session: Any) -> None:
    await _qualificar(session)
    await _imovel(
        session,
        "AP-506",
        status="VENDIDO",
        created_at=ANCORA + timedelta(days=1),
    )

    achado = await imovel_novo_compativel(
        session, channel=CANAL, conversation_key=CONVERSA, desde=ANCORA
    )

    assert achado is None
