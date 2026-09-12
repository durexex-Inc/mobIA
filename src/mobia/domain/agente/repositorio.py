import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.desambiguacao import intencao_efetiva
from mobia.domain.agente.models import ConversationIntent, Recomendacao
from mobia.domain.agente.recomendacao import motivo_do_match
from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IntencaoDaConversa:
    intencao: Intencao
    confianca: Decimal
    modelo: str
    desambiguado_em: datetime | None

    @property
    def efetiva(self) -> Intencao:
        """A intencao que se pode usar para rotear. **Leia por aqui.**

        `intencao` e o palpite cru, que abaixo do limiar nao sustenta decisao
        nenhuma. Ver `intencao_efetiva`.
        """
        return intencao_efetiva(self.intencao, self.confianca)


async def ler_intencao(
    session: AsyncSession, channel: str, conversation_key: str
) -> IntencaoDaConversa | None:
    linha = await session.get(ConversationIntent, (channel, conversation_key))
    if linha is None:
        return None
    return IntencaoDaConversa(
        intencao=Intencao(linha.intencao),
        confianca=linha.confianca,
        modelo=linha.modelo,
        desambiguado_em=linha.desambiguado_em,
    )


async def gravar_intencao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    intencao: Intencao,
    confianca: Decimal,
    modelo: str,
) -> None:
    """Upsert. **Nao commita** -- o chamador e dono da transacao.

    Mesma fronteira que `gravar_resumo` da TEC-127 passou a respeitar depois de
    uma review: quem abre a sessao e quem a finaliza.
    """
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        "intencao": str(intencao),
        "confianca": confianca,
        "modelo": modelo,
        # Linha nova comeca sem episodio em aberto: a primeira ambiguidade de
        # uma conversa tem de poder perguntar.
        "desambiguado_em": None,
        "updated_at": datetime.now(UTC),
    }
    statement = pg_insert(ConversationIntent).values(valores)

    atualizacoes: dict[str, Any] = {
        chave: statement.excluded[chave]
        for chave in ("intencao", "confianca", "modelo", "updated_at")
    }
    if confianca >= LIMIAR_DE_DESAMBIGUACAO:
        # Classificacao confiante encerra o episodio de ambiguidade: o proximo
        # trecho vago da conversa tem direito a uma pergunta nova.
        atualizacoes["desambiguado_em"] = None
    # Abaixo do limiar o marcador **nao** entra no set_: a ambiguidade e a
    # mesma, e a pergunta dela ja foi gasta.

    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_=atualizacoes,
        )
    )


async def marcar_desambiguacao(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    quando: datetime | None = None,
) -> None:
    """Registra que a pergunta de desambiguacao ja foi feita. **Nao commita.**

    Chamada **depois** da entrega confirmada, nunca antes: o marcador afirma
    "eu ja perguntei", e isso so e verdade se a pergunta chegou. Escrito antes,
    um 5xx da Meta queimaria a unica chance de desambiguar -- o sweeper
    reprocessa, encontra o marcador, e o lead fica em INDEFINIDA sem ninguem
    ter perguntado nada.

    A linha sempre existe neste ponto: `gravar_intencao` rodou e commitou mais
    cedo no mesmo turno.
    """
    await session.execute(
        update(ConversationIntent)
        .where(
            ConversationIntent.channel == channel,
            ConversationIntent.conversation_key == conversation_key,
        )
        .values(desambiguado_em=quando or datetime.now(UTC))
    )


