"""A quebra de resposta longa em ate duas mensagens, dentro do turno. TEC-140.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_apresentacao_no_turno.py` e `test_citacao_no_turno.py`.
"""

from typing import Any

from sqlalchemy import select

from mobia.domain.outbound.models import OutboundDispatch
from mobia.infra.db import get_sessionmaker


async def _kinds_reservados() -> list[str]:
    async with get_sessionmaker()() as leitura:
        return sorted((await leitura.scalars(select(OutboundDispatch.kind))).all())


async def _conversa_ja_existe(session: Any) -> None:
    """Semeia uma entrada anterior para que `e_conversa_nova` veja a
    conversa como NAO nova (TEC-139).

    Copiado de `test_apresentacao_no_turno.py`, e nao importado -- os arquivos
    de integracao deste repo sao autocontidos. Nenhum teste deste arquivo e
    sobre identificacao (que tem arquivo proprio,
    `test_identificacao_no_turno.py`): sem isto, `banco_limpo` (autouse)
    deixa cada teste comecar em silencio total, `e_conversa_nova` devolveria
    True e o prefixo de identificacao entraria no `texto` do turno --
    contaminando a comparacao caractere-a-caractere com `longa` que estes
    testes fazem.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


async def test_resposta_curta_continua_saindo_numa_mensagem_so(
    session: Any,
    classificador_fake: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    rodar_turno: Any,
) -> None:
    """O caminho de 99% dos turnos, e o que esta card nao pode quebrar. Uma
    regressao aqui faria todo lead receber duas mensagens para atender ao 1 em
    10 que estoura os 600.
    """
    await _conversa_ja_existe(session)
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert len(outbound.entregues) == 1
    assert await _kinds_reservados() == ["reply"]


async def test_resposta_longa_sai_em_duas_mensagens_com_kinds_distintos(
    session: Any,
    classificador_fake: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    rodar_turno: Any,
) -> None:
    """E o texto entregue, concatenado, e o texto que o modelo gerou -- nada se
    perde entre a geracao e o WhatsApp do lead.
    """
    await _conversa_ja_existe(session)
    longa = "Encontrei uma opcao muito boa para voce no centro da cidade. " * 12
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(resposta=longa),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert len(outbound.entregues) == 2
    assert await _kinds_reservados() == ["reply", "reply_2"]
    assert "".join(outbound.entregues).replace(" ", "") == longa.replace(" ", "")


async def test_o_recorder_grava_o_texto_inteiro_numa_linha_so(
    session: Any,
    classificador_fake: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    rodar_turno: Any,
) -> None:
    """A transcricao carrega o conteudo completo, e nao a fronteira entre as
    duas mensagens. Declarado na secao de testes do desenho: o corretor que ler
    o handoff ve o texto inteiro, mas nao ve que o lead o recebeu em duas
    partes. Este teste existe para que essa diferenca seja uma escolha
    registrada, e nao uma surpresa em auditoria.
    """
    from mobia.domain.messages.enums import MessageRole
    from mobia.domain.messages.models import Message
    from mobia.infra.crypto import aad_de, decrypt

    await _conversa_ja_existe(session)
    longa = "Encontrei uma opcao muito boa para voce no centro da cidade. " * 12
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(resposta=longa),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    faladas = (
        await session.scalars(select(Message).where(Message.role == MessageRole.AGENTE))
    ).all()
    assert len(faladas) == 1
    gravado = decrypt(faladas[0].text_body, aad_de(faladas[0].id, "text_body"))
    assert gravado == longa
