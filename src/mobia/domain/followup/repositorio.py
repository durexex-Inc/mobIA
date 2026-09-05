"""Quem esta devido de follow-up, e o registro de que disparou.

TEC-183. A cadencia nao e agendada: nao ha linha PENDENTE, e a pergunta "quem
esta devido agora?" e refeita a cada varredura. Ver a D1 do desenho.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.cadencia import CADENCIA, INTERVALO_MINIMO
from mobia.domain.followup.models import FollowUp

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Candidato:
    """Um lead que calou tempo suficiente para valer a pena consultar a regua.

    `ja_disparada` e o MAIOR numero de tentativa gravado sob `ancora_em`, ou
    zero quando nao ha nenhuma -- e nao uma contagem. A razao esta na docstring
    de `tentativa_devida`, e o resumo e que um lead muito atrasado recebe uma
    tentativa so, a ultima, e com contagem a regua refaria as anteriores.

    `ja_enviadas` e a CONTAGEM de linhas sob a mesma ancora, e nao o maximo --
    a inversa exata do campo acima, sobre exatamente as mesmas linhas. A regua
    pula tentativas intermediarias, entao um lead com uma unica linha de
    `tentativa_numero=3` tem `ja_disparada=3` e `ja_enviadas=1`. O maximo
    anti-spam da RN-13.7 conta mensagens que sairam, nao posicoes na regua.
    """

    channel: str
    conversation_key: str
    temperatura: Temperatura
    ancora_em: datetime
    ja_disparada: int
    ja_enviadas: int


# A ancora usa a MESMA definicao de fala do lead que `contar_mensagens_do_lead`
# fixou -- `direction = 'INBOUND'` e `bloqueada_em IS NULL`. Nao e uma segunda
# leitura desse fato: e a mesma regra, e a docstring daquela funcao existe
# precisamente para que a proxima card nao escreva uma terceira.
#
# O `HAVING` e o corte barato: nada abaixo de `INTERVALO_MINIMO` pode estar
# devido em temperatura nenhuma, entao o lead sai antes de qualquer outro
# trabalho.
#
# **`candidatos` e uma CTE, e nao um SELECT unico, porque o filtro de
# `ja_disparada` precisa do valor JA calculado.** Postgres nao deixa referenciar
# um alias da propria lista de SELECT no WHERE do mesmo nivel; promover o
# calculo a uma CTE e a forma mais legivel de filtrar por ele depois, sem
# repetir o subselect correlacionado numa segunda copia.
#
# **`lq.temperatura IN :temperaturas_validas` e a D3 E a defesa contra lixo.**
# `lead_qualification.temperatura` e uma `String(8)` sem CHECK de vocabulario:
# um `UPDATE` manual em producao e o bastante para gravar um valor fora do
# enum, e sem este filtro essa linha chegaria ao Python, onde
# `Temperatura(linha.temperatura)` levanta `ValueError` DENTRO da list
# comprehension -- antes de qualquer tratamento por lead, derrubando a
# varredura inteira e permanentemente (a linha continua la na proxima
# passagem). Com o filtro, um valor desconhecido vira um lead ignorado, nao uma
# parada de producao. `NULL` nunca casa um `IN`, entao o filtro tambem cobre a
# D3 sem precisar de um `IS NOT NULL` em separado. O vocabulario vem de
# `CADENCIA.keys()` -- nunca escrito a mao.
#
# **Os dois subselects sao a MESMA leitura com agregados opostos, e isso e
# proposital.** `ja_disparada` e o MAX porque a regua precisa saber ate onde a
# cadencia foi; `ja_enviadas` e o COUNT porque o maximo da RN-13.7 conta
# mensagens que sairam. A regua pula tentativas intermediarias, entao os dois
# divergem sempre que houve salto -- uma unica linha de `tentativa_numero=3`
# da MAX=3 e COUNT=1.
#
# O COUNT nao leva COALESCE e o MAX leva: `COUNT` de zero linhas e 0, enquanto
# `MAX` de zero linhas e NULL. Nao "corrija" a assimetria.
#
# Os dois rodam por linha ja filtrada e sao servidos pelo mesmo
# `ix_followups_lead`. O alias `f` se repete porque os escopos sao
# independentes.

# **O corte por esgotamento e o que evita a fome, e tem de ser POR
# TEMPERATURA.** Um lead exaurido tem a ancora mais antiga do lote -- `ORDER BY
# ancora` o poe na frente -- e, sem corte nenhum, ele nunca sai do topo da
# fila: candidatura nao muda so porque um disparo aconteceu. A versao anterior
# desta consulta usava um teto GLOBAL (`MAX_TENTATIVAS`, o maior entre as tres
# temperaturas) sob o argumento de que um FRIO com 2 disparos segue candidato
# porque, se esquentar, deve as tentativas 3 e 4 do QUENTE. O argumento sobre o
# aquecimento estava certo; a conclusao, nao -- um corte por temperatura
# reage ao aquecimento igual, porque e reavaliado contra `lq.temperatura` a
# cada passagem: o lead reaparece no instante em que a coluna muda. O teto
# global so tinha o efeito de nunca excluir ninguem que esgotou MORNO (3) ou
# FRIO (2) sem esquentar -- a maioria do trafego real (ver a lacuna 7 do
# desenho) -- e esses leads exauridos, por ficarem para sempre no topo da fila
# ordenada por ancora, bloqueavam QUALQUER lead novo assim que o numero deles
# excedesse `limite`. O `CASE` abaixo e gerado a partir de `CADENCIA`, e nunca
# reescrito com os tetos como literais em SQL -- seria a segunda fonte que este
# repo ja gastou cards inteiras evitando.
#
# **Esta consulta agrega `messages` a cada passagem.** E varredura, e o
# `ix_messages_timeline` serve "a ultima mensagem de UMA conversa", nao "todas
# as conversas cuja ultima fala e antiga". Aceitavel a cada 5 minutos no volume
# de MVP; a saida, quando doer, e uma coluna de ancora denormalizada em
# `lead_qualification` -- que o turno ja tem sob lock. Lacuna declarada.

# Os dois blocos abaixo sao a unica fonte dos tetos e do vocabulario de
# temperatura que a consulta usa -- derivados de `CADENCIA` (e, por
# transitividade, de `Temperatura`) em vez de escritos a mao, pela mesma razao
# de `INTERVALO_MINIMO` em `cadencia.py`: um numero ou um valor fixo aqui
# divergiria em silencio se alguem alongasse `CADENCIA` ou o enum.
_TETOS_POR_TEMPERATURA: dict[str, int] = {
    f"max_{temperatura.value.lower()}": len(intervalos)
    for temperatura, intervalos in CADENCIA.items()
}
_VALORES_TEMPERATURA_VALIDOS: tuple[str, ...] = tuple(temperatura.value for temperatura in CADENCIA)
#
# O `CAST(... AS smallint)` em cada ramo NAO e decoracao: sem um tipo
# explicito, o Postgres nao consegue inferir o tipo do `CASE` inteiro quando
# todo ramo e um parametro sem tipo -- ele cai no default do padrao SQL,
# `text`, e `ja_disparada < CASE ... END` vira "operator does not exist:
# integer < text". `tentativa_numero` e `smallint`, e e o que `ja_disparada`
# acumula via `MAX`. E `CAST(x AS tipo)`, e nao `x::tipo`: o `text()` do
# SQLAlchemy usa `::` como escape de um `:` literal para bind params por
# nome, entao `::smallint` colado a `:max_quente` nunca chega ao Postgres.
_CASE_TETO_POR_TEMPERATURA = " ".join(
    f"WHEN '{temperatura.value}' THEN CAST(:max_{temperatura.value.lower()} AS smallint)"
    for temperatura in CADENCIA
)

_SELECIONAR_CANDIDATOS = text(
    f"""
    WITH ultima_fala AS (
        SELECT channel, conversation_key, MAX(created_at) AS ancora
          FROM messages
         WHERE direction = 'INBOUND'
           AND bloqueada_em IS NULL
         GROUP BY channel, conversation_key
        HAVING MAX(created_at) <= :corte
    ),
    candidatos AS (
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
               ) AS ja_disparada,
               (SELECT COUNT(*)
                  FROM followups f
                 WHERE f.channel = lq.channel
                   AND f.conversation_key = lq.conversation_key
                   AND f.ancora_em = u.ancora) AS ja_enviadas
          FROM lead_qualification lq
          JOIN ultima_fala u
            ON u.channel = lq.channel
           AND u.conversation_key = lq.conversation_key
         WHERE lq.temperatura IN :temperaturas_validas
    )
    SELECT channel, conversation_key, temperatura, ancora, ja_disparada, ja_enviadas
      FROM candidatos
     WHERE ja_disparada < CASE temperatura {_CASE_TETO_POR_TEMPERATURA} END
     ORDER BY ancora, channel, conversation_key
     LIMIT :limite
    """
).bindparams(bindparam("temperaturas_validas", expanding=True))


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

    `ORDER BY ancora, channel, conversation_key` faz o `LIMIT` cortar os mais
    recentes quando ha mais candidatos que o teto -- quem esta esperando ha
    mais tempo passa primeiro, e o desempate por identidade evita que dois
    leads com a mesma ancora troquem de lugar entre varreduras. **A cabeca da
    fila e estavel entre passagens**: um lead que ja disparou continua
    candidato (nada na candidatura muda so por causa de um disparo), entao sem
    corte de esgotamento os leads exauridos, por terem as ancoras mais antigas,
    ocupariam o topo para sempre e um lote grande o bastante deles faria a
    varredura nunca mais alcancar quem esta realmente devido.

    **O corte de esgotamento e POR TEMPERATURA, e reavaliado a cada
    passagem contra a `temperatura` viva de `lead_qualification`.** Um lead
    exaure a propria temperatura (MORNO em 3, FRIO em 2, QUENTE em 4) e some
    da candidatura; se esquentar depois, a proxima varredura o ve com a nova
    temperatura e o teto certo, porque o corte nunca olha um valor congelado.
    Ver o comentario da query para o porque de um teto GLOBAL nao bastar.

    **Um resultado do tamanho de `limite` significa que leads podem ter
    ficado de fora desta passagem.** Fica um aviso no log -- silencioso, isso
    e exatamente a fome que o corte de esgotamento existe para evitar, e sem
    o aviso ninguem percebe ate reparar que follow-ups pararam de sair.
    """
    resultado = list(
        await session.execute(
            _SELECIONAR_CANDIDATOS,
            {
                "corte": agora - INTERVALO_MINIMO,
                "limite": limite,
                "temperaturas_validas": _VALORES_TEMPERATURA_VALIDOS,
                **_TETOS_POR_TEMPERATURA,
            },
        )
    )
    if len(resultado) == limite:
        log.warning("followup.candidatos_saturados", limite=limite)
    return [
        Candidato(
            channel=linha.channel,
            conversation_key=linha.conversation_key,
            temperatura=Temperatura(linha.temperatura),
            ancora_em=linha.ancora,
            ja_disparada=linha.ja_disparada,
            ja_enviadas=linha.ja_enviadas,
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
