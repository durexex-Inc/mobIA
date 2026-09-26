"""A identidade do lead e a sessao web vinculada a um telefone. TEC-129 e TEC-203.

**Uma linha por sessao, e nao por telefone.** A mesma pessoa em dois
navegadores sao duas sessoes apontando para o mesmo numero; o que a PK proibe
e a mesma sessao apontar para dois numeros. O primeiro telefone vale, e um
segundo diferente e ignorado -- ver `vincular_sessao`.

**So a sessao web tem linha aqui.** O lado WhatsApp nao precisa: o valor por
tras do `conversation_key` dele e o `wa_id`, e a absorcao o revela
(`indice.revelar`), leva a forma canonica com `normalizar` e consulta esta
tabela por `telefone_indice` -- o mesmo indice que o vinculo grava.

**O vinculo e so de ida, e isso e a decisao central da card (D1).** Quem le
esta tabela e o turno do WhatsApp, para absorver o que a sessao disse. O turno
web nunca a consulta: a sessao e anonima e nada verifica que o numero e de quem
o digitou, entao ler o WhatsApp a partir daqui entregaria a conversa de uma
pessoa a qualquer um que soubesse o telefone dela.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base
from mobia.infra.crypto import aad_de


def aad_da_identidade(channel: str, conversation_key: str) -> str:
    """Amarra o valor cifrado a sua propria linha. Prefixado por tamanho pelo
    mesmo motivo de `context/models.py::aad_do_resumo`."""
    return aad_de(f"{len(channel)}:{channel}:{conversation_key}", "identidade_do_lead")


def aad_do_vinculo(channel: str, conversation_key: str) -> str:
    """O AAD do telefone cifrado do vinculo, pela mesma regra de `aad_da_identidade`."""
    return aad_de(f"{len(channel)}:{channel}:{conversation_key}", "telefone_do_vinculo")


class IdentidadeDeLead(Base):
    """O valor cru por tras de um `conversation_key`. TEC-203, D2.

    No WhatsApp o valor e o telefone; no web, a sessao. As ~20 tabelas que
    guardam o `conversation_key` guardam o HMAC dele, e esta e a unica linha
    onde o valor existe -- cifrado, e so revelado por `indice.revelar`.
    """

    __tablename__ = "identidades_de_lead"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    valor_cifrado: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VinculoDeSessao(Base):
    __tablename__ = "vinculos_de_sessao"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # TEC-203. O telefone cifrado e o indice dele. Ate a TEC-203 o numero
    # ficava em claro, "como o conversation_key do WhatsApp ja e"; os dois
    # deixaram de ser. A absorcao e a busca consultam `telefone_indice`, que e
    # `indice_de_telefone` sobre a forma canonica de `telefone.normalizar`.
    telefone_cifrado: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    telefone_indice: Mapped[str] = mapped_column(String(64), nullable=False)

    # A fala que trouxe o numero. CASCADE porque o vinculo e derivado do
    # conteudo dela: apagada a mensagem (retencao, direito do titular), nao
    # sobra evidencia que sustente o vinculo.
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_vinculos_de_sessao_telefone_indice", "telefone_indice"),)
