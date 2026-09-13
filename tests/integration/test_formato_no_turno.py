"""A quebra de resposta longa em ate duas mensagens, dentro do turno. TEC-140.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_apresentacao_no_turno.py` e `test_citacao_no_turno.py`.
"""

import logging
import uuid
from typing import Any

import pytest
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
    """A terceira clausula da RN-04.2 (emenda E-02): no maximo
    `MAX_MENSAGENS_DE_TEXTO` mensagens de texto por turno. Ate esta card, isso
    era verdade so por construcao -- nada no repositorio reprovava se deixasse
    de ser.

    NAO chama `_conversa_ja_existe`, ao contrario dos outros dois testes deste
    arquivo, e pelo MESMO motivo do primeiro: a conversa precisa ficar NOVA
    para a identificacao (133 caracteres) somar ao texto e o pior caso ser o
    de verdade -- identificacao MAIS quebra, nao so a quebra sozinha (que
    `test_resposta_longa_sai_em_duas_mensagens_com_kinds_distintos` ja cobre
    com `_conversa_ja_existe`). Chamar o helper aqui removeria exatamente a
    soma que faz este ser o pior caso, e o teste voltaria a nao travar nada
    que o outro teste de quebra nao trave.

    Honestidade sobre o alcance: hoje `quebrar_em_mensagens` nunca devolve
    mais que duas partes (ver o docstring dela, em `formato.py`), entao este
    teste nao reprova por acidente -- e guarda contra mudanca FUTURA e
    deliberada: quebra virar recursiva, `MAX_MENSAGENS_DE_TEXTO` subir, ou a
    identificacao passar a virar mensagem propria tambem no caminho sem
    apresentacao. Se algum desses acontecer, o teto de duas mensagens de texto
    da RN-04.2 seria estourado e este teste e quem reprova.
    """
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


async def test_reserva_duplicada_na_segunda_parte_apos_entrega_vira_reentrega_suprimida(
    session: Any,
    classificador_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    caplog: Any,
) -> None:
    """Critical 1 da revisao final (TEC-140), a outra causa nomeada pelo
    docstring de `OutboundPort`: reentrega suprimida pela RESERVA, nao pela
    guarda de opt-out (esse caso concreto esta em `test_turno_optout.py`).

    Antes deste fix, `outbound.send` devolvendo False SEM levantar para a
    SEGUNDA parte (reserva ja existente em `outbound_dispatches`) deixava
    `entregue` True por causa da PRIMEIRA parte -- e o bloco que decide entre
    "reentrega_suprimida" e "bloqueado_por_optout" nunca rodava, porque aquele
    bloco so olhava para `not entregue`. O turno devolvia "respondido" com o
    texto INTEIRO gravado no recorder, mesmo a segunda parte nunca tendo
    saido -- e sem o `error` de `turno.reentrega_suprimida`, o alarme de dado
    sumido ficava mudo.
    """
    from conftest import OutboundFake, _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.agente.formato import quebrar_em_mensagens
    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.messages.enums import MessageRole
    from mobia.domain.messages.models import Message
    from mobia.infra.crypto import aad_de, decrypt

    await _conversa_ja_existe(session)
    mensagem = await _entrada_do_lead(session, texto="quero saber mais sobre apartamentos")
    longa = "Encontrei uma opcao muito boa para voce no centro da cidade. " * 12
    primeira_parte, _segunda_parte = quebrar_em_mensagens(longa)

    # A reserva da SEGUNDA parte ja existe -- simula uma tentativa anterior
    # que ja reservou (message_id, "reply_2"), do jeito real que
    # `GuardedOutbound.send` produziria com um `IntegrityError` na UNIQUE.
    session.add(
        OutboundDispatch(id=uuid.uuid4(), message_id=mensagem.id, kind=KINDS_DA_RESPOSTA[1])
    )
    await session.commit()

    outbound = OutboundFake(get_sessionmaker())

    with caplog.at_level(logging.INFO):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=mensagem,
            classificador=classificador_fake(resposta=longa),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    assert resultado == "reentrega_suprimida", (
        "a segunda parte foi suprimida por reserva duplicada -- o desfecho de "
        "dado sumido tem de sobreviver mesmo com a primeira parte entregue"
    )
    assert outbound.entregues == [primeira_parte]
    assert await _kinds_reservados() == ["reply", "reply_2"]

    faladas = (
        await session.scalars(select(Message).where(Message.role == MessageRole.AGENTE))
    ).all()
    assert len(faladas) == 1
    gravado = decrypt(faladas[0].text_body, aad_de(faladas[0].id, "text_body"))
    assert gravado == primeira_parte, (
        "so a parte que de fato saiu -- gravar `longa` inteira e a mentira que este fix corrige"
    )

    eventos = [
        registro
        for registro in caplog.records
        if "turno.reentrega_suprimida" in registro.getMessage()
    ]
    assert eventos and all(r.levelno == logging.ERROR for r in eventos), (
        "o alarme de dado sumido nao pode ficar mudo so porque a primeira parte entrou"
    )


