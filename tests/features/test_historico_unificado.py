"""Cenarios Gherkin de TEC-129.

Funcionalidade: Historico unificado do lead entre canais

O turno do WhatsApp roda pelo `process_message` de producao, com um
classificador que GUARDA o contexto que recebeu: e o contexto -- o estado e os
literais -- que diz se o agente reperguntaria. Afirmar sobre o texto da
resposta testaria o duble, que responde sempre a mesma coisa.
"""

import uuid
from typing import Any

from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake
from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeConfirmacaoNoop
from mobia.domain.agente.schemas import Extracao
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import gravar_resumo
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.domain.outbound.roteador import RoteadorPorCanal
from mobia.domain.outbound.web import WebOutbound
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message

TELEFONE_DIGITADO = "(48) 99999-0000"
WA_ID = "5548999990000"


class ClassificadorQueGuarda(ClassificadorFake):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.contextos: list[Any] = []

    async def classificar(self, contexto, *, porta=None):
        self.contextos.append(contexto)
        return await super().classificar(contexto, porta=porta)


class WhatsAppQueRegistra:
    """A porta da Meta que registra o envio em vez de falhar."""

    def __init__(self) -> None:
        self.envios: list[dict[str, Any]] = []

    async def send(self, message_id: Any, kind: str, payload: dict[str, Any]) -> bool:
        self.envios.append(payload)
        return True


def _ctx(redis_pool: Any, classificador: Any, whatsapp: Any) -> dict[str, Any]:
    """O `ctx` que `workers/main.py` monta, com dubles no lugar dos modelos."""
    session_factory = get_sessionmaker()
    return {
        "session_factory": session_factory,
        "outbound": RoteadorPorCanal(
            session_factory,
            {CANAL_WHATSAPP: whatsapp, CANAL_WEB: WebOutbound(session_factory, redis_pool)},
        ),
        "classificador": classificador,
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "agendador_de_confirmacao": AgendadorDeConfirmacaoNoop(),
        "indicadores": {CANAL_WHATSAPP: IndicadorNoop(), CANAL_WEB: IndicadorNoop()},
    }


async def _abrir(ws_cliente, sessao: str | None = None) -> tuple[Any, str]:
    ws = ws_cliente()
    await ws.__aenter__()
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": sessao})
    return ws, (await ws.receber())["sessao"]


