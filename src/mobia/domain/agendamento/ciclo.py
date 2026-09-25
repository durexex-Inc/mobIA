"""As quatro transicoes do ciclo de vida do agendamento. TEC-172, RN-12.3 a RN-12.5.

Molde de `repositorio.py::confirmar`: **um UPDATE com a condicao inteira no
WHERE**, sem janela entre ler "ainda vale" e gravar "mudou". Recebem a sessao
e **nao commitam** -- o commit e de quem chama, como em `confirmar` e em
`registrar_handoff`.

**A maquina de estados mora numa tabela so** (`_ORIGENS_DE`). Quatro `WHERE`
escritos a mao divergem, e o sintoma seria uma transicao aceita por um caminho
e recusada por outro -- com o banco concordando com os dois, porque o CHECK so
conhece o vocabulario, nao a ordem dele.

**"Libera o slot" nao esta aqui, e nao falta nada.** A exclusao por intervalo
(migration 0044) e allowlist de RESERVADO e CONFIRMADO, entao o UPDATE que poe
CANCELADO tira a linha do indice no mesmo statement e o horario fica livre no
commit -- muito abaixo dos 10 segundos da CA-12.2. Ver a docstring da
migration 0050, e `test_agendamento_schema.py`, que prova isso com insert cru.

**Duas destas quatro ja tem chamador de producao, e duas nao.** Desde a
TEC-372, `cancelar` e `remarcar` saem da conversa, quando o lead responde ao
lembrete de 24 horas -- e so dentro daquela janela (ver
`conversa.py::_lembrete_pendente`). `marcar_realizado` e
`marcar_nao_comparecimento` continuam sem chamador: sao acao do corretor, e a
interface dele e a E8, que nao existe.

O veto de `agendamento/deteccao.py::quer_agendar` a `cancelar` e `remarcar`
continua de pe e nao contradiz o acima: ele protege o caminho de MARCAR
visita nova; quem le essas palavras e `respondeu_ao_lembrete`, no mesmo
modulo, e so com lembrete pendente. A reserva que o lead recusa ou deixa
vencer vira EXPIRADO por `agendamento/conversa.py`, e nao CANCELADO,
justamente para nao acordar a varredura de remarcacao. Ver
docs/superpowers/specs/2026-09-25-tec-172-cancelar-remarcar-e-nao-comparecimento-design.md.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agendamento.janelas import Intervalo
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.context.auditoria import CAUSA_NAO_COMPARECIMENTO
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import Recalculo, registrar_recalculo

# RN-12.4. Regra do SRS e nao configuracao -- a card escreve o numero, o mesmo
# argumento da D4 da TEC-285 para os dias da janela de atendimento.
PONTOS_POR_NAO_COMPARECIMENTO = 15

# De onde cada transicao pode partir. Fonte unica da maquina de estados.
#
# `cancelar` aceita RESERVADO porque uma reserva de 5 minutos tambem se
# desiste; as outras tres exigem CONFIRMADO, porque so um compromisso
# confirmado pode ser remarcado, realizado ou faltado.
#
# EXPIRADO nao e origem de nada: ele ja e terminal, e a reserva que ele
# descreve nunca virou compromisso.
_ORIGENS_DE: dict[str, frozenset[str]] = {
    StatusDoAgendamento.CANCELADO: frozenset(
        {StatusDoAgendamento.RESERVADO, StatusDoAgendamento.CONFIRMADO}
    ),
    StatusDoAgendamento.REAGENDADO: frozenset({StatusDoAgendamento.CONFIRMADO}),
    StatusDoAgendamento.REALIZADO: frozenset({StatusDoAgendamento.CONFIRMADO}),
    StatusDoAgendamento.NO_SHOW: frozenset({StatusDoAgendamento.CONFIRMADO}),
}

# A coluna de carimbo de cada desfecho. Mora ao lado das origens pela mesma
# razao que elas moram juntas: sao o mesmo fato sobre a mesma transicao, e
# separa-los faria uma transicao nova esquecer metade de si.
_CARIMBO_DE: dict[str, str] = {
    StatusDoAgendamento.CANCELADO: "cancelado_em",
    StatusDoAgendamento.REALIZADO: "realizado_em",
    StatusDoAgendamento.NO_SHOW: "nao_compareceu_em",
    # REAGENDADO nao tem carimbo proprio: quando ele aconteceu se le do
    # `criado_em` do sucessor, que aponta para ca por `origem_id`. Uma coluna
    # a mais seria a segunda fonte da mesma data.
}


@dataclass(frozen=True)
class Transicionado:
    """A transicao aconteceu. `para` e o status novo."""

    id: uuid.UUID
    para: str


@dataclass(frozen=True)
class Recusado:
    """A transicao nao aconteceu, e `motivo` diz se era estado ou ausencia.

    Dois motivos e nao um `bool`, pela razao que `confirmar` ja aplica ao
    devolver `Confirmado | Expirado`: quem chama precisa distinguir "ja estava
    assim" de "nao existe" -- a primeira e idempotencia e a segunda e um id
    errado, e responder a mesma coisa nas duas esconde a segunda.
    """

    motivo: str


MOTIVO_ORIGEM_ILEGAL = "ORIGEM_ILEGAL"
MOTIVO_INEXISTENTE = "INEXISTENTE"


@dataclass(frozen=True)
class Remarcado:
    """O original virou REAGENDADO e o sucessor nasceu apontando para ele."""

    origem_id: uuid.UUID
    novo_id: uuid.UUID
    janela: Intervalo


@dataclass(frozen=True)
class NaoCompareceu:
    """O NO_SHOW, com o que ele custou ao lead.

    `recalculo` e `None` quando o lead nao tinha linha em `lead_qualification`
    -- a penalidade foi somada mesmo assim, e o proximo calculo a usara. Nao e
    erro: um agendamento pode existir para uma conversa que nunca qualificou.
    """

    id: uuid.UUID
    penalidade_total: int
    recalculo: Recalculo | None


async def _transicionar(
    session: AsyncSession, *, agendamento_id: uuid.UUID, para: str, agora: datetime
) -> Transicionado | Recusado:
    """O UPDATE unico que serve as quatro transicoes.

    O `WHERE` carrega a origem legal, entao nao ha leitura antes da escrita e
    nao ha janela em que outro caminho mude o status no meio. Quando ele nao
    casa, a segunda consulta -- so entao -- separa "origem ilegal" de
    "inexistente"; ela custa uma ida a mais **so no caminho de recusa**, que e
    o raro.
    """
    valores: dict[str, object] = {"status": para}
    carimbo = _CARIMBO_DE.get(para)
    if carimbo is not None:
        valores[carimbo] = agora
    resultado = await session.execute(
        update(Agendamento)
        .where(
            Agendamento.id == agendamento_id,
            Agendamento.status.in_(_ORIGENS_DE[para]),
        )
        .values(**valores)
        .returning(Agendamento.id)
    )
    if resultado.first() is not None:
        return Transicionado(agendamento_id, para)
    existe = await session.get(Agendamento, agendamento_id)
    return Recusado(MOTIVO_ORIGEM_ILEGAL if existe is not None else MOTIVO_INEXISTENTE)


async def cancelar(
    session: AsyncSession, *, agendamento_id: uuid.UUID, agora: datetime
) -> Transicionado | Recusado:
    """RN-12.3. O slot volta ao pool no commit -- ver a docstring do modulo."""
    return await _transicionar(
        session, agendamento_id=agendamento_id, para=StatusDoAgendamento.CANCELADO, agora=agora
    )


async def marcar_realizado(
    session: AsyncSession, *, agendamento_id: uuid.UUID, agora: datetime
) -> Transicionado | Recusado:
    """RN-12.5. O desfecho que nao custa nada ao lead."""
    return await _transicionar(
        session, agendamento_id=agendamento_id, para=StatusDoAgendamento.REALIZADO, agora=agora
    )


async def remarcar(
    session: AsyncSession,
    *,
    agendamento_id: uuid.UUID,
    janela: Intervalo,
    agora: datetime,
    corretor_id: uuid.UUID | None = None,
) -> Remarcado | Recusado:
    """RN-12.3. O original vira REAGENDADO e o sucessor aponta para ele.

    **Os dois na MESMA transacao**, que e o que o vinculo exige: um original
    REAGENDADO sem sucessor e um compromisso que sumiu da agenda sem nada no
    lugar, e o `origem_id` existe justamente para que a metrica de remarcacao
    seja possivel (a razao que a card da).

    `corretor_id` nulo mantem o corretor do original, que e o caso comum --
    remarcar nao troca de corretor. Informado, permite a troca sem uma segunda
    funcao.

    **Nao passa por `reservar`**, e a diferenca importa: aquela funcao expira
    reservas vencidas e traduz a recusa do banco em `Conflito`, o que serve
    quem esta disputando um horario com outro lead. Aqui o horario ja foi
    acordado com o lead, e a sobreposicao, se houver, tem de subir como
    `IntegrityError` para quem chamou decidir -- engoli-la como `Conflito`
    faria a remarcacao falhar em silencio com o original ja REAGENDADO.

    Sem teto de cadeia: A -> B -> C encadeia por `origem_id`, e quem quiser a
    origem primeira sobe a cadeia.
    """
    original = await session.get(Agendamento, agendamento_id)
    if original is None:
        return Recusado(MOTIVO_INEXISTENTE)
    if original.status not in _ORIGENS_DE[StatusDoAgendamento.REAGENDADO]:
        return Recusado(MOTIVO_ORIGEM_ILEGAL)

    novo = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor_id or original.corretor_id,
        channel=original.channel,
        conversation_key=original.conversation_key,
        imovel_id=original.imovel_id,
        tipo=original.tipo,
        inicio=janela.inicio,
        fim=janela.fim,
        status=StatusDoAgendamento.CONFIRMADO,
        # Ja nasce confirmado, entao a reserva nao tem prazo a cumprir: o
        # horario foi acordado com o lead antes de chegar aqui.
        reservado_ate=agora,
        criado_em=agora,
        confirmado_em=agora,
        motivo_da_alocacao=original.motivo_da_alocacao,
        origem_id=original.id,
    )
    session.add(novo)
    # Depois do `add`, e nao antes: o original so pode sair da exclusao quando
    # o sucessor ja esta na sessao, para o flush mandar os dois juntos. Com a
    # ordem trocada e um erro no meio, a transacao inteira volta -- o que e
    # correto --, mas a leitura do codigo sugeriria que ha um instante em que
    # o horario ficou sem dono.
    transicao = await _transicionar(
        session, agendamento_id=agendamento_id, para=StatusDoAgendamento.REAGENDADO, agora=agora
    )
    if isinstance(transicao, Recusado):
        return transicao
    return Remarcado(origem_id=original.id, novo_id=novo.id, janela=janela)


async def marcar_nao_comparecimento(
    session: AsyncSession, *, agendamento_id: uuid.UUID, agora: datetime
) -> NaoCompareceu | Recusado:
    """RN-12.4. NO_SHOW, mais 15 pontos de penalidade e a trilha do score.

    **A penalidade e ACUMULADA na coluna, e nao um desconto no total.** O
    score e derivado: `calcular_score` recalcula os cinco fatores a cada
    passagem, entao um desconto que nao morasse em `lead_qualification`
    evaporaria no recalculo seguinte. Ver a D5 do desenho.

    **Duas causas na mesma linha da trilha, e nao uma.**
    `CAUSA_NAO_COMPARECIMENTO` entra como causa EXTERNA -- ela diz por que a
    penalidade se moveu --, e `CAUSA_PENALIDADE` e derivada do diff por
    `causas_do_recalculo`, dizendo o que se moveu. Usar so uma apagaria metade
    da resposta que a trilha existe para dar.

    **O UPDATE da penalidade e relativo (`+ 15`), e nao "leia e grave".** Dois
    no-shows concorrentes do mesmo lead -- dois agendamentos diferentes, o que
    o schema permite -- somariam 15 uma vez so se cada um lesse o valor antes
    de escrever.

    "Entrar na cadencia de reengajamento" nao acontece aqui, e nao falta nada:
    a cadencia e DERIVADA (TEC-183) da temperatura viva e da ultima fala do
    lead, e um lead com no-show ja esta nela assim que calar o intervalo
    minimo. O que esta funcao muda e o score, e com ele possivelmente a
    temperatura -- e portanto qual regua se aplica. Ver a D7 do desenho, que
    registra a tensao entre as duas regras da RN-12.4.
    """
    agendamento = await session.get(Agendamento, agendamento_id)
    if agendamento is None:
        return Recusado(MOTIVO_INEXISTENTE)
    channel, conversation_key = agendamento.channel, agendamento.conversation_key

    transicao = await _transicionar(
        session, agendamento_id=agendamento_id, para=StatusDoAgendamento.NO_SHOW, agora=agora
    )
    if isinstance(transicao, Recusado):
        return transicao

    total = await _somar_penalidade(session, channel=channel, conversation_key=conversation_key)
    recalculo = await registrar_recalculo(
        session,
        channel=channel,
        conversation_key=conversation_key,
        causas_externas=(CAUSA_NAO_COMPARECIMENTO,),
    )
    return NaoCompareceu(id=agendamento_id, penalidade_total=total, recalculo=recalculo)


async def _somar_penalidade(session: AsyncSession, *, channel: str, conversation_key: str) -> int:
    """Soma os pontos na coluna e devolve o total. Zero se o lead nao tem linha.

    Sem linha em `lead_qualification` nao ha o que penalizar hoje -- e nao se
    cria uma: a linha e do motor de qualificacao, e inventa-la aqui poria um
    lead sem nenhum campo na fila de quem le a tabela. A consequencia esta
    declarada em `NaoCompareceu.recalculo`.
    """
    resultado = await session.execute(
        update(LeadQualification)
        .where(
            LeadQualification.channel == channel,
            LeadQualification.conversation_key == conversation_key,
        )
        .values(
            penalidade_pontos=LeadQualification.penalidade_pontos + PONTOS_POR_NAO_COMPARECIMENTO
        )
        .returning(LeadQualification.penalidade_pontos)
    )
    linha = resultado.first()
    return int(linha[0]) if linha is not None else 0
