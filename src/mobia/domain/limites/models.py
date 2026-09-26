"""O registro de bloqueio por rate limit, append-only (TEC-205, RNF-16).

Uma linha por chave por janela, nao por requisicao bloqueada. Escrever uma
linha por requisicao transformaria o registro de abuso no proprio vetor de
abuso: no widget, o atacante escreveria uma linha de banco por requisicao e a
defesa custaria mais que o ataque. Quem garante a unicidade e a chave
`ratelimit:evento:*` em Redis (`domain/limites/eventos.py`), nao um UNIQUE --
o banco nao tem como saber onde uma janela deslizante comeca.

**`limite` fica na linha porque o limite e configuravel.** Um evento que guarda
so o volume vira ilegivel no dia em que alguem mudar a configuracao: "volume
21" nao diz se houve abuso sem o 20 ao lado.

**Nunca o conteudo da mensagem.** Mesma regra de `moderation_events`: a card
pede o registro do evento -- numero, momento, volume --, nao do que foi dito.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base

ESCOPO_NUMERO = "numero"
ESCOPO_IP = "ip"

# O canal do escopo IP. Nao e "web": o middleware cobre toda rota HTTP, e o
# bloqueio ali e de uma requisicao a API, nao de mensagem de canal nenhum.
CHANNEL_HTTP = "http"


class RateLimitEvent(Base):
    __tablename__ = "rate_limit_events"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    escopo: Mapped[str] = mapped_column(String(8), nullable=False)

    # A chave do lead no escopo `numero`, o IP no escopo `ip`. Desde a TEC-203
    # a chave do escopo `numero` e o `conversation_key` (o HMAC de
    # `identidade/indice.py::chave_de`), e nao o numero: o numero se recupera
    # pela identidade do lead (`indice.revelar`), e a reindexacao troca esta
    # coluna junto com as demais. Inteiro, e nao mascarado: esta tabela e a
    # evidencia que responde "quem foi" numa investigacao. Quem sai mascarado
    # e o LOG, que vai para agregador e fica muito mais exposto -- `ip` esta em
    # `_CHAVES_MASCARADAS` (`app/logging.py`) pelo mesmo motivo que
    # `conversation_key` ja estava.
    chave: Mapped[str] = mapped_column(String(64), nullable=False)

    channel: Mapped[str] = mapped_column(String(32), nullable=False)

    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    limite: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nulo no escopo `ip`: la o bloqueio acontece antes de a rota rodar e nao
    # ha mensagem nenhuma. SEM FK, pelo motivo das migrations 0010 e 0020: a
    # retencao de `messages` (12 meses, RNF-22) e mais curta que a do registro
    # de conformidade, e uma FK apagaria evidencia por cascata.
    message_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_rate_limit_events_chave",
            "escopo",
            "chave",
            text("created_at DESC"),
        ),
    )
