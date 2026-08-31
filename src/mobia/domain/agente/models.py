from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class ConversationIntent(Base):
    """Intencao corrente da conversa, com a confianca que a produziu.

    Fica em tabela propria e nao em `lead_qualification`, apesar de aquela ja
    ter uma coluna `intencao`: a TEC-127 registrou que a dona de
    lead_qualification e a TEC-145, e confianca e artefato do classificador,
    nao criterio de qualificacao -- nao faz sentido ao lado de quartos e vagas.
    """

    __tablename__ = "conversation_intent"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # O palpite cru do classificador, mesmo quando a confianca nao o sustenta.
    # **Nao roteie por esta coluna**: use `IntencaoDaConversa.efetiva`, que
    # devolve INDEFINIDA abaixo do limiar. O valor cru fica aqui porque e dele
    # que a TEC-210 precisa para calibrar o limiar.
    intencao: Mapped[str] = mapped_column(String(20), nullable=False)

    # Autoavaliacao do modelo, nao probabilidade calibrada -- isso continua
    # verdade e nao muda. O que mudou: o limiar de 0,6 deixou de ser
    # provisorio. A TEC-210 construiu a regua, a TEC-235 mediu o custo e o
    # beneficio do rebaixamento em seis execucoes e a decisao de manter 0,6
    # esta registrada no comentario de `LIMIAR_DE_DESAMBIGUACAO`
    # (`schemas.py`), com os numeros. Nao existe um segundo limiar: o `0,8`
    # que esta linha citava nunca governou decisao nenhuma.
    confianca: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    modelo: Mapped[str] = mapped_column(String(64), nullable=False)

    # NULL = nenhum episodio de ambiguidade em aberto. Preenchido = a pergunta
    # de desambiguacao ja foi feita e entregue neste episodio, e nao se
    # pergunta de novo. Uma classificacao com confianca >=
    # LIMIAR_DE_DESAMBIGUACAO limpa o marcador -- e a evidencia de que a
    # ambiguidade anterior foi resolvida.
    #
    # Timestamp e nao booleano porque ocupa o mesmo espaco e responde "quando"
    # numa investigacao, igual ao `updated_at` logo abaixo.
    desambiguado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
