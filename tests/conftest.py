import os
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import Settings, get_settings
from mobia.app.logging import configure_logging
from mobia.app.main import create_app
from mobia.domain.agente.models import Recomendacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.context.resumo import ResumoGerado
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.repositorio import gravar_resumo, registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho
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

    from mobia.domain.agente.investidor import ExtracaoDoInvestidor
    from mobia.domain.agente.schemas import Extracao, Intencao

# Maximo de bancos logicos que um Redis serve por padrao (`databases 16` no
# redis.conf). E o teto real de workers: cada um precisa do seu.
_BANCOS_DO_REDIS = 16


def _isolar_por_worker() -> None:
    """Da a cada worker do xdist um Postgres e um Redis so dele.

    Sem isto, `-n` nao acelera nada: quebra. Os dois recursos que a suite usa sao
    globais ao servidor, nao ao processo -- `banco_limpo` faz `TRUNCATE` e
    `redis_pool` faz `flushdb()`, e cada um deles apaga o estado dos OUTROS
    workers no meio da execucao deles. O sintoma e falha em massa que nao se
    reproduz sozinha; foi medido nesta suite, por acidente, quando duas invocacoes
    de pytest rodaram juntas contra a mesma base.

    Roda na importacao do conftest, e nao numa fixture, porque precisa acontecer
    antes do primeiro `get_settings()` -- que e `@lru_cache` e le do ambiente. E
    seguro mexer em `os.environ` aqui: cada worker do xdist e um processo
    proprio, entao nao existe o vizinho que essa escrita poderia atrapalhar.
    Sem `-n`, `PYTEST_XDIST_WORKER` nao existe e esta funcao nao faz nada -- o
    comportamento de quem roda `pytest` puro nao muda em nada.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    indice = int(worker.removeprefix("gw"))
    if indice >= _BANCOS_DO_REDIS:
        raise RuntimeError(
            f"worker {worker}: o Redis serve {_BANCOS_DO_REDIS} bancos, entao "
            f"esta suite nao roda com mais de {_BANCOS_DO_REDIS} workers"
        )
    global _URL_BASE
    padrao = Settings()
    _URL_BASE = padrao.database_url
    os.environ["DATABASE_URL"] = f"{padrao.database_url.rsplit('/', 1)[0]}/mobia_{worker}"
    os.environ["REDIS_URL"] = f"{padrao.redis_url.rsplit('/', 1)[0]}/{indice}"
    get_settings.cache_clear()


# A URL do banco ANTES da troca por worker -- e nela que se conecta para criar a
# base do worker, porque nao da para criar um banco estando dentro dele. Fica
# `None` quando nao ha xdist, e e esse `None` que diz a `migrar_banco` que nao ha
# base nenhuma para criar.
_URL_BASE: str | None = None

# Roda em subprocesso porque `migrar_banco` e puxada por `banco_limpo`, que e
# async: quando ela executa ja existe event loop rodando, e `asyncio.run()` ali
# levanta. O Alembic logo abaixo vai por subprocesso pelo mesmo motivo.
_CRIAR_BANCO = """
import asyncio, sys, asyncpg

async def main(dsn, nome):
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute('CREATE DATABASE "%s"' % nome)
    except asyncpg.DuplicateDatabaseError:
        pass
    finally:
        await conn.close()

