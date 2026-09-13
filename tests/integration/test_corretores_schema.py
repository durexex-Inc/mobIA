"""O schema de `corretores` e a FK que a emenda E-02 da RN-16.1 prometeu."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.vocabulario import Especialidade
from mobia.domain.handoff.models import Handoff


def _corretor(**sobrescritas: object) -> Corretor:
    # criado_em/atualizado_em nao tem server_default -- mesma disciplina de
    # `Handoff`, cujo repositorio (repositorio.py) tambem os preenche na mao.
    # Sem um repositorio de Corretor ainda (Task 3), o teste de schema e quem
    # precisa fornecer os dois, como `test_handoff_schema.py::_linha` ja faz.
    agora = datetime.now(UTC)
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "nome": "Paulo Ribeiro",
        "email": "paulo@imobiliaria.com.br",
        "telefone": "5511988887777",
        "creci": "SP-123456",
        "especialidades": ["COMPRA", "INVESTIMENTO"],
        "regioes_atuacao": ["zona sul"],
        "horario_inicio": 9,
        "horario_fim": 18,
        "capacidade_diaria": 4,
        "plantao": False,
        "ativo": True,
        "criado_em": agora,
        "atualizado_em": agora,
    }
    return Corretor(**(campos | sobrescritas))  # type: ignore[arg-type]


async def test_corretor_completo_grava(session: AsyncSession) -> None:
    session.add(_corretor())
    await session.commit()

    linha = (await session.execute(select(Corretor))).scalar_one()
    assert linha.especialidades == ["COMPRA", "INVESTIMENTO"]
    assert linha.horario_inicio == 9
    assert linha.ativo is True


async def test_email_e_unico(session: AsyncSession) -> None:
    """A unica defesa contra corretor duplicado -- ver a D1 do desenho.

    E a razao pela qual o contato NAO e cifrado: nonce aleatorio faz a busca
    por igualdade deixar de existir, e com ela este UNIQUE.
    """
    session.add(_corretor())
    await session.commit()

    session.add(_corretor(email="paulo@imobiliaria.com.br"))
    with pytest.raises(IntegrityError, match="uq_corretores_email"):
        await session.commit()


async def test_jornada_invertida_e_recusada_pelo_banco(session: AsyncSession) -> None:
    session.add(_corretor(horario_inicio=18, horario_fim=9))
    with pytest.raises(IntegrityError, match="ck_corretores_jornada"):
        await session.commit()


async def test_capacidade_zero_e_recusada_pelo_banco(session: AsyncSession) -> None:
    session.add(_corretor(capacidade_diaria=0))
    with pytest.raises(IntegrityError, match="ck_corretores_capacidade"):
        await session.commit()


async def test_especialidade_fora_do_vocabulario_e_recusada(session: AsyncSession) -> None:
    """O CHECK guarda o vocabulario no banco, como `ck_handoffs_status` faz."""
    session.add(_corretor(especialidades=["ASTROLOGIA"]))
    with pytest.raises(IntegrityError, match="ck_corretores_especialidades"):
        await session.commit()


async def test_corretor_sem_especialidade_e_recusado(session: AsyncSession) -> None:
    session.add(_corretor(especialidades=[]))
    with pytest.raises(IntegrityError, match="ck_corretores_especialidades"):
        await session.commit()


async def test_handoff_aponta_para_corretor_existente(session: AsyncSession) -> None:
    """A emenda E-03 da RN-16.1: a FK enfim existe."""
    corretor = _corretor()
    session.add(corretor)
    await session.commit()

    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511911112222",
            gatilho="LEAD_QUENTE",
            etiqueta="lead-quente",
            prioridade="NORMAL",
            status="PENDENTE",
            corretor_id=corretor.id,
            gatilhos_adicionais=[],
            criado_em=datetime.now(UTC),
            atualizado_em=datetime.now(UTC),
        )
    )
    await session.commit()

    gravado = (await session.execute(select(Handoff.corretor_id))).scalar_one()
    assert gravado == corretor.id


async def test_handoff_com_corretor_inexistente_e_recusado(session: AsyncSession) -> None:
    """Antes desta card isto passava, porque nao havia FK."""
    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511911112222",
            gatilho="LEAD_QUENTE",
            etiqueta="lead-quente",
            prioridade="NORMAL",
            status="PENDENTE",
            corretor_id=uuid.uuid4(),
            gatilhos_adicionais=[],
            criado_em=datetime.now(UTC),
            atualizado_em=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError, match="fk_handoffs_corretor"):
        await session.commit()


async def test_corretor_continua_opcional_no_handoff(session: AsyncSession) -> None:
    """A nulabilidade permanece: alocar e a TEC-166, nao esta card."""
    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511911112222",
            gatilho="LEAD_QUENTE",
            etiqueta="lead-quente",
            prioridade="NORMAL",
            status="PENDENTE",
            gatilhos_adicionais=[],
            criado_em=datetime.now(UTC),
            atualizado_em=datetime.now(UTC),
        )
    )
    await session.commit()

    assert (await session.execute(select(Handoff.corretor_id))).scalar_one() is None


async def test_a_tabela_entrou_no_truncate_dos_testes() -> None:
    """Sem isto, o corretor de um teste vira o duplicado do proximo."""
    from tests.conftest import TABELAS

    assert "corretores" in TABELAS


async def test_check_de_especialidades_cobre_todo_o_enum(session: AsyncSession) -> None:
    """O vocabulario mora em dois lugares -- o enum `Especialidade` e o
    literal dentro do CHECK `ck_corretores_especialidades` --, exatamente como
    `ck_handoffs_status` ja duplica o enum `Status`. O repo nao tinha teste
    amarrando os dois lados daquele precedente, e sem essa amarra acrescentar
    um membro ao enum e esquecer de tocar a migration produz `IntegrityError`
    em producao e silencio na suite: nenhum teste em Python veria a lista do
    CHECK ficar para tras. Este teste le a clausula de volta do catalogo do
    Postgres (`pg_constraint`) e confere que todo valor do enum aparece nela.
    """
    clausula = await session.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_corretores_especialidades'"
        )
    )
    assert clausula is not None
    for especialidade in Especialidade:
        assert especialidade.value in clausula
