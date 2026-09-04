import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import Settings, get_settings
from mobia.app.logging import configure_logging
from mobia.app.main import create_app
from mobia.domain.context.resumo import ResumoGerado
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.port import GuardedOutbound
from mobia.infra.anthropic import get_client
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import dispose_engine, get_sessionmaker
from mobia.infra.moderacao import get_moderation_client
from mobia.infra.queue import create_redis_pool

if TYPE_CHECKING:
    from arq.connections import ArqRedis

    from mobia.domain.agente.schemas import Extracao, Intencao

TABELAS = (
    "conversation_intent",
    "conversation_summaries",
    "lead_qualification",
    # A trilha e append-only e nada a apaga em producao: sem o truncate, os
    # registros de um teste viram o "ultimo recalculo" do proximo.
    "lead_score_audit",
    "message_telemetry",
    "outbound_dispatches",
    "optout_events",
    "messages",
)

# Conversa de referencia usada pelos testes de montagem de contexto
# (tests/integration/test_montagem.py e tests/features/test_janela_de_contexto.py).
CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def semear(
    session: AsyncSession,
    quantidade: int,
    base: datetime | None = None,
    texto: str | None = None,
) -> list[Message]:
    """Cria `quantidade` mensagens da mesma conversa, uma por segundo.

    `texto`, quando informado, substitui o corpo padrao (`mensagem {i}`) em
    todas as mensagens -- serve para simular conteudo maior ou com caracteres
    diferentes sem duplicar este laco em cada teste que precisa disso.
    """
    inicio = base or datetime.now(UTC) - timedelta(hours=1)
    criadas = []
    for i in range(quantidade):
        identificador = uuid.uuid4()
        linha = Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt(texto or f"mensagem {i}", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=inicio + timedelta(seconds=i),
        )
        session.add(linha)
        criadas.append(linha)
    await session.commit()
    return criadas


CANAL_AGENTE = "whatsapp"
CONVERSA_AGENTE = "5511911112222"

# Default de `_entrada_do_lead` e de `rodar_turno`, e uma constante so: as
# duas funcoes tem de concordar sobre o texto do turno "sem nada de especial"
# quando quem chama nao passa `texto`, e uma copia divergente do literal em
# cada uma so seria descoberta quando uma mudasse e a outra nao.
TEXTO_PADRAO_DO_LEAD = "quero saber mais sobre apartamentos"