asyncio.run(main(sys.argv[1], sys.argv[2]))
"""


def _criar_banco_do_worker() -> None:
    """Cria a base deste worker, se ela ainda nao existir.

    Retenta porque `CREATE DATABASE` toma lock sobre o template, e doze workers
    criando a sua base no mesmo instante fazem o Postgres recusar com "source
    database is being accessed by other users". O nome de cada base e unico, entao
    a colisao e so de timing -- esperar e repetir resolve.
    """
    if _URL_BASE is None:
        return
    alvo = get_settings().database_url.rsplit("/", 1)[1]
    dsn = _URL_BASE.replace("+asyncpg", "")
    for tentativa in range(5):
        resultado = subprocess.run(
            [sys.executable, "-c", _CRIAR_BANCO, dsn, alvo], capture_output=True
        )
        if resultado.returncode == 0:
            return
        time.sleep(0.5 * (tentativa + 1))
    raise RuntimeError(f"nao foi possivel criar {alvo}: {resultado.stderr.decode()}")


_isolar_por_worker()

# Acrescentar uma tabela aqui NAO custa mais um statement por teste: desde
# 12/09/2026 a limpeza e um `TRUNCATE a, b, c CASCADE` unico, e `tests/unit/`
# nem paga. Custa uma tabela a mais no mesmo statement e um lock tomado junto
# com os outros. Ver `_comando_de_truncate` e `banco_limpo`.
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
    # As duas do catalogo (TEC-156). `imoveis` precisa entrar porque o UNIQUE
    # em `codigo` faz o imovel de um teste colidir com o do proximo; sem o
    # truncate a falha aparece so a partir do segundo teste do arquivo.
    "importacoes",
    "imoveis",
    "messages",
    # Mesmo raciocinio da lead_score_audit: followups tambem e append-only, e
    # o UNIQUE por (channel, conversation_key, ancora_em, tentativa_numero) faz
    # o registro de um teste colidir com o do proximo sem o truncate.
    "followups",
    # Append-only como `lead_score_audit` e `optout_events`: sem o truncate, as
    # recusas de um teste viram auditoria do proximo. O custo e conhecido e
    # aceito -- a alternativa e teste de auditoria que passa sozinho e falha em
    # conjunto.
    "moderation_events",
    # TEC-163. Entra aqui, ao contrario de `bairros_adjacentes`, porque e
    # escrita pelos TESTES e nao pelo schema: sem o truncate, as recomendacoes
    # de um teste viram historico do proximo e o ajuste de filtro da RN-10.4
    # dispara onde ninguem pediu. Custo conhecido e aceito pelo mesmo argumento
    # que `imoveis` e `lead_score_audit` ja registram acima: a alternativa e
    # teste que passa sozinho e falha em conjunto.
    "recomendacoes",
    # TEC-174. Mutavel, ao contrario das append-only acima: o UNIQUE parcial
    # sobre status='PENDENTE' faz um handoff de um teste bloquear a criacao no
    # proximo, e a falha apareceria so a partir do segundo teste do arquivo --
    # o mesmo sintoma que `imoveis` ja registra.
    "handoffs",
    # TEC-196. Mesmo raciocinio de `imoveis`: o UNIQUE em `email` faz o
    # corretor de um teste colidir com o do proximo, e a falha so apareceria a
    # partir do segundo teste do arquivo sem o truncate.
    "corretores",
    # TEC-179. Mutavel, como `handoffs`: o UNIQUE por (channel,
    # conversation_key) faz a conversa de um teste bloquear o assumir do
    # proximo, e a falha apareceria so a partir do segundo teste do arquivo.
    "atendimento_humano",
    # TEC-136. Append-only como `lead_score_audit` e `followups`: sem o
    # truncate, as trocas de intencao de um teste virariam trilha do proximo.
    "conversation_intent_audit",
    # TEC-138. Mutavel: sem o truncate, uma conversa encerrada por um teste
    # chega encerrada no proximo, e a guarda do topo de turno (Task 4) cala o
    # turno antes de qualquer asserta.
    "conversas",
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

# TEC-153. Texto DIFERENTE do de cima, de proposito: e ele que permite a um
# teste afirmar que o que saiu foi a resposta da trilha do investidor e nao a
# da chamada generica. Com os dois iguais, o ramo do investidor poderia nunca
# rodar e a asserta de texto continuaria verde.
RESPOSTA_DO_INVESTIDOR_FAKE = "Qual retorno voce espera desse investimento?"


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
        resposta: str = RESPOSTA_DO_CLASSIFICADOR_FAKE,
        investidor: "ExtracaoDoInvestidor | None" = None,
        resposta_do_investidor: str = RESPOSTA_DO_INVESTIDOR_FAKE,
        # `None` significa "o mesmo da chamada generica", e nao "vazio": um
        # default vazio faria o duble engolir em silencio o que a chamada do
        # investidor devolveu, e o unico ramo que a trilha padrao nao exercita
        # e justamente onde a quebra apareceria. Quem precisa que as DUAS
        # chamadas divirjam -- e so o turno da virada precisa -- passa os dois
        # explicitamente.
        candidatos_do_investidor: "list[dict[str, object]] | None" = None,
        perguntou_do_investidor: tuple[str, ...] | None = None,
    ) -> None:
        from mobia.domain.agente.investidor import ExtracaoDoInvestidor as _ExtracaoDoInvestidor
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
        self.resposta = resposta
        self.investidor = investidor if investidor is not None else _ExtracaoDoInvestidor()
        self.resposta_do_investidor = resposta_do_investidor
        self.candidatos_do_investidor = candidatos_do_investidor
        self.perguntou_do_investidor = perguntou_do_investidor
        self.chamadas = 0
        self.desambiguacoes = 0
        # TEC-153. Contador PROPRIO, e nao somado a `chamadas`: a afirmacao que
        # o desenho exige e "do segundo turno do investidor em diante a chamada
        # continua sendo UMA so", e ela e indizivel num contador unico -- duas
        # chamadas genericas e uma generica mais uma do investidor dariam o
        # mesmo numero.
        self.investidores = 0
        self.candidatos: list[dict[str, object]] = []
        self.portas: list[object] = []
        # Lista propria pela mesma razao do contador: a ferramenta de busca
        # precisa chegar a chamada do INVESTIDOR (sem ela o investidor nunca
        # receberia ficha de imovel), e uma lista unica nao diria qual das
        # duas chamadas recebeu a porta.
        self.portas_do_investidor: list[object] = []

    async def classificar(self, contexto, *, porta=None):
        from mobia.domain.agente.schemas import RespostaDoAgente

        self.chamadas += 1
        # Guardado, e nao ignorado: e o que o teste da TEC-265 afirma -- que o
        # turno monta a porta e a entrega pronta ao classificador (D3).
        self.portas.append(porta)
        if self.erro is not None:
            raise self.erro
        return RespostaDoAgente(
            intencao=self.intencao,
            confianca=self.confianca,
            resposta=self.resposta,
            modelo="claude-opus-5",
            tokens_in=1200,
            tokens_out=180,
            latency_ms=900,
            extracao=self.extracao,
            perguntou=self.perguntou,
            recusou=self.recusou,
            candidatos=self.candidatos,
        )

    async def qualificar_investidor(self, contexto, *, porta=None):
        """A irma de `classificar` para a trilha do investidor. TEC-153.

        Devolve os MESMOS valores de telemetria e de conteudo que
        `classificar`, so que no envelope `RespostaDoInvestidor` e com o texto
        proprio: o turno le o mesmo conjunto de campos das duas, e um duble
        que devolvesse menos aqui esconderia a quebra no unico ramo que a
        trilha padrao nao exercita.
        """
        from mobia.domain.agente.investidor import RespostaDoInvestidor

        self.investidores += 1
        self.portas_do_investidor.append(porta)
        if self.erro is not None:
            raise self.erro
        return RespostaDoInvestidor(
            intencao=self.intencao,
            confianca=self.confianca,
            resposta=self.resposta_do_investidor,
            modelo="claude-opus-5",
            tokens_in=1300,
            tokens_out=200,
            latency_ms=950,
            extracao=self.extracao,
            investidor=self.investidor,
            perguntou=(
                self.perguntou
                if self.perguntou_do_investidor is None
                else self.perguntou_do_investidor
            ),
            recusou=self.recusou,
            candidatos=(
                self.candidatos
                if self.candidatos_do_investidor is None
                else self.candidatos_do_investidor
            ),
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


class EmbedadorFake:
    """Substitui `infra.embeddings.embedar` na suite.

    Guarda os lotes recebidos em `chamadas`, que e o que permite afirmar
    ZERO chamadas -- a assercao central do criterio "alteracao de preco nao
    regera embedding". Afirmar "o vetor parece igual" nao provaria nada: com
    uma implementacao por posicao o vetor tambem sairia igual.
    """

    def __init__(
        self,
        dimensoes: int = 1536,
        falhar: bool = False,
        falhar_a_partir_da_chamada: int | None = None,
    ) -> None:
        self.dimensoes = dimensoes
        self.falhar = falhar
        # 1-indexado, e "a partir de" em vez de "exatamente nesta": o laco de
        # lotes da varredura loga e SEGUE, entao um falso que so falhasse na
        # segunda de tres chamadas gravaria a terceira -- e a assercao "o
        # primeiro lote sobreviveu e os outros continuam pendentes" deixaria
        # de ser expressavel. Aditivo: `falhar=True` continua significando
        # "falha em toda chamada".
        self.falhar_a_partir_da_chamada = falhar_a_partir_da_chamada
        self.chamadas: list[list[str]] = []

    async def __call__(self, textos: list[str]) -> list[list[float]]:
        if not textos:
            return []
        self.chamadas.append(list(textos))
        if self.falhar or (
            self.falhar_a_partir_da_chamada is not None
            and len(self.chamadas) >= self.falhar_a_partir_da_chamada
        ):
            raise RuntimeError("provedor de embedding indisponivel")
        # Vetor deterministico e distinto por texto: o teste precisa
        # distinguir "reindexou" de "manteve o vetor antigo".
        return [
            [float(len(texto) % 7 + indice) / 10.0] * self.dimensoes
            for indice, texto in enumerate(textos)
        ]


class OutboundFake(GuardedOutbound):
    def __init__(self, session_factory, erro: Exception | None = None) -> None:
        super().__init__(session_factory)
        self.erro = erro
        self.entregues: list[str] = []
        # TEC-162, fix wave: payload cru, ao lado de `entregues`. Nenhuma
        # asserta de outro arquivo olha para isto, entao acrescentar aqui nao
        # move nada que ja passava -- e e o unico jeito de um teste distinguir
        # `{"tipo": "imagem", "link": None, ...}` (que o adaptador de verdade
        # rejeitaria) de um payload de texto que so PARECE igual depois de
        # colapsado em string.
        self.payloads: list[dict] = []

    async def _deliver(self, message_id, kind, payload) -> None:
        if self.erro is not None:
            raise self.erro
        self.payloads.append(payload)
        # TEC-162: payload de imagem guarda a LEGENDA. `entregues` continua
        # `list[str]` para nao quebrar as assertas dos testes de antes desta
        # card, que comparam contra o texto entregue.
        #
        # O discriminador e `payload.get("tipo") == "imagem"`, e nao o antigo
        # `payload.get("legenda") or payload["texto"]` -- fix wave (Important).
        # O `or` tinha dois problemas: uma legenda vazia caia para
        # `payload["texto"]`, que payload de imagem nao tem, e levantava
        # `KeyError` de dentro do duble em vez de testar o codigo da card; e
        # nada aqui obrigava o payload de imagem a de fato ter `link`
        # preenchido, entao `_apresentar` podia mandar `link: None` e o duble
        # aceitava do mesmo jeito. Checar o `tipo` fecha os dois.
        eh_imagem = payload.get("tipo") == "imagem"
        self.entregues.append(payload["legenda"] if eh_imagem else payload["texto"])


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
        categoria_de_entrada: str = "DISCRIMINACAO",
        categoria_de_saida: str = "NEGOCIACAO",
    ) -> None:
        self.bloqueia_entrada = bloqueia_entrada
        self.bloqueia_saida = bloqueia_saida
        self.erro_na_entrada = erro_na_entrada
        self.erro_na_saida = erro_na_saida
        self.categoria_de_entrada = categoria_de_entrada
        self.categoria_de_saida = categoria_de_saida
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
            return Veredito(
                bloqueado=self.bloqueia_entrada,
                motivo="fake",
                # `None` quando libera: o duble nao pode inventar categoria em
                # veredito liberado, senao um teste passaria por causa de um
                # valor que o moderador real nunca produz.
                categoria=self.categoria_de_entrada if self.bloqueia_entrada else None,
            )
        self.saidas += 1
        if self.erro_na_saida is not None:
            raise self.erro_na_saida
        return Veredito(
            bloqueado=self.bloqueia_saida,
            motivo="fake",
            categoria=self.categoria_de_saida if self.bloqueia_saida else None,
        )


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
        agendador=None,
        *,
        texto: str = TEXTO_PADRAO_DO_LEAD,
    ) -> str:
        from mobia.domain.agente.turno import executar_turno
        from mobia.domain.handoff.agendador import AgendadorNoop

        linha = await _entrada_do_lead(session, texto=texto)
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor,
            contador=contador,
            outbound=outbound,
            moderador=moderador if moderador is not None else ModeradorFake(),
            agendador=agendador if agendador is not None else AgendadorNoop(),
        )

    return _rodar


@pytest.fixture
def semear_entrada():
    """Semeia a entrada do lead SEM rodar o turno.

    `rodar_turno` semeia e executa junto, e os testes de escrita da auditoria
    precisam da linha sem o turno em volta -- eles exercitam o escritor
    diretamente, e um turno no meio tornaria ambiguo quem gravou o evento.
    """

    async def _semear(session, *, texto: str = TEXTO_PADRAO_DO_LEAD):
        return await _entrada_do_lead(session, texto=texto)

    return _semear


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


# `tests/unit/` nao fala com banco: conferido nos 50 arquivos do diretorio --
# zero pedem `session`, `session_factory` ou `client`, e zero chamam
# `get_sessionmaker()`. As duas unicas mencoes a `AsyncSession` e
# `session_factory` la estao em docstring, descrevendo um duble.
DIRETORIO_SEM_BANCO = Path(__file__).parent / "unit"


def _precisa_de_banco(request: pytest.FixtureRequest) -> bool:
    return DIRETORIO_SEM_BANCO not in request.path.parents


@pytest.fixture(scope="session")
def migrar_banco() -> None:
    """Aplica as migrations uma vez por sessao de teste.

    Roda o Alembic de verdade em vez de `metadata.create_all` para que as
    migrations sejam exercitadas pelos testes.

    NAO e autouse desde 12/09/2026: quem a puxa e `banco_limpo`, e so quando o
    teste da vez precisa de banco. Sendo autouse, uma sessao so com testes de
    `tests/unit/` pagava o Alembic -- e, pior, exigia Postgres de pe para rodar
    testes que nao tocam banco nenhum.

    Sob `-n`, cada worker migra a SUA base, entao o Alembic roda N vezes em vez
    de uma. E o preco do isolamento de `_isolar_por_worker`, e ele e pago uma vez
    por worker, nao por teste.
    """
    _criar_banco_do_worker()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        capture_output=True,
    )


# O comando de limpeza, descoberto uma vez e reusado pelo resto da sessao. Ver
# `_comando_de_truncate`.
_TRUNCATE: str | None = None


async def _comando_de_truncate(sessao: AsyncSession) -> str:
    """Monta (uma vez) o `TRUNCATE` unico que limpa `TABELAS`.

    Antes de 12/09/2026 `banco_limpo` fazia, para CADA teste, um
    `SELECT to_regclass` por tabela e depois um `TRUNCATE` por tabela existente
    -- ate 26 ida-e-volta ao Postgres por teste, numa conexao recem aberta. A
    pergunta que o `to_regclass` responde nao muda durante a sessao: `migrar_banco`
    ja rodou, e nenhuma tabela de `TABELAS` aparece ou some no meio do caminho.
    Entao o primeiro teste que precisa de banco paga a descoberta e os outros
    reusam a string.

    Um `TRUNCATE a, b, c CASCADE` unico nao e so menos round-trip: ele toma o
    lock das tabelas todas de uma vez, em vez de ir acumulando lock tabela a
    tabela. Menos janela para a contencao que o CLAUDE.md registra como origem
    dos flakes de integracao quando a suite roda junta.

    O `to_regclass` continua existindo, em vez de virar lista fixa, porque e ele
    que deixa `TABELAS` citar uma tabela que so uma migration futura cria sem
    quebrar a suite inteira nesse intervalo.

    O cache e modulo-global, e nao fixture de sessao, porque descobrir exige
    `await`: uma fixture sincrona nao pode, e uma fixture async de escopo de
    sessao colidiria com o `asyncio_default_fixture_loop_scope = "function"` do
    pyproject.
    """
    global _TRUNCATE
    if _TRUNCATE is None:
        existentes = [
            tabela
            for tabela in TABELAS
            if await sessao.scalar(text(f"SELECT to_regclass('public.{tabela}')"))
        ]
        _TRUNCATE = f"TRUNCATE TABLE {', '.join(existentes)} CASCADE"
    return _TRUNCATE


@pytest.fixture(autouse=True)
async def banco_limpo(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Trunca antes do teste e descarta o engine depois.

    Truncar na entrada (nao na saida) evita disputar lock com a sessao do teste.
    O dispose no fim e obrigatorio: cada teste roda no seu proprio event loop e
    conexoes asyncpg nao sobrevivem a troca de loop.

    Sai cedo para `tests/unit/` desde 12/09/2026. O custo era por teste da suite
    INTEIRA -- 13 `SELECT to_regclass` mais ate 13 `TRUNCATE ... CASCADE`, e um
    connect asyncpg novo, ja que o `dispose_engine()` abaixo descarta a engine e
    o teste seguinte nao reaproveita conexao. Medido sobre 53f7e55, Python
    3.13.15: `tests/unit` caiu de 227,0s para 5,7s (988 testes). Somado ao
    `TRUNCATE` unico de `_comando_de_truncate`, a suite inteira caiu de 413,1s
    para 153,8s, e no CI o passo `Rodar a suite` foi de 168s para 71s.

    O ganho aqui e maior no loop de quem desenvolve do que no total: `tests/unit`
    passou a rodar SEM Postgres e SEM Redis, entao rodar so a parte unitaria
    durante um card nao precisa de `docker compose` de pe.

    A decisao por caminho parece torta -- o natural seria um
    `tests/unit/conftest.py` sobrescrevendo a fixture pelo nome. Nao da: 15
    arquivos de teste fazem `from conftest import ...` (por exemplo
    `_entrada_do_lead` em `integration/test_apresentacao_no_turno.py`), o que so
    funciona porque no import mode `prepend` existe UM modulo de topo chamado
    `conftest`. Um segundo `conftest.py` em qualquer subdiretorio sombreia o
    raiz em `sys.modules` e derruba esses 15 arquivos com ImportError -- medido,
    35 falhas. Enquanto esses imports existirem, este arquivo e o unico conftest
    possivel, e a condicao tem de morar aqui dentro.
    """
    if not _precisa_de_banco(request):
        yield
        return
    request.getfixturevalue("migrar_banco")
    async with get_sessionmaker()() as sessao:
        await sessao.execute(text(await _comando_de_truncate(sessao)))
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


