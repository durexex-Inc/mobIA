"""As versoes de prompt e as ativacoes. TEC-199, D4 do desenho.

**Duas tabelas, as duas so de acrescimo.** `versoes_de_prompt` guarda cada
texto publicado; `ativacoes_de_prompt` guarda cada vez que uma versao passou
a valer -- por publicacao ou por rollback. A vigente de um agente e o
`numero` da ativacao mais recente dele, e sem ativacao vale o padrao do
codigo.

Com o ponteiro, o que vale depois de um rollback para a 3 E a versao 3, e nao
uma versao 5 com o texto dela -- que e o que o cenario da card diz. E o
registro do rollback que a card pede (autor, momento, versao de destino) e
uma linha de `ativacoes_de_prompt`.

**A versao 0 e o padrao, e nao tem linha.** So existe como `numero=0` numa
ativacao e como `anterior=0` numa versao. Semear o padrao congelaria o texto
de hoje, pelo argumento da `0058`.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class VersaoDePrompt(Base):
    __tablename__ = "versoes_de_prompt"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    agente: Mapped[str] = mapped_column(String(16), nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    # O numero que VALIA quando esta foi publicada -- depois de um rollback,
    # nao e `numero - 1`. 0 e o padrao.
    anterior: Mapped[int] = mapped_column(Integer, nullable=False)
    # Contra `anterior`, gravado na publicacao: o padrao muda por deploy, e um
    # diff calculado na leitura mentiria sobre o que o administrador editou.
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    autor: Mapped[str] = mapped_column(String(120), nullable=False)
    # `clock_timestamp()` pela razao de `configuracoes_do_agente.criado_em`.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    # O UNIQUE e o que transforma duas publicacoes simultaneas em uma
    # recusada, e nao em duas versoes com o mesmo numero.
    __table_args__ = (UniqueConstraint("agente", "numero", name="uq_versoes_de_prompt_numero"),)


class AtivacaoDePrompt(Base):
    __tablename__ = "ativacoes_de_prompt"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    agente: Mapped[str] = mapped_column(String(16), nullable=False)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    motivo: Mapped[str] = mapped_column(String(12), nullable=False)
    autor: Mapped[str] = mapped_column(String(120), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        Index("ix_ativacoes_de_prompt_agente_criado_em", "agente", text("criado_em DESC")),
    )
