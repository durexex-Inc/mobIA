"""A consulta da lista de leads. TEC-192, RF-18 e RN-18.1.

**A espinha dorsal e `messages`, e nao `conversas`** (D1 do desenho). Parece
contraintuitivo e nao e: o unico INSERT de `conversas` esta em
`encerrar_conversa`, entao so existe linha para conversa ENCERRADA -- usa-la
como base listaria exatamente os leads que ja acabaram. `lead_qualification`
tambem nao serve, porque o lead que disse "oi" e parou nao tem linha la. A
unica tabela com uma linha garantida por lead e `messages`.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos repositorios deste repo.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, false, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import Status
from mobia.domain.handoff.models import Handoff
from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.leads.consulta import SEM_RECORTE, Cursor, Filtro, RecorteDoPapel
from mobia.domain.messages.models import Message

_SO_DIGITOS = re.compile(r"\D+")


@dataclass(frozen=True)
class LeadDaLista:
    """Uma linha da lista. E o que a card pede, menos o que nao existe.

    **Sem `nome` e sem `telefone`**, e nenhum dos dois por escolha desta
    consulta: nenhuma tabela deste sistema guarda o nome do lead (Emenda E-02
    da RN-15.1), e o telefone so sairia mascarado, o que e a TEC-195. Ver a
    Emenda E-01 a secao 6.2.

    **`channel` e `conversation_key` no lugar de um `id`**: nao existe entidade
    lead neste sistema, e o par e a identidade que `handoffs`, `optout_events`
    e `lead_qualification` ja usam (D2).
    """

    channel: str
    conversation_key: str
    score: int | None
    temperatura: str | None
    status: str
    regiao: str | None
    intencao: str | None
    qualificado_em: datetime | None
    ultima_interacao_em: datetime


def _ultima_interacao() -> Any:
    """O instante da fala mais recente de cada conversa, e a lista de leads.

    Espelho do `_nascimento()` de `metricas/repositorio.py`, com `max` no lugar
    de `min` -- e a mesma razao: `messages` e a unica tabela que tem esse
    instante. O indice `ix_messages_timeline` cobre o par, entao o agrupamento
    nao e varredura cega.
    """
    return (
        select(
            Message.channel.label("channel"),
            Message.conversation_key.label("conversation_key"),
            func.max(Message.created_at).label("ultima_interacao_em"),
        )
        .group_by(Message.channel, Message.conversation_key)
        .subquery()
    )


def _score_corrente() -> Any:
    """O score de agora de cada lead: a ultima linha da trilha.

    `DISTINCT ON` e nao `max(created_at)` com auto-join: a trilha guarda o
    TOTAL de cada recalculo, entao o que se quer e a LINHA mais recente, e nao
    o maior valor -- um lead que esfriou tem total menor no registro mais novo,
    e `max` devolveria o score de quando ele estava quente.

    O `ORDER BY` e exatamente o do indice `ix_lead_score_audit_lead`
    (`channel, conversation_key, created_at DESC`), que existe para esta
    pergunta.
    """
    return (
        select(
            LeadScoreAudit.channel.label("channel"),
            LeadScoreAudit.conversation_key.label("conversation_key"),
            LeadScoreAudit.total_novo.label("score"),
        )
        # `distinct_on` e nao `.distinct(col)`: o segundo produz o mesmo SQL e
        # esta deprecado na SQLAlchemy 2.1, com warning por execucao.
        .ext(distinct_on(LeadScoreAudit.channel, LeadScoreAudit.conversation_key))
        .order_by(
            LeadScoreAudit.channel,
            LeadScoreAudit.conversation_key,
            LeadScoreAudit.created_at.desc(),
        )
        .subquery()
    )


def _onde_a_busca_bate(base: Any, termo: str) -> Any:
    """Bairro de interesse, ou telefone -- nas duas origens dele. D3.

    **Nao ha busca por nome**, porque nao ha nome (L1). A card pede as tres, e
    esta e a unica das tres que nao tem de onde sair.

    O telefone mora em dois lugares e os dois entram: no WhatsApp, o proprio
    `conversation_key` E o numero; no web, a sessao e anonima e o numero so
    existe se o lead o digitou, em `vinculos_de_sessao` (TEC-129).

    **O termo e comparado em duas formas.** `%termo%` cru para a regiao, e
    `%so-os-digitos%` para telefone: quem digita "+55 (48) 99999" esta
    procurando `5548999...`, e um ILIKE do texto cru com pontuacao nao acharia
    nada -- o que se leria como "este lead nao existe".
    """
    alvos: list[Any] = [LeadQualification.regiao.ilike(f"%{termo}%")]

    digitos = _SO_DIGITOS.sub("", termo)
    if digitos:
        alvos.append(base.c.conversation_key.ilike(f"%{digitos}%"))
        alvos.append(
            select(VinculoDeSessao.telefone)
            .where(
                VinculoDeSessao.channel == base.c.channel,
                VinculoDeSessao.conversation_key == base.c.conversation_key,
                VinculoDeSessao.telefone.ilike(f"%{digitos}%"),
            )
            .exists()
        )

    return or_(*alvos)


def _depois_do_cursor(base: Any, score: Any, cursor: Cursor) -> Any:
    """A pagina seguinte, por keyset. D5 do desenho.

    A ordem e `score DESC NULLS LAST, channel, conversation_key`, e este
    predicado e o complemento exato dela:

    - com score no cursor, vem depois quem tem score MENOR, quem nao tem score
      nenhum (porque nulo vai para o fim), e quem empata e perde no desempate;
    - sem score no cursor, ja se esta na cauda dos sem score, e so o desempate
      decide.

    **`OFFSET` nao serve aqui, e nao e questao de gosto:** o score e
    recalculado a cada turno, e um lead que sobe entre a primeira e a segunda
    pagina faz uma linha ser pulada e outra aparecer duas vezes. O defeito e
    invisivel em teste de pagina unica.
    """
    desempate = func.row(base.c.channel, base.c.conversation_key) > func.row(
        cursor.channel, cursor.conversation_key
    )

    if cursor.score is None:
        return and_(score.c.score.is_(None), desempate)

    return or_(
        score.c.score < cursor.score,
        score.c.score.is_(None),
        and_(score.c.score == cursor.score, desempate),
    )


def _consulta(filtro: Filtro, *, recorte: RecorteDoPapel) -> Select[Any]:
    base = _ultima_interacao()
    score = _score_corrente()

    consulta = (
        select(
            base.c.channel,
            base.c.conversation_key,
            base.c.ultima_interacao_em,
            score.c.score,
            LeadQualification.temperatura,
            LeadQualification.regiao,
            LeadQualification.intencao,
            LeadQualification.qualificado_em,
            Conversa.status,
        )
        .select_from(base)
        .join(
            score,
            (score.c.channel == base.c.channel)
            & (score.c.conversation_key == base.c.conversation_key),
            isouter=True,
        )
        .join(
            LeadQualification,
            (LeadQualification.channel == base.c.channel)
            & (LeadQualification.conversation_key == base.c.conversation_key),
            isouter=True,
        )
        # LEFT JOIN, e e ele que torna a D8 necessaria: `conversas` so tem
        # linha depois do encerramento, entao a ausencia AQUI significa ATIVA.
        .join(
            Conversa,
            (Conversa.channel == base.c.channel)
            & (Conversa.conversation_key == base.c.conversation_key),
            isouter=True,
        )
    )

    if filtro.canal is not None:
        consulta = consulta.where(base.c.channel == filtro.canal)

    if filtro.temperatura is not None:
        consulta = consulta.where(LeadQualification.temperatura == filtro.temperatura)

    if filtro.status == Status.ATIVA.value:
        # A ausencia de linha e ATIVA (D8). Sem o `is_(None)`, filtrar por
        # ATIVA devolveria so os leads que ja foram encerrados e reabertos --
        # o oposto do pedido.
        consulta = consulta.where(or_(Conversa.status.is_(None), Conversa.status == Status.ATIVA))
    elif filtro.status is not None:
        consulta = consulta.where(Conversa.status == filtro.status)

    if filtro.busca is not None:
        consulta = consulta.where(_onde_a_busca_bate(base, filtro.busca))

    if recorte.nao_ve_nada:
        # Fail-CLOSED explicito, e nao "sem filtro". Ver `RecorteDoPapel`.
        return consulta.where(false())

    # **O do papel vence o da query, e por isso e aplicado depois** (D7). Mandar
    # `corretorId=<outro>` sendo CORRETOR nao alarga nada: os dois viram AND, e
    # o recorte do papel esta sempre presente.
    for dono in (filtro.corretor_id, recorte.corretor_id if recorte.e_corretor else None):
        if dono is not None:
            consulta = consulta.where(
                select(Handoff.id)
                .where(
                    Handoff.channel == base.c.channel,
                    Handoff.conversation_key == base.c.conversation_key,
                    Handoff.corretor_id == dono,
                )
                .exists()
            )

    if filtro.cursor is not None:
        consulta = consulta.where(_depois_do_cursor(base, score, filtro.cursor))

    return consulta.order_by(
        score.c.score.desc().nullslast(),
        base.c.channel,
        base.c.conversation_key,
    )


async def listar_leads(
    session: AsyncSession, *, filtro: Filtro, recorte: RecorteDoPapel = SEM_RECORTE
) -> tuple[list[LeadDaLista], Cursor | None]:
    """A pagina pedida e o cursor da proxima, ou `None` quando acabou.

    **Pede um item a mais do que o limite, e o descarta.** E o que responde
    "ha proxima pagina?" sem um `COUNT(*)` sobre a consulta inteira -- que
    custaria a agregacao de `messages` duas vezes por requisicao para produzir
    um numero que o cliente nao usa para nada alem de saber se continua.

    `recorte` vem da claim do JWT, nunca da query: ver a D7 e `RecorteDoPapel`.
    """
    linhas = (
        await session.execute(_consulta(filtro, recorte=recorte).limit(filtro.limite + 1))
    ).all()

    tem_mais = len(linhas) > filtro.limite
    pagina = [
        LeadDaLista(
            channel=linha.channel,
            conversation_key=linha.conversation_key,
            score=linha.score,
            temperatura=linha.temperatura,
            # A ausencia de linha em `conversas` e ATIVA (D8), e a traducao
            # mora aqui e nao no SQL: quem le a resposta nao deve precisar
            # saber que a tabela so nasce no encerramento.
            status=linha.status or Status.ATIVA.value,
            regiao=linha.regiao,
            intencao=linha.intencao,
            qualificado_em=linha.qualificado_em,
            ultima_interacao_em=linha.ultima_interacao_em,
        )
        for linha in linhas[: filtro.limite]
    ]

    if not tem_mais or not pagina:
        return pagina, None

    ultimo = pagina[-1]
    return pagina, Cursor(
        score=ultimo.score,
        channel=ultimo.channel,
        conversation_key=ultimo.conversation_key,
    )
