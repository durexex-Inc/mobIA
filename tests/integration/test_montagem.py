import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from mobia.app.config import get_settings
from mobia.domain.context.janela import Marca, literais_apos
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import montar_contexto
from mobia.domain.context.repositorio import ler_resumo
from mobia.domain.context.resumo import (  # noqa: F401  (documenta a fronteira)
    INSTRUCAO_DOBRAR,
    ResumidorPort,
    ResumoGerado,
)
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def semear(session, quantidade: int, base: datetime | None = None) -> list[Message]:
    """Cria `quantidade` mensagens da mesma conversa, uma por segundo."""
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
            text_body=encrypt(f"mensagem {i}", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=inicio + timedelta(seconds=i),
        )
        session.add(linha)
        criadas.append(linha)
    await session.commit()
    return criadas


async def test_sem_marca_traz_a_conversa_inteira(session) -> None:
    await semear(session, 5)

    literais = await literais_apos(session, CANAL, CONVERSA, None)

    assert len(literais) == 5


async def test_marca_corta_o_que_ja_foi_resumido(session) -> None:
    criadas = await semear(session, 10)
    marca = Marca(created_at=criadas[3].created_at, message_id=criadas[3].id)

    literais = await literais_apos(session, CANAL, CONVERSA, marca)

    assert len(literais) == 6
    assert literais[0].id == criadas[4].id


async def test_empate_de_timestamp_nao_pula_nem_repete(session) -> None:
    """Duas mensagens no mesmo instante: o desempate e o id, nao a sorte.

    Com comparacao so por `created_at` uma das duas sumiria (se `>`) ou as duas
    voltariam (se `>=`) -- e o resumo perderia ou duplicaria conteudo.
    """
    instante = datetime.now(UTC) - timedelta(minutes=5)
    criadas = await semear(session, 2, base=instante)
    for linha in criadas:
        linha.created_at = instante
    await session.commit()

    primeira, segunda = sorted(criadas, key=lambda m: m.id)
    marca = Marca(created_at=instante, message_id=primeira.id)

    literais = await literais_apos(session, CANAL, CONVERSA, marca)

    assert [linha.id for linha in literais] == [segunda.id]


async def test_conversa_de_outro_lead_nao_entra(session) -> None:
    await semear(session, 3)
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            conversation_key="5511999998888",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
        )
    )
    await session.commit()

    literais = await literais_apos(session, CANAL, CONVERSA, None)

    assert len(literais) == 3


def test_resumo_gerado_tem_custo_calculavel() -> None:
    """O log de `resumo.gerado` carrega custo; o modelo padrao tem preco."""
    gerado = ResumoGerado(
        texto="lead procura apto na zona sul",
        modelo="claude-opus-5",
        tokens_in=8000,
        tokens_out=500,
        latency_ms=1200,
    )
    custo = custo_em_dolar(gerado.modelo, gerado.tokens_in, gerado.tokens_out)

    assert custo is not None, "modelo padrao do projeto tem de estar na tabela de precos"
    assert custo > 0


