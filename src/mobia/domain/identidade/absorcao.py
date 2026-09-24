"""O turno do WhatsApp herda o que a mesma pessoa disse no site. TEC-129, D4.

**So grava no par do WhatsApp, e isso e a card inteira.** A sessao web e
anonima e nada verifica que o telefone digitado e de quem o digitou (D1): o
que vai do site para o WhatsApp e o que a sessao disse, e nunca o contrario.
Uma absorcao que escrevesse no par web entregaria, no turno web seguinte, a
qualificacao do WhatsApp a quem digitou o numero de outra pessoa.

**O que o WhatsApp ja sabe prevalece.** Preenche so campo vazio: o numero e o
lado autenticado, e o que ele disse diretamente vale mais que o que uma sessao
anonima disse em nome dele.

**O que fica de fora, e por que** -- ver a D4 da spec por extenso:
`recomendacoes` (a linha sem reacao dispara a pergunta de reacao, e a ordem e
o ordinal), `conversation_intent` (confianca, desambiguacao e o contador de
fora de escopo sao do episodio, nao da pessoa), o resumo (um bloco a mais no
prompt a cada turno), score e temperatura (recalculados no proprio turno) e
opt-out, handoff e atendimento humano (uma sessao nao verificada nao silencia
nem escala o numero de outra pessoa).

Idempotente: roda em todo turno, e o segundo passe sobre o mesmo estado nao
muda nada. E isso que cobre a sessao web que continua viva depois de o
WhatsApp comecar.
"""

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import MARCA_DO_ORCAMENTO
from mobia.domain.identidade.repositorio import sessoes_vinculadas
from mobia.domain.identidade.telefone import normalizar
from mobia.domain.messages.canais import CANAL_WHATSAPP

# Os criterios, e so eles. `intencao` entra: e a coluna de qualificacao, e nao
# a linha de `conversation_intent`. O que NAO entra e bookkeeping do turno --
# `perguntados_sem_resposta`, `perguntas_feitas` -- e o que o turno recalcula,
# `temperatura*` e `qualificado_em`.
CAMPOS_ABSORVIDOS: tuple[str, ...] = (
    "intencao",
    "faixa_preco_min_centavos",
    "faixa_preco_max_centavos",
    "regiao",
    "tipo_imovel",
    "quartos",
    "vagas",
    "urgencia",
    "forma_pagamento",
    "tem_imovel_para_vender",
    "ticket_investimento_centavos",
    "retorno_esperado_pct",
    "retorno_esperado_tipo",
    "horizonte",
    "tolerancia_reforma",
    "ja_investe_em_imoveis",
    "perfil_investidor",
)

# `campos_recusados` guarda o vocabulario da MARCA (`_marca_de` em
# `domain/context/repositorio.py`), nao nome de coluna -- e o unico nome desse
# vocabulario que cobre mais de uma coluna e o orcamento: `campos_a_recusar`
# grava toda recusa de faixa de preco sob `MARCA_DO_ORCAMENTO` -- importada, e
# nao escrita a mao aqui, pela razao que o comentario do descarte em
# `registrar_mudanca_de_intencao` da --, ainda que o lead tenha se recusado a
# dar so um dos dois extremos (`faixa_preco_min_centavos` / `faixa_preco_max_centavos` -- ver
# `_preenchido` em `domain/context/qualificacao.py`, que trata as duas do
# mesmo jeito: "qualquer uma basta"). Por isso uma recusa de orcamento tem de
# cair quando QUALQUER um dos dois extremos ja esta preenchido no WhatsApp, e
# nao so quando os dois estao. Nomes fora deste mapa continuam resolvidos por
# `getattr` direto (o comportamento e o mesmo, com uma coluna so na tupla).
_COLUNAS_DO_CAMPO_RECUSADO: dict[str, tuple[str, ...]] = {
    MARCA_DO_ORCAMENTO: ("faixa_preco_min_centavos", "faixa_preco_max_centavos"),
}


def _ja_preenchido(destino: LeadQualification, campo: str) -> bool:
    colunas = _COLUNAS_DO_CAMPO_RECUSADO.get(campo, (campo,))
    return any(getattr(destino, coluna, None) is not None for coluna in colunas)


async def absorver_sessoes_vinculadas(
    session_factory: async_sessionmaker[AsyncSession], *, conversation_key: str
) -> tuple[tuple[str, str], ...]:
    """Preenche o estado do WhatsApp com o das sessoes vinculadas; devolve os pares delas.

    Os pares vao para `montar_contexto`, que os poe na janela de literais. Sem
    vinculo -- ou com um `wa_id` que nao e brasileiro -- devolve `()` e nao
    escreve nada: o turno segue exatamente como antes desta card.
    """
    telefone = normalizar(conversation_key)
    if telefone is None:
        return ()

    async with session_factory() as session:
        pares = await sessoes_vinculadas(session, telefone)
        if not pares:
            return ()

        origens = list(
            await session.scalars(
                select(LeadQualification)
                .where(
                    tuple_(LeadQualification.channel, LeadQualification.conversation_key).in_(pares)
                )
                # A mais recente primeiro: e ela que vence um campo que duas
                # sessoes preencheram diferente.
                .order_by(LeadQualification.updated_at.desc())
            )
        )
        if origens:
            await _preencher(session, conversation_key, origens)
            await session.commit()
    return tuple(pares)


async def _preencher(
    session: AsyncSession, conversation_key: str, origens: list[LeadQualification]
) -> None:
    # Garante a linha antes do `FOR UPDATE`: sem ela nao ha o que travar, e dois
    # turnos simultaneos do mesmo numero criariam a linha os dois.
    await session.execute(
        pg_insert(LeadQualification)
        .values(channel=CANAL_WHATSAPP, conversation_key=conversation_key)
        .on_conflict_do_nothing(index_elements=["channel", "conversation_key"])
    )
    destino = (
        await session.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == CANAL_WHATSAPP,
                LeadQualification.conversation_key == conversation_key,
            )
            .with_for_update()
        )
    ).scalar_one()

    for campo in CAMPOS_ABSORVIDOS:
        if getattr(destino, campo) is not None:
            continue
        for origem in origens:
            valor = getattr(origem, campo)
            if valor is not None:
                setattr(destino, campo, valor)
                break

    # Uniao, menos o que o destino ja tem preenchido: a recusa no site sobre um
    # campo que o WhatsApp respondeu depois nao pode fazer o agente tratar como
    # recusado o que a pessoa ja disse. `_ja_preenchido` cobre o caso do
    # orcamento, onde a marca recusada e as colunas de valor nao tem o mesmo
    # nome -- ver o comentario de `_COLUNAS_DO_CAMPO_RECUSADO` acima.
    recusados = set(destino.campos_recusados or [])
    for origem in origens:
        recusados |= set(origem.campos_recusados or [])
    recusados = {campo for campo in recusados if not _ja_preenchido(destino, campo)}
    if recusados != set(destino.campos_recusados or []):
        destino.campos_recusados = sorted(recusados)
