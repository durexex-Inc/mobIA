import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text as sql

from mobia.domain.context.models import ConversationSummary, LeadQualification, aad_do_resumo
from mobia.domain.context.repositorio import gravar_resumo, ler_estado, ler_resumo
from mobia.infra.crypto import DecryptionError, decrypt

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def gravar(session, texto: str = "lead procura apto de 2 quartos na zona sul") -> uuid.UUID:
    marca = uuid.uuid4()
    await gravar_resumo(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        texto=texto,
        watermark_created_at=datetime.now(UTC),
        watermark_message_id=marca,
        mensagens_cobertas=40,
        modelo="claude-opus-5",
    )
    # gravar_resumo nao commita -- quem chama e dono da fronteira da transacao.
    await session.commit()
    return marca


async def test_resumo_faz_roundtrip(session) -> None:
    marca = await gravar(session)

    lido = await ler_resumo(session, CANAL, CONVERSA)
    assert lido is not None
    assert lido.texto == "lead procura apto de 2 quartos na zona sul"
    assert lido.watermark_message_id == marca
    assert lido.mensagens_cobertas == 40
    assert lido.modelo == "claude-opus-5"


async def test_resumo_vai_cifrado_para_o_banco(session) -> None:
    """Um resumo destila as mesmas frases que text_body guarda."""
    await gravar(session)

    cru = await session.scalar(
        sql(
            "SELECT resumo FROM conversation_summaries WHERE channel = :c AND conversation_key = :k"
        ),
        {"c": CANAL, "k": CONVERSA},
    )
    assert b"zona sul" not in bytes(cru)


async def test_resumo_de_outra_conversa_nao_decifra(session) -> None:
    """O AAD amarra o resumo a sua propria conversa."""
    await gravar(session)

    cru = await session.scalar(
        sql(
            "SELECT resumo FROM conversation_summaries WHERE channel = :c AND conversation_key = :k"
        ),
        {"c": CANAL, "k": CONVERSA},
    )
    with pytest.raises(DecryptionError):
        decrypt(bytes(cru), aad_do_resumo(CANAL, "5511999998888"))


async def test_gravar_duas_vezes_atualiza_em_vez_de_duplicar(session) -> None:
    """Uma conversa tem um resumo, nao um historico deles."""
    await gravar(session, "primeira versao")
    await gravar(session, "segunda versao")

    lido = await ler_resumo(session, CANAL, CONVERSA)
    assert lido is not None
    assert lido.texto == "segunda versao"

    total = await session.scalar(sql("SELECT count(*) FROM conversation_summaries"))
    assert total == 1


async def test_marca_nunca_anda_para_tras(session) -> None:
    """Dois turnos concorrentes nao podem recuar a marca.

    Ambos leem o mesmo estado, dobram e gravam. Sem a guarda de monotonia o
    mais lento sobrescreve o mais rapido, a marca recua e as mensagens entre
    as duas marcas voltam a ser dobradas -- conteudo duplicado no resumo, para
    sempre.
    """
    recente = datetime.now(UTC)
    antiga = recente - timedelta(minutes=10)

    await gravar_resumo(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        texto="resumo do turno rapido",
        watermark_created_at=recente,
        watermark_message_id=uuid.uuid4(),
        mensagens_cobertas=40,
        modelo="claude-opus-5",
    )
    await session.commit()

    await gravar_resumo(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        texto="resumo do turno lento",
        watermark_created_at=antiga,
        watermark_message_id=uuid.uuid4(),
        mensagens_cobertas=20,
        modelo="claude-opus-5",
    )
    await session.commit()

    lido = await ler_resumo(session, CANAL, CONVERSA)
    assert lido is not None
    assert lido.watermark_created_at == recente, "a marca so anda para frente"
    assert lido.texto == "resumo do turno rapido"


async def test_marca_igual_ainda_grava_a_compressao(session) -> None:
    """`<=` e nao `<`: comprimir regrava a mesma marca de proposito.

    A compressao so encurta o texto -- nao cobre mensagem nova, entao a marca
    e identica. Com `<` estrito o texto comprimido seria descartado em
    silencio e a conversa pagaria a mesma compressao todo turno.
    """
    marca = datetime.now(UTC)
    identificador = uuid.uuid4()
    for texto in ("resumo dobrado", "resumo comprimido"):
        await gravar_resumo(
            session,
            channel=CANAL,
            conversation_key=CONVERSA,
            texto=texto,
            watermark_created_at=marca,
            watermark_message_id=identificador,
            mensagens_cobertas=40,
            modelo="claude-opus-5",
        )
        await session.commit()

    lido = await ler_resumo(session, CANAL, CONVERSA)
    assert lido is not None
    assert lido.texto == "resumo comprimido"


async def test_conversa_sem_resumo_devolve_none(session) -> None:
    assert await ler_resumo(session, CANAL, "nunca-falou") is None


async def test_estado_de_qualificacao_e_lido_do_banco(session) -> None:
    """TEC-127 le; quem escreve e TEC-145."""
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao="COMPRA",
            faixa_preco_max=Decimal("600000.00"),
            regiao="zona sul",
            quartos=2,
        )
    )
    await session.commit()

    estado = await ler_estado(session, CANAL, CONVERSA)
    assert estado is not None
    assert estado.faixa_preco_max == Decimal("600000.00")
    assert estado.regiao == "zona sul"
    assert estado.vagas is None, "campo nao informado fica nulo, nao zero"


async def test_estado_ausente_devolve_none(session) -> None:
    assert await ler_estado(session, CANAL, "nunca-falou") is None


def test_aad_do_resumo_e_injetivo_sobre_channel_e_key() -> None:
    """`channel` nao tem whitelist de caracteres -- sem prefixo de tamanho, dois pares
    diferentes colapsariam no mesmo AAD e um resumo decifraria sob a chave de outra
    conversa."""
    assert aad_do_resumo("a:b", "c") != aad_do_resumo("a", "b:c")


def test_texto_claro_no_resumo_e_recusado() -> None:
    """Mesma guarda de `Message`: str aqui vira vazamento no texto do erro."""
    with pytest.raises(TypeError) as erro:
        ConversationSummary(
            channel=CANAL,
            conversation_key=CONVERSA,
            resumo="quero apto na zona sul",
            watermark_created_at=datetime.now(UTC),
            watermark_message_id=uuid.uuid4(),
            mensagens_cobertas=1,
            modelo="claude-opus-5",
        )

    assert "resumo" in str(erro.value)
    assert "zona sul" not in str(erro.value)
