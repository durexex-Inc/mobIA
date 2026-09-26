"""O registro de consentimento, append-only. TEC-363, RN-FE-20.2.

Uma linha por evento, e o estado atual de uma pessoa e o ULTIMO evento por
`(channel, conversation_key)`. Nao e coluna booleana mutavel pelo mesmo motivo
que `optout_events` nao e: sobrescrever apaga a evidencia, e evidencia e o
produto aqui -- uma auditoria precisa ver que a pessoa recusou em marco e
aceitou em julho, nao so o estado de hoje.

**Onde a analogia com o opt-out SE INVERTE, e segui-la cegamente seria o
erro.** Aquele modulo deliberadamente NAO copia o texto que disparou o evento:
referencia `message_id`, porque o corpo ja esta cifrado em `messages` e
copia-lo criaria uma segunda copia em claro da fala do lead.

Aqui `texto_exibido` e NOSSO texto, nao o dela -- e o aviso de privacidade que
mostramos. Ele e precisamente a prova de a que a pessoa consentiu: sem ele o
registro diz "aceitou" sem dizer aceitou o que, e nao vale como evidencia.
Copiar e obrigatorio, e nao ha dado pessoal nisso.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class Consentimento(Base):
    __tablename__ = "consentimentos"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O mesmo par que identifica o lead em `optout_events` e
    # `lead_qualification`. No canal web, `conversation_key` e o HMAC da sessao
    # (TEC-203, `identidade/indice.py::chave_de`), e nao a sessao crua.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # **A recusa TAMBEM vira linha** (D3 do desenho). Sem ela, "nao
    # perguntamos" e "perguntamos e ela disse nao" ficam indistinguiveis, e sao
    # coisas muito diferentes numa auditoria. Quem quiser a pergunta de
    # produto usa `tem_consentimento_de_marketing`, e nao um SELECT na tabela.
    marketing: Mapped[bool] = mapped_column(Boolean, nullable=False)

    texto_exibido: Mapped[str] = mapped_column(Text, nullable=False)

    # Relogio do CLIENTE. Guardado porque mostra quanto tempo a pessoa levou
    # entre ver e responder, e porque denuncia skew -- mas um navegador com a
    # hora errada, ou um cliente forjado, escreve aqui o que quiser. A data
    # que responde "quando ela consentiu" e a de baixo.
    exibido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relogio do POSTGRES, e e esta a evidencia. Mesmo argumento que
    # `optout_events` ja faz: com o relogio de cada maquina escrevendo a
    # coluna, um skew inverte a ordem de dois eventos e o "ultimo" passa a ser
    # o errado.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # A consulta quente e "qual o ultimo evento desta pessoa?". DESC no
        # indice para o LIMIT 1 nao ordenar em memoria, mesmo formato do
        # `ix_optout_events_lead`.
        Index(
            "ix_consentimentos_lead",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
    )
