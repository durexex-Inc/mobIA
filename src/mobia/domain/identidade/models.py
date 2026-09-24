"""A sessao web vinculada a um telefone. TEC-129, D3.

**Uma linha por sessao, e nao por telefone.** A mesma pessoa em dois
navegadores sao duas sessoes apontando para o mesmo numero; o que a PK proibe
e a mesma sessao apontar para dois numeros. O primeiro telefone vale, e um
segundo diferente e ignorado -- ver `vincular_sessao`.

**So a sessao web tem linha aqui.** O lado WhatsApp nao precisa: o
`conversation_key` dele ja e o numero, e `normalizar` o leva a mesma forma
canonica deste `telefone`.

**O vinculo e so de ida, e isso e a decisao central da card (D1).** Quem le
esta tabela e o turno do WhatsApp, para absorver o que a sessao disse. O turno
web nunca a consulta: a sessao e anonima e nada verifica que o numero e de quem
o digitou, entao ler o WhatsApp a partir daqui entregaria a conversa de uma
pessoa a qualquer um que soubesse o telefone dela.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class VinculoDeSessao(Base):
    __tablename__ = "vinculos_de_sessao"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Forma canonica de `domain/identidade/telefone.py`: so digitos, com o 55.
    # Em claro, como o `conversation_key` do WhatsApp ja e.
    telefone: Mapped[str] = mapped_column(String(16), nullable=False)

    # A fala que trouxe o numero. CASCADE porque o vinculo e derivado do
    # conteudo dela: apagada a mensagem (retencao, direito do titular), nao
    # sobra evidencia que sustente o vinculo.
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_vinculos_de_sessao_telefone", "telefone"),)
