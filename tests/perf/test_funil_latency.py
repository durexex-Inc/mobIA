"""Criterio de aceite do TEC-190: p95 do painel abaixo de 2 s com 1.000 leads
(RNF-04, e o quarto cenario do Gherkin da card).

Marcado `perf` e fora do run padrao, no molde de `test_busca_latency.py`: a
medicao depende da maquina, e o `CLAUDE.md` registra que medir p95 em runner
compartilhado seria flake e nao sinal. Rode com `python -m pytest -m perf`.

**A fronteira medida e o BANCO**, e nao o HTTP: o que a RNF-04 poe em risco
sao as agregacoes sobre a coorte, e nao a serializacao de um dicionario com
vinte chaves. Medir pelo `AsyncClient` acrescentaria o ASGI e o middleware de
rate limit ao numero sem acrescentar risco.

**Dois grupos, nunca uma media.** Sem filtro e o caminho de custo pleno --
toda a coorte do periodo entra em todas as agregacoes. Com filtro de corretor
e o mais estreito, porque o JOIN com `handoffs` corta a coorte antes delas.
Uma media dos dois esconderia qual estoura o orcamento.

## Evidencia medida

- 2026-09-24, maquina de desenvolvimento Windows 11 rodando Postgres via
  docker compose, Python 3.13.15, 1.000 leads (2.000 mensagens, 1.000 linhas
  de `lead_qualification`, 200 handoffs), 20 medicoes por grupo apos
  `ANALYZE`: grupo "sem filtro" p50=0,062s p95=0,068s max=0,069s; grupo "por
  corretor" p50=0,053s p95=0,065s max=0,078s. Os dois PASSAM o teto de 2 s
  com cerca de **29x de margem**.

## O cache foi recusado, e a recusa e medida

A D5 do desenho condicionou o cache a esta medicao, e ela nao o pede: a
consulta ao vivo atende a RNF-04 com 29x de folga, e tem defasagem ZERO, o
que satisfaz o teto de 60 s da RN-17.3 de graca. Um cache aqui gastaria parte
desse teto de defasagem para comprar latencia que ja sobra.

**Quando reabrir a conta:** se a base crescer uma ordem de grandeza (10.000
leads) ou se o p95 aqui passar de ~1 s. A margem e grande, mas as agregacoes
varrem `messages` inteira para achar o nascimento de cada conversa -- e esse
e o custo que cresce com a base, nao com o periodo consultado. Rode este
teste antes de concluir qualquer coisa; nao e para ser estimado.
"""

import statistics
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import _corretor
from sqlalchemy import text

from mobia.domain.context.models import LeadQualification
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import Status
from mobia.domain.handoff.models import Handoff
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.metricas.filtros import Recorte, montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import Etapa
from mobia.infra.crypto import aad_de, encrypt

pytestmark = pytest.mark.perf

CANAL = "whatsapp"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
INICIO = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
LEADS = 1000
TETO_SEGUNDOS = 2.0
MEDICOES = 20


async def _semear(session, corretor_alvo: uuid.UUID) -> None:
    """1.000 leads espalhados por agosto, um quinto com handoff do alvo."""
    for indice in range(LEADS):
        conversa = f"5511{indice:09d}"
        nasceu = INICIO + timedelta(minutes=indice * 20)
        for fala in range(2):
            identificador = uuid.uuid4()
            session.add(
                Message(
                    id=identificador,
                    channel=CANAL,
                    provider_message_id=f"wamid.{identificador.hex[:12]}",
                    sender_external_id=conversa,
                    recipient_external_id="222222222",
                    conversation_key=conversa,
                    role=MessageRole.LEAD,
                    direction=MessageDirection.INBOUND,
                    content_type=MessageContentType.TEXTO,
                    text_body=encrypt("oi", aad_de(identificador, "text_body")),
                    raw_payload=None,
                    status=MessageStatus.PROCESSED,
                    created_at=nasceu + timedelta(minutes=fala),
                )
            )
        session.add(Conversa(channel=CANAL, conversation_key=conversa, status=Status.ATIVA))
        session.add(
            LeadQualification(
                channel=CANAL,
                conversation_key=conversa,
                temperatura=("QUENTE", "MORNO", "FRIO")[indice % 3],
                qualificado_em=(nasceu + timedelta(minutes=30)) if indice % 2 else None,
            )
        )
        if indice % 5 == 0:
            session.add(
                Handoff(
                    id=uuid.uuid4(),
                    channel=CANAL,
                    conversation_key=conversa,
                    gatilho="QUENTE",
                    etiqueta="LEAD_QUENTE",
                    prioridade="ALTA",
                    status="ACEITO",
                    corretor_id=corretor_alvo,
                    aceito_em=nasceu + timedelta(hours=1),
                    sla_limite_em=nasceu + timedelta(hours=2),
                    criado_em=nasceu,
                    atualizado_em=nasceu,
                )
            )
        if indice % 100 == 0:
            await session.commit()
    await session.commit()


async def _medir(session, recorte: Recorte) -> float:
    comeco = time.perf_counter()
    etapas = await contar_etapas(session, recorte=recorte)
    await calcular_indicadores(session, recorte=recorte, novos=etapas[Etapa.NOVO])
    return time.perf_counter() - comeco


async def test_p95_do_painel_com_mil_leads(session) -> None:
    corretor = await _corretor(session)
    await _semear(session, corretor)
    await session.execute(text("ANALYZE messages, lead_qualification, handoffs, recomendacoes"))

    grupos = (
        ("sem filtro", montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO)),
        (
            "por corretor",
            montar_recorte(
                de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, corretor_id=corretor
            ),
        ),
    )

    for rotulo, recorte in grupos:
        duracoes = sorted([await _medir(session, recorte) for _ in range(MEDICOES)])
        p95 = duracoes[int(len(duracoes) * 0.95) - 1]
        print(
            f"\n{rotulo}: p50={statistics.median(duracoes):.3f}s "
            f"p95={p95:.3f}s max={duracoes[-1]:.3f}s"
        )
        assert p95 < TETO_SEGUNDOS, f"{rotulo}: p95={p95:.3f}s estourou o teto de {TETO_SEGUNDOS}s"
