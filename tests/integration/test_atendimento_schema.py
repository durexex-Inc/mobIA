"""A tabela que diz quem assumiu qual conversa. TEC-179, RN-16.4."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mobia.domain.atendimento.models import AtendimentoHumano

pytestmark = pytest.mark.asyncio


async def test_uma_conversa_so_tem_uma_linha(session, semear_corretor, banco_limpo):
    """O UNIQUE e o que faz o 409 "ja assumida por outro" ser do banco.

    Sem ele, duas abas do painel clicando "assumir" ao mesmo tempo gravariam
    duas linhas e as duas se achariam vencedoras -- exatamente o padrao que a
    D6 da TEC-178 e a L4 da TEC-174 existem para eliminar.
    """
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    agora = datetime.now(UTC)
    for _ in range(2):
        session.add(
            AtendimentoHumano(
                id=uuid.uuid4(),
                channel="whatsapp",
                conversation_key="5511988887777",
                assumido_por=corretor_id,
                assumido_em=agora,
                criado_em=agora,
                atualizado_em=agora,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_devolvido_nulo_significa_silenciada(session, semear_corretor, banco_limpo):
    """Nao ha coluna `ativo`: silenciada E `devolvido_em IS NULL` (D4).

    Uma booleana ao lado dos carimbos seria uma segunda representacao do
    mesmo fato, e as duas podem divergir -- a classe de defeito que a revisao
    final da TEC-177 encontrou em `notificado_em`/`aviso_manual_pendente`.
    """
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    agora = datetime.now(UTC)
    session.add(
        AtendimentoHumano(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511988887777",
            assumido_por=corretor_id,
            assumido_em=agora,
            criado_em=agora,
            atualizado_em=agora,
        )
    )
    await session.flush()

    linha = (await session.execute(select(AtendimentoHumano))).scalar_one()
    assert linha.devolvido_em is None
    assert linha.devolvido_por is None
    assert not hasattr(linha, "ativo"), "coluna `ativo` viola a D4 do desenho"
