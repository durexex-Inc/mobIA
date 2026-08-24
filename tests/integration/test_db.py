"""hide_parameters do engine (infra/db.py) nao pode ser so promessa em comentario.

SQLAlchemy por padrao ecoa os bind params inteiros na propria mensagem de um
`DBAPIError` -- o bloco `[parameters: (...)]` -- e essa mensagem e exatamente o
que os handlers de `api/routes/whatsapp.py` jogam em `detail=str(exc)`. Sem
`hide_parameters=True`, qualquer INSERT em `messages` que falhe por qualquer
motivo (nao so um relacionado a text_body/raw_payload) vaza todos os bind
params daquele INSERT, inclusive os que nao tem nada a ver com a falha.

O caso aqui e uma violacao de UNIQUE (channel, provider_message_id) -- a mesma
constraint do TEC-125 -- de proposito: a causa raiz da falha (a chave
duplicada) nao tem relacao com o conteudo de `text_body`, o que isola o
mecanismo que este teste prova. Existe um segundo canal de vazamento, mais
estreito, que este teste nao cobre e que `hide_parameters` nao fecha: quando o
proprio driver assincrono rejeita um parametro por tipo incompatível (ex.:
`str` onde a coluna e `bytea`), a mensagem de erro do asyncpg ja embute o valor
antes de a excecao chegar ao SQLAlchemy. Isso e o que hoje aparece nos testes
que ainda passam por `IngestionService`/`service.py` sem cifrar -- e desaparece
quando o TEC-126 (Task 5) passar a escrever bytea de verdade, nao por causa
deste flag.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mobia.infra.db import get_sessionmaker

_INSERIR = text(
    """
    INSERT INTO messages (
        id, channel, provider_message_id, conversation_key,
        role, direction, content_type, text_body
    ) VALUES (
        :id, 'whatsapp', :provider_message_id, '5511911112222',
        'LEAD', 'INBOUND', 'TEXTO', :texto
    )
    """
)


async def test_erro_de_insercao_nao_vaza_bind_params_no_texto_da_excecao() -> None:
    # Bytes crus, sem passar por `encrypt`: o que este teste prova e que o
    # bind param nao vaza pelo mecanismo do SQLAlchemy, nao que a cifra
    # escondesse o segredo -- ciphertext nunca contem o texto claro como
    # substring, e isso tornaria a asercao verdadeira mesmo sem o flag.
    segredo = b"conteudo-sigiloso-que-nao-pode-aparecer-em-log"
    provider_message_id = f"wamid.HIDE_PARAMS.{uuid.uuid4().hex[:8]}"

    async with get_sessionmaker()() as sessao:
        await sessao.execute(
            _INSERIR,
            {
                "id": uuid.uuid4(),
                "provider_message_id": provider_message_id,
                "texto": b"primeira",
            },
        )
        await sessao.commit()

        with pytest.raises(DBAPIError) as excinfo:
            await sessao.execute(
                _INSERIR,
                {
                    "id": uuid.uuid4(),
                    "provider_message_id": provider_message_id,
                    "texto": segredo,
                },
            )
            await sessao.commit()

    mensagem = str(excinfo.value)
    assert segredo not in mensagem.encode(), "o bind param nao pode aparecer no texto da excecao"
    assert "hidden due to hide_parameters" in mensagem, (
        "o engine tem de estar configurado com hide_parameters=True"
    )
