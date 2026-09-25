"""A escrita da trilha de auditoria. TEC-206, D1 do desenho.

**Escrita explicita, e nao trigger nas tabelas de origem.** O banco nao
conhece o usuario, o IP nem o `correlation_id`, e trigger nao ve leitura --
que e metade do que se audita. O custo: todo caminho auditado precisa de uma
linha de codigo, e um caminho novo que a esqueca nao e auditado. A defesa e um
teste por evento, nao um mecanismo implicito.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.vocabulario import Acao, Ator, Entidade, validar_detalhes


@dataclass(frozen=True)
class Origem:
    """De onde veio uma requisicao HTTP. Agente e sistema nao tem origem.

    Montada por `api/middleware.py::origem_da_requisicao`. O opt-out chega
    pelo webhook, e o IP ali e o da Meta, nao o do lead -- grava-lo seria
    afirmar uma origem falsa, e por isso os escritores do dominio nao passam
    origem nenhuma.
    """

    ip: str | None
    correlation_id: str | None


async def registrar_evento(
    session: AsyncSession,
    *,
    ator: Ator,
    acao: Acao,
    entidade: Entidade,
    entidade_id: str,
    campo: str | None = None,
    lead: tuple[str, str] | None = None,
    detalhes: Mapping[str, str | None] | None = None,
    origem: Origem | None = None,
) -> uuid.UUID:
    """Acrescenta o evento a sessao de quem chama. **Nao commita.**

    O molde de `registrar_recalculo`: numa operacao de escrita, o evento e a
    operacao commitam juntos ou nenhum dos dois -- nao ha handoff sem
    registro, nem registro de handoff desfeito. Nas leituras, quem chama abre
    uma sessao curta e commita antes de a resposta sair.

    Flush e nao so `add`: um CHECK violado estoura aqui, no ponto da chamada,
    e nao num commit distante que ja nao diz de onde veio a linha.

    `lead` e o par `(channel, conversation_key)`; o que vai para a linha e o
    `lead_ref`, e nenhum chamador lida com o HMAC.
    """
    evento_id = uuid.uuid4()
    session.add(
        EventoAuditoria(
            id=evento_id,
            ator_tipo=ator.tipo.value,
            ator_id=ator.id,
            acao=acao.value,
            entidade=entidade.value,
            entidade_id=entidade_id,
            campo=campo,
            lead_ref=(
                lead_ref(lead[0], lead[1], chave=get_settings().auditoria_chave_do_lead)
                if lead is not None
                else None
            ),
            detalhes=validar_detalhes(detalhes) if detalhes is not None else None,
            ip=origem.ip if origem is not None else None,
            correlation_id=origem.correlation_id if origem is not None else None,
        )
    )
    await session.flush()
    return evento_id
