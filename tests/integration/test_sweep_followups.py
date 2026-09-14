"""A varredura da cadencia, ponta a ponta.

TEC-183. Integracao: a decisao mora na funcao pura, mas quem entra na
varredura e o que ela grava so da para verificar contra o banco.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import OutboundFake  # type: ignore[import-not-found]
from sqlalchemy import select

import mobia.workers.jobs.sweep_followups as sweep_followups_module
from mobia.app.config import Settings
from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.mensagem import CONVITE_PARA_AGENDAR
from mobia.domain.followup.models import FollowUp
from mobia.domain.followup.repositorio import Candidato, candidatos_a_followup
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.models import EVENTO_OPT_OUT, OptoutEvent
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import EnvioForaDaJanela
from mobia.domain.texto import dobrar
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_followups import MAXIMO_DE_ENVIOS_POR_EXECUCAO, sweep_followups

CANAL = "whatsapp"
CONVERSA = "5511944443333"

# Nome do fuso, e nao so o ZoneInfo: `_ctx()` passa este MESMO nome para
# `Settings`, para o fuso do relogio dos testes e o fuso da varredura nao
# poderem divergir.
NOME_DO_FUSO = "America/Sao_Paulo"
FUSO = ZoneInfo(NOME_DO_FUSO)

# Todo teste deste arquivo fixa `agora`. Com a guarda de horario da TEC-185 a
# varredura depende da hora do dia, e sem fixar o momento a suite inteira desta
# card passaria ou reprovaria conforme a hora em que o CI rodasse. Nao da para
# resolver com uma janela "sempre aberta": a borda e inclusiva no minuto, entao
# `inicio=0, fim=23` recusa 23:01-23:59.
DENTRO_DA_JANELA = datetime(2026, 9, 4, 14, 0, tzinfo=FUSO).astimezone(UTC)
FORA_DA_JANELA = datetime(2026, 9, 4, 3, 0, tzinfo=FUSO).astimezone(UTC)


async def _lead(
    session,
    *,
    temperatura: str | None = "QUENTE",
    calado_ha: timedelta,
    agora: datetime = DENTRO_DA_JANELA,
    semear_qualificacao: bool = True,
    conversa: str = CONVERSA,
) -> uuid.UUID:
    """Um lead com temperatura e uma fala de entrada com a idade pedida.

    `agora` e a referencia da idade, e nao `datetime.now()`: a varredura
    tambem recebe um momento fixo, e os dois tem de concordar.

    Devolve o id da mensagem semeada -- e a ancora que `candidatos_a_followup`
    deve carregar. `semear_qualificacao=False` pula a `LeadQualification`: a
    PK dela e por conversa, entao uma segunda fala na MESMA conversa (para
    testar qual das duas vira a ancora) nao pode semear-la de novo.

    `conversa` existe para os testes que precisam de VARIOS leads devidos ao
    mesmo tempo (o teto por execucao, o lote que nao pode ser derrubado por um
    candidato): a PK de `lead_qualification` e por conversa, entao dois leads
    distintos so existem com chaves distintas.
    """
    if semear_qualificacao:
        session.add(
            LeadQualification(
                channel=CANAL,
                conversation_key=conversa,
                intencao=Intencao.COMPRA.value,
                faixa_preco_max_centavos=50_000_000,
                regiao="vila mariana",
                urgencia=Urgencia.IMEDIATA.value,
                temperatura=temperatura,
            )
        )
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=conversa,
            recipient_external_id="222222222",
            conversation_key=conversa,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            created_at=agora - calado_ha,
        )
    )
    await session.commit()
    return identificador


def _ctx(outbound: object | None = None) -> dict:
    """A janela default da card (9h-20h, fuso `NOME_DO_FUSO`) explicita, e nao
    herdada do ambiente -- as TRES pontas, nao so duas.

    **A chave `outbound` e a MESMA que producao usa** (TEC-184): `startup`
    grava `ctx["outbound"] = WhatsAppOutbound(...)` em `workers/main.py`, e o
    job le dali -- nenhum default de producao mudou para este teste existir.
    Sem argumento vale um `OutboundFake` novo por chamada, porque quase todo
    teste deste arquivo so precisa que a porta EXISTA; quem inspeciona o que
    saiu passa o seu (da fixture `outbound_fake`, ou uma subclasse).

    `_env_file=None` desliga o `.env`, mas nao a variavel de ambiente do
    PROCESSO -- e kwarg de construtor vence env var, entao `inicio` e `fim`
    ja ficavam pinados so com eles no `Settings(...)`. O `followup_fuso` NAO
    ficava: sem o kwarg abaixo ele vinha direto do ambiente, e o horario e
    metade fuso -- um `FOLLOWUP_FUSO` exportado na maquina de quem roda o
    teste bastaria para reintroduzir a mesma nao-determinismo de relogio de
    parede que a D10 existe para eliminar. Passar `NOME_DO_FUSO` aqui, o
    mesmo nome que constroi o `FUSO` do modulo, fecha o buraco e impede as
    duas pontas de divergirem entre si.
    """
    return {
        "session_factory": get_sessionmaker(),
        "outbound": outbound if outbound is not None else OutboundFake(get_sessionmaker()),
        "settings": Settings(
            _env_file=None,
            followup_horario_inicio=9,
            followup_horario_fim=20,
            followup_fuso=NOME_DO_FUSO,
        ),
    }


@pytest.fixture(autouse=True)
def sem_prosa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum teste deste arquivo fala com o provedor.

    `redigir_abertura` chama `get_client()` direto (molde de
    `handoff/resumo.py`), entao sem esta troca cada candidato tentaria um POST
    de verdade. Ele nao quebraria o teste -- o `except Exception` de la
    devolve `None` e o follow-up sai sem prefixo --, mas pagaria o timeout do
    cliente por candidato, e o teste do teto tem VINTE E SEIS deles.

    `autouse` e nao fixture pedida: esquecer de pedi-la num teste novo nao
    daria erro nenhum, so uma suite lenta que ninguem associa a isto. Quem
    precisa de prefixo troca de novo por cima -- o ultimo `setattr` vence.

    O que a prosa faz com a ficha e com a queda esta em
    `tests/unit/test_prosa_do_followup.py`; aqui o que se verifica e a
    varredura.
    """

    async def _sem_abertura(
        session: object,
        *,
        channel: str,
        conversation_key: str,
        ficha: object,
        queda: object,
    ) -> None:
        return None

    monkeypatch.setattr(sweep_followups_module, "redigir_abertura", _sem_abertura)


