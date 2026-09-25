"""A notificacao de ponta a ponta, com canais falsos."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from conftest import eventos_de_log  # type: ignore[import-not-found]
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.context.models import LeadQualification
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.sla import PRAZO_PADRAO_MINUTOS, PRAZO_QUENTE_MINUTOS, limite_de_aceite
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.notificacao.envio import KIND_DA_JANELA_HUMANA, notificar
from mobia.domain.notificacao.mensagem import Aviso
from mobia.infra.crypto import encrypt


class _CanalEspiao:
    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.recebidas: list[tuple[str, str, str]] = []

    async def enviar(self, *, destino: str, aviso: Aviso) -> None:
        self.recebidas.append((destino, aviso.assunto, aviso.corpo))


class _CanalQueFalha:
    def __init__(self, nome: str) -> None:
        self.nome = nome

    async def enviar(self, *, destino: str, aviso: Aviso) -> None:
        raise FalhaDeCanal(f"{self.nome} recusou")


class _OutboundFalso:
    """Duble de `OutboundPort` que so registra as chamadas."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[uuid.UUID, str, dict[str, Any]]] = []

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        self.chamadas.append((message_id, kind, payload))
        return True


# Dois candidatos fixos, ~12h opostos no relogio (2h-9h e 14h-21h). A escolha
# entre os dois -- nunca um horario calculado a partir da hora atual -- e o
# que evita a virada de meia-noite: um par assim so precisaria wrap-around se
# a janela em si cruzasse a meia-noite, e nenhum dos dois cruza.
_CANDIDATOS_DE_JANELA: tuple[tuple[int, int], ...] = ((2, 9), (14, 21))


def _folga_em_minutos(momento_min: int, inicio_hora: int, fim_hora: int) -> int:
    """Distancia, em minutos, de `momento_min` (0..1439) ate a janela [inicio_hora,
    fim_hora] (horas cheias), pelo lado mais curto do relogio de 24h -- CICLICA,
    entao 23:59 fica a 1 minuto de 00:00 e nao a quase um dia, que e exatamente
    a virada que o docstring de `_janela_fechada_para_agora` explica. Devolve
    -1 quando `momento_min` ja esta dentro da janela (nunca deveria ser
    escolhida nesse caso).
    """
    inicio_min = inicio_hora * 60
    fim_min = fim_hora * 60
    if inicio_min <= momento_min <= fim_min:
        return -1
    ida = (inicio_min - momento_min) % 1440
    volta = (momento_min - fim_min) % 1440
    return min(ida, volta)


def _janela_fechada_para_agora() -> tuple[int, int]:
    """Uma janela (inicio, fim) que NAO contem a hora local de agora, com folga.

    `notificar` nao recebe `momento` por parametro -- le `datetime.now(UTC)`
    por dentro --, entao o teste nao pode fixar o relogio: ele calcula a
    janela num instante e `notificar` le o relogio de novo, um pouco depois.
    A folga existe para que essa segunda leitura nao caia dentro da janela --
    sem ela, o teste flakearia raramente (contando so em minutos por dia) mas
    de verdade, exatamente quando o relogio vira de um lado da janela para o
    outro entre as duas leituras.

    **A escolha e entre dois candidatos fixos, nunca um horario calculado a
    partir da hora atual.** Uma primeira versao devolvia janelas como `(0, 9)`
    sempre que a hora atual fosse maior que 11 -- e com a hora atual em 23,
    a folga ate a borda `inicio=0` da propria janela, contada CICLICAMENTE
    (23:59 esta a 1 MINUTO de 00:00, nao a quase um dia), caia para cerca de
    um minuto: exatamente o cenario da virada de meia-noite que o paragrafo
    acima descreve. Escolher sempre entre os mesmos dois candidatos -- nunca
    construir a janela a partir da hora atual -- elimina essa classe de erro
    por construcao: nenhum dos dois cruza a meia-noite, e a escolha (pelo
    maior `_folga_em_minutos` dentre os dois) so decide QUAL usar, nunca
    onde colocar a borda.

    Verificado numericamente para os 1440 minutos do dia (nao so as 24 horas
    cheias): a pior folga entre os dois candidatos e de **150 minutos
    (2h30min)**, no minuto 11:30 (e, por simetria, 23:30) -- o ponto medio
    exato entre as duas janelas, onde as duas ficam igualmente distantes.
    """
    agora = datetime.now(UTC).astimezone(get_settings().fuso_de_envio)
    momento_min = agora.hour * 60 + agora.minute
    return max(_CANDIDATOS_DE_JANELA, key=lambda janela: _folga_em_minutos(momento_min, *janela))


