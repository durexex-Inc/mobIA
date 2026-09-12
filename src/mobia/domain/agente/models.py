import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
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


class Recomendacao(Base):
    """Um imovel apresentado a um lead, e o que ele fez com isso. RN-10.3.

    **Chaveada pelo par `(channel, conversation_key)`, e nao por `conversa_id`.**
    O SRS especifica uma FK para `Conversa`, e `Conversa` nao e entidade neste
    sistema e nunca foi: `conversation_summaries`, `lead_qualification` e
    `conversation_intent` usam todas o par. Seguir o SRS aqui introduziria um
    SEGUNDO jeito de identificar conversa, que e pior que a divergencia. Ver a
    D2 e a emenda E-01 da RN-10.3.

    **O `UNIQUE` e o cenario 4 do Gherkin.** "Os ja apresentados nao sao
    repetidos" vira garantia de schema em vez de disciplina de consulta: o
    banco recusa a segunda insercao do mesmo imovel na mesma conversa.

    `reacao_lead` NULL significa "ainda nao reagiu", e e o gatilho da chamada
    de reacao (D8). `motivo_descarte` guarda a CATEGORIA (`CategoriaDescarte`),
    nao a frase do lead -- ver a D13.
    """

    __tablename__ = "recomendacoes"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    imovel_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("imoveis.id"), nullable=False
    )

    # A relevancia da RN-09.6, no tipo que a ficha da tabela do SRS escreve.
    score_match: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    # Derivado dos criterios da busca, nunca escrito pelo modelo (D5). E por
    # BUSCA e nao por imovel: os candidatos de uma mesma busca casaram o mesmo
    # filtro, e o que os distingue e o `score_match` (D4).
    motivo_match: Mapped[str] = mapped_column(Text, nullable=False)

    reacao_lead: Mapped[str | None] = mapped_column(String(16), nullable=True)
    motivo_descarte: Mapped[str | None] = mapped_column(String(80), nullable=True)

    apresentado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "channel", "conversation_key", "imovel_id", name="uq_recomendacoes_conversa_imovel"
        ),
    )
