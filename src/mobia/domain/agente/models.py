import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
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

    # Quantas mensagens FORA_DE_ESCOPO seguidas. RN-03.5, TEC-138.
    #
    # Mora aqui, e nao em `lead_qualification`, por um motivo mecanico: aquela
    # tabela NAO ganha linha em turno fora de escopo -- `campos_a_gravar`
    # devolve {} e `gravar_estado` retorna cedo com "Deliberadamente NAO cria
    # linha" --, entao um lead cujo historico inteiro e fora de escopo nunca
    # teria onde ser contado. Esta tabela e a unica escrita em TODO turno.
    #
    # Sobe ou zera em `gravar_intencao`, em DOIS lugares que tem de andar
    # juntos: o INSERT (a linha nasce, e a primeira mensagem de uma conversa
    # nova precisa nascer em 1 quando ela mesma e FORA_DE_ESCOPO) e o CASE do
    # `set_` do ON CONFLICT DO UPDATE (turnos seguintes da mesma conversa).
    # Nao e so o segundo: a primeira mensagem de uma conversa nunca passa por
    # um CONFLICT, e um contador que so soubesse dele gravaria 0 nela --
    # exatamente o bug que a TEC-138 mediu antes de duplicar a regra no
    # INSERT.
    #
    # **O encerramento zera este contador.** Sem isso o lead que volta depois
    # dos 30 dias iria de 3 para 4 e seria encerrado na primeira mensagem, sem
    # as tres tentativas que a regra lhe da.
    fora_de_escopo_seguidas: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Recomendacao(Base):
    """Um imovel apresentado a um lead, e o que ele fez com isso. RN-10.3.

    **Chaveada pelo par `(channel, conversation_key)`, e nao por `conversa_id`.**
    O SRS especifica uma FK para `Conversa`. A entidade existe desde a
    TEC-138 (`domain/conversa/models.py`), mas so para o ciclo de vida da
    conversa -- `conversation_summaries`, `lead_qualification` e
    `conversation_intent` (e esta tabela) continuam todas usando o par.
    Seguir o SRS aqui introduziria um SEGUNDO jeito de identificar conversa,
    que e pior que a divergencia. Ver a D2 e a emenda E-01 da RN-10.3.

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

    # TEC-275, D2. Quem apresentou esta linha. Sem isto, "a apresentacao desta
    # mensagem" nao e consultavel -- so inferivel pelo `apresentado_em` mais
    # recente da conversa, que e inferencia e nao fato. Nullable: linha
    # anterior a TEC-275 nao tem dono (L2 do desenho).
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    # TEC-275, D3. O unico dos dez campos de `Ficha` que NAO sai da linha de
    # `imoveis`: a linha tem `preco_venda` e `preco_aluguel` e nao diz qual foi
    # mostrado, porque a operacao so existe dentro de `porta_de_busca`. Guarda
    # o preco JA RESOLVIDO -- o numero que o lead viu --, que e o que uma
    # continuacao precisa reproduzir.
    #
    # Isto NAO e uma segunda copia do preco do imovel: e um fato historico
    # sobre o que foi apresentado, e continua certo depois de o preco do
    # imovel mudar.
    preco_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # TEC-275, D9. O kind com que esta linha saiu. NAO reconstrua pela posicao:
    # quando a linha de uma ficha recusada e apagada (D8), ou quando um imovel
    # some do catalogo (D7), as linhas restantes re-indexam e toda posicao
    # depois do buraco desloca -- a continuacao leria a reserva errada.
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "channel", "conversation_key", "imovel_id", name="uq_recomendacoes_conversa_imovel"
        ),
    )