async def _entrada_do_lead(session: AsyncSession, *, texto: str = TEXTO_PADRAO_DO_LEAD) -> Message:
    """Semeia a mensagem INBOUND que dispara um turno, ja reivindicada.

    `status=PROCESSING` porque e o estado que `process_message` deixa depois
    do claim, antes de rodar o turno -- e o ponto de partida real de
    `executar_turno`, nao um QUEUED que nunca existiria naquele momento.

    O `texto` e parametro desde a TEC-151, cujos gatilhos da RN-06.3 sao
    detectados na fala do lead -- um turno que precisa que o lead peca visita
    nao tem outro jeito de dizer isso. O default e o texto de sempre, entao
    nenhum teste anterior muda.
    """
    identificador = uuid.uuid4()
    linha = Message(
        id=identificador,
        channel=CANAL_AGENTE,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        sender_external_id=CONVERSA_AGENTE,
        recipient_external_id="222222222",
        conversation_key=CONVERSA_AGENTE,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt(texto, aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.PROCESSING,
    )
    session.add(linha)
    await session.commit()
    return linha


RESPOSTA_DO_CLASSIFICADOR_FAKE = "Ola! Em qual regiao voce procura?"


class ClassificadorFake:
    """Duble do provedor. Nenhum teste desta suite toca a rede."""

    def __init__(
        self,
        intencao: "Intencao" = None,  # type: ignore[assignment]
        confianca: Decimal = Decimal("0.91"),
        extracao: "Extracao | None" = None,
        erro: Exception | None = None,
        pergunta: str = "Me conta um pouco mais sobre o que voce procura?",
        erro_da_desambiguacao: Exception | None = None,
        perguntou: tuple[str, ...] = (),
        recusou: tuple[str, ...] = (),
    ) -> None:
        from mobia.domain.agente.schemas import Extracao as _Extracao
        from mobia.domain.agente.schemas import Intencao as _Intencao

        self.intencao = intencao or _Intencao.COMPRA
        self.confianca = confianca
        self.extracao = extracao if extracao is not None else _Extracao()
        self.erro = erro
        self.pergunta = pergunta
        self.erro_da_desambiguacao = erro_da_desambiguacao
        self.perguntou = perguntou
        self.recusou = recusou
        self.chamadas = 0
        self.desambiguacoes = 0

    async def classificar(self, contexto):
        from mobia.domain.agente.schemas import RespostaDoAgente

        self.chamadas += 1
        if self.erro is not None:
            raise self.erro
        return RespostaDoAgente(
            intencao=self.intencao,
            confianca=self.confianca,
            resposta=RESPOSTA_DO_CLASSIFICADOR_FAKE,
            modelo="claude-opus-5",
            tokens_in=1200,
            tokens_out=180,
            latency_ms=900,
            extracao=self.extracao,
            perguntou=self.perguntou,
            recusou=self.recusou,
        )

    async def desambiguar(self, contexto):
        from mobia.domain.agente.schemas import PerguntaDeDesambiguacao

        self.desambiguacoes += 1
        if self.erro_da_desambiguacao is not None:
            raise self.erro_da_desambiguacao
        return PerguntaDeDesambiguacao(
            texto=self.pergunta,
            modelo="claude-opus-5",
            tokens_in=1100,
            tokens_out=40,
            latency_ms=600,
        )


class OutboundFake(GuardedOutbound):
    def __init__(self, session_factory, erro: Exception | None = None) -> None:
        super().__init__(session_factory)
        self.erro = erro
        self.entregues: list[str] = []

    async def _deliver(self, message_id, kind, payload) -> None:
        if self.erro is not None:
            raise self.erro
        self.entregues.append(payload["texto"])


@pytest.fixture
def classificador_fake():
    return ClassificadorFake


@pytest.fixture
def outbound_fake():
    def _criar(erro: Exception | None = None) -> OutboundFake:
        return OutboundFake(get_sessionmaker(), erro=erro)

    return _criar


class ModeradorFake:
    """Duble do moderador. Nenhum teste desta suite toca a rede."""

    def __init__(
        self,
        bloqueia_entrada: bool = False,
        bloqueia_saida: bool = False,
        erro_na_entrada: Exception | None = None,
        erro_na_saida: Exception | None = None,
    ) -> None:
        self.bloqueia_entrada = bloqueia_entrada
        self.bloqueia_saida = bloqueia_saida
        self.erro_na_entrada = erro_na_entrada
        self.erro_na_saida = erro_na_saida
        self.entradas = 0
        self.saidas = 0
        self.direcoes: list = []

    async def moderar(self, texto, *, direcao):
        from mobia.domain.moderacao.port import Direcao, Veredito

        self.direcoes.append(direcao)
        if direcao is Direcao.ENTRADA:
            self.entradas += 1
            if self.erro_na_entrada is not None:
                raise self.erro_na_entrada
            return Veredito(bloqueado=self.bloqueia_entrada, motivo="fake")
        self.saidas += 1
        if self.erro_na_saida is not None:
            raise self.erro_na_saida
        return Veredito(bloqueado=self.bloqueia_saida, motivo="fake")


@pytest.fixture
def moderador_fake():
    def _criar(**kwargs) -> ModeradorFake:
        return ModeradorFake(**kwargs)

    return _criar


@pytest.fixture
def rodar_turno():
    """Semeia uma entrada e roda o turno inteiro sobre ela."""

    async def _rodar(
        session,
        classificador,
        outbound,
        resumidor,
        contador,
        moderador=None,
        *,
        texto: str = TEXTO_PADRAO_DO_LEAD,
    ) -> str:
        from mobia.domain.agente.turno import executar_turno

        linha = await _entrada_do_lead(session, texto=texto)
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor,
            contador=contador,
            outbound=outbound,
            moderador=moderador if moderador is not None else ModeradorFake(),
        )

    return _rodar


class ResumidorFake:
    """Duble do provedor. Nenhum teste desta suite toca a rede."""

    def __init__(
        self,
        texto: str = "resumo do que veio antes",
        falha: bool = False,
        roteiro: list[str] | None = None,
    ) -> None:
        self.texto = texto
        self.falha = falha
        self.roteiro = roteiro or []
        self.chamadas: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.chamadas.append(instrucao)
        if self.falha:
            raise RuntimeError("provedor fora do ar")
        texto = self.roteiro.pop(0) if self.roteiro else self.texto
        return ResumoGerado(
            texto=texto,
            modelo="claude-opus-5",
            tokens_in=100,
            tokens_out=50,
            latency_ms=10,
        )


class ContadorFake:
    """Conta por caractere/4, ou devolve valores roteirizados em sequencia."""

    def __init__(self, roteiro: list[int] | None = None) -> None:
        self.roteiro = roteiro or []
        self.chamadas = 0

    async def contar(self, texto: str) -> int:
        self.chamadas += 1
        if self.roteiro:
            return self.roteiro.pop(0)
        return len(texto) // 4


