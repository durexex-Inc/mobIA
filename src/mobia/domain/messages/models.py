import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates


class Base(DeclarativeBase):
    pass


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Id externo do lead, invariante a direcao: e por ele que a conversa e
    # agrupada, porque sender e recipient se invertem entre entrada e saida.
    #
    # A TEC-138 criou `Conversa` (`domain/conversa/models.py`), mas com o MESMO
    # par como chave -- ela guarda SE a conversa esta encerrada, nao onde uma
    # sessao termina e a proxima comeca. As duas cards que ainda faltam sao
    # concerns diferentes: a TEC-130 encerra por inatividade (e estende aquela
    # entidade, ver a Emenda E-02 da RN-02.3) e a TEC-129 ligou o historico
    # multicanal SEM mexer nesta coluna -- a sessao web e o numero do WhatsApp
    # continuam pares distintos, e `vinculos_de_sessao`
    # (`domain/identidade/models.py`) e quem diz que um aponta para o outro.
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)

    content_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Cifrados com AES-GCM, AAD `{id}:{coluna}`. A cifra e explicita nos dois
    # escritores em vez de um TypeDecorator porque o bind do decorator nao
    # conhece o id da linha, e sem o id no AAD o ciphertext pode ser movido de
    # um lead para outro.
    text_body: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # NULL significa "nao participa do pipeline de ingestao" -- e o que a linha
    # de saida grava. Ver a docstring do sweeper.
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # NULL = a moderacao de entrada nao bloqueou esta fala. Preenchido = ela
    # bloqueou, e a linha nao pode entrar em contexto nem em resumo (TEC-236).
    #
    # **Marca em paralelo ao `status`, e nao um `MessageStatus` novo** -- a
    # card deixou a escolha ao implementador e esta e a decisao, registrada
    # aqui. Tres razoes:
    #
    #   - `status` responde "o pipeline de ingestao terminou com esta linha?".
    #     Um turno bloqueado **entregou** a recusa ao lead: ele terminou, e
    #     PROCESSED e a resposta certa. Um BLOCKED terminal contaria a mesma
    #     historia com outra palavra e faria "respondemos?" virar duas
    #     perguntas.
    #   - `CLAIMABLE_STATUSES` governa o que o sweeper reivindica. Um valor
    #     novo no enum obriga a revisar essa tupla e todo `status ==` do
    #     projeto para uma pergunta que nao e sobre retentativa.
    #   - As duas coisas podem coexistir e vao querer coexistir: uma fala
    #     bloqueada cuja recusa nao foi entregue e FAILED **e** bloqueada.
    #     Um campo so nao representa isso.
    #
    # Timestamp e nao booleano pelo mesmo motivo de `desambiguado_em`
    # (`agente/models.py`): ocupa o mesmo espaco e responde "quando" numa
    # investigacao.
    #
    # So a entrada escreve aqui. Bloqueio de saida nao grava linha nenhuma --
    # `_entregar_texto_fixo` registra o texto neutro que foi entregue, e nao a
    # fala recusada do modelo, que nunca existiu como linha.
    bloqueada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Contexto do envelope da Meta -- `change.value` sem o array `messages`.
    # Coluna reservada pelo TEC-217; nada escreve nela ainda.
    #
    # Cifrada em repouso desde o TEC-221, ANTES de existir escritor. O que o
    # TEC-217 vai gravar aqui carrega `contacts[].profile.name` e `wa_id` --
    # nome e telefone do lead --, e a premissa desta tabela desde o TEC-126 e
    # que conteudo pessoal nao fica em claro. Cifrar com a coluna vazia custou
    # uma migracao trivial; depois do escritor, custaria backfill.
    #
    # Mesma troca que o TEC-126 aceitou para `raw_payload`: deixa de ser
    # consultavel por operador JSONB. Quem precisar filtrar por dentro do
    # envelope tera de decifrar na aplicacao.
    envelope_context: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Instante da reivindicacao, para o lease de exclusao mutua entre workers.
    # Coluna reservada pelo TEC-218; nada escreve nela ainda.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @validates("text_body", "raw_payload", "envelope_context")
    def _exigir_bytes(self, coluna: str, valor: object) -> object:
        """Fecha por construcao o canal de vazamento pelo texto da excecao.

        `hide_parameters=True` cala o eco de parametros da propria SQLAlchemy,
        mas o asyncpg monta a mensagem de erro dele com o valor ofensivo dentro
        antes de a SQLAlchemy ver qualquer coisa. Ate a TEC-292 esse texto
        chegava ao log via `detail=str(exc)`; desde entao os quatro sitios de
        banco usam `motivo_do_erro_de_banco`, que extrai campos em vez de
        repassar texto.

        **O canal do structlog fechou; a guarda continua necessaria por outra
        razao.** Ate a TEC-293, `webhook.persist_failed` logava com
        `log.exception` e o traceback levava o texto do asyncpg para a chave
        `exception` independente do que `detail=` carregava. Desde ela o
        traceback leva pilha, cadeia e tipo, e nenhum dos quatro sitios repassa
        mensagem -- dentro do structlog.

        **Fora dele o vazamento continua.** `webhook.persist_failed` faz
        `raise` depois de logar, e a excecao que sobe escapa do nosso `except`
        e cai no uvicorn, que a loga de novo, crua e com a mensagem inteira,
        por fora deste pipeline. Isso nao enfraquece a guarda desta coluna --
        reforca: e mais um lugar por onde `Message(text_body="oi")` vazaria se
        a validacao nao barrasse o valor antes de ele virar excecao nenhuma.

        O que sustenta a guarda agora e a premissa da propria tabela, do
        TEC-126: conteudo pessoal nao fica em claro aqui. Escrever
        `Message(text_body="oi")` e o engano natural, e nenhuma decisao sobre
        log protege contra ele.

        Aqui a falha vira erro de aplicacao com mensagem que nos controlamos, e
        ela nunca cita o valor.
        """
        if valor is None or isinstance(valor, bytes | bytearray | memoryview):
            return valor
        raise TypeError(
            f"{coluna} recebeu {type(valor).__name__}: a coluna e bytea e o conteudo "
            "tem de vir cifrado por mobia.infra.crypto.encrypt"
        )

    __table_args__ = (
        Index("ix_messages_status_created_at", "status", "created_at"),
        # A consulta que TEC-127 faz a cada turno: as N mensagens mais recentes
        # de uma conversa, nas duas direcoes.
        Index(
            "ix_messages_timeline",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
        # Composta com `channel` de proposito: o widget web (TEC-124) tem espaco
        # de ids proprio e nao deve colidir com o wamid da Meta. O indice desta
        # constraint atende buscas pelo par e por `channel` sozinho, mas nao por
        # `provider_message_id` sozinho -- nenhuma consulta faz isso hoje, e quem
        # precisar deve criar o indice junto com a consulta.
        UniqueConstraint(
            "channel",
            "provider_message_id",
            name="uq_messages_channel_provider_message_id",
        ),
        # O vocabulario fechado, guardado no banco e nao so no enum (TEC-223).
        # `sweep_stalled.py` e a ancora de `followup/repositorio.py` filtram por
        # literal em SQL cru, entao uma linha gravada como `'inbound'` burla as
        # duas em silencio -- e seria varrida, devolvendo a fala do agente ao
        # `process_message`. Mesma forma de `ck_handoffs_status`. Os quatro
        # nomes e textos sao os da migration 0037, e o teste
        # `test_o_check_e_o_enum_dizem_a_mesma_coisa` amarra cada um ao enum.
        # Mas essa amarra le pg_constraint, ou seja, le a migration -- esta
        # copia aqui dentro do __table_args__ nao e verificada por teste
        # nenhum, porque as fixtures sobem o esquema por alembic upgrade e nao
        # por create_all. Quem editar aqui edita junto a migration mais recente
        # que escreve o CHECK -- a 0037 para os tres primeiros, a 0061
        # (TEC-209) para `status`.
        CheckConstraint(
            "role IN ('LEAD', 'AGENTE', 'CORRETOR', 'SISTEMA')",
            name="ck_messages_role",
        ),
        CheckConstraint(
            "direction IN ('INBOUND', 'OUTBOUND')",
            name="ck_messages_direction",
        ),
        CheckConstraint(
            "content_type IN ('TEXTO', 'AUDIO', 'IMAGEM', 'DOCUMENTO', 'DESCONHECIDO')",
            name="ck_messages_content_type",
        ),
        # NULL passa de proposito: e o que a linha de saida grava, e significa
        # "nao participa do pipeline de ingestao" -- ver o comentario de
        # `status` acima. O `IS NULL` e redundante (`IN` com NULL da UNKNOWN,
        # que nao viola CHECK) e esta aqui para dizer que e deliberado.
        CheckConstraint(
            "status IS NULL OR status IN "
            "('RECEIVED', 'QUEUED', 'PROCESSING', 'PROCESSED', 'FAILED', 'ESGOTADA')",
            name="ck_messages_status",
        ),
    )


class MessageTelemetry(Base):
    """Tokens, custo e latencia de uma resposta do agente.

    Fica ao lado e nao dentro de `messages` porque as duas tabelas respondem a
    perguntas diferentes: TEC-127 le a linha do tempo e nao quer saber de custo;
    o painel de custo soma dolares e nao deve tocar em conteudo de lead.
    """

    __tablename__ = "message_telemetry"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    subagent: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nullable porque o agente do TEC-134 ainda nao existe e nem todo turno usa
    # cache. As colunas nascem agora para que o dado seja capturado desde a
    # primeira linha: numero nao gravado nao se recupera depois, enquanto a
    # aritmetica e mudanca de configuracao. `custo_em_dolar` continua somando so
    # `tokens_in` e `tokens_out` de proposito -- precificacao ciente de cache
    # fica para a historia que liga o agente, que e quando existe forma de uso
    # real para tarifar em vez de chute.
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # NULL = modelo sem preco cadastrado. Gravar 0.00 somaria silenciosamente no
    # painel e faria o custo parecer menor do que foi; NULL aparece como lacuna.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
