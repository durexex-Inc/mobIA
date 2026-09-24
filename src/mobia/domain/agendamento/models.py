"""Os agendamentos, e a garantia de que dois nao se sobrepoem. TEC-168, RT-07.

**A garantia nao mora aqui.** A constraint de exclusao por intervalo
(`EXCLUSAO_DE_SOBREPOSICAO`) e criada em SQL pela migration 0044 e nao e
declarada no modelo: o `ExcludeConstraint` do SQLAlchemy nao expressa bem o
`tstzrange(inicio, fim, '[)')`, e o que importa para o RT-07 e o banco
recusar -- ver `tests/integration/test_agendamento_schema.py`, que prova com
insert cru, sem passar por este modelo.

O lead e o par `(channel, conversation_key)`, como em `handoffs` e
`optout_events`: nao existe tabela de lead.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

# Importados para registrar as tabelas-alvo das FKs no mesmo metadata: sem
# eles o flush nao sabe ordenar `agendamentos` depois de `corretores` e
# `imoveis`.
from mobia.domain.catalogo.models import Imovel  # noqa: F401
from mobia.domain.corretores.models import Corretor  # noqa: F401
from mobia.domain.messages.models import Base


class StatusDoAgendamento(StrEnum):
    RESERVADO = "RESERVADO"
    CONFIRMADO = "CONFIRMADO"
    # A reserva que venceu e foi atropelada por outra (D3 do desenho). Uma
    # vencida que ninguem disputou continua RESERVADO: quem le filtra por
    # `reservado_ate`, e nao por este status.
    EXPIRADO = "EXPIRADO"


EXCLUSAO_DE_SOBREPOSICAO = "ex_agendamentos_sem_sobreposicao"


class Agendamento(Base):
    __tablename__ = "agendamentos"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    corretor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("corretores.id", name="fk_agendamentos_corretor"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nulo: reuniao remota pode nao ter imovel. O contrato do SRS (6.4) tem
    # `imovelId`, e a FK impede apontar para imovel que nao existe.
    imovel_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("imoveis.id", name="fk_agendamentos_imovel"),
        nullable=True,
    )
    tipo: Mapped[str] = mapped_column(String(24), nullable=False)
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reservado_ate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "tipo IN ('VISITA_PRESENCIAL','REUNIAO_REMOTA')", name="ck_agendamentos_tipo"
        ),
        CheckConstraint(
            "status IN ('RESERVADO','CONFIRMADO','EXPIRADO')", name="ck_agendamentos_status"
        ),
        CheckConstraint("inicio < fim", name="ck_agendamentos_intervalo"),
    )
