"""O vocabulario fechado de `messages` e garantido pelo banco, nao so pelo enum.

Os dois escritores de hoje passam pelos enums, entao isto e defesa em
profundidade -- para o terceiro escritor, que a TEC-124 traz com o canal web e
que vai gravar sem passar pelo parser da Meta. Duas garantias do sistema
comparam literal em SQL cru (`sweep_stalled.py` e a ancora de
`followup/repositorio.py`), e uma linha com grafia divergente as burla em
silencio.

Os testes montam o `Message` pelo ORM de proposito: nenhuma das quatro colunas
tem validador, entao o ORM aceita a grafia errada de bom grado -- e e
exatamente por isso que a garantia precisa estar no banco.
"""

import re
import uuid
from enum import StrEnum

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.enums import (
    MessageContentType,
    MessageDirection,
    MessageRole,
)
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus


def _mensagem(**sobrescritas: object) -> Message:
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": "whatsapp",
        "provider_message_id": f"wamid.{uuid.uuid4()}",
        "sender_external_id": "5511900000000",
        "recipient_external_id": "5511000000000",
        "conversation_key": "whatsapp:5511900000000",
        "role": "LEAD",
        "direction": "INBOUND",
        "content_type": "TEXTO",
        "status": "RECEIVED",
    }
    campos.update(sobrescritas)
    return Message(**campos)


@pytest.mark.parametrize(
    ("coluna", "valor"),
    [
        ("role", "lead"),
        ("role", "COMPRADOR"),
        ("direction", "inbound"),
        ("direction", "ENTRADA"),
        ("content_type", "text"),
        ("content_type", "TEXT"),
        ("status", "received"),
        ("status", "PENDENTE"),
    ],
)
async def test_grafia_fora_do_vocabulario_e_recusada(
    session: AsyncSession, coluna: str, valor: str
) -> None:
    """`'inbound'` e o caso que motivou a card: o sweeper filtra por 'INBOUND'.

    Uma linha com a grafia minuscula seria varrida, e a fala do proprio agente
    voltaria para `process_message`, que emitiria efeito externo por uma
    mensagem que ninguem enviou.
    """
    session.add(_mensagem(**{coluna: valor}))
    with pytest.raises(IntegrityError, match=f"ck_messages_{coluna}"):
        await session.commit()


@pytest.mark.parametrize("valor", ["LEAD", "AGENTE", "CORRETOR", "SISTEMA"])
async def test_todo_role_legitimo_passa(session: AsyncSession, valor: str) -> None:
    """Inclui CORRETOR e SISTEMA, que nenhum codigo grava hoje: o CHECK espelha
    o enum, e recusar um membro dele seria recusar por engano."""
    session.add(_mensagem(role=valor))
    await session.commit()


@pytest.mark.parametrize("valor", ["INBOUND", "OUTBOUND"])
async def test_toda_direction_legitima_passa(session: AsyncSession, valor: str) -> None:
    session.add(_mensagem(direction=valor))
    await session.commit()


@pytest.mark.parametrize("valor", ["TEXTO", "AUDIO", "IMAGEM", "DOCUMENTO", "DESCONHECIDO"])
async def test_todo_content_type_legitimo_passa(session: AsyncSession, valor: str) -> None:
    """`DESCONHECIDO` e o que `content_type_da_meta` devolve para tipo que nao
    conhecemos, entao e o valor mais provavel de aparecer em producao."""
    session.add(_mensagem(content_type=valor))
    await session.commit()


@pytest.mark.parametrize("valor", ["RECEIVED", "QUEUED", "PROCESSING", "PROCESSED", "FAILED"])
async def test_todo_status_legitimo_passa(session: AsyncSession, valor: str) -> None:
    session.add(_mensagem(status=valor))
    await session.commit()


async def test_status_nulo_continua_passando(session: AsyncSession) -> None:
    """NULL em `status` e semantico, nao ausencia de dado: e o que a linha de
    SAIDA grava (`recorder.py`), e significa "nao participa do pipeline de
    ingestao". Um CHECK que o recusasse quebraria toda mensagem do agente.
    """
    session.add(_mensagem(status=None))
    await session.commit()


_VOCABULARIOS = (
    ("ck_messages_role", MessageRole),
    ("ck_messages_direction", MessageDirection),
    ("ck_messages_content_type", MessageContentType),
    ("ck_messages_status", MessageStatus),
)

# O Postgres reescreve `IN (...)` como `= ANY (ARRAY[...])` e anota o tipo em
# cada literal. Medido contra o banco, nao suposto.
_LITERAL_DO_CHECK = re.compile(r"'([^']+)'::character varying")


@pytest.mark.parametrize(("constraint", "enum"), _VOCABULARIOS)
async def test_o_check_e_o_enum_dizem_a_mesma_coisa(
    session: AsyncSession, constraint: str, enum: type[StrEnum]
) -> None:
    """O vocabulario mora em dois lugares, e eles tem de coincidir.

    Sem esta amarra, acrescentar um membro ao enum e esquecer a migration
    produz `IntegrityError` em producao e silencio na suite -- nenhum teste em
    Python veria a lista do CHECK ficar para tras. E o inverso tambem: um valor
    que saiu do enum e ficou no CHECK deixa o banco aceitando o que o codigo
    ja nao produz.

    Mesma ideia de `test_check_de_especialidades_cobre_todo_o_enum` em
    `test_corretores_schema.py`, nos DOIS sentidos em vez de um.
    """
    clausula = await session.scalar(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :nome"),
        {"nome": constraint},
    )
    assert clausula is not None, f"{constraint} nao existe no banco"

    no_check = set(_LITERAL_DO_CHECK.findall(clausula))
    no_enum = {membro.value for membro in enum}

    assert no_check == no_enum, (
        f"{constraint}: no enum e nao no CHECK = {sorted(no_enum - no_check)}; "
        f"no CHECK e nao no enum = {sorted(no_check - no_enum)}"
    )
