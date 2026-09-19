"""O relogio do indicador de digitacao, e as guardas do disparo. TEC-274, RN-04.7."""

import asyncio
import uuid

from conftest import CANAL_AGENTE, CONVERSA_AGENTE

from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import registrar_optout
from mobia.domain.outbound.presenca import indicador_de_digitacao
from mobia.infra.db import get_sessionmaker

# Centesimos de segundo e nao os 4 s da regra: tres cenarios a 4 s reais
# custariam mais de doze segundos por execucao da suite. O que se exercita e o
# relogio, e ele nao sabe que numero esta contando -- ver a D7 do desenho.
DEPRESSA = 0.02
DEVAGAR = 0.20


class IndicadorEspiao:
    """Conta os disparos. `erro` faz o disparo levantar, sem deixar de contar."""

    def __init__(self, erro: Exception | None = None) -> None:
        self.chamadas: list[tuple[str, str]] = []
        self._erro = erro

    async def indicar_digitacao(self, *, provider_message_id: str, de: str) -> None:
        self.chamadas.append((provider_message_id, de))
        if self._erro is not None:
            raise self._erro


async def _entrada(session, *, wamid: str | None = "wamid.TESTE") -> Message:
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL_AGENTE,
        provider_message_id=wamid,
        conversation_key=CONVERSA_AGENTE,
        recipient_external_id="222222222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status="PROCESSING",
    )
    session.add(linha)
    await session.commit()
    return linha


async def test_geracao_demorada_dispara_o_indicador_uma_vez(session, banco_limpo) -> None:
    """O primeiro cenario do Gherkin, com a clausula 'UMA vez' afirmada.

    A asserta e `== 1` e nao `>= 1` de proposito: um laco de renovacao
    acidental passaria em `>= 1` e e exatamente o que a card proibe.
    """
    linha = await _entrada(session)
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await asyncio.sleep(DEVAGAR)

    assert espiao.chamadas == [("wamid.TESTE", "222222222")]


async def test_geracao_rapida_nao_dispara_nada(session, banco_limpo) -> None:
    """O segundo cenario do Gherkin."""
    linha = await _entrada(session)
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEVAGAR
    ):
        await asyncio.sleep(DEPRESSA)

    assert espiao.chamadas == []


async def test_falha_no_indicador_nao_derruba_o_corpo(session, banco_limpo) -> None:
    """O terceiro cenario do Gherkin, no nivel do agendador.

    O corpo do `async with` e a resposta do agente: ele tem de completar e
    devolver o valor dele mesmo com o indicador levantando.
    """
    linha = await _entrada(session)
    espiao = IndicadorEspiao(erro=RuntimeError("a Meta caiu"))
    entregue = None

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await asyncio.sleep(DEVAGAR)
        entregue = "a resposta saiu"

    assert espiao.chamadas != []
    assert entregue == "a resposta saiu"


async def test_optout_durante_a_espera_barra_o_indicador(session, banco_limpo) -> None:
    """A D3 do desenho, e a razao de as guardas rodarem no disparo.

    O opt-out chega DEPOIS de o relogio partir. Uma guarda que dependesse da
    posicao no codigo -- conferida antes de agendar -- deixaria o indicador
    sair para quem acabou de pedir silencio.
    """
    linha = await _entrada(session)
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await registrar_optout(
            get_sessionmaker(),
            channel=CANAL_AGENTE,
            conversation_key=CONVERSA_AGENTE,
            message_id=linha.id,
        )
        await asyncio.sleep(DEVAGAR)

    assert espiao.chamadas == []


async def test_atendimento_humano_barra_o_indicador(session, semear_corretor, banco_limpo) -> None:
    """RN-16.4: quem assumiu a conversa nao pode ter o agente digitando por cima."""
    linha = await _entrada(session)
    corretor = await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    await session.commit()
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await asyncio.sleep(DEVAGAR)

    assert espiao.chamadas == []


async def test_linha_sem_wamid_nao_agenda_nada(session, banco_limpo) -> None:
    """`provider_message_id` e nullable, e o indicador nao existe sem ele.

    A Meta nao aceita indicador para um numero -- so como anotacao sobre uma
    mensagem recebida. Sem o wamid nao ha o que enviar, e agendar uma tarefa
    para descobrir isso quatro segundos depois seria trabalho para nada.
    """
    linha = await _entrada(session, wamid=None)
    espiao = IndicadorEspiao()

    async with indicador_de_digitacao(
        get_sessionmaker(), message=linha, indicador=espiao, apos_segundos=DEPRESSA
    ):
        await asyncio.sleep(DEVAGAR)

    assert espiao.chamadas == []


async def test_turno_lento_dispara_o_indicador_de_ponta_a_ponta(
    session,
    semear_entrada,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
    monkeypatch,
    caches_de_cliente_limpos,
    banco_limpo,
) -> None:
    """A fiacao inteira: `process_message` -> gerente de contexto -> porta.

    O limiar vem do ambiente e nao do argumento, porque o que este teste
    exercita e justamente a leitura de `Settings` que `process_message` faz --
    os testes acima ja cobrem o relogio com o limiar injetado.
    """
    from mobia.app.config import get_settings
    from mobia.domain.handoff.agendador import AgendadorNoop
    from mobia.workers.jobs.process_message import process_message

    monkeypatch.setenv("INDICADOR_DE_DIGITACAO_APOS_SEGUNDOS", "0.02")
    get_settings.cache_clear()

    class ClassificadorLento:
        """Delega para o fake, com uma pausa na frente do relogio."""

        def __init__(self, interno) -> None:
            self._interno = interno

        def __getattr__(self, nome: str):
            return getattr(self._interno, nome)

        async def classificar(self, *args, **kwargs):
            await asyncio.sleep(DEVAGAR)
            return await self._interno.classificar(*args, **kwargs)

    linha = await semear_entrada(session)
    espiao = IndicadorEspiao()
    ctx = {
        "session_factory": get_sessionmaker(),
        "outbound": outbound_fake(),
        "classificador": ClassificadorLento(classificador_fake()),
        "resumidor": resumidor_fake(),
        "contador": contador_fake(),
        "moderador": moderador_fake(),
        "agendador": AgendadorNoop(),
        "indicador": espiao,
    }

    await process_message(ctx, str(linha.id))

    assert len(espiao.chamadas) == 1
