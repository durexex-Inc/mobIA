"""Quem esta devido de follow-up, e o registro de que disparou.

TEC-183. A cadencia nao e agendada: nao ha linha PENDENTE, e a pergunta "quem
esta devido agora?" e refeita a cada varredura. Ver a D1 do desenho.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import INTERVALO_MINIMO
from mobia.domain.followup.models import FollowUp


@dataclass(frozen=True)
class Candidato:
    """Um lead que calou tempo suficiente para valer a pena consultar a regua.

    `ja_disparada` e o MAIOR numero de tentativa gravado sob `ancora_em`, ou
    zero quando nao ha nenhuma -- e nao uma contagem. A razao esta na docstring
    de `tentativa_devida`, e o resumo e que um lead muito atrasado recebe uma
    tentativa so, a ultima, e com contagem a regua refaria as anteriores.
    """

    channel: str
    conversation_key: str
    temperatura: Temperatura
    ancora_em: datetime
    ja_disparada: int


# A ancora usa a MESMA definicao de fala do lead que `contar_mensagens_do_lead`
# fixou -- `direction = 'INBOUND'` e `bloqueada_em IS NULL`. Nao e uma segunda
# leitura desse fato: e a mesma regra, e a docstring daquela funcao existe
# precisamente para que a proxima card nao escreva uma terceira.
#
# O `HAVING` e o corte barato: nada abaixo de `INTERVALO_MINIMO` pode estar
# devido em temperatura nenhuma, entao o lead sai antes de qualquer outro
# trabalho. `temperatura IS NOT NULL` e o outro corte (D3).
#
# O subselect de `ja_disparada` roda por linha ja filtrada, e o indice
# `ix_followups_lead` o atende.
#
# **Esta consulta agrega `messages` a cada passagem.** E varredura, e o
# `ix_messages_timeline` serve "a ultima mensagem de UMA conversa", nao "todas
# as conversas cuja ultima fala e antiga". Aceitavel a cada 5 minutos no volume
# de MVP; a saida, quando doer, e uma coluna de ancora denormalizada em
# `lead_qualification` -- que o turno ja tem sob lock. Lacuna declarada.
_SELECIONAR_CANDIDATOS = text(
    """
    WITH ultima_fala AS (
        SELECT channel, conversation_key, MAX(created_at) AS ancora
          FROM messages
         WHERE direction = 'INBOUND'
           AND bloqueada_em IS NULL
         GROUP BY channel, conversation_key
        HAVING MAX(created_at) <= :corte
    )
    SELECT lq.channel,
           lq.conversation_key,
           lq.temperatura,
           u.ancora,
           COALESCE(
               (SELECT MAX(f.tentativa_numero)
                  FROM followups f
                 WHERE f.channel = lq.channel
                   AND f.conversation_key = lq.conversation_key
                   AND f.ancora_em = u.ancora),
               0
           ) AS ja_disparada
      FROM lead_qualification lq
      JOIN ultima_fala u
        ON u.channel = lq.channel
       AND u.conversation_key = lq.conversation_key
     WHERE lq.temperatura IS NOT NULL
     ORDER BY u.ancora
     LIMIT :limite
    """
)


async def candidatos_a_followup(
    session: AsyncSession, *, agora: datetime, limite: int = 500
) -> list[Candidato]:
    """Os leads que calaram tempo bastante para a regua valer a pena.

    Ser candidato NAO significa estar devido: o corte aqui e o menor intervalo
    que existe em qualquer temperatura, e quem decide de fato e
    `tentativa_devida`. Separar as duas coisas mantem a regra no modulo puro,
    onde da para testa-la sem banco.

    `agora` entra por parametro e nao sai de `datetime.now()` aqui dentro: sem
    isso nenhum teste consegue posicionar o relogio, e a cadencia inteira e
    sobre tempo.

    `ORDER BY u.ancora` faz o `LIMIT` cortar os mais recentes quando ha mais
    candidatos que o teto -- ou seja, quem esta esperando ha mais tempo passa
    primeiro. A proxima varredura pega o resto cinco minutos depois.
    """
    resultado = await session.execute(
        _SELECIONAR_CANDIDATOS,
        {"corte": agora - INTERVALO_MINIMO, "limite": limite},
    )
    return [
        Candidato(
            channel=linha.channel,
            conversation_key=linha.conversation_key,
            temperatura=Temperatura(linha.temperatura),
            ancora_em=linha.ancora,
            ja_disparada=linha.ja_disparada,
        )
        for linha in resultado
    ]


async def registrar_followup(
    session: AsyncSession, *, candidato: Candidato, tentativa: int, devido_em: datetime
) -> FollowUp | None:
    """Grava a tentativa. Devolve `None` quando outra varredura chegou primeiro.

    `ON CONFLICT DO NOTHING` e nao `try/except IntegrityError`: a excecao
    envenenaria a transacao inteira, e a varredura processa varios candidatos
    numa so -- um conflito no terceiro derrubaria os dois primeiros junto.

    Nao commita: a sessao e emprestada, e quem chama e dono da fronteira da
    transacao, como em `gravar_estado` e `registrar_recalculo`.
    """
    statement = (
        pg_insert(FollowUp)
        .values(
            id=uuid.uuid4(),
            channel=candidato.channel,
            conversation_key=candidato.conversation_key,
            tentativa_numero=tentativa,
            temperatura=candidato.temperatura.value,
            ancora_em=candidato.ancora_em,
            devido_em=devido_em,
        )
        .on_conflict_do_nothing(constraint="uq_followups_tentativa_por_ancora")
        .returning(FollowUp)
    )
    return (await session.scalars(statement)).first()