async def test_o_candidato_traz_o_id_da_mensagem_ancora(session) -> None:
    """D1: e este id que ancora a reserva de saida do follow-up.

    Sem ele, `outbound_dispatches` (que tem FK para `messages`) nao teria a
    que se prender, e as guardas de opt-out e silencio -- que resolvem o lead
    PELA mensagem -- ficariam sem sujeito.
    """
    antiga = await _lead(session, calado_ha=timedelta(days=2))
    recente = await _lead(session, calado_ha=timedelta(hours=3), semear_qualificacao=False)

    (candidato,) = await candidatos_a_followup(session, agora=DENTRO_DA_JANELA)

    assert candidato.ancora_message_id == recente, (
        "a ancora e a ULTIMA fala do lead, nao a primeira -- com uma fala so "
        "este teste nao distinguiria as duas"
    )
    assert candidato.ancora_message_id != antiga


async def test_o_desempate_por_id_e_estavel_quando_duas_falas_empatam_no_carimbo(
    session,
) -> None:
    """A defesa contra o empate que `IngestionService._persist` produz de
    verdade: um envelope com duas mensagens do mesmo lead entregues juntas
    grava as duas com o MESMO `created_at`, porque `_persist` faz um unico
    INSERT multi-VALUES sem passar `created_at` -- a coluna cai no
    `server_default` `now()`, que e constante dentro do mesmo statement.

    Sem desempate por `id`, qual das duas vira `ancora_message_id` seria
    indefinido -- o Postgres poderia escolher qualquer uma, e nao de forma
    estavel entre execucoes. Este teste prende as duas pontas: chama
    `candidatos_a_followup` duas vezes e afirma que as duas devolvem o MESMO
    id, e que esse id e o que o desempate `id DESC` de fato escolhe (o maior
    dos dois).
    """
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.IMEDIATA.value,
            temperatura="QUENTE",
        )
    )
    empatada_em = DENTRO_DA_JANELA - timedelta(hours=3)
    identificadores = [uuid.uuid4(), uuid.uuid4()]
    esperado = max(identificadores)
    for identificador in identificadores:
        session.add(
            Message(
                id=identificador,
                channel=CANAL,
                provider_message_id=f"wamid.{identificador.hex[:10]}",
                sender_external_id=CONVERSA,
                recipient_external_id="222222222",
                conversation_key=CONVERSA,
                role=MessageRole.LEAD,
                direction=MessageDirection.INBOUND,
                content_type=MessageContentType.TEXTO,
                text_body=encrypt("oi", aad_de(identificador, "text_body")),
                raw_payload=None,
                status=MessageStatus.PROCESSED,
                created_at=empatada_em,
            )
        )
    await session.commit()

    (primeira,) = await candidatos_a_followup(session, agora=DENTRO_DA_JANELA)
    (segunda,) = await candidatos_a_followup(session, agora=DENTRO_DA_JANELA)

    assert primeira.ancora_message_id == esperado
    assert segunda.ancora_message_id == esperado


