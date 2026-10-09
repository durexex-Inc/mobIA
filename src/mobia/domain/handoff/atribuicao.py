"""A atribuicao manual do handoff pelo admin. TEC-404, D1.

**Segundo escritor de `handoffs.corretor_id`** (Emenda E-07 da RN-16.2): ate a
TEC-404 so `notificacao/envio.py::notificar` o gravava, e so quando nulo. Aqui
ele e SOBRESCRITO de proposito -- e o admin trocando o dono. A regra "so quando
nulo" continua valendo para a notificacao, que e o que protege o dono contra
uma retentativa do ARQ.

**Atribuir desfaz o aceite e reinicia o prazo** (decisao 4 da card; Emenda E-08
da RN-16.3). O handoff volta a PENDENTE sem `aceito_em`, sem `sla_limite_em` e
sem `notificado_em`; a notificacao enfileirada pela rota calcula o prazo pela
jornada do NOVO corretor, porque `notificar` so calcula prazo quando ele e
nulo e o status e PENDENTE, e `destinatario_do_handoff` devolve o
`corretor_id` gravado quando ele esta ativo -- o que esta funcao confere.
`sweep_sla` nao precisa mudar: `escalar_vencidos` olha PENDENTE com prazo
vencido, e `recuperar_sem_prazo` cobre o intervalo ate a notificacao rodar.

Nao commita: a trilha e a escrita commitam juntas, ou nenhuma das duas.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.registro import Origem, registrar_evento
from mobia.domain.auditoria.vocabulario import Acao, Ator, Entidade, detalhes_da_atribuicao
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status


class AtribuicaoRecusada(Exception):
    """`motivo` em `corretor_invalido`, `nao_existe` ou `concluido`; a rota traduz em HTTP."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class Atribuicao:
    mudou: bool
    aceito_desfeito: bool


def id_do_job_de_atribuicao(handoff_id: uuid.UUID) -> str:
    """Id NOVO a cada atribuicao (D1): o ARQ descarta em silencio um enqueue
    cujo `_job_id` ja tenha chave de job ou de resultado no Redis.

    `notificar_corretor` roda com `keep_result=0` (`workers/main.py`), entao a
    chave de RESULTADO do `notificar:{id}` da primeira notificacao some ao
    terminar. A chave de JOB, nao: ela vive enquanto aquele job esta na fila,
    rodando ou entre retentativas -- e atribuir logo depois do nascimento do
    handoff cai exatamente nesse intervalo. O mesmo id ali seria um no-op, e o
    novo corretor nao seria avisado por esta via.
    """
    return f"notificar:{handoff_id}:atribuicao:{uuid.uuid4()}"


async def atribuir(
    session: AsyncSession,
    *,
    handoff_id: uuid.UUID,
    corretor_id: uuid.UUID,
    ator: Ator,
    origem: Origem | None,
) -> Atribuicao:
    # Corretor inativo seria descartado em silencio por
    # `destinatario_do_handoff`, que cairia no plantao: o admin escolheria um
    # dono e a notificacao avisaria outro. Por isso a recusa e aqui, na entrada.
    corretor = await session.get(Corretor, corretor_id)
    if corretor is None or not corretor.ativo:
        raise AtribuicaoRecusada("corretor_invalido")

    # FOR UPDATE: a leitura do status e a escrita abaixo precisam ver a mesma
    # versao da linha. Um `aceitar` que commitar antes faz este SELECT esperar
    # e ler ACEITO -- e o aceite e desfeito e registrado como tal. O que o lock
    # NAO impede: `aceitar` e `escalar_vencidos` sao UPDATEs condicionados so a
    # `status`, e os que estiverem esperando por esta linha reavaliam a
    # condicao depois do nosso commit, ja contra PENDENTE. Um aceite do dono
    # anterior ou uma escalada de um prazo que JA tinha vencido podem, assim,
    # cair logo em seguida sobre o handoff recem-atribuido.
    handoff = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id).with_for_update())
    ).scalar_one_or_none()
    if handoff is None:
        raise AtribuicaoRecusada("nao_existe")
    if handoff.status == Status.CONCLUIDO.value:
        raise AtribuicaoRecusada("concluido")

    if handoff.corretor_id == corretor_id and handoff.status == Status.PENDENTE.value:
        # D7: atribuir de novo ao mesmo dono de um handoff ainda pendente nao
        # reenvia aviso nem escreve trilha.
        return Atribuicao(mudou=False, aceito_desfeito=False)

    anterior = handoff.corretor_id
    aceito_desfeito = handoff.status == Status.ACEITO.value
    agora = datetime.now(UTC)
    handoff.corretor_id = corretor_id
    handoff.status = Status.PENDENTE.value
    handoff.aceito_em = None
    handoff.sla_limite_em = None
    handoff.notificado_em = None
    handoff.aviso_manual_pendente = False
    handoff.atualizado_em = agora

    await registrar_evento(
        session,
        ator=ator,
        acao=Acao.HANDOFF_ATRIBUIDO,
        entidade=Entidade.HANDOFF,
        entidade_id=str(handoff_id),
        lead=(handoff.channel, handoff.conversation_key),
        detalhes=detalhes_da_atribuicao(
            anterior=anterior, novo=corretor_id, aceito_desfeito=aceito_desfeito
        ),
        origem=origem,
    )
    return Atribuicao(mudou=True, aceito_desfeito=aceito_desfeito)
