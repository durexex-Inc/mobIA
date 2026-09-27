"""O acesso a solicitacao de titular: registrar, recusar, atender e listar --
e, desde a revisao final, saber se a pergunta de eliminacao esta pendente
(`pergunta_de_eliminacao_pendente`, o segundo passo da eliminacao pelo
WhatsApp).

TEC-207, D2 e D3 do desenho. Funcoes livres com `session` posicional e o
resto keyword-only, sem commit -- convencao dos repositorios deste repo (ver
`handoff/repositorio.py`).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.auditoria.referencia import lead_ref as calcular_lead_ref
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import Acao, Ator, Entidade
from mobia.domain.leads.repositorio import referencias_para
from mobia.domain.messages.models import Message
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.titular.deteccao import (
    JANELA_DA_CONFIRMACAO_DE_ELIMINACAO,
    KIND_DA_PERGUNTA_DE_ELIMINACAO,
)
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.vocabulario import (
    PRAZO_DO_TITULAR,
    OrigemDaSolicitacao,
    StatusDaSolicitacao,
    TipoDeSolicitacao,
)


class SolicitacaoNaoAberta(ValueError):
    """Recusar uma solicitacao que nao esta ABERTA. Vira 409 na rota."""


async def pergunta_de_eliminacao_pendente(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    antes_da_mensagem: uuid.UUID,
) -> bool:
    """A ultima coisa que o agente mandou a este lead foi a pergunta de
    eliminacao, ha menos de `JANELA_DA_CONFIRMACAO_DE_ELIMINACAO` -- o segundo
    passo da eliminacao pelo WhatsApp (C2 da revisao final da TEC-207).

    **A fonte e `outbound_dispatches`, e nao `messages`.** Todo envio ao lead
    passa por `GuardedOutbound.send`, que reserva `(message_id, kind)` antes do
    efeito externo -- a resposta do modelo, os textos fixos, o follow-up, os
    avisos de agendamento e a fala do corretor (`atendimento/fala.py`) --, e so
    a reserva guarda o KIND. A linha OUTBOUND de `messages` nao diz qual texto
    fixo foi, e o follow-up nem grava linha la. A reserva e chaveada pela
    mensagem INBOUND que ancorou o envio, entao o par sai do JOIN com
    `messages`.

    **A reserva da propria mensagem que confirma fica de fora**
    (`antes_da_mensagem`): numa retentativa do turno do "apagar", a
    confirmacao que a passada anterior reservou seria a mais recente, e o
    segundo passo deixaria de se reconhecer -- o turno cairia no fluxo normal
    em vez de chegar na supressao de reentrega.

    Presenca de reserva significa "encerrado", nao "entregue" (ver
    `outbound/repositorio.py::kinds_reservados`): uma pergunta recusada de
    vez pela Meta ainda conta como a ultima fala. O custo e so um "apagar"
    solto, dentro de 24 horas, ser lido como confirmacao de uma pergunta que
    o lead nao viu -- e o lead teria acabado de pedir a eliminacao.

    O relogio e o do Postgres (`now()`), o mesmo que carimbou a reserva.
    """
    ultima = (
        await session.execute(
            select(OutboundDispatch.kind, OutboundDispatch.created_at)
            .join(Message, Message.id == OutboundDispatch.message_id)
            .where(
                Message.channel == channel,
                Message.conversation_key == conversation_key,
                OutboundDispatch.message_id != antes_da_mensagem,
            )
            .order_by(OutboundDispatch.created_at.desc(), OutboundDispatch.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if ultima is None or ultima.kind != KIND_DA_PERGUNTA_DE_ELIMINACAO:
        return False
    agora_no_banco = (await session.execute(select(func.now()))).scalar_one()
    return bool(agora_no_banco - ultima.created_at < JANELA_DA_CONFIRMACAO_DE_ELIMINACAO)


async def registrar_solicitacao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    tipo: TipoDeSolicitacao,
    origem: OrigemDaSolicitacao,
    ator: Ator,
) -> uuid.UUID:
    """Cria a solicitacao ABERTA, ou devolve o id da que ja existe.

    **Idempotente por `(channel, conversation_key, tipo)`** (D2 e D3): um
    segundo pedido do mesmo tipo, do mesmo lead, nao cria uma segunda linha
    enquanto a primeira espera. Pelo par, e nao por `lead_ref`, desde a
    revisao final (I2): a rotacao de chave da TEC-203 arrasta o par e nao
    recalcula o `lead_ref` desta tabela -- ver `uq_solicitacao_aberta` em
    `titular/models.py`. `lead_ref` continua gravado, como a referencia que
    sobra depois de a solicitacao fechar. Um INSERT com
    `ON CONFLICT DO NOTHING` sobre `uq_solicitacao_aberta`
    decide isso no banco, e nao com um SELECT antes -- a corrida e a mesma que
    `registrar_handoff` previne, so que aqui basta saber se a linha nasceu ou
    nao, sem acumular nada na que ja existia.

    `prazo_em` e `recebida_em + PRAZO_DO_TITULAR` (15 dias, RNF-21), calculado
    aqui e nao pelo banco -- o mesmo `agora` vale para os dois, sem uma
    segunda ida ao servidor para ler o `server_default` de volta.

    **So grava `TITULAR_SOLICITOU` quando cria** a linha: um pedido repetido
    nao e um novo fato para a trilha. **Nao commita.**

    **Garante o apelido do lead (`referencias_para`) na mesma transacao**
    (segunda revisao, sobre o M2). A fila de solicitacoes so le apelidos, e as
    rotas do ADMIN -- exportar, apagar -- entram por `leadId`; sem apelido, o
    pedido de um lead que nunca apareceu no painel de leads ficava na fila sem
    porta de entrada, e o prazo do ACESSO corria sem o ADMIN poder atende-lo.
    Criar aqui nao reabre o defeito do M2: este registro so roda a partir de
    uma mensagem viva do lead, da rota do ADMIN ou do sweep de retencao --
    nunca sobre um par que uma anonimizacao ja apagou, porque a anonimizacao
    apaga o apelido e fecha as solicitacoes do par na mesma transacao.
    """
    ref = calcular_lead_ref(channel, conversation_key, chave=get_settings().auditoria_chave_do_lead)
    agora = datetime.now(UTC)

    statement = pg_insert(SolicitacaoDeTitular).values(
        id=uuid.uuid4(),
        lead_ref=ref,
        channel=channel,
        conversation_key=conversation_key,
        tipo=tipo.value,
        origem=origem.value,
        status=StatusDaSolicitacao.ABERTA.value,
        prazo_em=agora + PRAZO_DO_TITULAR,
    )
    inserida = (
        await session.execute(
            statement.on_conflict_do_nothing(
                index_elements=["channel", "conversation_key", "tipo"],
                index_where=text("status = 'ABERTA'"),
            ).returning(SolicitacaoDeTitular.id)
        )
    ).scalar_one_or_none()

    await referencias_para(session, [(channel, conversation_key)])

    if inserida is not None:
        await registrar_evento(
            session,
            ator=ator,
            acao=Acao.TITULAR_SOLICITOU,
            entidade=Entidade.SOLICITACAO_DE_TITULAR,
            entidade_id=str(inserida),
            lead=(channel, conversation_key),
        )
        return inserida

    # ON CONFLICT DO NOTHING nao devolveu linha: a ABERTA deste par e deste
    # tipo ja existia. `uq_solicitacao_aberta` garante que ha exatamente uma.
    existente = await solicitacao_aberta(
        session, channel=channel, conversation_key=conversation_key, tipo=tipo
    )
    if existente is None:
        raise RuntimeError(
            f"uq_solicitacao_aberta garantia uma ABERTA para {tipo.value}, e nao achei"
        )
    return existente.id


async def solicitacao_aberta(
    session: AsyncSession, *, channel: str, conversation_key: str, tipo: TipoDeSolicitacao
) -> SolicitacaoDeTitular | None:
    """A ABERTA deste lead e deste tipo, se houver -- pelo par, que e o que
    `uq_solicitacao_aberta` garante unico e o que a rotacao de chave arrasta
    (ver `registrar_solicitacao`)."""
    return (
        await session.execute(
            select(SolicitacaoDeTitular).where(
                SolicitacaoDeTitular.channel == channel,
                SolicitacaoDeTitular.conversation_key == conversation_key,
                SolicitacaoDeTitular.tipo == tipo.value,
                SolicitacaoDeTitular.status == StatusDaSolicitacao.ABERTA.value,
            )
        )
    ).scalar_one_or_none()


async def marcar_atendida(
    session: AsyncSession, solicitacao_id: uuid.UUID, *, agora: datetime
) -> None:
    """Fecha a solicitacao como ATENDIDA e zera o par, num UPDATE so.

    **O `WHERE` leva `status = 'ABERTA'`, e nao so o id** -- sem isso a
    chamada era um UPDATE cego que revivia uma RECUSADA (ou uma ja ATENDIDA)
    como ATENDIDA em silencio, e um id inexistente virava no-op sem avisar
    ninguem. Com o predicado, `RETURNING` devolve zero linhas nesses casos e
    a funcao levanta `SolicitacaoNaoAberta` -- e o UPDATE em si continua
    atomico: status e par mudam juntos, na mesma linha de comando, entao o
    CHECK `ck_solicitacoes_de_titular_par_com_status` nunca ve um estado
    intermediario. **Nao commita.**
    """
    resultado = await session.execute(
        update(SolicitacaoDeTitular)
        .where(
            SolicitacaoDeTitular.id == solicitacao_id,
            SolicitacaoDeTitular.status == StatusDaSolicitacao.ABERTA.value,
        )
        .values(
            status=StatusDaSolicitacao.ATENDIDA.value,
            atendida_em=agora,
            channel=None,
            conversation_key=None,
        )
        .returning(SolicitacaoDeTitular.id)
    )
    if resultado.scalar_one_or_none() is None:
        raise SolicitacaoNaoAberta(f"solicitacao {solicitacao_id} nao esta aberta")


async def recusar(
    session: AsyncSession, solicitacao_id: uuid.UUID, *, motivo: str, ator: Ator
) -> None:
    """Recusa uma solicitacao ABERTA, com motivo obrigatorio, e zera o par.

    `motivo` nao tem default: a recusa sem justificativa (ex.: retencao
    legal) e o que a RN de titular exige registrado, e um default vazio
    tornaria a exigencia decorativa.

    **`SELECT ... FOR UPDATE` antes do UPDATE, e nao um SELECT solto** -- o
    `FOR UPDATE` trava a linha ate o fim desta transacao, entao nenhuma outra
    chamada (por exemplo `marcar_atendida` no MESMO id) pode mudar o status
    entre a leitura e a escrita. Sem o lock, as duas intercalavam: esta
    funcao lia ABERTA, `marcar_atendida` committava ATENDIDA, e esta funcao
    sobrescrevia para RECUSADA por cima -- apagando a transicao para ATENDIDA
    e logando `TITULAR_RECUSADO` sobre um pedido que ja tinha sido atendido.
    O UPDATE repete o mesmo predicado `status = 'ABERTA'` e confere
    `RETURNING`: com o lock ja tomado pelo SELECT, isso nunca falha de fato
    aqui, mas deixa a garantia explicita em vez de implicita no lock sozinho.

    Levanta `SolicitacaoNaoAberta` se a linha nao existe ou ja nao esta
    ABERTA -- recusar uma ja ATENDIDA ou ja RECUSADA nao e uma segunda
    recusa, e um estado que a chamada nao pode produzir. So registra
    `TITULAR_RECUSADO` **depois** do UPDATE ter sucesso.
    """
    if not motivo.strip():
        raise ValueError("motivo da recusa e obrigatorio")

    solicitacao = (
        await session.execute(
            select(SolicitacaoDeTitular)
            .where(SolicitacaoDeTitular.id == solicitacao_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if solicitacao is None or solicitacao.status != StatusDaSolicitacao.ABERTA.value:
        raise SolicitacaoNaoAberta(f"solicitacao {solicitacao_id} nao esta aberta")

    # Capturados antes do UPDATE que os zera: e o par que localiza a conversa
    # para o evento da trilha, e o CHECK do par-com-status exige que ele
    # suma junto com o status ABERTA.
    channel = solicitacao.channel
    conversation_key = solicitacao.conversation_key
    if channel is None or conversation_key is None:
        raise RuntimeError(
            f"solicitacao {solicitacao_id} estava ABERTA sem o par -- "
            "ck_solicitacoes_de_titular_par_com_status deveria ter impedido isso"
        )

    resultado = await session.execute(
        update(SolicitacaoDeTitular)
        .where(
            SolicitacaoDeTitular.id == solicitacao_id,
            SolicitacaoDeTitular.status == StatusDaSolicitacao.ABERTA.value,
        )
        .values(
            status=StatusDaSolicitacao.RECUSADA.value,
            motivo_da_recusa=motivo,
            channel=None,
            conversation_key=None,
        )
        .returning(SolicitacaoDeTitular.id)
    )
    if resultado.scalar_one_or_none() is None:
        raise SolicitacaoNaoAberta(f"solicitacao {solicitacao_id} nao esta aberta")

    await registrar_evento(
        session,
        ator=ator,
        acao=Acao.TITULAR_RECUSADO,
        entidade=Entidade.SOLICITACAO_DE_TITULAR,
        entidade_id=str(solicitacao_id),
        lead=(channel, conversation_key),
    )


async def listar(
    session: AsyncSession, *, status: StatusDaSolicitacao | None
) -> list[SolicitacaoDeTitular]:
    """A fila, por prazo -- o que vence primeiro aparece primeiro (D4)."""
    consulta = select(SolicitacaoDeTitular)
    if status is not None:
        consulta = consulta.where(SolicitacaoDeTitular.status == status.value)
    consulta = consulta.order_by(SolicitacaoDeTitular.prazo_em, SolicitacaoDeTitular.recebida_em)
    return list((await session.execute(consulta)).scalars())


async def vencendo(
    session: AsyncSession, *, agora: datetime, tipo: TipoDeSolicitacao, antecedencia: timedelta
) -> list[SolicitacaoDeTitular]:
    """As ABERTAS deste tipo cujo prazo vence ate `agora + antecedencia`.

    O sweep de retencao (D5) passa com `ANTECEDENCIA_DO_CUMPRIMENTO` (1 dia):
    ele roda uma vez por dia, entao cumprir so o que ja venceu deixaria todo
    pedido passar do prazo por ate um dia. Cumprir o que vence ate amanha
    mantem a passagem diaria dentro do prazo e deixa ao ADMIN os ~14 dias
    restantes para executar ou recusar. O que ja venceu tambem entra -- uma
    passagem perdida nao o esconde da seguinte.
    """
    consulta = (
        select(SolicitacaoDeTitular)
        .where(
            SolicitacaoDeTitular.status == StatusDaSolicitacao.ABERTA.value,
            SolicitacaoDeTitular.tipo == tipo.value,
            SolicitacaoDeTitular.prazo_em <= agora + antecedencia,
        )
        .order_by(SolicitacaoDeTitular.prazo_em)
    )
    return list((await session.execute(consulta)).scalars())