async def test_o_quente_calado_ha_duas_horas_recebe_a_primeira(session, caplog) -> None:
    """A CA-13.1, ponta a ponta."""
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5))

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 1
    linhas = (await session.scalars(select(FollowUp))).all()
    assert len(linhas) == 1
    assert linhas[0].tentativa_numero == 1
    assert linhas[0].temperatura == "QUENTE"
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 1


async def test_o_lead_com_optout_nao_recebe_nada(session, caplog) -> None:
    """O criterio de aceite do opt-out. `esta_em_optout` e a unica
    implementacao desse fato, e a varredura a consulta em vez de reescrever a
    regra em SQL."""
    await _lead(session, calado_ha=timedelta(days=30))
    session.add(
        OptoutEvent(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            evento=EVENTO_OPT_OUT,
        )
    )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 0
    assert (await session.scalars(select(FollowUp))).all() == []
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 0


async def test_a_conversa_silenciada_nao_recebe_followup(
    session, semear_corretor, banco_limpo, caplog
) -> None:
    """O terceiro cenario do Gherkin da TEC-179: conversa assumida por um
    corretor nao dispara automacao nenhuma.

    A assercao cobre as DUAS consequencias, nao so o retorno: sem a guarda no
    laco, a tentativa seria gravada em `followups` (append-only) mesmo com a
    guarda da porta de saida barrando o envio depois -- e essas tentativas
    fantasma contariam contra o lead na RN-13.1 quando a conversa fosse
    devolvida. Checar so `gravadas == 0` passaria mesmo com a guarda no lugar
    errado.
    """
    await _lead(session, calado_ha=timedelta(days=30))
    corretor_id = (await semear_corretor(email=f"p-{uuid.uuid4().hex[:8]}@ex.com")).id
    await assumir(session, channel=CANAL, conversation_key=CONVERSA, corretor_id=corretor_id)
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 0
    assert (await session.scalars(select(FollowUp))).all() == []
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 0


async def test_o_lead_muito_atrasado_recebe_uma_tentativa_so(session) -> None:
    """A guarda contra a rajada: dez dias de silencio dao as quatro do QUENTE
    vencidas, e a varredura grava so a quarta. Rodar de novo nao grava mais
    nada."""
    await _lead(session, calado_ha=timedelta(days=10))

    assert await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA) == 1
    assert await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA) == 0

    linhas = (await session.scalars(select(FollowUp))).all()
    assert [linha.tentativa_numero for linha in linhas] == [4]


async def test_a_segunda_passagem_nao_repete_a_tentativa_ja_servida(session) -> None:
    """Um lead ja atendido nao recebe nada novo enquanto nada mais vence.

    A primeira varredura grava a tentativa 1 (QUENTE, +2h). Na segunda, com
    `ja_disparada=1` e so 3h decorridas, `tentativa_devida` nao acha nenhuma
    tentativa vencida (a proxima, +24h, ainda nao chegou) e o loop pula antes
    de tocar `registrar_followup` -- o zero vem de "nada esta devido", nao do
    `UNIQUE` absorvendo um conflito. Esse caso e coberto a parte, no nivel do
    job, por `test_a_varredura_absorve_a_corrida_entre_duas_passagens`
    abaixo."""
    await _lead(session, calado_ha=timedelta(hours=3))

    assert await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA) == 1
    assert await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA) == 0


