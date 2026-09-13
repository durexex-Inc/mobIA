"""O turno cala quando um corretor assumiu a conversa. TEC-179, RN-16.4.

Espelha `tests/integration/test_turno_optout.py` na forma -- mesmas fixtures
(`rodar_turno`, os dubles de `tests/conftest.py`) --, mas exercita a guarda de
atendimento humano em vez da de opt-out. So os tres cenarios do Gherkin desta
task: a saida barata do topo, a mensagem do lead que continua registrada, e a
devolucao que reabre o turno.

A armadilha do setup: `rodar_turno` chama `executar_turno(get_sessionmaker(),
...)`, e o turno abre sessoes proprias. `assumir` (e `devolver`) tem de estar
COMMITADO antes de `rodar_turno` rodar, ou a guarda le um banco sem o estado
que o teste acabou de escrever.
"""

import logging
import uuid
from typing import Any

import pytest
from conftest import CANAL_AGENTE, CONVERSA_AGENTE, ModeradorFake, OutboundFake
from sqlalchemy import func, select

from mobia.domain.agente.turno import executar_turno
from mobia.domain.atendimento.repositorio import assumir, devolver
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import esta_em_optout
from mobia.infra.db import get_sessionmaker

pytestmark = pytest.mark.asyncio


async def test_conversa_assumida_o_turno_nao_responde(
    session,
    semear_corretor,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Primeiro cenario do Gherkin. O desfecho e `atendimento_humano`."""
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    linha = await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    assert linha is not None
    await session.commit()

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "atendimento_humano"
    assert outbound.entregues == []
    # A saida e ANTES do modelo -- e isso que faz a guarda ser barata.
    assert classificador.chamadas == 0


async def test_a_mensagem_do_lead_continua_registrada(
    session,
    semear_corretor,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Segundo cenario do Gherkin -- e ele passa SEM codigo novo.

    A mensagem e gravada pelo webhook, que commita o lote antes sequer de
    enfileirar o job (`api/routes/whatsapp.py`); o `process_message` so
    reivindica a linha e a le. Quando `executar_turno` roda, o registro ja
    esta commitado -- a saida antecipada nao tem como alcanca-lo.

    Este teste existe para provar que continua assim, nao para construir
    nada. Se ele algum dia reprovar, alguem moveu o registro para depois do
    turno e o silencio passou a comer mensagem do lead.
    """
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    await session.commit()

    resultado = await rodar_turno(
        session,
        classificador_fake(),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    assert resultado == "atendimento_humano"
    total = (await session.execute(select(func.count()).select_from(Message))).scalar_one()
    assert total == 1, "a fala do lead continua gravada -- o silencio nao apaga nada"


async def test_devolvida_o_turno_volta_a_responder(
    session,
    semear_corretor,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Prova que a guarda le o estado CORRENTE."""
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    devolvida = await devolver(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    assert devolvida is not None
    await session.commit()

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues != []
    assert classificador.chamadas == 1


class _OutboundQueAssumeNoMeio(OutboundFake):
    """Simula a corrida do recheque concorrente: um corretor assume a MESMA
    conversa depois que o turno passou pela guarda barata do topo (ou nunca
    passou por ela porque o kind e o da recusa de entrada, que nao tem
    guarda barata equivalente), mas ANTES deste `send()`.

    Espelha `_OutboundQueOptaNoMeio` de `test_turno_optout.py`: assumir
    DENTRO de `send()`, antes de `super().send()`, e o unico jeito de a
    reserva ver o estado novo -- `GuardedOutbound.send` consulta
    `esta_silenciada_por_mensagem` antes da reserva.
    """

    def __init__(
        self,
        session_factory: Any,
        *,
        channel: str,
        conversation_key: str,
        corretor_id: uuid.UUID,
    ) -> None:
        super().__init__(session_factory)
        self._channel = channel
        self._conversation_key = conversation_key
        self._corretor_id = corretor_id

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        async with self._session_factory() as sessao:
            await assumir(
                sessao,
                channel=self._channel,
                conversation_key=self._conversation_key,
                corretor_id=self._corretor_id,
            )
            await sessao.commit()
        return await super().send(message_id, kind, payload)


async def test_bloqueio_da_guarda_concorrente_nao_vira_reentrega_suprimida(
    session,
    semear_corretor,
    semear_entrada,
    classificador_fake,
    resumidor_fake,
    contador_fake,
    caplog,
) -> None:
    """A guarda (`GuardedOutbound.send`) barra o envio porque OUTRO turno da
    mesma conversa assumiu entre a checagem do topo deste turno e este envio.

    Mesmo criterio de `test_bloqueio_da_guarda_por_optout_nao_vira_reentrega_suprimida`
    em `test_turno_optout.py`, mas para a terceira causa: a guarda funcionou
    como desenhada -- nada foi perdido --, entao este desfecho nao pode se
    disfarcar de `reentrega_suprimida`.
    """
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    outbound = _OutboundQueAssumeNoMeio(
        get_sessionmaker(),
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )

    with caplog.at_level(logging.INFO):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=await semear_entrada(session),
            classificador=classificador_fake(),
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=ModeradorFake(),
            agendador=AgendadorNoop(),
        )

    assert resultado == "bloqueado_por_atendimento_humano"
    assert resultado != "reentrega_suprimida"
    assert outbound.entregues == [], "a guarda nunca chega a chamar _deliver"

    eventos_de_erro = [registro for registro in caplog.records if registro.levelno == logging.ERROR]
    assert eventos_de_erro == [], "a guarda funcionando nao e um alarme de error"

    eventos = [
        registro
        for registro in caplog.records
        if "turno.bloqueado_por_atendimento_humano_concorrente" in registro.getMessage()
    ]
    assert eventos, "o desfecho tem de aparecer no log"
    assert all(registro.levelno == logging.INFO for registro in eventos)


async def test_bloqueio_da_guarda_na_entrada_bloqueada_tambem_nao_vira_reentrega(
    session, semear_corretor, semear_entrada, resumidor_fake, contador_fake, caplog
) -> None:
    """Mesma corrida, mas no terceiro sitio do recheque -- dentro de
    `_entregar_texto_fixo`, no caminho da recusa de entrada. Este sitio nao
    esta no brief da task (que so nomeava os dois do bloco principal), mas
    tem o mesmo problema: a guarda de atendimento humano barra TODO kind,
    inclusive o da recusa de entrada, e sem este recheque o bloqueio virava
    `reentrega_suprimida` -- o mesmo alarme falso que o resto da task existe
    para evitar.
    """
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    outbound = _OutboundQueAssumeNoMeio(
        get_sessionmaker(),
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )

    with caplog.at_level(logging.INFO):
        resultado = await executar_turno(
            get_sessionmaker(),
            message=await semear_entrada(session),
            classificador=None,  # type: ignore[arg-type]
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=ModeradorFake(bloqueia_entrada=True),
            agendador=AgendadorNoop(),
        )

    assert resultado == "bloqueado_por_atendimento_humano"
    assert resultado != "reentrega_suprimida"
    eventos_de_erro = [registro for registro in caplog.records if registro.levelno == logging.ERROR]
    assert not any(
        "turno.reentrega_suprimida" in registro.getMessage() for registro in eventos_de_erro
    )


async def test_pedido_de_optout_numa_conversa_assumida_e_registrado(
    session,
    semear_corretor,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Fix Critical da revisao. A guarda de atendimento humano so pode ser
    `if not pedido_de_optout:` -- espelhando a checagem de opt-out logo
    acima dela --, nunca incondicional.

    Incondicional (o defeito original desta task), um lead que digitasse
    "parar" numa conversa ja assumida caia na saida barata, devolvia
    "atendimento_humano" e o `if pedido_de_optout:` que registra o opt-out
    NUNCA rodava -- o pedido de saida se perdia, sem NENHUM registro. E
    defeito de LGPD: a pessoa pediu para sair e o sistema nao tem como provar
    que o pedido chegou.

    A asserção que prova a correcao 1 e a de `esta_em_optout`: ela tem de ser
    True depois do turno, INDEPENDENTE de a confirmacao ter saido ou nao. As
    demais (resultado == "opt_out", outbound.entregues) provam que a
    correcao 2 (a escotilha de `KIND_DA_CONFIRMACAO_DE_OPTOUT` na guarda de
    atendimento humano, em `GuardedOutbound.send`) tambem funciona -- sem
    ela, o registro aconteceria mas a confirmacao seria barrada pela mesma
    guarda que a conversa assumida ativa, e o turno devolveria
    "bloqueado_por_atendimento_humano" em vez de "opt_out".
    """
    corretor = await semear_corretor(email=f"corretor-{uuid.uuid4().hex[:8]}@ex.com")
    await assumir(
        session,
        channel=CANAL_AGENTE,
        conversation_key=CONVERSA_AGENTE,
        corretor_id=corretor.id,
    )
    await session.commit()

    classificador = classificador_fake()
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake(), texto="parar"
    )

    # A asserção que falsifica a saida barata incondicional: com o bug, esta
    # linha reprova (esta_em_optout devolve False -- o registro nunca rodou).
    assert await esta_em_optout(session, channel=CANAL_AGENTE, conversation_key=CONVERSA_AGENTE), (
        "o opt-out tem de ser registrado mesmo numa conversa assumida"
    )

    # A escotilha da correcao 2: a confirmacao atravessa a guarda de
    # atendimento humano e o turno fecha em "opt_out", nao em
    # "bloqueado_por_atendimento_humano".
    assert resultado == "opt_out"
    assert outbound.entregues != [], "a confirmacao do proprio pedido tem de sair"
    assert classificador.chamadas == 0