async def test_notifica_os_dois_canais_com_resumo_e_link(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Primeiro cenario do Gherkin, com dubles -- ver a L1 do desenho."""
    corretor = await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="## Quem e o lead\nfulano")
    email, whats = _CanalEspiao("email"), _CanalEspiao("whatsapp")

    assert await notificar(
        session_factory, canais=(email, whats), outbound=_OutboundFalso(), handoff_id=handoff_id
    )

    for canal in (email, whats):
        assert len(canal.recebidas) == 1
        _, _, corpo = canal.recebidas[0]
        assert "## Quem e o lead" in corpo
        assert "/conversas/whatsapp/" in corpo

    assert email.recebidas[0][0] == corretor.email
    assert whats.recebidas[0][0] == corretor.telefone


async def test_falha_de_um_canal_nao_cancela_o_outro(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Segundo cenario do Gherkin."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    email = _CanalEspiao("email")

    assert await notificar(
        session_factory,
        canais=(_CanalQueFalha("whatsapp"), email),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    assert len(email.recebidas) == 1
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.notificado_em is not None
    assert linha.aviso_manual_pendente is False


async def test_falha_dos_dois_marca_aviso_manual(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Terceiro cenario do Gherkin."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert not await notificar(
        session_factory,
        canais=(_CanalQueFalha("email"), _CanalQueFalha("whatsapp")),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.notificado_em is None
    assert linha.aviso_manual_pendente is True


async def test_sem_destinatario_marca_aviso_manual(
    session, session_factory, semear_handoff_com_resumo
) -> None:
    """D4: nenhum corretor cadastrado.

    Escala na hora (emenda E-02 da RN-16.3): sem corretor nao ha jornada
    contra a qual contar um prazo, entao `sla_limite_em` fica nulo PARA
    SEMPRE -- dar um prazo generico inventaria um dono que nao existe.
    """
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert not await notificar(
        session_factory,
        canais=(_CanalEspiao("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.aviso_manual_pendente is True
    assert linha.status == Status.ESCALADO
    assert linha.sla_limite_em is None


async def _semear_qualificacao(
    session: AsyncSession, *, channel: str, conversation_key: str, temperatura: str | None
) -> None:
    session.add(
        LeadQualification(
            channel=channel, conversation_key=conversation_key, temperatura=temperatura
        )
    )
    await session.commit()


# Jornada quase o dia inteiro (o CHECK `ck_corretores_jornada` proibe `fim=24`,
# que nao e expressavel -- mesma borda de `followup_horario_fim`, ver
# `app/config.py`). Existe para que os prazos de 15 min (QUENTE) e 240 min
# (MORNO/nulo) caibam no MESMO dia relativo ao instante em que o teste roda,
# na maioria das horas -- e para as poucas que nao cabem (perto de 23h), o
# proprio `limite_de_aceite` resolve o estouro para o dia seguinte, e as
# fronteiras `antes`/`depois` abaixo continuam validas porque a funcao e
# monotona no instante de entrada.
_JORNADA_QUASE_INTEIRA = (0, 23)


async def _grava_sla_esperado(
    handoff_id, session_factory, *, canais, temperatura: str | None
) -> tuple[datetime, datetime]:
    """Chama `notificar` e devolve os limites [antes, depois] do `sla_limite_em`.

    `notificar` le `datetime.now(UTC)` por dentro -- o teste nao controla esse
    relogio -- entao em vez de comparar por igualdade, calcula o mesmo
    `limite_de_aceite` nas duas pontas do instante em que a chamada rodou.
    `limite_de_aceite` e monotona nao-decrescente no `inicio` (mais cedo nunca
    produz um limite mais tarde), entao o valor gravado tem de cair entre as
    duas pontas, qualquer que seja a hora em que a suite rode.
    """
    antes = datetime.now(UTC)
    await notificar(
        session_factory, canais=canais, outbound=_OutboundFalso(), handoff_id=handoff_id
    )
    depois = datetime.now(UTC)

    fuso = get_settings().fuso_de_envio
    minutos = PRAZO_QUENTE_MINUTOS if temperatura == "QUENTE" else PRAZO_PADRAO_MINUTOS
    inicio, fim = _JORNADA_QUASE_INTEIRA
    limite_min = limite_de_aceite(
        inicio=antes, minutos=minutos, jornada_inicio=inicio, jornada_fim=fim, fuso=fuso
    )
    limite_max = limite_de_aceite(
        inicio=depois, minutos=minutos, jornada_inicio=inicio, jornada_fim=fim, fuso=fuso
    )
    return limite_min, limite_max


async def test_handoff_de_lead_quente_grava_sla_de_quinze_minutos(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """D2/emenda E-01 da RN-16.3: a temperatura vem de `lead_qualification`,
    NUNCA do gatilho -- `semear_handoff_com_resumo` sempre abre com
    `Gatilho.LEAD_QUENTE`, e mesmo assim so o registro QUENTE em
    `lead_qualification` deveria produzir os 15 minutos.
    """
    canal, conversa = "whatsapp", "5511900000001"
    await semear_corretor(
        email="plantao@x.com",
        plantao=True,
        horario_inicio=_JORNADA_QUASE_INTEIRA[0],
        horario_fim=_JORNADA_QUASE_INTEIRA[1],
    )
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal=canal, conversa=conversa)
    await _semear_qualificacao(
        session, channel=canal, conversation_key=conversa, temperatura="QUENTE"
    )

    limite_min, limite_max = await _grava_sla_esperado(
        handoff_id,
        session_factory,
        canais=(_CanalEspiao("email"),),
        temperatura="QUENTE",
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.sla_limite_em is not None
    assert limite_min <= linha.sla_limite_em <= limite_max


async def test_handoff_de_lead_morno_grava_sla_de_quatro_horas(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    canal, conversa = "whatsapp", "5511900000002"
    await semear_corretor(
        email="plantao@x.com",
        plantao=True,
        horario_inicio=_JORNADA_QUASE_INTEIRA[0],
        horario_fim=_JORNADA_QUASE_INTEIRA[1],
    )
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal=canal, conversa=conversa)
    await _semear_qualificacao(
        session, channel=canal, conversation_key=conversa, temperatura="MORNO"
    )

    limite_min, limite_max = await _grava_sla_esperado(
        handoff_id,
        session_factory,
        canais=(_CanalEspiao("email"),),
        temperatura="MORNO",
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.sla_limite_em is not None
    assert limite_min <= linha.sla_limite_em <= limite_max


async def test_handoff_de_lead_sem_temperatura_grava_as_quatro_horas_padrao(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """`temperatura` nula (linha anterior a TEC-151) conta como nao-QUENTE --
    NUNCA como os 15 minutos do QUENTE.
    """
    canal, conversa = "whatsapp", "5511900000003"
    await semear_corretor(
        email="plantao@x.com",
        plantao=True,
        horario_inicio=_JORNADA_QUASE_INTEIRA[0],
        horario_fim=_JORNADA_QUASE_INTEIRA[1],
    )
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal=canal, conversa=conversa)
    await _semear_qualificacao(session, channel=canal, conversation_key=conversa, temperatura=None)

    limite_min, limite_max = await _grava_sla_esperado(
        handoff_id,
        session_factory,
        canais=(_CanalEspiao("email"),),
        temperatura=None,
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.sla_limite_em is not None
    assert limite_min <= linha.sla_limite_em <= limite_max


async def test_resumo_que_nao_decifra_notifica_mesmo_assim(
    session, session_factory, semear_handoff_com_resumo, semear_corretor, caplog
) -> None:
    """Important 1 da revisao final: `DecryptionError` degrada, nao derruba.

    Cifra o `resumo` com um AAD errado -- rotacao de chave, escrita parcial e
    restore de outro ambiente produzem o mesmo `InvalidTag` na leitura. Sem a
    guarda em `notificar`, isto subiria cru e deixaria o handoff sem
    `notificado_em` e sem `aviso_manual_pendente`, invisivel para sempre.
    """
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="## Quem e o lead\nfulano")
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(resumo=encrypt("outro texto", "aad errado"))
    )
    await session.commit()
    email = _CanalEspiao("email")

    with caplog.at_level("WARNING"):
        assert await notificar(
            session_factory, canais=(email,), outbound=_OutboundFalso(), handoff_id=handoff_id
        )

    _, _, corpo = email.recebidas[0]
    assert "nao pode ser gerado" in corpo

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.notificado_em is not None
    assert linha.aviso_manual_pendente is False

    avisos = eventos_de_log(caplog, "notificacao.resumo_ilegivel")
    assert len(avisos) == 1
    assert avisos[0].corpo["handoff_id"] == str(handoff_id)
    assert avisos[0].corpo["erro"] == "DecryptionError"
    # Nunca o blob nem o texto decifrado -- so o tipo do erro e o handoff_id.
    #
    # `ensure_ascii=False`, e nao o default, pela mesma razao que o comentario
    # de `test_conversa_encerrada.py` registra: com o escape ligado, agulha
    # acentuada NUNCA e achada, e a asserta passa dissesse o log o que
    # dissesse. As duas agulhas de hoje sao ASCII e passariam de qualquer
    # jeito -- o flag e o que mantem esta asserta real no dia em que alguem
    # trocar "fulano" por um nome de verdade, que e o que uma fixture destas
    # deveria usar. Guardado por `test_assercao_de_ausencia_sobre_log.py`.
    corpo_serializado = json.dumps(avisos[0].corpo, ensure_ascii=False)
    assert "fulano" not in corpo_serializado
    assert "outro texto" not in corpo_serializado


async def test_sucesso_apos_falha_anterior_limpa_aviso_manual_pendente(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Important 2 da revisao final: as duas colunas nao sao independentes.

    Caminho alcancavel hoje, descrito na revisao: handoff criado SEM plantao
    cadastrado termina `aviso_manual_pendente=True`; alguem cadastra o
    plantao; uma retentativa do ARQ roda `notificar` de novo e aceita. O
    handoff nao pode terminar com `notificado_em` preenchido E
    `aviso_manual_pendente` ainda verdadeiro -- as duas tem de descrever o
    estado CORRENTE, nunca um historico.
    """
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert not await notificar(
        session_factory,
        canais=(_CanalEspiao("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.aviso_manual_pendente is True
    assert linha.notificado_em is None

    await semear_corretor(email="plantao@x.com", plantao=True)

    assert await notificar(
        session_factory,
        canais=(_CanalEspiao("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    # `session` e `get_sessionmaker()` abre com `expire_on_commit=False`
    # (`infra/db.py`) -- sem este `expire`, o SELECT abaixo devolveria o
    # objeto ja identity-mapped pelo SELECT anterior, com os valores de ANTES
    # do UPDATE que `notificar` fez por uma sessao propria. Mesmo motivo do
    # `session.expire` em `test_fora_da_jornada_e_nenhum_canal_aceitou_ainda_assim_avisa_o_lead`
    # acima.
    session.expire(linha)
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.notificado_em is not None
    assert linha.aviso_manual_pendente is False


async def test_notificar_duas_vezes_nao_recalcula_o_sla(
    session: AsyncSession, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """Ruling R3 (I2 da revisao final): D1 -- "gravado uma vez e nao recalculado".

    A retentativa e caminho declarado (L3 da TEC-177), nao hipotese: uma
    segunda chamada de `notificar` sobre o MESMO handoff nao pode mover
    `sla_limite_em`. A prova exige que um recalculo desse um valor DIFERENTE
    do original -- senao a assercao passaria mesmo sem guarda nenhuma. Por
    isso a jornada do corretor muda para uma janela hoje FECHADA
    (`_janela_fechada_para_agora`, ja usada acima) entre as duas chamadas: se
    a segunda chamada recalculasse, o novo limite so comecaria a contar na
    proxima abertura -- um valor bem posterior ao gravado na primeira vez.
    """
    email_corretor = "plantao_recalculo@x.com"
    await semear_corretor(
        email=email_corretor,
        plantao=True,
        horario_inicio=_JORNADA_QUASE_INTEIRA[0],
        horario_fim=_JORNADA_QUASE_INTEIRA[1],
    )
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert await notificar(
        session_factory,
        canais=(_CanalEspiao("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )
    primeira = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    sla_original = primeira.sla_limite_em
    assert sla_original is not None

    inicio_fechado, fim_fechado = _janela_fechada_para_agora()
    await session.execute(
        update(Corretor)
        .where(Corretor.email == email_corretor)
        .values(horario_inicio=inicio_fechado, horario_fim=fim_fechado)
    )
    await session.commit()

    assert await notificar(
        session_factory,
        canais=(_CanalEspiao("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    session.expire(primeira)
    segunda = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert segunda.sla_limite_em == sla_original


async def test_handoff_sem_resumo_notifica_mesmo_assim(
    session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """D2: silencio seria pior que resumo faltando."""
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo=None)
    email = _CanalEspiao("email")

    assert await notificar(
        session_factory, canais=(email,), outbound=_OutboundFalso(), handoff_id=handoff_id
    )

    _, _, corpo = email.recebidas[0]
    assert "nao pode ser gerado" in corpo


async def _semear_mensagem_do_lead(session: AsyncSession, *, handoff: Handoff) -> Message:
    mensagem = Message(
        id=uuid.uuid4(),
        channel=handoff.channel,
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id=handoff.conversation_key,
        recipient_external_id="222222222",
        conversation_key=handoff.conversation_key,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=None,
        raw_payload=None,
    )
    session.add(mensagem)
    await session.commit()
    return mensagem


async def test_fora_da_jornada_do_corretor_avisa_o_lead_da_janela_humana(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    semear_handoff_com_resumo,
    semear_corretor,
) -> None:
    """Quarto cenario do Gherkin: jornada fechada, e o lead e avisado.

    A jornada testada e a DO CORRETOR (`horario_inicio`/`horario_fim` de
    `Corretor`), calculada em funcao do relogio de agora -- ver
    `_janela_fechada_para_agora` -- para o teste nao depender da hora em que
    a suite roda. O corretor ainda recebe a notificacao normalmente: a
    jornada fechada so acrescenta o aviso ao lead, e nao impede o envio ao
    corretor.
    """
    inicio, fim = _janela_fechada_para_agora()
    await semear_corretor(
        email="plantao@x.com", plantao=True, horario_inicio=inicio, horario_fim=fim
    )
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal="whatsapp")
    handoff = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    mensagem_do_lead = await _semear_mensagem_do_lead(session, handoff=handoff)

    email = _CanalEspiao("email")
    outbound = _OutboundFalso()

    assert await notificar(
        session_factory, canais=(email,), outbound=outbound, handoff_id=handoff_id
    )

    assert len(email.recebidas) == 1

    assert len(outbound.chamadas) == 1
    message_id, kind, payload = outbound.chamadas[0]
    assert message_id == mensagem_do_lead.id
    assert kind == KIND_DA_JANELA_HUMANA
    assert payload["para"] == handoff.conversation_key
    assert payload["de"] == "222222222"
    assert f"{inicio}h" in payload["texto"]
    assert f"{fim}h" in payload["texto"]
    # O texto NAO pode afirmar que um corretor foi avisado nem que alguem vai
    # responder -- nenhuma das duas coisas e garantida hoje, ver o comentario
    # de `TEXTO_DA_JANELA_HUMANA`.
    assert "avisei" not in payload["texto"].lower()


async def test_fora_da_jornada_e_nenhum_canal_aceitou_ainda_assim_avisa_o_lead(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    semear_handoff_com_resumo,
    semear_corretor,
) -> None:
    """O aviso da janela humana nao promete entrega, entao roda mesmo quando
    `notificar` devolve `False` -- o handoff existe e a jornada do corretor
    designado esta fechada nos dois casos, aceite o canal ou nao.
    """
    inicio, fim = _janela_fechada_para_agora()
    await semear_corretor(
        email="plantao@x.com", plantao=True, horario_inicio=inicio, horario_fim=fim
    )
    handoff_id = await semear_handoff_com_resumo(resumo="texto", canal="whatsapp")
    handoff = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    mensagem_do_lead = await _semear_mensagem_do_lead(session, handoff=handoff)

    outbound = _OutboundFalso()

    assert not await notificar(
        session_factory,
        canais=(_CanalQueFalha("email"), _CanalQueFalha("whatsapp")),
        outbound=outbound,
        handoff_id=handoff_id,
    )

    # `session` ja tinha `handoff` na identity map (a leitura acima, antes de
    # `notificar`, para seguir a message do lead) -- sem isto a releitura
    # devolveria o objeto cacheado, com os valores de antes do UPDATE que
    # `notificar` fez por uma sessao propria. So este objeto, e nao
    # `expire_all()`: expirar `mensagem_do_lead` tambem faria o acesso a
    # `.id` mais abaixo tentar um refresh assincrono fora de um `await`.
    session.expire(handoff)
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.notificado_em is None
    assert linha.aviso_manual_pendente is True

    assert len(outbound.chamadas) == 1
    message_id, kind, payload = outbound.chamadas[0]
    assert message_id == mensagem_do_lead.id
    assert kind == KIND_DA_JANELA_HUMANA
    assert f"{inicio}h" in payload["texto"]
    assert f"{fim}h" in payload["texto"]


async def test_grava_o_destinatario_no_handoff(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """TEC-192, D6 e emenda E-06 da RN-16.2.

    Ate aqui a escolha do destinatario era usada e jogada fora: a notificacao
    enviava e gravava `notificado_em` sem dizer para quem. `handoffs.corretor_id`
    tem FK desde a TEC-196 e nunca teve escritor -- a emenda E-05 da RN-16.1
    registrou isso em 24/09/2026 e declarou o criterio "handoff aponta o
    corretor" INEXERCITAVEL. E ele que a lista de leads consulta para responder
    "de quem e este lead".
    """
    plantao = await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert await notificar(
        session_factory,
        canais=(_CanalEspiao("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.corretor_id == plantao.id


async def test_grava_o_destinatario_mesmo_quando_o_canal_falha(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """O destinatario foi ESCOLHIDO; a falha e do canal.

    Sem esta asserta, um handoff que falhou na entrega ficaria sem dono na
    lista de leads -- e e justamente o que precisa de aviso manual, o que o
    corretor mais precisa enxergar.
    """
    plantao = await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")

    assert not await notificar(
        session_factory,
        canais=(_CanalQueFalha("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.corretor_id == plantao.id
    assert linha.aviso_manual_pendente is True


async def test_nao_troca_o_dono_numa_retentativa(
    session, session_factory, semear_handoff_com_resumo, semear_corretor
) -> None:
    """So grava quando nula, pela disciplina do `sla_limite_em`.

    Uma retentativa do ARQ recalcula a cascata, e o plantao de agora pode nao
    ser o de entao. Sobrescrever trocaria o dono do lead por causa de um
    reenvio -- o mesmo defeito que a D8 da TEC-178 evita para `aceito_em`.
    """
    await semear_corretor(email="plantao@x.com", plantao=True)
    handoff_id = await semear_handoff_com_resumo(resumo="texto")
    dono_original = (await semear_corretor(email="dono@x.com")).id
    await session.execute(
        update(Handoff).where(Handoff.id == handoff_id).values(corretor_id=dono_original)
    )
    await session.commit()

    await notificar(
        session_factory,
        canais=(_CanalEspiao("email"),),
        outbound=_OutboundFalso(),
        handoff_id=handoff_id,
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.corretor_id == dono_original