async def test_falha_retentavel_na_segunda_parte_loga_entrega_parcial_antes_de_propagar(
    session: Any,
    classificador_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    rodar_turno: Any,
    caplog: Any,
) -> None:
    """Critical 2 da revisao final (TEC-140). `EnvioRetentavel` na SEGUNDA
    parte, com a primeira ja entregue, subia crua por este laco sem log
    nenhum antes desta clausula -- a mesma excecao, capturada no laco de
    fichas (`_entregar_fichas` desde a TEC-275), ja loga ha mais tempo. O
    desfecho NAO muda (FAILED, o sweeper reenfileira); so a visibilidade da
    entrega parcial antes da falha muda.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.formato import quebrar_em_mensagens
    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA
    from mobia.domain.outbound.port import EnvioRetentavel

    await _conversa_ja_existe(session)
    longa = "Encontrei uma opcao muito boa para voce no centro da cidade. " * 12
    primeira_parte, _segunda_parte = quebrar_em_mensagens(longa)

    class _RetentavelNaSegunda(OutboundFake):
        async def _deliver(self, message_id: Any, kind: Any, payload: Any) -> None:
            if kind == KINDS_DA_RESPOSTA[1]:
                raise EnvioRetentavel("http 503")
            await super()._deliver(message_id, kind, payload)

    outbound = _RetentavelNaSegunda(get_sessionmaker())

    with caplog.at_level(logging.INFO), pytest.raises(EnvioRetentavel):
        await rodar_turno(
            session,
            classificador_fake(resposta=longa),
            outbound,
            resumidor_fake(),
            contador_fake(),
            moderador_fake(),
        )

    assert outbound.entregues == [primeira_parte]
    # `EnvioRetentavel` libera, diferente de `EnvioRecusado` (ver
    # `GuardedOutbound.send`) -- e desde a TEC-273 libera o GRUPO, nao so o
    # kind que falhou. A retentativa do sweeper roda o turno inteiro de novo,
    # com uma chamada NOVA ao modelo; se a reserva da primeira parte
    # sobrevivesse, a retentativa suprimiria a parte 1 da geracao nova e
    # entregaria so a parte 2 -- metade de um texto colada na metade de
    # outro. Por isso nenhuma reserva sobra aqui.
    assert await _kinds_reservados() == []

    eventos = [
        registro
        for registro in caplog.records
        if "turno.entrega_parcial_antes_de_falha_retentavel" in registro.getMessage()
    ]
    assert eventos and all(r.levelno == logging.ERROR for r in eventos), (
        "sem este log, uma entrega parcial antes de um 5xx fica invisivel ate "
        "a proxima tentativa reaparecer no mesmo lugar"
    )


async def test_entrega_parcial_nao_marca_pergunta_como_feita(
    session: Any,
    classificador_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    rodar_turno: Any,
) -> None:
    """Important 2 da revisao final (TEC-140). Decisao tomada: com entrega
    PARCIAL, `marcar_perguntados` NAO roda.

    `entrega_parcial` nao diz ONDE dentro do texto a quebra caiu -- a pergunta
    de `gerada.perguntou` pode estar inteira na parte que saiu, ou pode estar
    na parte suprimida. Marcar quando ela estava na parte suprimida queimaria,
    para sempre e em silencio, a chance de perguntar aquele campo de verdade
    (a uniao no SQL nunca remove, mesmo comentario do bloco em `turno.py`).
    Nao marcar quando ela estava na parte entregue custa uma repeticao da
    pergunta depois -- irritante, mas reversivel. Entre os dois, a repeticao e
    o lado barato.
    """
    from conftest import CANAL, CONVERSA, OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA
    from mobia.domain.context.repositorio import ler_estado
    from mobia.domain.outbound.port import EnvioRecusado

    await _conversa_ja_existe(session)
    longa = "Encontrei uma opcao muito boa para voce no centro da cidade. " * 12

    class _RecusaASegundaMensagem(OutboundFake):
        async def _deliver(self, message_id: Any, kind: Any, payload: Any) -> None:
            if kind == KINDS_DA_RESPOSTA[1]:
                raise EnvioRecusado("http 400 codigo 131053")
            await super()._deliver(message_id, kind, payload)

    outbound = _RecusaASegundaMensagem(get_sessionmaker())

    resultado = await rodar_turno(
        session,
        classificador_fake(resposta=longa, perguntou=("regiao",)),
        outbound,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(),
    )

    assert resultado == "respondido"

    async with get_sessionmaker()() as outra:
        estado = await ler_estado(outra, CANAL, CONVERSA)
    assert estado is not None
    assert estado.perguntados_sem_resposta == [], (
        "entrega parcial: a pergunta de `gerada` pode estar na parte "
        "suprimida, entao a marca nao pode ser gravada"
    )


async def test_retentativa_da_parte_2_nao_mistura_geracoes(
    session: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    moderador_fake: Any,
    semear_entrada: Any,
) -> None:
    """TEC-273, cenario 1 do Gherkin. As duas partes vem da MESMA geracao.

    Passada 1: a parte 1 sai, a parte 2 toma um 429. Antes desta card a
    reserva de `reply` sobrevivia, e na passada 2 -- que roda o turno inteiro
    com uma chamada NOVA ao modelo -- a parte 1 do texto B era suprimida e so
    a parte 2 de B saia. O lead lia a primeira metade de A colada a segunda
    metade de B, sem nada no sistema dizer.

    Com a liberacao em grupo, a passada 2 reentrega as DUAS partes de B. O
    lead ve uma duplicata da primeira metade -- visivel e recuperavel, que e o
    lado que o precedente TEC-134/TEC-227 escolheu.

    Duas instancias simples de `ClassificadorFake(resposta=...)` bastam --
    cada `_rodar` constroi um classificador NOVO, entao nenhum roteiro de
    passadas dentro de uma unica instancia chegaria a avancar.
    """
    from conftest import ClassificadorFake, OutboundFake  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA, executar_turno
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.domain.outbound.port import EnvioRetentavel
    from mobia.infra.db import get_sessionmaker

    texto_a = "A" * 400 + " " + "a" * 400
    texto_b = "B" * 400 + " " + "b" * 400

    linha = await semear_entrada(session)

    class _RetentavelNaParte2(OutboundFake):  # type: ignore[misc, valid-type]
        async def _deliver(self, message_id: Any, kind: str, payload: Any) -> None:
            if kind == KINDS_DA_RESPOSTA[1]:
                raise EnvioRetentavel("http 429")
            await super()._deliver(message_id, kind, payload)

    async def _rodar(outbound: Any, classificador: Any) -> str:
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=moderador_fake(),
            agendador=AgendadorNoop(),
        )

    primeira = _RetentavelNaParte2(get_sessionmaker())
    with pytest.raises(EnvioRetentavel):
        await _rodar(primeira, ClassificadorFake(resposta=texto_a))

    assert len(primeira.entregues) == 1, (
        "o teste so vale se a passada 1 entregou UMA parte e parou na segunda"
    )

    segunda = OutboundFake(get_sessionmaker())
    assert await _rodar(segunda, ClassificadorFake(resposta=texto_b)) == "respondido"

    assert len(segunda.entregues) == 2, (
        "a passada 2 tem de reentregar as DUAS partes -- se so uma saiu, a "
        "reserva da parte 1 sobreviveu e a mistura continua"
    )
    entregue = "".join(segunda.entregues)
    assert "A" not in entregue, (
        f"nenhuma parte da geracao anterior pode sobrar colada a esta. Entregue: {entregue[:120]}"
    )
