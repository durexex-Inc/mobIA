"""O detalhe do lead: os seis blocos que cabem numa resposta, e o resumo. TEC-193.

RN-18.2 e D4 do desenho. A transcricao, que e o setimo bloco, mora em
`transcricao.py` e tem rota propria (D1): ela e paginada, e embuti-la aqui faria
a tela pagar a conversa inteira para mostrar o resumo.

**Os seis blocos sao pequenos pela natureza deles, e nao por teto** -- a trilha
de score so grava quando algo muda, e um lead tem poucas recomendacoes, poucos
agendamentos e no maximo a cadencia de follow-ups. Isso NAO foi medido num lead
de conversa longa (L5).

**Listas vazias saem vazias, nunca nulas.** A TEC-325 distingue "sem
recomendacoes" de "Ainda nao medido", e um nulo obrigaria a tela a adivinhar
qual dos dois e.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos repositorios deste repo.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from mobia.domain.agendamento.models import Agendamento
from mobia.domain.agente.models import Recomendacao
from mobia.domain.atendimento.repositorio import AtendimentoEmCurso, em_curso
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import Status
from mobia.domain.followup.models import FollowUp
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.identidade.indice import telefones_de
from mobia.domain.leads.mascara import mascarar_telefone
from mobia.domain.messages.models import Message
from mobia.infra.crypto import decrypt


@dataclass(frozen=True)
class ResumoDoLead:
    """O resumo do handoff MAIS RECENTE do lead. TEC-175 e TEC-176.

    **O resumo e do handoff, e nao do lead** -- `conversation_summaries` tambem
    se chama resumo e e outra coisa, a janela de contexto do agente. Lead que
    nunca teve handoff nao tem resumo (L2).

    `handoff_id` e o que o botao de regenerar chama (D6): a regeneracao continua
    em `POST /handoffs/{id}/resumo`. `fallback` e o que a TEC-323 usa para
    escolher entre "Resumo simplificado" e "Gerado pelo assistente".
    """

    handoff_id: uuid.UUID
    texto: str
    gerado_em: datetime | None
    modelo: str | None
    fallback: bool


@dataclass(frozen=True)
class RecalculoDoScore:
    em: datetime
    anterior: int | None
    novo: int
    fatores: dict[str, int]
    causas: list[str]


@dataclass(frozen=True)
class ImovelRecomendado:
    imovel_id: uuid.UUID
    codigo: str
    titulo: str
    bairro: str
    score_match: Decimal
    motivo_match: str
    reacao: str | None
    motivo_descarte: str | None
    apresentado_em: datetime


@dataclass(frozen=True)
class AgendamentoDoLead:
    id: uuid.UUID
    tipo: str
    inicio: datetime
    fim: datetime
    status: str
    imovel_id: uuid.UUID | None


@dataclass(frozen=True)
class FollowUpDisparado:
    """Uma tentativa que disparou. O que nao disparou nao tem linha (TEC-183)."""

    tentativa: int
    temperatura: str
    disparado_em: datetime


@dataclass(frozen=True)
class DetalheDoLead:
    """Tudo o que a tela do corretor mostra, menos a transcricao.

    **`telefone` so mascarado** (D4 da TEC-195): nenhuma resposta da API do
    dashboard contem o numero em claro, e quem o quer chama `revelar`. **Sem
    `nome` e sem `email`**, porque nenhuma tabela deste sistema guarda um nem
    outro (Emenda E-02 da RN-15.1; D7 da TEC-195).

    `qualificacao` e `None` quando o lead nunca teve a linha -- o lead que disse
    "oi" e parou --, e nao um dicionario de nulos: "o agente ainda nao extraiu
    nada" e um fato so, e a tela o mostra como um.
    """

    lead_id: uuid.UUID
    channel: str
    status: str
    ultima_interacao_em: datetime
    telefone: str | None
    score: int | None
    resumo: ResumoDoLead | None
    qualificacao: dict[str, object] | None
    historico_score: list[RecalculoDoScore]
    recomendacoes: list[ImovelRecomendado]
    agendamentos: list[AgendamentoDoLead]
    followups: list[FollowUpDisparado]
    # Quem tem a conversa agora, ou `None` (TEC-327, D2): sem isto a faixa
    # "Voce esta no controle" sumiria ao recarregar a pagina.
    atendimento: AtendimentoEmCurso | None = None


# O que sai de `lead_qualification`, e com qual nome. Lista explicita, e nao
# "todas as colunas": `perguntados_sem_resposta`, `perguntas_feitas` e
# `penalidade_pontos` sao contabilidade interna do agente, e uma coluna nova na
# tabela nao deve aparecer na tela sem alguem decidir que ela e para gente.
_QUALIFICACAO = {
    "intencao": LeadQualification.intencao,
    "temperatura": LeadQualification.temperatura,
    "qualificadoEm": LeadQualification.qualificado_em,
    "faixaPrecoMinCentavos": LeadQualification.faixa_preco_min_centavos,
    "faixaPrecoMaxCentavos": LeadQualification.faixa_preco_max_centavos,
    "regiao": LeadQualification.regiao,
    "tipoImovel": LeadQualification.tipo_imovel,
    "quartos": LeadQualification.quartos,
    "vagas": LeadQualification.vagas,
    "urgencia": LeadQualification.urgencia,
    "formaPagamento": LeadQualification.forma_pagamento,
    "temImovelParaVender": LeadQualification.tem_imovel_para_vender,
    "camposRecusados": LeadQualification.campos_recusados,
    "ticketInvestimentoCentavos": LeadQualification.ticket_investimento_centavos,
    "retornoEsperadoPct": LeadQualification.retorno_esperado_pct,
    "retornoEsperadoTipo": LeadQualification.retorno_esperado_tipo,
    "horizonte": LeadQualification.horizonte,
    "toleranciaReforma": LeadQualification.tolerancia_reforma,
    "jaInvesteEmImoveis": LeadQualification.ja_investe_em_imoveis,
    "perfilInvestidor": LeadQualification.perfil_investidor,
}


def _do_lead(
    channel: InstrumentedAttribute[str],
    conversation_key: InstrumentedAttribute[str],
    par: tuple[str, str],
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """O `WHERE` pelo par, que toda tabela deste modulo usa no lugar de um id."""
    return channel == par[0], conversation_key == par[1]


async def ler_detalhe(
    session: AsyncSession, *, lead_id: uuid.UUID, par: tuple[str, str]
) -> DetalheDoLead | None:
    """O detalhe, ou `None` quando o par nao tem mensagem nenhuma.

    `None` nao deveria acontecer -- o apelido so nasce na listagem, e a lista
    so mostra quem tem mensagem (D1 da TEC-192) -- e a TEC-207 nao abriu esse
    caso: nem a eliminacao nem a retencao apagam linha de `messages` (zeram o
    conteudo e mantem a linha, que as metricas contam), e a anonimizacao apaga
    o apelido na mesma transacao em que troca o par, entao o lead anonimizado
    ja e 404 em `par_de`, antes de chegar aqui. A guarda fica porque um
    apelido sem mensagem, se um dia existir, e 404, nao uma tela de blocos
    vazios que afirmaria um lead sem conversa.
    """
    # Anotado a mao: o stub tipa `max()` como a coluna, sem nulo, e o `max` de
    # zero linhas e nulo.
    ultima: datetime | None = (
        await session.execute(
            select(func.max(Message.created_at)).where(
                *_do_lead(Message.channel, Message.conversation_key, par)
            )
        )
    ).scalar_one()
    if ultima is None:
        return None

    status = (
        await session.execute(
            select(Conversa.status).where(
                *_do_lead(Conversa.channel, Conversa.conversation_key, par)
            )
        )
    ).scalar_one_or_none()

    return DetalheDoLead(
        lead_id=lead_id,
        channel=par[0],
        # A ausencia de linha em `conversas` e ATIVA (D8 da TEC-192).
        status=status or Status.ATIVA.value,
        ultima_interacao_em=ultima,
        telefone=await _telefone_mascarado(session, par),
        score=await _score_corrente(session, par),
        resumo=await _resumo(session, par),
        qualificacao=await _qualificacao(session, par),
        historico_score=await _historico_score(session, par),
        recomendacoes=await _recomendacoes(session, par),
        agendamentos=await _agendamentos(session, par),
        followups=await _followups(session, par),
        atendimento=await em_curso(session, channel=par[0], conversation_key=par[1]),
    )


async def _telefone_mascarado(session: AsyncSession, par: tuple[str, str]) -> str | None:
    """As duas origens do telefone, pela mesma `telefones_de` de `listar_leads`.

    Desde a TEC-203 a `conversation_key` e o HMAC do valor, e nao o numero:
    no WhatsApp o telefone vem da identidade cifrada, no web do vinculo
    cifrado, se o lead o digitou (TEC-129). Decifrado so em memoria, para a
    mascara -- sem registro na trilha, como na lista.
    """
    telefone = (await telefones_de(session, [par]))[par]
    return mascarar_telefone(telefone) if telefone else None


async def _score_corrente(session: AsyncSession, par: tuple[str, str]) -> int | None:
    """A ultima linha da trilha, pela razao de `repositorio._score_corrente`."""
    return (
        await session.execute(
            select(LeadScoreAudit.total_novo)
            .where(*_do_lead(LeadScoreAudit.channel, LeadScoreAudit.conversation_key, par))
            .order_by(LeadScoreAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _resumo(session: AsyncSession, par: tuple[str, str]) -> ResumoDoLead | None:
    """O do handoff mais recente que ja tem texto.

    **"Que ja tem texto", e nao so "o mais recente"**: a geracao e assincrona
    (D1 da TEC-175), e um handoff criado ha dois segundos ainda nao tem resumo.
    Mostrar nada nesse intervalo, tendo o resumo do handoff anterior na mao,
    esconderia do corretor o unico texto que existe.
    """
    linha = (
        await session.execute(
            select(Handoff)
            .where(
                *_do_lead(Handoff.channel, Handoff.conversation_key, par),
                Handoff.resumo.is_not(None),
            )
            .order_by(Handoff.criado_em.desc(), Handoff.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if linha is None:
        return None
    texto = decrypt(linha.resumo, aad_do_resumo_de_handoff(linha.id))
    if texto is None:
        return None
    return ResumoDoLead(
        handoff_id=linha.id,
        texto=texto,
        gerado_em=linha.resumo_gerado_em,
        modelo=linha.resumo_modelo,
        fallback=linha.resumo_fallback,
    )


async def _qualificacao(session: AsyncSession, par: tuple[str, str]) -> dict[str, object] | None:
    linha = (
        await session.execute(
            select(*(coluna.label(nome) for nome, coluna in _QUALIFICACAO.items())).where(
                *_do_lead(LeadQualification.channel, LeadQualification.conversation_key, par)
            )
        )
    ).first()
    return dict(linha._mapping) if linha is not None else None


async def _historico_score(session: AsyncSession, par: tuple[str, str]) -> list[RecalculoDoScore]:
    """Em ordem cronologica CRESCENTE: e o que um grafico de linha consome, e o
    que o quarto cenario do Gherkin afirma.

    Os cinco fatores e a penalidade saem inteiros: sao eles que explicam o
    recalculo, e `causas` so diz o que o disparou.
    """
    linhas = (
        (
            await session.execute(
                select(LeadScoreAudit)
                .where(*_do_lead(LeadScoreAudit.channel, LeadScoreAudit.conversation_key, par))
                .order_by(LeadScoreAudit.created_at, LeadScoreAudit.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        RecalculoDoScore(
            em=linha.created_at,
            anterior=linha.total_anterior,
            novo=linha.total_novo,
            fatores={
                "completude": linha.completude,
                "urgencia": linha.urgencia,
                "catalogo": linha.catalogo,
                "engajamento": linha.engajamento,
                "capacidade": linha.capacidade,
                "penalidade": linha.penalidade,
            },
            causas=list(linha.causas),
        )
        for linha in linhas
    ]


async def _recomendacoes(session: AsyncSession, par: tuple[str, str]) -> list[ImovelRecomendado]:
    """Cada imovel apresentado, com o motivo do match e a reacao do lead.

    `motivo_descarte` e a CATEGORIA (`CategoriaDescarte`), e nao a frase do
    lead -- ver a docstring de `Recomendacao`. E o que a tela pode mostrar sem
    repetir texto digitado.
    """
    linhas = (
        await session.execute(
            select(Recomendacao, Imovel.codigo, Imovel.titulo, Imovel.bairro)
            .join(Imovel, Imovel.id == Recomendacao.imovel_id)
            .where(*_do_lead(Recomendacao.channel, Recomendacao.conversation_key, par))
            .order_by(Recomendacao.apresentado_em, Recomendacao.id)
        )
    ).all()
    return [
        ImovelRecomendado(
            imovel_id=recomendacao.imovel_id,
            codigo=codigo,
            titulo=titulo,
            bairro=bairro,
            score_match=recomendacao.score_match,
            motivo_match=recomendacao.motivo_match,
            reacao=recomendacao.reacao_lead,
            motivo_descarte=recomendacao.motivo_descarte,
            apresentado_em=recomendacao.apresentado_em,
        )
        for recomendacao, codigo, titulo, bairro in linhas
    ]


async def _agendamentos(session: AsyncSession, par: tuple[str, str]) -> list[AgendamentoDoLead]:
    """Todos, inclusive os cancelados e remarcados.

    A TEC-323 escreve "Agendamentos (sem fonte ate RF-11/RF-12) seguem 'Ainda
    nao medido'" -- a fonte passou a existir na TEC-371, e a tela passa a ter o
    que mostrar. O historico inteiro, e nao so o vigente: um lead que remarcou
    duas vezes e informacao que o corretor quer antes de ligar.
    """
    linhas = (
        (
            await session.execute(
                select(Agendamento)
                .where(*_do_lead(Agendamento.channel, Agendamento.conversation_key, par))
                .order_by(Agendamento.inicio, Agendamento.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        AgendamentoDoLead(
            id=linha.id,
            tipo=linha.tipo,
            inicio=linha.inicio,
            fim=linha.fim,
            status=linha.status,
            imovel_id=linha.imovel_id,
        )
        for linha in linhas
    ]


async def _followups(session: AsyncSession, par: tuple[str, str]) -> list[FollowUpDisparado]:
    """Os disparos, em ordem. As tarefas de corretor (TEC-186) ficam de fora:
    a card pede follow-ups ENVIADOS, e a tarefa e o que nao pode sair (L6).
    """
    linhas = (
        (
            await session.execute(
                select(FollowUp)
                .where(*_do_lead(FollowUp.channel, FollowUp.conversation_key, par))
                .order_by(FollowUp.created_at, FollowUp.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        FollowUpDisparado(
            tentativa=linha.tentativa_numero,
            temperatura=linha.temperatura,
            disparado_em=linha.created_at,
        )
        for linha in linhas
    ]