async def test_a_varredura_absorve_a_corrida_entre_duas_passagens(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A defesa de verdade contra duas varreduras concorrentes, testada no
    nivel do job e nao so no repositorio.

    Nenhuma escolha de numeros faz o teste anterior (que so pre-inseria uma
    linha e deixava `candidatos_a_followup` rodar de verdade) funcionar:
    `ja_disparada` e `MAX(tentativa_numero)` sob a ancora, entao qualquer
    linha pre-inserida que colidisse com o que a varredura fosse gravar ja
    teria subido `ja_disparada` o bastante para `tentativa_devida` escolher
    uma tentativa MAIOR -- nunca a que colidiria. O zero saia sempre de "nada
    esta devido", nunca do `ON CONFLICT DO NOTHING` absorvendo alguma coisa --
    um espiao em `registrar_followup` no teste antigo media ZERO chamadas.

    A saida e mockar a fronteira da consulta: `candidatos_a_followup` e
    substituida por um coroutine que devolve um `Candidato` construido a mao,
    com `ja_disparada=0`, enquanto a linha para a tentativa 1 sob a MESMA
    `ancora_em` ja existe na tabela. Mockar aqui e legitimo -- a consulta e a
    fronteira, e o que este teste cobre e o tratamento de conflito do job, nao
    a consulta em si (que tem os proprios testes em
    `test_followups_model.py`). `ancora_em` tem de ser EXATAMENTE igual entre
    o candidato mockado e a linha pre-inserida, senao o `UNIQUE` nao bate e o
    teste volta a ser vacuo.

    Sem o `ON CONFLICT DO NOTHING` (ou com o nome errado de constraint), o
    `INSERT` levantaria `IntegrityError` e a varredura quebraria no meio do
    lote. A nao-vacuidade repousa no calculo: o `Candidato` mockado e a linha
    pre-inserida compartilham os quatro campos do `UNIQUE` (`channel`,
    `conversation_key`, `ancora_em`, `tentativa_numero`), e `tentativa_devida`
    com `ja_disparada=0` e cerca de duas horas e cinco minutos decorridos retorna
    tentativa 1, exatamente a que a linha pre-inserida ocupa. Esse e o conflito
    genuino. Que o `INSERT` chega ao banco foi verificado alterando-se a
    constraint para `uq_followups_tentativa_por_ancora_typo` em `registrar_followup`:
    o teste falha com `sqlalchemy.exc.ProgrammingError` (constraint inexistente)."""
    ancora = DENTRO_DA_JANELA - timedelta(hours=2, minutes=5)
    candidato = Candidato(
        channel=CANAL,
        conversation_key=CONVERSA,
        temperatura=Temperatura.QUENTE,
        ancora_em=ancora,
        # ancora_message_id virou campo obrigatorio com a TEC-184. Este teste
        # mocka a fronteira da consulta e nao exercita a D1 -- so precisa de
        # um id qualquer.
        #
        # Um id sem linha em `messages` so passa porque o laco NUNCA chega ao
        # envio neste cenario: `registrar_followup` devolve `None` (o conflito
        # que o teste monta) e a iteracao para ali, antes da reserva de
        # `outbound_dispatches`, que tem FK para `messages`. Se alguem mover o
        # envio para antes do registro, este teste passa a falhar por
        # `IntegrityError` de FK -- e essa falha e informacao, nao ruido.
        ancora_message_id=uuid.uuid4(),
        ja_disparada=0,
        # ja_enviadas virou campo obrigatorio com a TEC-188. Este teste e da
        # TEC-183 e nao exercita o antispam -- so precisa de um valor que nao
        # acione a guarda, e 0 e o mais neutro.
        ja_enviadas=0,
    )

    async def _candidatos_a_followup_stub(session, *, agora, limite=500):
        return [candidato]

    monkeypatch.setattr(
        sweep_followups_module, "candidatos_a_followup", _candidatos_a_followup_stub
    )

    session.add(
        FollowUp(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            tentativa_numero=1,
            temperatura="QUENTE",
            ancora_em=ancora,
            devido_em=ancora + timedelta(hours=2),
        )
    )
    await session.commit()

    assert await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA) == 0

    linhas = (await session.scalars(select(FollowUp))).all()
    assert len(linhas) == 1


async def test_o_lead_que_falou_ha_pouco_nao_entra(session) -> None:
    await _lead(session, calado_ha=timedelta(minutes=30))

    assert await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA) == 0


async def test_o_lead_sem_temperatura_nao_entra(session) -> None:
    """A D3, ponta a ponta."""
    await _lead(session, temperatura=None, calado_ha=timedelta(days=30))

    assert await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA) == 0


async def test_a_madrugada_nao_dispara_nada(session, caplog) -> None:
    """A guarda da TEC-185, ponta a ponta: mesmo lead, mesma divida, outra hora.

    As duas assertivas existem porque devolver 0 sem gravar e gravar sem contar
    sao falhas diferentes, e um `return 0` no lugar errado passaria com uma so.
    """
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5), agora=FORA_DA_JANELA)

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=FORA_DA_JANELA)

    assert gravadas == 0
    assert (await session.scalars(select(FollowUp))).all() == []
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 0


async def test_o_adiamento_nao_consome_a_tentativa(session) -> None:
    """O criterio de aceite inteiro do adiamento, em tres momentos.

    "Parou de responder as 19h30 ... nada e enviado as 21h30 ... o follow-up e
    enviado as 9h do dia seguinte ... ele conta como a primeira tentativa."

    Nao existe codigo de adiamento: fora da janela nada e gravado,
    `ja_disparada` continua zero, e a varredura das 9h reencontra a MESMA
    tentativa 1 pela aritmetica. E o teste que morre se alguem tentar
    implementar o adiamento com estado -- uma linha PENDENTE, uma coluna
    `adiado_para` -- em vez de deixar a ancora responder.
    """
    parou = datetime(2026, 9, 4, 19, 30, tzinfo=FUSO)
    await _lead(session, calado_ha=timedelta(0), agora=parou.astimezone(UTC))

    tarde_da_noite = (parou + timedelta(hours=2)).astimezone(UTC)
    assert await sweep_followups(_ctx(), agora=tarde_da_noite) == 0
    assert (await session.scalars(select(FollowUp))).all() == []

    manha_seguinte = datetime(2026, 9, 5, 9, 0, tzinfo=FUSO).astimezone(UTC)
    assert await sweep_followups(_ctx(), agora=manha_seguinte) == 1

    linhas = (await session.scalars(select(FollowUp))).all()
    assert [linha.tentativa_numero for linha in linhas] == [1]


async def test_as_vinte_em_ponto_ainda_disparam(session) -> None:
    """A CA-13.1 e a borda das 20h no mesmo teste: um lead QUENTE que parou de
    falar as 18h vence a primeira tentativa (+2h) exatamente as 20h.

    A borda sobrevive nas duas pontas do caminho, e as duas sao inclusivas de
    proposito: o corte da consulta e `HAVING MAX(created_at) <= :corte` e a
    regua compara com `>=`. Trocar qualquer uma por estrita faz este teste
    reprovar por um instante.
    """
    parou = datetime(2026, 9, 4, 18, 0, tzinfo=FUSO)
    await _lead(session, calado_ha=timedelta(0), agora=parou.astimezone(UTC))

    vinte_em_ponto = (parou + timedelta(hours=2)).astimezone(UTC)
    assert await sweep_followups(_ctx(), agora=vinte_em_ponto) == 1


async def test_o_evento_de_maximo_sai_quando_a_quarta_e_gravada(session, caplog) -> None:
    """O criterio de aceite: "um evento registra que o teto foi atingido".

    Lead QUENTE calado ha mais de sete dias, com as tentativas 1, 2 e 3 ja
    gravadas sob a ancora. A quarta vence, e gravar ela fecha o maximo.
    """
    parou_ha = timedelta(days=8)
    await _lead(session, calado_ha=parou_ha, agora=DENTRO_DA_JANELA)
    ancora = DENTRO_DA_JANELA - parou_ha
    for numero in (1, 2, 3):
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=CONVERSA,
                tentativa_numero=numero,
                temperatura="QUENTE",
                ancora_em=ancora,
                devido_em=ancora + timedelta(days=numero),
            )
        )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 1
    assert sum(1 for r in caplog.records if "followup.antispam_atingido" in r.getMessage()) == 1


async def test_o_evento_de_maximo_nao_sai_na_terceira(session, caplog) -> None:
    """A outra metade da mesma assertiva: emitir cedo e emitir sempre sao
    defeitos diferentes, e um teste so nao separa os dois.

    Mesmo lead, duas tentativas gravadas em vez de tres, e silencio de quatro
    dias -- bastante para a tentativa 3 (+3d) e nao para a 4 (+7d).
    """
    parou_ha = timedelta(days=4)
    await _lead(session, calado_ha=parou_ha, agora=DENTRO_DA_JANELA)
    ancora = DENTRO_DA_JANELA - parou_ha
    for numero in (1, 2):
        session.add(
            FollowUp(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=CONVERSA,
                tentativa_numero=numero,
                temperatura="QUENTE",
                ancora_em=ancora,
                devido_em=ancora + timedelta(days=numero),
            )
        )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 1
    assert sum(1 for r in caplog.records if "followup.antispam_atingido" in r.getMessage()) == 0


async def test_o_evento_de_maximo_nao_confunde_contagem_com_posicao_da_regua(
    session, caplog
) -> None:
    """A distincao central da card, pinada onde os dois testes acima nao a
    alcancam: neles a contagem de linhas e a posicao da regua coincidem
    (tres linhas -> ja_enviadas=3, ou duas linhas -> ja_enviadas=2), entao um
    `if tentativa == MAXIMO_SEM_RESPOSTA` no lugar de
    `if ja_enviadas + 1 == MAXIMO_SEM_RESPOSTA` passaria nos dois sem se
    denunciar.

    Aqui a UNICA linha pre-existente sob a ancora e a tentativa 3 -- o caso do
    lead atrasado, que a regua ja pula direto para a maior tentativa vencida.
    `ja_disparada=3` (MAX) mantem o lead candidato (3 < 4), e `ja_enviadas=1`
    (COUNT). A varredura grava a tentativa 4, mas so DUAS mensagens sairam no
    total (a antiga mais esta) -- o evento NAO pode sair. Uma implementacao
    por posicao dispara aqui, cedo demais; a implementacao por contagem nao.
    """
    parou_ha = timedelta(days=8)
    await _lead(session, calado_ha=parou_ha, agora=DENTRO_DA_JANELA)
    ancora = DENTRO_DA_JANELA - parou_ha
    session.add(
        FollowUp(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=CONVERSA,
            tentativa_numero=3,
            temperatura="QUENTE",
            ancora_em=ancora,
            devido_em=ancora + timedelta(days=3),
        )
    )
    await session.commit()

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 1
    linhas = (await session.scalars(select(FollowUp))).all()
    assert [linha.tentativa_numero for linha in linhas] == [3, 4]
    assert sum(1 for r in caplog.records if "followup.antispam_atingido" in r.getMessage()) == 0


async def test_a_guarda_do_maximo_barra_o_candidato(
    session, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A guarda da D5, testada pela fronteira porque a consulta real nao a
    alcanca.

    O `UNIQUE` limita a quatro linhas por ancora e a cadencia do QUENTE para em
    quatro, entao `ja_enviadas=4` implica `ja_disparada=4`, que o corte de
    esgotamento ja exclui da candidatura. O ramo da guarda so tem cobertura se
    o `Candidato` vier construido a mao -- e mockar `candidatos_a_followup` e
    legitimo pelo mesmo motivo que no teste da corrida: a consulta e a
    fronteira, e o que se testa aqui e o tratamento do job.

    `ja_disparada=0` de proposito: sem isso `tentativa_devida` devolveria None e
    o teste passaria pela guarda errada, verde e vazio.

    A assertiva de `followup.antispam_atingido` nao e cosmetica: a D6 do
    desenho considerou e rejeitou emitir o evento a cada supressao, e essa
    alternativa rejeitada emitiria exatamente neste cenario -- com a suite
    inteira ainda verde, porque nenhum outro teste barra por esta guarda.
    """
    ancora = DENTRO_DA_JANELA - timedelta(hours=2, minutes=5)
    candidato = Candidato(
        channel=CANAL,
        conversation_key=CONVERSA,
        temperatura=Temperatura.QUENTE,
        ancora_em=ancora,
        # ancora_message_id virou campo obrigatorio com a TEC-184. Este teste
        # mocka a fronteira da consulta e nao exercita a D1 -- so precisa de
        # um id qualquer.
        #
        # Um id sem linha em `messages` so passa porque a guarda do maximo
        # corta este candidato antes de qualquer envio, e a reserva de
        # `outbound_dispatches` tem FK para `messages`. Se a guarda deixar de
        # cortar, este teste falha por FK antes de falhar pela assertiva -- o
        # que ainda e reprovar pelo motivo certo.
        ancora_message_id=uuid.uuid4(),
        ja_disparada=0,
        ja_enviadas=4,
    )

    async def _candidatos_a_followup_stub(session, *, agora, limite=500):
        return [candidato]

    monkeypatch.setattr(
        sweep_followups_module, "candidatos_a_followup", _candidatos_a_followup_stub
    )

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(), agora=DENTRO_DA_JANELA)

    assert gravadas == 0
    assert (await session.scalars(select(FollowUp))).all() == []
    assert sum(1 for r in caplog.records if "followup.devido" in r.getMessage()) == 0
    assert sum(1 for r in caplog.records if "followup.antispam_atingido" in r.getMessage()) == 0