@pytest.fixture
def semear_lead_completo(session: AsyncSession):
    """Um lead com qualificacao, score, recomendacoes e handoff aberto.

    Existe porque o dossie cruza quatro tabelas e montar isso a mao em cada
    teste seria quatro copias do mesmo setup, livres para divergir.
    """

    async def _semear(*, score: int, faixa_max_centavos: int, imoveis: int) -> uuid.UUID:
        agora = datetime.now(UTC)
        session.add(
            LeadQualification(
                channel=CANAL_AGENTE,
                conversation_key=CONVERSA_AGENTE,
                intencao="COMPRAR",
                faixa_preco_max_centavos=faixa_max_centavos,
                regiao="Pinheiros",
                temperatura="QUENTE",
                campos_recusados=["renda"],
                perguntados_sem_resposta=["prazo"],
            )
        )
        # Dois registros, e nao um: `carregar_dossie` faz ORDER BY
        # created_at DESC LIMIT 1, e com um registro so o teste passaria
        # igual se esse ORDER BY sumisse, virasse ASC ou trocasse de coluna
        # -- a trilha e append-only e so o mais novo e o score de hoje. O
        # antigo tem um score diferente (`score - 1`) para que o dossie so
        # bata com a asserta do teste se ele de fato ler o CORRENTE.
        # `ck_lead_score_audit_total` exige total_novo = soma dos cinco
        # fatores. O registro ANTIGO poe tudo em `completude` e o resto zero
        # -- soma certo para qualquer `score` sem amarrar o antigo a uma
        # composicao fixa. O registro CORRENTE, logo abaixo, faz o oposto:
        # 25/20/12/10/5 fixos, que so somam 72 -- por isso os testes deste
        # modulo usam score=72. Quem passar outro `score` aqui tem de ajustar
        # os cinco fatores do registro corrente tambem, ou o INSERT viola a
        # constraint.
        antigo = score - 1
        session.add(
            LeadScoreAudit(
                id=uuid.uuid4(),
                channel=CANAL_AGENTE,
                conversation_key=CONVERSA_AGENTE,
                total_anterior=None,
                total_novo=antigo,
                completude=antigo,
                urgencia=0,
                catalogo=0,
                engajamento=0,
                capacidade=0,
                causas=["PRIMEIRO_CALCULO"],
            )
        )
        # Flush entre os dois INSERTs: cada um vira um statement proprio, e
        # `clock_timestamp()` (o server_default de `created_at`) e avaliado
        # de novo em cada um -- carimbo do antigo garantidamente anterior ao
        # do corrente, sem depender de os dois carem no mesmo batch.
        await session.flush()
        session.add(
            LeadScoreAudit(
                id=uuid.uuid4(),
                channel=CANAL_AGENTE,
                conversation_key=CONVERSA_AGENTE,
                total_anterior=antigo,
                total_novo=score,
                completude=25,
                urgencia=20,
                catalogo=12,
                engajamento=10,
                capacidade=5,
                causas=["CAMPOS_OBRIGATORIOS"],
            )
        )
        for indice in range(imoveis):
            imovel_id = uuid.uuid4()
            codigo = f"AP-{indice:03d}"
            session.add(
                Imovel(
                    id=imovel_id,
                    codigo=codigo,
                    titulo=f"Apartamento {codigo}",
                    descricao="Sala ampla com varanda.",
                    tipo="APARTAMENTO",
                    operacao="VENDA",
                    preco_venda=58_000_000 + indice,
                    bairro="Pinheiros",
                    bairro_busca="pinheiros",
                    cidade="Sao Paulo",
                    uf="SP",
                    area_util_m2=54,
                    quartos=2,
                    suites=1,
                    banheiros=2,
                    vagas=1,
                    status="DISPONIVEL",
                )
            )
            # Flush antes da Recomendacao: `imovel_id` e FK crua, sem
            # `relationship()` entre as duas classes, entao o unit-of-work
            # nao sabe ordenar as duas tabelas sozinho no commit final -- sem
            # isto o Postgres pode ver a Recomendacao antes do Imovel que ela
            # referencia e recusar com ForeignKeyViolationError.
            await session.flush()
            session.add(
                Recomendacao(
                    id=uuid.uuid4(),
                    channel=CANAL_AGENTE,
                    conversation_key=CONVERSA_AGENTE,
                    imovel_id=imovel_id,
                    score_match=Decimal("0.900"),
                    motivo_match="faixa e regiao",
                    apresentado_em=agora,
                )
            )
        await session.commit()

        registro = await registrar_handoff(
            session,
            channel=CANAL_AGENTE,
            conversation_key=CONVERSA_AGENTE,
            gatilho=Gatilho.LEAD_QUENTE,
        )
        await session.commit()
        return registro.id

    return _semear