class ResumidorFake:
    """Dublê do provedor. Nenhum teste desta suite toca a rede."""

    def __init__(self, texto: str = "resumo do que veio antes", falha: bool = False) -> None:
        self.texto = texto
        self.falha = falha
        self.chamadas: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.chamadas.append(instrucao)
        if self.falha:
            raise RuntimeError("provedor fora do ar")
        return ResumoGerado(
            texto=self.texto,
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
def sempre_contar(monkeypatch):
    """Forca a contagem real em todo turno.

    Sem isso a estimativa barata (len/4) responde sozinha: mensagens curtas de
    teste nunca passam do limiar de 10.000, o ContadorFake nao e consultado e o
    roteiro de estouro nunca acontece. O teste passaria sem exercitar o laco.
    """
    monkeypatch.setenv("CONTEXTO_LIMIAR_DE_CONTAGEM", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_regenera_ao_atingir_o_gatilho(session) -> None:
    await semear(session, 40)
    resumidor = ResumidorFake()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert len(resumidor.chamadas) == 1, "quarenta literais disparam uma regeneracao"
    assert len(contexto.literais) == 20, "o piso fica intacto depois de dobrar"
    assert contexto.resumo == "resumo do que veio antes"

    async with get_sessionmaker()() as outra:
        gravado = await ler_resumo(outra, CANAL, CONVERSA)
    assert gravado is not None, "a marca avanca no banco, nao so em memoria"
    assert gravado.mensagens_cobertas == 20


async def test_nao_regenera_abaixo_do_gatilho(session) -> None:
    await semear(session, 39)
    resumidor = ResumidorFake()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert resumidor.chamadas == []
    assert len(contexto.literais) == 39, "sem resumo ainda, tudo entra literal"
    assert contexto.resumo is None


async def test_o_piso_vale_em_todo_ponto_entre_regeneracoes(session) -> None:
    """A regressao que os quatro cenarios Gherkin sozinhos nao pegariam.

    Eles testam estados; este testa a transicao. O brief original semeava as 80
    mensagens de uma vez e depois apagava tudo que fosse mais novo que um corte
    crescente -- a primeira iteracao ja apagava as mensagens 42..80 para sempre,
    entao as 39 iteracoes seguintes rodavam contra um banco que nunca mais
    crescia e nao testavam nada.

    Aqui o crescimento e de verdade: comeca com 40 mensagens (o suficiente para
    disparar a primeira regeneracao) e depois acrescenta uma mensagem por vez
    ate 80, chamando `montar_contexto` a cada passo. Isso caminha pela transicao
    inteira, inclusive o turno logo apos cada regeneracao -- e e exatamente ali
    que uma marca colada no presente derrubaria o piso.
    """
    criadas = await semear(session, 40)
    resumidor = ResumidorFake()
    minimas = get_settings().contexto_literais_minimas

    for numero in range(41, 81):
        proxima = criadas[-1].created_at + timedelta(seconds=1)
        nova = (await semear(session, 1, base=proxima))[0]
        criadas.append(nova)

        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=resumidor,
            contador=ContadorFake(),
        )
        assert len(contexto.literais) >= minimas, (
            f"com {numero} mensagens o prompt caiu para {len(contexto.literais)} literais"
        )


async def test_estouro_avanca_a_marca_antes_de_comprimir(session, sempre_contar) -> None:
    """A ordem importa: dobrar mensagem e perda normal, re-resumir e cascata."""
    await semear(session, 25)
    resumidor = ResumidorFake()
    # 1a contagem estoura, 2a (depois de dobrar) cabe.
    contador = ContadorFake(roteiro=[13500, 9000])

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert resumidor.chamadas[0] == INSTRUCAO_DOBRAR, "primeiro dobra, so depois comprime"


async def test_laco_termina_mesmo_com_resumidor_que_nao_encolhe(session, sempre_contar) -> None:
    """Um `while` aqui gastaria dinheiro em circulo. O teto de iteracoes corta."""
    await semear(session, 25)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500] * 10)

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert len(resumidor.chamadas) <= get_settings().contexto_max_iteracoes + 1
    assert contexto.degradado is True


async def test_falha_do_provedor_degrada_sem_derrubar(session, caplog) -> None:
    """A Marina esta esperando: o turno segue, o teto e respeitado, o log grita."""
    await semear(session, 40)

    with caplog.at_level(logging.WARNING):
        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=ResumidorFake(falha=True),
            contador=ContadorFake(),
        )

    assert contexto.degradado is True
    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert "contexto.degradado" in caplog.text


async def test_estado_de_qualificacao_entra_no_contexto(session) -> None:
    await semear(session, 3)
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            faixa_preco_max=Decimal("600000.00"),
            regiao="zona sul",
        )
    )
    await session.commit()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=ContadorFake(),
    )

    assert contexto.estado is not None
    assert contexto.estado.faixa_preco_max == Decimal("600000.00")
