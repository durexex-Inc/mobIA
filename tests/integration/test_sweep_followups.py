"""A varredura da cadencia, ponta a ponta.

TEC-183. Integracao: a decisao mora na funcao pura, mas quem entra na
varredura e o que ela grava so da para verificar contra o banco.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import mobia.workers.jobs.sweep_followups as sweep_followups_module
from mobia.app.config import Settings
from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.atendimento.repositorio import assumir
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.models import FollowUp
from mobia.domain.followup.repositorio import Candidato
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.models import EVENTO_OPT_OUT, OptoutEvent
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.sweep_followups import sweep_followups

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
) -> None:
    """Um lead com temperatura e uma fala de entrada com a idade pedida.

    `agora` e a referencia da idade, e nao `datetime.now()`: a varredura
    tambem recebe um momento fixo, e os dois tem de concordar.
    """
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
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
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
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


def _ctx() -> dict:
    """A janela default da card (9h-20h, fuso `NOME_DO_FUSO`) explicita, e nao
    herdada do ambiente -- as TRES pontas, nao so duas.

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
        "settings": Settings(
            _env_file=None,
            followup_horario_inicio=9,
            followup_horario_fim=20,
            followup_fuso=NOME_DO_FUSO,
        ),
    }


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
