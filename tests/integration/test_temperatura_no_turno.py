"""A temperatura persistida, os dois CHECK, e a borda que notifica.

TEC-151. Integracao: os CHECK vivem no banco, e o forcamento so significa
algo se sobreviver a uma transacao.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.context.models import LeadQualification

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque a Task 6 roda `rodar_turno`, que semeia a fala nessa conversa -- os
# testes de turno leem a linha por esta chave. `test_turno.py` redefine os dois
# localmente do mesmo jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"


def _linha(**campos) -> LeadQualification:
    """Os quatro obrigatorios preenchidos, menos o que o teste sobrescrever."""
    base = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.IMEDIATA.value,
    }
    return LeadQualification(**{**base, **campos})


async def test_as_tres_colunas_nascem_nulas(session) -> None:
    """`NULL` em `temperatura` significa "nunca recalculada", e e contra esse
    `NULL` que a borda da notificacao compara. Nao ha backfill: um backfill
    para FRIO apagaria a distincao entre "nunca calculei" e "ja era FRIO"."""
    session.add(_linha())
    await session.commit()

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura is None
    assert carregada.temperatura_forcada_em is None
    assert carregada.temperatura_forcada_motivos is None


async def test_o_check_recusa_forcamento_que_nao_seja_quente(session) -> None:
    """Forcado implica QUENTE. Sem o CHECK, uma linha pode afirmar as duas
    coisas contrarias e nada reclama."""
    session.add(
        _linha(
            temperatura="MORNO",
            temperatura_forcada_em=datetime.now(UTC),
            temperatura_forcada_motivos=["VISITA"],
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_o_check_recusa_forcamento_sem_motivo(session) -> None:
    """Molde do `CHECK (cardinality(causas) > 0)` da 0012, e pela mesma razao:
    uma linha que afirma que o lead foi forcado a QUENTE sem nomear o que o
    forcou e a mesma forma de mentira. `NOT NULL` cobriria metade -- o array
    vazio passaria."""
    session.add(
        _linha(
            temperatura="QUENTE",
            temperatura_forcada_em=datetime.now(UTC),
            temperatura_forcada_motivos=[],
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_temperatura_sem_forcamento_e_livre(session) -> None:
    """Os dois CHECK sao condicionais a `temperatura_forcada_em`: uma
    temperatura derivada, sem forcamento, aceita qualquer das tres."""
    session.add(_linha(temperatura="FRIO"))
    await session.commit()

    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.temperatura == "FRIO"
    assert carregada.temperatura_forcada_em is None
