"""A solicitacao de titular. TEC-207, D2 do desenho.

Ver `alembic/versions/0063_solicitacoes_de_titular.py` para os CHECKs e o
indice unico parcial -- os dois tem copia literal na migration, e nao import,
pela mesma razao de `auditoria/vocabulario.py`.

`ck_solicitacoes_de_titular_par_completo` e `ck_solicitacoes_de_titular_par_com_status`
juntos amarram o par: o segundo liga a PRESENCA do par ao status, o primeiro
liga os dois lados do par entre si -- sem ele, `channel` preenchido com
`conversation_key` nulo (ou o inverso) passaria pelo primeiro CHECK sozinho.
"""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class SolicitacaoDeTitular(Base):
    __tablename__ = "solicitacoes_de_titular"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # HMAC do par (`auditoria/referencia.py::lead_ref`) -- sobrevive a
    # anonimizacao, ao contrario do par abaixo. E a referencia DEPOIS de a
    # solicitacao fechar, e so isso: enquanto ABERTA, quem localiza a linha e
    # o par (ver `uq_solicitacao_aberta`), porque a rotacao de chave da
    # TEC-203 arrasta o par e nao recalcula este campo.
    lead_ref: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    # O par, SO ENQUANTO ABERTA -- vira nulo ao ser atendida ou recusada
    # (ck_solicitacoes_de_titular_par_com_status abaixo). E o que permite
    # localizar a conversa para responder enquanto o pedido espera, sem que a
    # linha continue carregando o identificador do lead depois de resolvida.
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    conversation_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    origem: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    # So a recusa preenche.
    motivo_da_recusa: Mapped[str | None] = mapped_column(Text, nullable=True)

    recebida_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # recebida_em + PRAZO_DO_TITULAR (15 dias), calculado por quem grava.
    prazo_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atendida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("tipo IN ('ELIMINACAO', 'ACESSO')", name="ck_solicitacoes_de_titular_tipo"),
        CheckConstraint(
            "origem IN ('WHATSAPP', 'ADMIN', 'RETENCAO')",
            name="ck_solicitacoes_de_titular_origem",
        ),
        CheckConstraint(
            "status IN ('ABERTA', 'ATENDIDA', 'RECUSADA')",
            name="ck_solicitacoes_de_titular_status",
        ),
        # O par so existe enquanto aberta -- some ao ser atendida ou recusada.
        CheckConstraint(
            "(status = 'ABERTA') = (channel IS NOT NULL)",
            name="ck_solicitacoes_de_titular_par_com_status",
        ),
        # Os dois lados do par aparecem juntos ou nenhum aparece -- channel
        # sem conversation_key (ou o inverso) e estado que nao corresponde a
        # nenhuma conversa real.
        CheckConstraint(
            "(channel IS NOT NULL) = (conversation_key IS NOT NULL)",
            name="ck_solicitacoes_de_titular_par_completo",
        ),
        # Uma aberta por tipo e por lead: pedir eliminacao duas vezes nao cria
        # duas linhas (D3 do desenho, "idempotente"). Pelo PAR, e nao por
        # `lead_ref` -- revisao final da TEC-207, I2: a rotacao da chave de
        # indice (TEC-203) move `conversation_key` nesta tabela como em toda
        # outra de `TABELAS_COM_CHAVE_DE_LEAD`, mas so recalcula `lead_ref` em
        # `eventos_auditoria`. Chaveada por `lead_ref`, a unicidade deixava o
        # pedido repetido depois de uma rotacao abrir uma segunda linha. O par
        # esta sempre presente enquanto ABERTA (o CHECK acima), entao o indice
        # parcial cobre exatamente as linhas que ele precisa cobrir.
        Index(
            "uq_solicitacao_aberta",
            "channel",
            "conversation_key",
            "tipo",
            unique=True,
            postgresql_where=text("status = 'ABERTA'"),
        ),
        # O sweep de retencao (D5) le por status e prazo, em lote.
        Index("ix_solicitacoes_de_titular_status_prazo", "status", "prazo_em"),
    )