async def _imovel(session: Any, codigo: str, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos. Molde de `tests/integration/test_novidade_do_followup.py`."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Trindade",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 59_000_000,
        "bairro": "Trindade",
        "cidade": "Florianopolis",
        "uf": "SC",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    campos.setdefault("bairro_busca", dobrar(str(campos["bairro"])))
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def _recomendar(session: Any, imovel_id: uuid.UUID, **sobrescritas: object) -> None:
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "imovel_id": imovel_id,
        "score_match": Decimal("0.870"),
        "motivo_match": "3 quartos, Trindade, dentro do teto",
        "apresentado_em": DENTRO_DA_JANELA,
    }
    campos.update(sobrescritas)
    session.add(Recomendacao(**campos))
    await session.commit()


async def test_o_followup_sai_pela_porta_ancorado_na_ultima_fala(session, outbound_fake) -> None:
    """D1: `message_id` e o da mensagem-ancora, `kind` e `followup_<n>`.

    A ancora nao e detalhe de implementacao: e ela que da a idempotencia por
    tentativa (a UNIQUE `(message_id, kind)` de `outbound_dispatches` espelha
    a de `followups`) e e por ela que as guardas de opt-out e de atendimento
    humano de `GuardedOutbound` resolvem o lead. Um `message_id` de outra
    mensagem passaria num teste de "algo saiu" e quebraria as duas coisas.

    Sem catalogo semeado nao ha queda nem imovel novo, entao o corpo e o
    convite -- o fundo da precedencia da D2, e o que torna a mensagem vazia
    impossivel (D6).
    """
    ancora = await _lead(session, calado_ha=timedelta(hours=2, minutes=5))
    outbound = outbound_fake()

    assert await sweep_followups(_ctx(outbound), agora=DENTRO_DA_JANELA) == 1

    assert outbound.entregues, "nada saiu -- o teste nao afirmaria nada"
    assert outbound.entregues == [CONVITE_PARA_AGENDAR]
    assert outbound.payloads[0]["para"] == CONVERSA
    # O nosso numero, que so existe na linha da mensagem -- `Candidato` nao o
    # carrega. Sem ele o POST iria para a URL errada da Meta.
    assert outbound.payloads[0]["de"] == "222222222"

    reservas = (await session.scalars(select(OutboundDispatch))).all()
    assert [(reserva.message_id, reserva.kind) for reserva in reservas] == [(ancora, "followup_1")]


