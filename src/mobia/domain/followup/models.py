"""As duas trilhas append-only do follow-up: as tentativas e as tarefas.

TEC-183 (`FollowUp`) e TEC-186 (`TarefaDeCorretor`). As duas sao append-only e
compartilham a mesma UNIQUE `(channel, conversation_key, ancora_em,
tentativa_numero)`: uma linha por tentativa, e o que nao aconteceu nao tem
linha. Nao ha estado PENDENTE nem CANCELADO -- a cadencia e derivada. Ver a
emenda a RN-13.4 (status) e a E-01 da RN-13.6 (a tarefa) no SRS.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class FollowUp(Base):
    __tablename__ = "followups"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # 1-based. Zero seria indistinguivel de "nenhuma disparou", que e o que a
    # ausencia de linha ja significa -- por isso o CHECK.
    tentativa_numero: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # A temperatura NO MOMENTO do disparo, e nao a de agora. Redundante com
    # `lead_qualification` de proposito: e ela que explica por que foram N
    # tentativas, e a coluna viva ja tera mudado quando alguem ler a trilha.
    temperatura: Mapped[str] = mapped_column(String(8), nullable=False)

    # A ultima fala do lead que gerou este disparo -- o `created_at` daquela
    # mensagem, exato e nao aproximado. E contra a igualdade nesta coluna que
    # se conta ate onde a cadencia ja foi; quando o lead responde, a ancora
    # muda e a contagem zera sozinha.
    ancora_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # `ancora_em + CADENCIA[temperatura][n-1]`. Calculado, nao agendado -- e
    # **nao** esta ajustado a janela de 9h-20h, ao contrario do que o modelo de
    # dados do SRS diz sobre `agendado_para`. Isso e a TEC-185.
    devido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        CheckConstraint("tentativa_numero > 0", name="ck_followups_tentativa"),
        # Duas varreduras concorrentes veriam o mesmo candidato devido e ambas
        # inseririam. Nao da para usar FOR UPDATE SKIP LOCKED sobre a agregacao
        # que produz os candidatos, entao a exclusao mora aqui.
        UniqueConstraint(
            "channel",
            "conversation_key",
            "ancora_em",
            "tentativa_numero",
            name="uq_followups_tentativa_por_ancora",
        ),
        Index("ix_followups_lead", "channel", "conversation_key", "ancora_em"),
    )


class TarefaDeCorretor(Base):
    """Um follow-up que nao pode sair sozinho e virou trabalho para o corretor.

    TEC-186, RN-13.6. Fora da janela de 24h e sem template aprovado aplicavel
    ao contexto, o follow-up nao vira envio -- a Meta recusaria mensagem livre,
    e template aplicavel nao ha. Vira esta linha, no molde de `followups`:
    append-only, uma linha por tentativa, a mesma UNIQUE por ancora. Quem a
    consome e o dashboard (E8), que nao existe; ate la, `listar_tarefas_de_corretor`
    a le sem rota HTTP, pelo mesmo motivo de `listar_dormentes`. Ver a emenda
    E-01 da RN-13.6 no SRS.
    """

    __tablename__ = "tarefas_de_corretor"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # A ancora e o numero da tentativa espelham `followups` -- e o que da a
    # UNIQUE identica e a idempotencia por tentativa: uma varredura que ja
    # gravou o follow-up nao pode gravar a tarefa dele duas vezes.
    ancora_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tentativa_numero: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # O contexto da novidade (queda_de_preco / imovel_novo / convite), para o
    # corretor saber com que gancho retomar o contato -- o mesmo que teria ido
    # no template se ele estivesse aprovado.
    categoria: Mapped[str] = mapped_column(String(24), nullable=False)

    # Por que virou tarefa. Hoje so `sem_template_aprovado`; a coluna existe
    # para o dia em que houver um segundo motivo, e nao para ser lida por um
    # `if` agora.
    motivo: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        CheckConstraint("tentativa_numero > 0", name="ck_tarefas_de_corretor_tentativa"),
        UniqueConstraint(
            "channel",
            "conversation_key",
            "ancora_em",
            "tentativa_numero",
            name="uq_tarefas_de_corretor_por_ancora",
        ),
        Index("ix_tarefas_de_corretor_lead", "channel", "conversation_key", "ancora_em"),
    )
