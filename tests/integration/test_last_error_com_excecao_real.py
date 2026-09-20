"""O que uma excecao REAL do driver carrega, e o que dela chega a coluna.

A TEC-222 pede este teste por escrito: "o teste forca uma excecao real do
banco, nao um `raise ValueError(...)` sintetico -- o formato da mensagem do
driver e justamente o que importa". Duble nenhum reproduz esse formato, porque
o que se investiga aqui e uma decisao do asyncpg, nao deste projeto.
"""

import uuid

from sqlalchemy import insert

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.infra.db import get_engine
from mobia.workers.jobs.process_message import _detalhe_para_a_coluna

# Cabe nos 38 caracteres que o asyncpg ecoa antes de truncar -- medido na
# TEC-222. Um sentinela mais longo nunca apareceria inteiro em `str(exc)`, e a
# primeira asserta abaixo reprovaria por uma razao que nao e a investigada.
SENTINELA = "SENTINELA rua das palmeiras 2 quartos"


async def test_excecao_real_do_driver_ecoa_o_valor_e_a_coluna_nao() -> None:
    """O eco do driver existe; o que vai para `last_error` nao o carrega.

    O `insert()` de Core passa ao largo do `@validates("text_body", ...)` do
    ORM, que rejeitaria o `str` antes de qualquer viagem ao banco. E e esse
    desvio que reproduz o caso: o asyncpg monta a mensagem de erro dele com o
    valor ofensivo dentro, ANTES de a SQLAlchemy ver qualquer coisa -- entao o
    `hide_parameters=True` de `infra/db.py`, que aparece na mesma string logo
    abaixo, nao o alcanca.

    **As duas assertas sao necessarias.** Sem a primeira, este teste
    continuaria verde no dia em que o driver parasse de ecoar o valor, e seria
    uma asserta de ausencia sempre satisfeita -- a classe de defeito que a
    TEC-289 tratou.
    """
    async with get_engine().begin() as conn:
        try:
            await conn.execute(
                insert(Message).values(
                    id=uuid.uuid4(),
                    channel="whatsapp",
                    conversation_key="5511911112222",
                    role=MessageRole.LEAD,
                    direction=MessageDirection.INBOUND,
                    content_type=MessageContentType.TEXTO,
                    # `str` numa coluna `bytea`: e o descasamento de tipo que a
                    # card reproduziu na review da TEC-126.
                    text_body=SENTINELA,
                )
            )
        except Exception as exc:
            assert SENTINELA in str(exc), "o driver deixou de ecoar o valor; o teste perdeu o alvo"
            assert type(exc).__module__ == "sqlalchemy.exc"
            assert SENTINELA not in _detalhe_para_a_coluna(exc)
            assert _detalhe_para_a_coluna(exc) == "DBAPIError"
        else:
            raise AssertionError("o INSERT deveria ter falhado com erro de tipo do driver")