async def test_a_segunda_varredura_nao_reenvia_a_mesma_tentativa(session, outbound_fake) -> None:
    """O lead recebe UMA mensagem por tentativa, mesmo com a varredura rodando
    de novo sobre o mesmo instante.

    **Qual das duas UNIQUEs absorve depende do caminho, e neste e a de
    `followups`**: a segunda passagem encontra `ja_disparada=1` e
    `tentativa_devida` nao devolve nada (a proxima posicao do QUENTE so vence
    em +24h), entao o laco para antes da porta. A UNIQUE `(message_id, kind)`
    de `outbound_dispatches` e a segunda tranca, para a corrida real entre
    duas varreduras concorrentes -- ela e exercitada em
    `test_a_reserva_de_saida_absorve_a_entrega_repetida`, logo abaixo.

    O que este teste prende e o observavel que importa para o lead, e ele
    reprovaria se alguem movesse o envio para antes de `registrar_followup`.
    """
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5))
    outbound = outbound_fake()

    assert await sweep_followups(_ctx(outbound), agora=DENTRO_DA_JANELA) == 1
    assert await sweep_followups(_ctx(outbound), agora=DENTRO_DA_JANELA) == 0

    assert len(outbound.entregues) == 1
    assert len((await session.scalars(select(FollowUp))).all()) == 1