async def gravar_recomendacoes(
    session_factory: Any,
    *,
    channel: str,
    conversation_key: str,
    candidatos: Sequence[Mapping[str, Any]],
    scores: Mapping[uuid.UUID, float],
    criterios: Sequence[str],
    agora: datetime,
) -> None:
    """Uma linha por imovel apresentado. RN-10.3, e a L1 da TEC-162.

    **`ON CONFLICT DO NOTHING`, e nao um `raise`.** O UNIQUE existe para
    impedir DUPLICATA, nao para derrubar o turno: o lead pede "mostra de novo
    aquele do Campeche" e a reapresentacao e legitima. Deixar o IntegrityError
    subir mataria o turno por causa de um registro, e a D9 da TEC-265 ja
    escreveu a regra oposta para este caminho.

    A linha original sobrevive com a reacao que ja tiver -- que e o
    comportamento certo: a opiniao do lead sobre aquele imovel nao muda porque
    ele o viu de novo.

    **Gravada ANTES da entrega**, por quem chama. O docstring de `_apresentar`
    registra que uma falha parcial perde o conjunto escolhido e o turno
    seguinte pode reapresentar os mesmos imoveis; gravar depois manteria esse
    buraco aberto.

    **Toda apresentacao vira linha, sem excecao (RN-10.3).** A regra nao tem
    clausula de excecao -- "toda apresentacao e registrada como
    `Recomendacao`" -- e uma linha faltando quebra tres coisas por quem le
    depois: o UNIQUE que e a garantia do cenario 4 do Gherkin (o proximo
    candidato deste imovel nesta conversa nao teria contra o que colidir), o
    gatilho `reacao_lead IS NULL` que a Task 5 usa para saber quem perguntar,
    e a propria medida de conversao que esta tabela existe para dar.

    **Um candidato sem entrada em `scores` AINDA vira linha, com
    `score_match = 0.0` e um `log.error`.** Isto e decisao de ruling, nao a
    original desta funcao -- a original recusava `0.0` como valor ROTINEIRO,
    e continua certa sobre isso: se este caminho fosse o normal, `0.0`
    tornaria a coluna decorativa e derrubaria o D4 (o que distingue os
    candidatos de uma recomendacao e o score). Mas o `0.0` daqui so e
    alcancado quando um invariante que deveria ser impossivel ja quebrou --
    por construcao (D17, `_PortaComScore` em `ferramenta_de_busca.py`), o
    turno monta `scores` chamando `score_de` para cada imovel de
    `candidatos` logo apos a MESMA busca que os gerou, entao a ausencia so
    acontece se as duas listas vieram de chamadas diferentes. Entre um numero
    errado que berra (`error` no log, `0.0` que salta aos olhos em qualquer
    consulta) e um fato que falta em silencio (a linha simplesmente nao
    existe, e ninguem que le a tabela depois sabe que o imovel foi
    apresentado), a regra escolhe o que berra: a linha existir e a Task 5 ter
    o que reagir importa mais que o numero dela estar certo neste caso que
    nunca deveria acontecer. **Nao filtre o candidato da ENTREGA por causa
    disto** -- o lead ja recebeu a ficha nesse ponto do turno, e transformar
    um defeito de contabilidade nosso numa apresentacao que ele nunca ve so
    troca nosso problema pelo dele.
    """
    if not candidatos:
        return

    motivo = motivo_do_match(criterios)
    linhas: list[dict[str, Any]] = []
    for candidato in candidatos:
        imovel_id = uuid.UUID(str(candidato["imovel_id"]))
        score = scores.get(imovel_id)
        if score is None:
            # Nunca deveria acontecer (ver docstring) -- `error`, nao
            # `warning`, porque e sinal de invariante quebrado, e `0.0` fica
            # gravado de proposito para o numero errado saltar aos olhos em
            # vez de a linha faltar em silencio.
            log.error(
                "recomendacao.score_ausente",
                channel=channel,
                conversation_key=conversation_key,
                imovel_id=str(imovel_id),
            )
            score = 0.0
        linhas.append(
            {
                "id": uuid.uuid4(),
                "channel": channel,
                "conversation_key": conversation_key,
                "imovel_id": imovel_id,
                "score_match": Decimal(str(score)),
                "motivo_match": motivo,
                "apresentado_em": agora,
            }
        )

    async with session_factory() as session:
        await session.execute(pg_insert(Recomendacao).values(linhas).on_conflict_do_nothing())
        await session.commit()
