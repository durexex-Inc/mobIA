"""A recusa de campo: coluna, gravacao e as duas leituras.

TEC-148.
"""

from sqlalchemy import select

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _linha(session, **ajustes: object) -> LeadQualification:
    """Os quatro obrigatorios preenchidos, menos o que o teste mudar."""
    base: dict[str, object] = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.ATE_3_MESES.value,
    }
    linha = LeadQualification(**{**base, **ajustes})
    session.add(linha)
    await session.commit()
    return linha


async def test_a_coluna_aceita_lista_e_devolve_lista(session) -> None:
    await _linha(session, campos_recusados=["faixa_preco_max"])

    gravada = (await session.scalars(select(LeadQualification))).one()
    assert gravada.campos_recusados == ["faixa_preco_max"]


async def test_null_e_vazio_sao_estados_diferentes_na_coluna(session) -> None:
    """`NULL` e "linha anterior a esta card, ninguem registrava"; `{}` e
    "registrava, e nao havia recusa". Quem le trata os dois igual, mas a
    coluna guarda a diferenca."""
    await _linha(session, campos_recusados=None)
    nula = (await session.scalars(select(LeadQualification))).one()
    assert nula.campos_recusados is None

    nula.campos_recusados = []
    await session.commit()
    vazia = (await session.scalars(select(LeadQualification))).one()
    assert vazia.campos_recusados == []