async def test_a_reserva_de_saida_absorve_a_entrega_repetida(session, outbound_fake) -> None:
    """A outra tranca, a que a corrida entre duas varreduras usa.

    Com a reserva `(ancora, followup_1)` ja gravada -- o que uma varredura
    concorrente teria deixado --, `GuardedOutbound.send` devolve `False` sem
    chamar `_deliver`. A linha de `followups` e gravada do mesmo jeito, porque
    a supressao acontece do lado de fora do job.

    Sem esta tranca, duas varreduras simultaneas mandariam a mesma tentativa
    duas vezes -- e e por ela que `KIND_DO_FOLLOWUP` da um kind por tentativa
    em vez de um kind unico repetido: com kind unico, a supressao que protege
    a tentativa 1 engoliria tambem a 2.
    """
    ancora = await _lead(session, calado_ha=timedelta(hours=2, minutes=5))
    session.add(OutboundDispatch(id=uuid.uuid4(), message_id=ancora, kind="followup_1"))
    await session.commit()
    outbound = outbound_fake()

    assert await sweep_followups(_ctx(outbound), agora=DENTRO_DA_JANELA) == 1

    assert outbound.entregues == []
    assert len((await session.scalars(select(FollowUp))).all()) == 1


class _JanelaFechadaNoPrimeiro(OutboundFake):
    """Recusa so a PRIMEIRA entrega. Molde das subclasses de
    `test_apresentacao_no_turno.py`."""

    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.tentativas = 0

    async def _deliver(self, message_id, kind, payload) -> None:
        self.tentativas += 1
        if self.tentativas == 1:
            raise EnvioForaDaJanela("fora da janela de 24h")
        await super()._deliver(message_id, kind, payload)


async def test_fora_da_janela_de_24h_vira_log_e_nao_derruba_o_lote(session, caplog) -> None:
    """L1: hoje so a tentativa de 2h do QUENTE chega. As outras oito posicoes
    batem em `EnvioForaDaJanela`, e a varredura tem de seguir para o proximo
    candidato -- um lead fora da janela nao pode custar o follow-up dos
    outros.

    A recusa e no PRIMEIRO da fila, e nao no segundo: com ela no segundo o
    teste passaria mesmo sem o `except`, porque nao sobraria candidato para
    perder. A ordem da fila e `ORDER BY ancora_em`, entao quem calou ha mais
    tempo vem antes.
    """
    await _lead(session, calado_ha=timedelta(hours=3), conversa=CONVERSA)
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5), conversa="5511944443334")
    outbound = _JanelaFechadaNoPrimeiro(get_sessionmaker())

    with caplog.at_level(logging.INFO):
        gravadas = await sweep_followups(_ctx(outbound), agora=DENTRO_DA_JANELA)

    assert outbound.tentativas == 2, "o laco parou no primeiro candidato"
    assert len(outbound.entregues) == 1  # o segundo candidato saiu
    assert gravadas == 2
    assert sum(1 for r in caplog.records if "followup.fora_da_janela_de_24h" in r.getMessage()) == 1


