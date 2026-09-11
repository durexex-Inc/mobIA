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


async def test_o_prefixo_da_identificacao_conta_para_os_600(
    session: Any,
    classificador_fake: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    rodar_turno: Any,
) -> None:
    """A identificacao da TEC-139 e prefixada ANTES da quebra, entao ela
    empurra o texto para cima dos 600. Uma resposta que caberia sozinha pode
    passar a quebrar por causa dela -- e a interacao que ninguem conferiria,
    porque cada card sozinha esta certa.

    Nao chama `_conversa_ja_existe` DE PROPOSITO -- ao contrario de todo outro
    teste deste arquivo. O ponto aqui e o oposto do que aquele helper garante:
    este teste precisa que a conversa seja NOVA para que
    `TEXTO_DA_IDENTIFICACAO` (131 caracteres) mais o separador (2) sejam
    prefixados a `texto` antes da quebra. Chamar o helper apagaria a propria
    soma que o teste existe para provar, e ele passaria medindo outra coisa.
    """
    # 131 (identificacao) + 2 (separador) + 510 (este texto) = 643 > 600.
    quase = "Uma frase de tamanho medio para encher a resposta. " * 10  # 510 chars
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(resposta=quase),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert len(outbound.entregues) == 2, (
        "em conversa nova a identificacao soma 133 chars e deveria empurrar "
        "este texto de 510 para duas mensagens"
    )


async def test_o_teto_de_duas_mensagens_de_texto_vale_no_pior_caso(
    session: Any,
    classificador_fake: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    rodar_turno: Any,
) -> None:
    """A terceira clausula da RN-04.2, que ate agora era verdade por
    construcao e nao tinha nada travando. O pior caso soma identificacao e
    quebra: se alguem acrescentar uma terceira mensagem de texto no futuro,
    reprova aqui.
    """
    await _conversa_ja_existe(session)
    longa = "Uma frase bem longa para forcar a quebra da resposta. " * 30
    outbound = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(resposta=longa),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert len(outbound.entregues) <= 2


async def test_segunda_parte_recusada_nao_apaga_a_primeira_ja_entregue(
    session: Any,
    classificador_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    rodar_turno: Any,
) -> None:
    """Fix round 1 (TEC-140). Antes deste teste, uma recusa permanente na
    SEGUNDA parte fazia a excecao subir crua -- e como `EnvioRecusado` e
    capturada DENTRO de `executar_turno`, o turno terminava em
    "sem_resposta" ANTES do recorder gravar. O lead ja tinha recebido a
    primeira parte de verdade, mas a transcricao ficava muda sobre aquele
    turno inteiro, do mesmo jeito que ficaria se nada tivesse saido -- as
    duas situacoes eram indistinguiveis para quem le o handoff.

    Copia o padrao de `test_recusa_permanente_numa_ficha_nao_cala_as_outras`
    em `test_apresentacao_no_turno.py`: subclasse de `OutboundFake` que
    recusa so um `kind` especifico, porque o duble compartilhado
    (`outbound_fake`) so aceita um erro para TODAS as chamadas.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.formato import quebrar_em_mensagens
    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA
    from mobia.domain.messages.enums import MessageRole
    from mobia.domain.messages.models import Message
    from mobia.domain.outbound.port import EnvioRecusado
    from mobia.infra.crypto import aad_de, decrypt

    await _conversa_ja_existe(session)
    longa = "Encontrei uma opcao muito boa para voce no centro da cidade. " * 12
    primeira_parte, _segunda_parte = quebrar_em_mensagens(longa)

    class _RecusaASegundaMensagem(OutboundFake):
        async def _deliver(self, message_id: Any, kind: Any, payload: Any) -> None:
            if kind == KINDS_DA_RESPOSTA[1]:
                raise EnvioRecusado("http 400 codigo 131053")
            await super()._deliver(message_id, kind, payload)

    outbound = _RecusaASegundaMensagem(get_sessionmaker())

    resultado = await rodar_turno(
        session,
        classificador_fake(resposta=longa),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    # O turno segue "respondido": a primeira parte chegou, e nao ha por que
    # tratar isto como turno mudo (a diferenca com "sem_resposta" e exatamente
    # o que este teste existe para travar).
    assert resultado == "respondido"
    assert outbound.entregues == [primeira_parte]
    # A reserva da segunda parte FICA -- `EnvioRecusado` nao libera (so
    # `EnvioRetentavel`/cancelamento liberam, ver `GuardedOutbound.send`).
    # Sem a reserva presa, o sweeper tentaria reentregar um payload que a
    # Meta ja recusou de forma permanente.
    assert await _kinds_reservados() == ["reply", "reply_2"]

    faladas = (
        await session.scalars(select(Message).where(Message.role == MessageRole.AGENTE))
    ).all()
    assert len(faladas) == 1
    gravado = decrypt(faladas[0].text_body, aad_de(faladas[0].id, "text_body"))
    # So a parte que de fato saiu -- gravar `longa` inteira aqui trocaria a
    # mentira "nada saiu" pela mentira "saiu tudo", que e o proprio defeito
    # que este fix corrige. `len(gravado) < len(longa)` prova que nao e o
    # texto inteiro (um `in` contra `_segunda_parte` nao provaria nada: a
    # frase se repete dentro de `longa`, entao ela aparece dentro da PRIMEIRA
    # parte tambem).
    assert gravado == primeira_parte
    assert len(gravado) < len(longa)
