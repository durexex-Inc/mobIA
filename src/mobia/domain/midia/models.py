"""A midia recebida: onde ela mora e o estado do download. TEC-132, D1-D3.

**Tabela a parte, e nao colunas em `messages`** (D2): so midia tem estes
campos, e o estado do download muda DEPOIS que a mensagem ja foi gravada --
misturar faria toda leitura de `messages` carregar colunas que so IMAGEM e
DOCUMENTO usam.

**O nome do arquivo do documento nao vira coluna.** Ele ja fica cifrado em
`messages.raw_payload`, onde o parser o grava; guardar de novo aqui
duplicaria um dado sensivel fora do cofre que ja o protege.

**CASCADE em `message_id`**, que e PK e FK ao mesmo tempo (uma linha por
mensagem): a midia e da mensagem, entao mensagem apagada (retencao, direito
do titular) nao deixa midia orfa para apontar para lugar nenhum.

**`status` e `motivo` sao `String` livre, sem CHECK.** A 0037 (TEC-223) criou
CHECK para o vocabulario de `messages` porque DUAS guardas do sistema
comparam literal em SQL cru contra aquelas colunas (`sweep_stalled.py`, a
ancora do follow-up), e uma linha fora do vocabulario as burlaria em
silencio. Nenhuma leitura desta tabela compara literal cru -- `marcar`,
`pendentes_para_reenfileirar`, `expirar_pendentes` e `esgotar_pendentes`
filtram pelo enum Python --, e nenhuma tabela criada depois da 0037
(`tarefas_de_corretor.motivo`, `rate_limit_events.escopo`) ganhou CHECK so
por ser vocabulario novo. Repetir o CHECK aqui teria sido excecao, nao
padrao.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class StatusDaMidia(StrEnum):
    PENDENTE = "PENDENTE"
    ARMAZENADA = "ARMAZENADA"
    RECUSADA = "RECUSADA"
    FALHOU = "FALHOU"


class MotivoDaMidia(StrEnum):
    TIPO_NAO_PERMITIDO = "tipo_nao_permitido"
    ACIMA_DO_TETO = "acima_do_teto"
    SHA256_DIVERGENTE = "sha256_divergente"
    RECUSADA_PELA_META = "recusada_pela_meta"
    TENTATIVAS_ESGOTADAS = "tentativas_esgotadas"
    EXPIRADA = "expirada"


class MidiaRecebida(Base):
    __tablename__ = "midias_recebidas"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    media_id_da_meta: Mapped[str] = mapped_column(String(128), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chave_no_armazem: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # String(32), e nao o String(64) que a D2 da spec dizia antes (desvio
    # deliberado, registrado na propria D2): o maior literal de `MotivoDaMidia`
    # (`tentativas_esgotadas`) tem 20 caracteres, e `tarefas_de_corretor.motivo`
    # (0039) ja usa String(32) para o mesmo tipo de vocabulario curto.
    motivo: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Quantas vezes a varredura re-enfileirou esta linha -- o enfileiramento da
    # ingestao nao conta, e os `Retry` do ARQ dentro de um job tambem nao. E o
    # teto de `sweep_midias_pendentes` (`TETO_DE_REENFILEIRAMENTOS`) que le.
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Unico caminho de leitura por status (D2): a varredura de
        # `pendentes_para_reenfileirar`, `expirar_pendentes` e
        # `esgotar_pendentes`. Parcial porque so PENDENTE e varrida --
        # ARMAZENADA, RECUSADA e FALHOU sao terminais e nunca entram nesse
        # WHERE.
        Index(
            "ix_midias_recebidas_pendentes",
            "criado_em",
            postgresql_where=text("status = 'PENDENTE'"),
        ),
    )