@pytest.fixture
def resumidor_fake():
    return ResumidorFake


@pytest.fixture
def contador_fake():
    return ContadorFake


@pytest.fixture
def sempre_contar(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Forca a contagem real em todo turno.

    Sem isso a estimativa barata (len/4) responde sozinha: mensagens curtas de
    teste nunca passam do limiar efetivo (`Settings.limiar_de_contagem_efetivo`,
    derivado do teto -- ver `config.py`), o ContadorFake nao e consultado e o
    roteiro de estouro nunca acontece. O teste passaria sem exercitar o laco.
    """
    monkeypatch.setenv("CONTEXTO_LIMIAR_DE_CONTAGEM", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def configurar_logging() -> None:
    """Configura o structlog uma vez por sessao de teste.

    structlog e estado global de processo e em producao so e configurado dentro
    de `create_app()`. Sem esta fixture, um teste que nao sobe o app fica com o
    logger nao-configurado e `caplog` nao enxerga evento nenhum -- a suite
    passaria so por acidente de ordenacao entre arquivos.
    """
    configure_logging(get_settings().log_level)


@pytest.fixture(scope="session", autouse=True)
def migrar_banco() -> None:
    """Aplica as migrations uma vez por sessao de teste.

    Roda o Alembic de verdade em vez de `metadata.create_all` para que as
    migrations sejam exercitadas pelos testes.
    """
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        capture_output=True,
    )


@pytest.fixture(autouse=True)
async def banco_limpo(migrar_banco: None) -> AsyncIterator[None]:
    """Trunca antes do teste e descarta o engine depois.

    Truncar na entrada (nao na saida) evita disputar lock com a sessao do teste.
    O dispose no fim e obrigatorio: cada teste roda no seu proprio event loop e
    conexoes asyncpg nao sobrevivem a troca de loop.
    """
    async with get_sessionmaker()() as sessao:
        for tabela in TABELAS:
            existe = await sessao.scalar(text(f"SELECT to_regclass('public.{tabela}')"))
            if existe:
                await sessao.execute(text(f"TRUNCATE TABLE {tabela} CASCADE"))
        await sessao.commit()
    yield
    await dispose_engine()


@pytest.fixture
async def session(banco_limpo: None) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as sessao:
        yield sessao


@pytest.fixture
def session_factory(banco_limpo: None) -> async_sessionmaker[AsyncSession]:
    return get_sessionmaker()


@pytest.fixture
def caches_de_cliente_limpos() -> Iterator[None]:
    """Zera `get_settings` e os dois clientes juntos, na entrada e na saida.

    As tres funcoes tem `@lru_cache` independente (Task 1 do TEC-127,
    `get_moderation_client` na TEC-233) e nada
    estrutural forca quem limpa uma a limpar a outra. Um teste que so chama
    `get_settings.cache_clear()` -- por exemplo depois de mudar
    `ANTHROPIC_API_KEY` via monkeypatch -- deixa `get_client()` cacheado com um
    `AsyncAnthropic` construido a partir da chave antiga vivo para o proximo
    teste que chamar `get_client()`. E poluicao entre testes que so aparece
    dependendo da ordem de execucao, dificil de reproduzir. Limpar tambem na
    saida (nao so na entrada) fecha o buraco nos dois sentidos: nenhum teste
    que use esta fixture pode deixar cache stale para o vizinho, e nenhum
    vizinho pode herdar cache de quem rodou antes. Qualquer teste que mexa em
    `Settings`/`ANTHROPIC_API_KEY` deve depender desta fixture (diretamente ou
    via `settings`, abaixo) em vez de chamar `cache_clear()` na mao.

    `get_moderation_client` entra pelo mesmo motivo, e nao porque hoje quebre
    sem ele: todo teste de moderacao usa duble. Todo construtor novo com
    `@lru_cache` sobre `get_settings()` reabre este buraco, e a lista aqui e o
    unico lugar que o fecha.
    """
    get_settings.cache_clear()
    get_client.cache_clear()
    get_moderation_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_client.cache_clear()
    get_moderation_client.cache_clear()


@pytest.fixture
def settings(caches_de_cliente_limpos: None) -> Settings:
    return get_settings()


@pytest.fixture
async def redis_pool() -> AsyncIterator["ArqRedis"]:
    pool = await create_redis_pool()
    await pool.flushdb()
    try:
        yield pool
    finally:
        await pool.flushdb()
        await pool.aclose()


@pytest.fixture
async def client(banco_limpo: None, redis_pool) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.state.redis_pool = redis_pool
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
