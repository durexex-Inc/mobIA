"""Quem assumiu qual conversa, e ate quando o agente fica calado.

TEC-179, RN-16.4. Uma linha por conversa, e NAO um log append-only como
`optout_events` -- a D1 do desenho explica: o SRS especifica 409 "ja assumida
por outro", e com append-only responder isso exige ler antes de inserir. Duas
abas do painel clicando ao mesmo tempo gravariam dois eventos, ambos se
achando vencedores. O historico de todos os ciclos, que o append-only daria
de graca, nao fica em lugar nenhum: a trilha de auditoria da TEC-206 nao
registra assumir nem devolver.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.corretores.models import Corretor
from mobia.domain.messages.models import Base


class AtendimentoHumano(Base):
    __tablename__ = "atendimento_humano"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica a conversa, o mesmo de `optout_events` e
    # `handoffs`. Ate a TEC-138 nao existia entidade "conversa" neste sistema
    # -- era este par, espalhado por oito tabelas (D9 do desenho). A TEC-138
    # criou `Conversa` (`domain/conversa/models.py`), mas com o MESMO par
    # como chave primaria; esta tabela nao ganhou FK para ela e continua com
    # sua propria copia do par.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # `ForeignKey(Corretor.id)` em vez da string "corretores.id": o alvo
    # precisa estar no mesmo `MetaData` para o SQLAlchemy resolver a FK, e a
    # string so funciona se ALGUEM MAIS ja tiver importado `Corretor` antes.
    # Sem o import explicito acima, este teste de schema reprova com
    # `NoReferencedTableError` quando roda sozinho -- e "rodar o arquivo
    # sozinho" e o proprio procedimento de diagnostico do CLAUDE.md. Mesma
    # razao ja escrita em `handoff/models.py`.
    assumido_por: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey(Corretor.id), nullable=False
    )
    assumido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # **Nulos os dois sao o que significa "silenciada" -- nao ha coluna
    # `ativo`.** D4 do desenho: uma booleana ao lado destes carimbos seria uma
    # segunda representacao do mesmo fato, e as duas podem divergir. Esse e o
    # defeito que a revisao final da TEC-177 encontrou em
    # `notificado_em`/`aviso_manual_pendente` e que a D5 da TEC-176 preveniu.
    # Quem pergunta "esta silenciada?" pergunta `devolvido_em IS NULL`, e
    # `esta_silenciada` (repositorio.py) e a unica implementacao dessa frase.
    devolvido_por: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey(Corretor.id), nullable=True
    )
    devolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # E o arbitro da corrida, nao um indice de performance: o `ON
        # CONFLICT` de `assumir` (repositorio.py) casa por ele.
        UniqueConstraint("channel", "conversation_key", name="uq_atendimento_conversa"),
    )