@pytest.fixture
def semear_corretor(session: AsyncSession):
    """Cria um `Corretor` direto no modelo, sem passar por `criar_corretor`.

    O repositorio nao aceita `criado_em` -- ele sempre carimba com `agora` --,
    e o teste dos dois plantoes (TEC-177) precisa fixar carimbos diferentes
    para provar que a cascata escolhe o mais antigo. Por isso o modelo entra
    direto, preenchendo os mesmos campos obrigatorios e CHECKs que
    `criar_corretor` preenche (jornada, capacidade, especialidades, regioes).
    """

    async def _semear(
        *,
        email: str,
        plantao: bool = False,
        gerente: bool = False,
        ativo: bool = True,
        criado_em: datetime | None = None,
        horario_inicio: int = 9,
        horario_fim: int = 18,
    ) -> Corretor:
        agora = criado_em if criado_em is not None else datetime.now(UTC)
        corretor = Corretor(
            id=uuid.uuid4(),
            nome="Corretor de Teste",
            email=email,
            telefone="11999999999",
            creci=None,
            especialidades=["COMPRA"],
            regioes_atuacao=["pinheiros"],
            horario_inicio=horario_inicio,
            horario_fim=horario_fim,
            capacidade_diaria=5,
            plantao=plantao,
            gerente=gerente,
            ativo=ativo,
            criado_em=agora,
            atualizado_em=agora,
        )
        session.add(corretor)
        await session.commit()
        return corretor

    return _semear


@pytest.fixture
def semear_handoff_com_resumo(session: AsyncSession):
    """Um handoff de LEAD_QUENTE, com resumo cifrado quando `resumo` e dado.

    `resumo=None` deixa a coluna nula por construcao -- o caminho do D2 que
    `TEXTO_SEM_RESUMO` cobre (TEC-177): a geracao pode falhar ou ainda nao ter
    rodado, e a notificacao sai mesmo assim.
    """

    async def _semear(
        *,
        resumo: str | None,
        canal: str = "whatsapp",
        conversa: str = "5511900000000",
    ) -> uuid.UUID:
        registro = await registrar_handoff(
            session, channel=canal, conversation_key=conversa, gatilho=Gatilho.LEAD_QUENTE
        )
        if resumo is not None:
            await gravar_resumo(
                session,
                handoff_id=registro.id,
                texto=resumo,
                modelo="modelo-de-teste",
                fallback=False,
            )
        await session.commit()
        return registro.id

    return _semear
