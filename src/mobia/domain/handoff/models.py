"""O handoff: a tarefa que o lead pronto vira para o corretor.

TEC-174. Ver `alembic/versions/0023_handoffs.py` para o porque do par como
identidade, do UNIQUE parcial e do `corretor_id` sem FK.
"""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, Index, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from mobia.domain.messages.models import Base
from mobia.infra.crypto import aad_de


def aad_do_resumo_de_handoff(handoff_id: uuid.UUID) -> str:
    """Amarra o resumo ao handoff que ele descreve.

    Diferente do `aad_do_resumo` de `context/models.py`, que precisa compor o
    par `(channel, conversation_key)` e por isso prefixa cada parte pelo
    tamanho: aqui a identidade da linha e um UUID, que nao tem como colidir
    com outro por concatenacao ambigua. `aad_de` basta.
    """
    return aad_de(handoff_id, "resumo")


class Handoff(Base):
    __tablename__ = "handoffs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # O gatilho que CRIOU o handoff. Os que chegarem depois vao para
    # `gatilhos_adicionais` -- a etiqueta nao muda, porque e por ela que a fila
    # do dashboard e filtrada (TEC-192) e etiqueta movel embaralha filtro salvo.
    gatilho: Mapped[str] = mapped_column(String(32), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(32), nullable=False)

    # Escala para ALTA e nunca desce -- emenda E-01 da RN-16.1. Sem isso, um
    # pedido explicito de humano sobre um handoff aberto ficaria NORMAL, o que
    # contraria a RN-04.6.
    prioridade: Mapped[str] = mapped_column(String(8), nullable=False)

    # Nasce e permanece PENDENTE nesta card. ACEITO/ESCALADO vem da TEC-178 e
    # CONCLUIDO da TEC-179 -- o enum nasce completo porque mudar valor de enum
    # depois custa migration, e o `IN` do CHECK e o unico lugar a mexer.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    # Nulavel e sem FK ate a TEC-196 criar `corretores`. Nada escreve aqui hoje.
    corretor_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    gatilhos_adicionais: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
    )

    # Cifrado com AES-GCM, AAD de `aad_do_resumo_de_handoff`. Nulavel por
    # construcao: a geracao e assincrona (ver a D1 do desenho), entao todo
    # handoff existe por alguns segundos sem resumo -- e permanece sem quando
    # a geracao falha, que e o caso que a TEC-176 vai atender.
    resumo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    resumo_gerado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Qual modelo escreveu. Mesmo papel do `modelo` de `conversation_summaries`:
    # quando a saida piorar, e por ele que se descobre o que mudou.
    resumo_modelo: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @validates("resumo")
    def _recusar_texto_claro(self, coluna: str, valor: object) -> object:
        """Mesma guarda de `Message` e de `ConversationSummary`.

        O driver embute o argumento recusado na propria mensagem de excecao,
        antes de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log.
        """
        if valor is not None and not isinstance(valor, bytes | bytearray | memoryview):
            raise TypeError(
                f"{coluna} aceita apenas bytes cifrados, recebeu {type(valor).__name__}"
            )
        return valor

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("prioridade IN ('ALTA', 'NORMAL')", name="ck_handoffs_prioridade"),
        CheckConstraint(
            "status IN ('PENDENTE', 'ACEITO', 'ESCALADO', 'CONCLUIDO')",
            name="ck_handoffs_status",
        ),
        Index(
            "uq_handoffs_conversa_pendente",
            "channel",
            "conversation_key",
            unique=True,
            postgresql_where=text("status = 'PENDENTE'"),
        ),
    )