async def test_a_linha_de_followups_permanece_quando_o_envio_e_recusado(
    session, outbound_fake
) -> None:
    """L1, a parte que custa: a tentativa e CONSUMIDA. `followups` e
    append-only e a linha e gravada antes do envio, entao ela nao volta
    quando a TEC-186 entrar. Este teste existe para que isso seja uma decisao
    visivel e nao um efeito colateral.

    O retorno continua sendo 1: ele conta linhas GRAVADAS, e nao mensagens
    entregues. Desfazer a linha aqui faria a varredura reprocessar a mesma
    tentativa a cada cinco minutos, pagando a chamada de prosa toda vez para
    bater na mesma recusa.
    """
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5))
    outbound = outbound_fake(EnvioForaDaJanela("fora da janela de 24h"))

    assert await sweep_followups(_ctx(outbound), agora=DENTRO_DA_JANELA) == 1

    assert outbound.entregues == []
    linhas = (await session.scalars(select(FollowUp))).all()
    assert len(linhas) == 1
    assert linhas[0].tentativa_numero == 1


async def test_o_teto_de_envios_por_execucao_corta_o_excedente(session, outbound_fake) -> None:
    """D7: com 26 candidatos devidos, 25 saem e 1 fica -- e ele continua
    devido na varredura seguinte, porque a cadencia e ancorada e nao
    encadeada.

    A segunda passagem e a metade que importa: um teto que DESCARTASSE o
    excedente em vez de adia-lo passaria na primeira assertiva e falharia
    aqui. Os 25 ja atendidos nao voltam -- `ja_disparada=1`, e a proxima
    posicao do QUENTE so vence em +24h.
    """
    total = MAXIMO_DE_ENVIOS_POR_EXECUCAO + 1
    for indice in range(total):
        await _lead(
            session,
            # Idades decrescentes para a ordem da fila (`ORDER BY ancora_em`)
            # ser determinada e nao sorteada pelo banco: quem sobra tem de ser
            # sempre o que calou ha menos tempo.
            calado_ha=timedelta(hours=2, minutes=5) + timedelta(minutes=total - indice),
            conversa=f"55119444{indice:05d}",
        )
    outbound = outbound_fake()

    gravadas = await sweep_followups(_ctx(outbound), agora=DENTRO_DA_JANELA)

    assert gravadas == MAXIMO_DE_ENVIOS_POR_EXECUCAO
    assert len(outbound.entregues) == MAXIMO_DE_ENVIOS_POR_EXECUCAO

    segunda = outbound_fake()
    assert await sweep_followups(_ctx(segunda), agora=DENTRO_DA_JANELA) == 1
    assert len(segunda.entregues) == 1
    assert len((await session.scalars(select(FollowUp))).all()) == total


async def test_a_queda_de_preco_e_a_abertura_falam_do_mesmo_imovel(
    session, outbound_fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A montagem inteira, ponta a ponta: novidade escolhida, prosa na frente,
    ficha e linha da queda no corpo.

    **A assertiva sobre os argumentos da prosa nao e cosmetica.** A abertura e
    o corpo tem de falar do MESMO imovel, e a unica coisa que garante isso e a
    `ficha` e a `queda` serem escolhidas uma vez e passadas as duas funcoes.
    Uma implementacao que consultasse a novidade de novo para a prosa
    entregaria um texto que parece certo e cita outro imovel -- e nenhuma
    assertiva sobre o texto entregue pegaria isso.

    A queda vence o convite pela precedencia da D2, e o preco da FICHA e o de
    hoje: quem carrega o valor antigo e a linha da queda.
    """
    vistos: dict[str, Any] = {}

    async def _abertura(session, *, channel, conversation_key, ficha, queda):
        vistos["ficha"] = ficha
        vistos["queda"] = queda
        return "Vi que voce procurava perto do centro"

    monkeypatch.setattr(sweep_followups_module, "redigir_abertura", _abertura)

    imovel = await _imovel(session, "AP-901", preco_venda=59_000_000)
    await _recomendar(session, imovel, preco_centavos=62_000_000)
    await _lead(session, calado_ha=timedelta(hours=2, minutes=5))
    outbound = outbound_fake()

    assert await sweep_followups(_ctx(outbound), agora=DENTRO_DA_JANELA) == 1

    (texto,) = outbound.entregues
    assert texto.startswith("Vi que voce procurava perto do centro")
    assert "Apartamento na Trindade" in texto
    assert "De R$ 620.000 por R$ 590.000" in texto
    assert CONVITE_PARA_AGENDAR not in texto

    assert vistos["queda"].imovel_id == imovel
    assert vistos["ficha"].id == imovel
    assert vistos["ficha"].preco_centavos == 59_000_000
