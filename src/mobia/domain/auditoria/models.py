"""A linha da trilha de auditoria. TEC-206, D2 do desenho.

O `EventoAuditoria` da secao 5.1 do SRS com quatro diferencas: entram `campo`,
`lead_ref`, `correlation_id` e `detalhes`; saem `dados_antes` e `dados_depois`
-- para qualificacao e dado pessoal, o antes e o depois SAO o dado pessoal que
a card proibe guardar em claro. Ver a Emenda E-01 ao `EventoAuditoria`.

CHECKs, indices e os dois triggers moram na migration 0053, escrita a mao --
o vocabulario de acao e entidade foi redefinido na 0055 (TEC-204) --, e nao
aqui: o modelo so serve ao ORM.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, DateTime, String, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class EventoAuditoria(Base):
    __tablename__ = "eventos_auditoria"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O valor enviado e sempre descartado: o trigger `eventos_auditoria_carimbo`
    # o sobrescreve com `clock_timestamp()`. O `server_default` so poupa o ORM
    # de mandar um valor que nao vale nada.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    ator_tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    # `usuario_id` de pessoa, `token-compartilhado` pelo `X-Admin-Token`, nulo
    # para agente e sistema -- o par e conferido por `ck_eventos_auditoria_ator_id`.
    ator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    acao: Mapped[str] = mapped_column(String(32), nullable=False)
    entidade: Mapped[str] = mapped_column(String(32), nullable=False)
    # O uuid da entidade, ou o template da rota numa negativa.
    entidade_id: Mapped[str] = mapped_column(String(200), nullable=False)
    campo: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # HMAC do par do lead -- ver `auditoria/referencia.py`. Nunca o telefone.
    lead_ref: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)

    # So metadado fechado, montado por `auditoria/vocabulario.py` (D5).
    detalhes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Na escrita vai texto; na leitura o asyncpg devolve `ipaddress.IPv4Address`
    # ou `IPv6Address`, e quem serializa faz `str()`.
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    # O id da requisicao (TEC-368), que liga o registro ao log de aplicacao.
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
