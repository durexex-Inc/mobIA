"""O corretor corrige a qualificacao e pede para recontar o score. TEC-194.

RN-18.3 e RN-18.4, D4 a D6 do desenho. Funcoes livres com `session` posicional
e o resto keyword-only, sem commit -- quem chama e dono da transacao, e aqui
isso nao e convencao: o upsert, a trilha de score e os eventos de auditoria que
a rota grava TEM de entrar no mesmo commit. Uma trilha que registrasse um score
calculado sobre um estado que o rollback desfez seria pior que trilha nenhuma
-- o argumento de `registrar_recalculo`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.auditoria import CAUSA_EDICAO_MANUAL, CAUSA_RECALCULO_MANUAL
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.context.qualificacao import esta_qualificado
from mobia.domain.context.repositorio import carimbar_qualificacao, registrar_recalculo
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import Status

# O nome que a API usa -> a coluna. **So estes se editam** (D4), e `intencao`
# fica de fora de proposito: troca-la dispara `aplicar_mudanca_de_intencao`,
# que descarta o orcamento dito sob outra banda e grava trilha propria
# (TEC-136). E uma operacao com regra, nao um campo.
#
# O nome da API e tambem o `campo` que vai para a trilha de auditoria: e o que
# quem le a trilha reconhece, porque e o que a tela mostra.
EDITAVEIS: dict[str, str] = {
    "faixaPrecoMinCentavos": "faixa_preco_min_centavos",
    "faixaPrecoMaxCentavos": "faixa_preco_max_centavos",
    "regiao": "regiao",
    "tipoImovel": "tipo_imovel",
    "quartos": "quartos",
    "vagas": "vagas",
    "urgencia": "urgencia",
    "formaPagamento": "forma_pagamento",
    "temImovelParaVender": "tem_imovel_para_vender",
}


class EdicaoRecusada(Exception):
    """Pedido que a regra recusa. `motivo` diz qual, e vira o status HTTP."""

    def __init__(self, motivo: str, detalhe: str) -> None:
        super().__init__(detalhe)
        self.motivo = motivo


CONVERSA_ENCERRADA = "conversa_encerrada"
FAIXA_INVERTIDA = "faixa_invertida"
SEM_QUALIFICACAO = "sem_qualificacao"


@dataclass(frozen=True)
class Resultado:
    """O que a secao 6.2 escreve para a resposta do `PATCH`, mais os campos.

    `alterados` sao os nomes da API, na ordem de `EDITAVEIS`: e deles que a
    rota monta um `QUALIFICACAO_ALTERADA` por campo. Campo enviado com o valor
    que ja tinha NAO entra -- a trilha diria que algo mudou quando nada mudou.
    """

    alterados: tuple[str, ...]
    score_anterior: int | None
    score_atual: int | None
    temperatura: str | None


async def _ultimo_score(session: AsyncSession, par: tuple[str, str]) -> int | None:
    channel, conversation_key = par
    return (
        await session.execute(
            select(LeadScoreAudit.total_novo)
            .where(
                LeadScoreAudit.channel == channel,
                LeadScoreAudit.conversation_key == conversation_key,
            )
            .order_by(LeadScoreAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _exigir_conversa_aberta(session: AsyncSession, par: tuple[str, str]) -> None:
    """409 na secao 6.2. A ausencia de linha e ATIVA (D8 da TEC-192)."""
    channel, conversation_key = par
    status = (
        await session.execute(
            select(Conversa.status).where(
                Conversa.channel == channel, Conversa.conversation_key == conversation_key
            )
        )
    ).scalar_one_or_none()
    if status == Status.ENCERRADA.value:
        raise EdicaoRecusada(CONVERSA_ENCERRADA, "conversa encerrada")


async def editar_qualificacao(
    session: AsyncSession,
    *,
    par: tuple[str, str],
    campos: dict[str, object],
    autor: str,
) -> Resultado:
    """Aplica os campos presentes, recalcula e carimba a qualificacao. D4.

    `campos` vem com os nomes da API e so com os que o pedido trouxe --
    ausente nao muda, `None` explicito limpa. Quem garante que as chaves estao
    em `EDITAVEIS` e que os valores estao no vocabulario e a borda.

    **Cria a linha quando ela nao existe**, ao contrario de
    `carimbar_qualificacao`, que recusa isso para nao inventar estado. Aqui o
    estado nao e inventado: foi uma pessoa que o informou.

    **O carimbo `qualificado_em` e posto quando a edicao faz o lead cruzar a
    borda da RN-05.3**, pela mesma funcao que o turno usa. O carimbo e da
    primeira travessia, e ela aconteceu -- quem a causou e o que a trilha de
    score registra, com `EDICAO_MANUAL` e o autor.

    **Faixa invertida e conferida DEPOIS de juntar o pedido ao que ja havia**:
    mandar so o maximo, abaixo de um minimo antigo, inverteria a faixa sem que
    o pedido sozinho parecesse errado.
    """
    await _exigir_conversa_aberta(session, par)
    channel, conversation_key = par
    colunas = {EDITAVEIS[nome]: valor for nome, valor in campos.items()}

    # Garante a linha e toma o lock dela no mesmo passo. `DO NOTHING` e nao
    # `DO UPDATE`: o que se quer do INSERT e so a existencia da linha; os
    # valores entram pelo ORM logo abaixo, depois da comparacao com o antigo.
    await session.execute(
        insert(LeadQualification)
        .values(channel=channel, conversation_key=conversation_key)
        .on_conflict_do_nothing(index_elements=["channel", "conversation_key"])
    )
    estado = (
        await session.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == conversation_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    alterados = tuple(
        nome
        for nome in EDITAVEIS
        if nome in campos and getattr(estado, EDITAVEIS[nome]) != campos[nome]
    )

    minimo = colunas.get("faixa_preco_min_centavos", estado.faixa_preco_min_centavos)
    maximo = colunas.get("faixa_preco_max_centavos", estado.faixa_preco_max_centavos)
    if isinstance(minimo, int) and isinstance(maximo, int) and minimo > maximo:
        raise EdicaoRecusada(FAIXA_INVERTIDA, "faixa de preco com minimo acima do maximo")

    anterior = await _ultimo_score(session, par)
    if not alterados:
        return Resultado(
            alterados=(),
            score_anterior=anterior,
            score_atual=anterior,
            temperatura=estado.temperatura,
        )

    for coluna, valor in colunas.items():
        setattr(estado, coluna, valor)
    estado.updated_at = datetime.now(UTC)
    await session.flush()

    recalculo = await registrar_recalculo(
        session,
        channel=channel,
        conversation_key=conversation_key,
        causas_externas=(CAUSA_EDICAO_MANUAL,),
        autor=autor,
    )

    if esta_qualificado(estado, frozenset(estado.campos_recusados or ())):
        await carimbar_qualificacao(
            session,
            channel=channel,
            conversation_key=conversation_key,
            quando=datetime.now(UTC),
        )

    return Resultado(
        alterados=alterados,
        score_anterior=anterior,
        score_atual=recalculo.total if recalculo is not None else anterior,
        temperatura=recalculo.temperatura.value if recalculo is not None else estado.temperatura,
    )


async def recalcular_a_pedido(
    session: AsyncSession, *, par: tuple[str, str], autor: str
) -> Resultado:
    """Grava um recalculo com `RECALCULO_MANUAL`, mesmo com o total igual. D5.

    A linha nasce sempre -- e para isso que `causas_externas` existe: o
    terceiro cenario pede o registro com o motivo, e nao so quando o numero
    muda. Lead sem qualificacao e recusado: nao ha o que pontuar, e gravar um
    zero seria afirmar algo sobre o lead.

    **O fator de catalogo e sempre zero** (`imoveis_compativeis=0` em
    `registrar_recalculo`), entao o "catalogo mudou" do terceiro cenario nao
    move o score por aqui (L2 do desenho).
    """
    channel, conversation_key = par
    anterior = await _ultimo_score(session, par)
    recalculo = await registrar_recalculo(
        session,
        channel=channel,
        conversation_key=conversation_key,
        causas_externas=(CAUSA_RECALCULO_MANUAL,),
        autor=autor,
    )
    if recalculo is None:
        raise EdicaoRecusada(SEM_QUALIFICACAO, "lead sem qualificacao para pontuar")
    return Resultado(
        alterados=(),
        score_anterior=anterior,
        score_atual=recalculo.total,
        temperatura=recalculo.temperatura.value,
    )