async def _falar_no_site(
    ws_cliente, redis_pool, textos: list[str], classificador, sessao: str | None = None
) -> str:
    """Abre (ou retoma) uma sessao, diz cada texto e roda o turno de cada um.

    O id de cada fala e um uuid, e nao `m-0`: numa sessao retomada, `m-0`
    colidiria com a primeira fala e a UNIQUE a descartaria.
    """
    retomada = sessao is not None
    ws, sessao = await _abrir(ws_cliente, sessao)
    if retomada:
        # Na retomada o servidor manda o historico logo depois do `ola`
        # (TEC-124, D6), e ele tem de sair da frente antes do `recebido`.
        assert (await ws.receber())["tipo"] == "historico"
    fabrica = get_sessionmaker()
    try:
        for texto in textos:
            await ws.enviar({"tipo": "mensagem", "id": str(uuid.uuid4()), "texto": texto})
            assert (await ws.receber())["tipo"] == "recebido"
            async with fabrica() as sessao_db:
                linha = (
                    await sessao_db.execute(
                        select(Message)
                        .where(
                            Message.conversation_key == sessao,
                            Message.role == MessageRole.LEAD,
                        )
                        .order_by(Message.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one()
            resultado = await process_message(
                _ctx(redis_pool, classificador, WhatsAppQueRegistra()), str(linha.id)
            )
            assert resultado == "respondido"
            assert (await ws.receber())["tipo"] == "mensagem"  # a resposta do agente
    finally:
        await ws.__aexit__()
    return sessao


async def _falar_no_whatsapp(redis_pool, texto: str, classificador) -> WhatsAppQueRegistra:
    fabrica = get_sessionmaker()
    [message_id] = await IngestionService(fabrica, redis_pool).ingest(
        [
            ParsedMessage(
                provider_message_id=f"wamid.{uuid.uuid4()}",
                sender_external_id=WA_ID,
                recipient_external_id="phone-number-id",
                content_type=MessageContentType.TEXTO,
                text_body=texto,
                raw_payload={},
            )
        ],
        channel=CANAL_WHATSAPP,
    )
    whatsapp = WhatsAppQueRegistra()
    await process_message(_ctx(redis_pool, classificador, whatsapp), str(message_id))
    return whatsapp


async def test_mesma_pessoa_migra_do_site_para_o_whatsapp(ws_cliente, session, redis_pool) -> None:
    """Cenario: Mesma pessoa migra do site para o WhatsApp."""
    # Dado um lead que informou o telefone no widget web
    no_site = ClassificadorQueGuarda(extracao=Extracao(quartos=2, regiao="Campeche"))
    await _falar_no_site(
        ws_cliente,
        redis_pool,
        [f"quero 2 quartos no Campeche, meu whats e {TELEFONE_DIGITADO}"],
        no_site,
    )

    # Quando ele escreve pelo WhatsApp a partir desse mesmo numero
    no_whatsapp = ClassificadorQueGuarda()
    await _falar_no_whatsapp(redis_pool, "oi, vim do site", no_whatsapp)

    # Entao o atendimento reconhece o historico da conversa web
    [contexto] = no_whatsapp.contextos
    assert CANAL_WEB in {m.channel for m in contexto.literais}
    # E nao repergunta os criterios ja informados: eles estao no estado que o
    # prompt recebe, e o que esta no estado nao e perguntado.
    assert (contexto.estado.quartos, contexto.estado.regiao) == (2, "Campeche")


async def test_sessao_anonima_e_vinculada_ao_informar_o_telefone(
    ws_cliente, session, redis_pool
) -> None:
    """Cenario: Sessao anonima e vinculada ao informar o telefone."""
    # Dada uma sessao web anonima com 6 mensagens trocadas (3 do lead, 3 do agente)
    classificador = ClassificadorQueGuarda()
    sessao = await _falar_no_site(
        ws_cliente, redis_pool, ["oi", "quero comprar", "dois quartos"], classificador
    )
    assert (await session.execute(select(VinculoDeSessao))).first() is None

    # Quando o visitante informa o telefone
    await _falar_no_site(
        ws_cliente, redis_pool, [f"meu numero e {TELEFONE_DIGITADO}"], classificador, sessao=sessao
    )

    # Entao as 6 mensagens passam a pertencer ao lead desse telefone
    no_whatsapp = ClassificadorQueGuarda()
    await _falar_no_whatsapp(redis_pool, "oi", no_whatsapp)
    [contexto] = no_whatsapp.contextos
    da_sessao = [m for m in contexto.literais if m.channel == CANAL_WEB]
    assert {m.conversation_key for m in da_sessao} == {sessao}
    # O criterio da card e que as falas da sessao pertencem ao lead -- TODAS
    # elas --, e por isso a igualdade e contra o que o banco tem da sessao, e
    # nao so uma contagem sobre a janela.
    async with get_sessionmaker()() as sessao_db:
        gravadas = set(
            await sessao_db.scalars(
                select(Message.id).where(
                    Message.channel == CANAL_WEB,
                    Message.conversation_key == sessao,
                    Message.bloqueada_em.is_(None),
                )
            )
        )
    # As 6 de antes do telefone, mais as 2 da fala que o trouxe: uma linha de
    # agente por resposta.
    assert len(gravadas) == 8
    assert {m.id for m in da_sessao} == gravadas


async def test_telefones_diferentes_nao_sao_unificados(ws_cliente, session, redis_pool) -> None:
    """Cenario: Telefones diferentes nao sao unificados."""
    # Dados dois atendimentos com telefones distintos
    await _falar_no_site(
        ws_cliente,
        redis_pool,
        ["quero 4 quartos, meu whats e (48) 98888-1111"],
        ClassificadorQueGuarda(extracao=Extracao(quartos=4)),
    )

    # Quando ambos estao ativos
    no_whatsapp = ClassificadorQueGuarda()
    await _falar_no_whatsapp(redis_pool, "oi", no_whatsapp)

    # Entao cada um mantem historico e qualificacao proprios
    [contexto] = no_whatsapp.contextos
    assert {m.channel for m in contexto.literais} == {CANAL_WHATSAPP}
    assert contexto.estado is None or contexto.estado.quartos is None


async def test_a_sessao_web_nao_ve_o_whatsapp_de_quem_ela_digitou(
    ws_cliente, session, redis_pool
) -> None:
    """D1: quem digita o telefone de outra pessoa nao recebe nada do WhatsApp dela."""
    session.add(
        LeadQualification(channel=CANAL_WHATSAPP, conversation_key=WA_ID, quartos=3, regiao="Lagoa")
    )
    await session.commit()
    await _falar_no_whatsapp(redis_pool, "procuro 3 quartos na Lagoa", ClassificadorQueGuarda())

    no_site = ClassificadorQueGuarda()
    await _falar_no_site(
        ws_cliente,
        redis_pool,
        [f"oi, meu whats e {TELEFONE_DIGITADO}", "o que eu procurava?"],
        no_site,
    )

    assert len(no_site.contextos) == 2
    for contexto in no_site.contextos:
        assert {m.channel for m in contexto.literais} == {CANAL_WEB}
        assert contexto.estado is None or contexto.estado.regiao != "Lagoa"


async def test_criterios_chegam_mesmo_com_falas_web_antes_da_marca(
    ws_cliente, session, redis_pool
) -> None:
    """A fala web mais antiga que o resumo do WhatsApp fica fora da janela,
    e o criterio chega pela qualificacao."""
    no_site = ClassificadorQueGuarda(extracao=Extracao(quartos=2))
    await _falar_no_site(ws_cliente, redis_pool, [f"2 quartos, whats {TELEFONE_DIGITADO}"], no_site)
    # Um resumo do WhatsApp cuja marca e posterior a tudo o que o site disse.
    ultimo = (
        await session.execute(select(Message).order_by(Message.created_at.desc()).limit(1))
    ).scalar_one()
    async with get_sessionmaker()() as sessao_db:
        assert await gravar_resumo(
            sessao_db,
            channel=CANAL_WHATSAPP,
            conversation_key=WA_ID,
            texto="O lead ja conversou antes.",
            watermark_created_at=ultimo.created_at,
            watermark_message_id=ultimo.id,
            mensagens_cobertas=0,
            modelo="claude-haiku-4-5",
        )
        await sessao_db.commit()

    no_whatsapp = ClassificadorQueGuarda()
    await _falar_no_whatsapp(redis_pool, "oi", no_whatsapp)
    [contexto] = no_whatsapp.contextos
    assert CANAL_WEB not in {m.channel for m in contexto.literais}
    assert contexto.estado.quartos == 2


async def test_absorcao_quebrada_nao_derruba_o_turno(session, redis_pool, monkeypatch) -> None:
    import mobia.domain.agente.turno as turno

    async def quebrada(*args: Any, **kwargs: Any) -> tuple[tuple[str, str], ...]:
        raise RuntimeError("vinculos indisponivel")

    monkeypatch.setattr(turno, "absorver_sessoes_vinculadas", quebrada)
    whatsapp = await _falar_no_whatsapp(redis_pool, "oi", ClassificadorQueGuarda())

    assert whatsapp.envios  # o lead recebeu resposta


async def test_o_turno_web_nao_chama_a_absorcao(
    ws_cliente, session, redis_pool, monkeypatch
) -> None:
    """O gate de `executar_turno` (D1): so o turno do WhatsApp absorve.

    O duble registra e delega: o turno do WhatsApp, logo abaixo, prova que ele
    esta no caminho -- sem isso um `[]` passaria tambem com o duble no lugar
    errado.
    """
    import mobia.domain.agente.turno as turno

    chamadas: list[str] = []
    original = turno.absorver_sessoes_vinculadas

    async def registrando(*args: Any, **kwargs: Any) -> tuple[tuple[str, str], ...]:
        chamadas.append(kwargs["channel"])
        return await original(*args, **kwargs)

    monkeypatch.setattr(turno, "absorver_sessoes_vinculadas", registrando)
    await _falar_no_site(
        ws_cliente,
        redis_pool,
        [f"meu whats e {TELEFONE_DIGITADO}", "quero 2 quartos"],
        ClassificadorQueGuarda(),
    )
    assert chamadas == []

    await _falar_no_whatsapp(redis_pool, "oi", ClassificadorQueGuarda())
    assert chamadas == [CANAL_WHATSAPP]


async def test_fala_web_posterior_a_do_whatsapp_nao_entra_no_turno(
    ws_cliente, session, redis_pool
) -> None:
    """Revisao final da TEC-129 (I2): o turno do WhatsApp so enxerga o que o site
    disse ate a fala que ele responde -- o instante vem da propria mensagem, e
    nao do relogio de quando o turno roda."""
    fabrica = get_sessionmaker()
    [message_id] = await IngestionService(fabrica, redis_pool).ingest(
        [
            ParsedMessage(
                provider_message_id=f"wamid.{uuid.uuid4()}",
                sender_external_id=WA_ID,
                recipient_external_id="phone-number-id",
                content_type=MessageContentType.TEXTO,
                text_body="oi",
                raw_payload={},
            )
        ],
        channel=CANAL_WHATSAPP,
    )
    # O site fala DEPOIS de a mensagem do WhatsApp chegar, e antes de o turno
    # dela rodar.
    await _falar_no_site(
        ws_cliente,
        redis_pool,
        [f"meu whats e {TELEFONE_DIGITADO}"],
        ClassificadorQueGuarda(extracao=Extracao(quartos=2)),
    )

    no_whatsapp = ClassificadorQueGuarda()
    await process_message(_ctx(redis_pool, no_whatsapp, WhatsAppQueRegistra()), str(message_id))

    [contexto] = no_whatsapp.contextos
    assert {m.channel for m in contexto.literais} == {CANAL_WHATSAPP}
    # O criterio chega pela qualificacao, que nao e texto e nao tem instante.
    assert contexto.estado.quartos == 2
