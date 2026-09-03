import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from mobia.domain.messages.models import Base
from mobia.infra.crypto import aad_de


def aad_do_resumo(channel: str, conversation_key: str) -> str:
    """Amarra o resumo a sua propria conversa.

    Nao ha `message_id` aqui -- o resumo cobre muitas mensagens -- entao a
    identidade da linha e o par (channel, conversation_key). Prefixado por
    tamanho porque `channel` e `String(32)` sem whitelist de caracteres: sem o
    prefixo, `("a:b", "c")` e `("a", "b:c")` colapsariam no mesmo AAD e um
    resumo poderia decifrar sob a chave de outra conversa. Com o tamanho na
    frente de cada parte, o ponto onde ela termina deixa de depender do
    conteudo, entao dois pares diferentes nunca produzem a mesma string.
    """
    identidade = f"{len(channel)}:{channel}:{len(conversation_key)}:{conversation_key}"
    return aad_de(identidade, "resumo")


class ConversationSummary(Base):
    """Resumo do que veio antes da marca d'agua.

    Uma linha por conversa: e estado corrente, nao historico. A marca e um par
    ordenavel `(created_at, id)` e nao uma contagem, porque contagem quebra
    quando uma linha e apagada ou quando duas mensagens chegam fora de ordem.
    """

    __tablename__ = "conversation_summaries"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Cifrado com AES-GCM, AAD de `aad_do_resumo` (formato em detalhe la). Um
    # resumo destila as mesmas frases que `messages.text_body` guarda --
    # deixa-lo em claro ao lado de uma coluna cifrada seria manter a
    # fechadura e tirar a porta.
    resumo: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    watermark_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    watermark_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mensagens_cobertas: Mapped[int] = mapped_column(Integer, nullable=False)
    modelo: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @validates("resumo")
    def _recusar_texto_claro(self, coluna: str, valor: object) -> object:
        """Mesma guarda de `Message`: str aqui vira vazamento no texto do erro.

        O driver embute o argumento recusado na propria mensagem de excecao,
        antes de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log.
        """
        if valor is not None and not isinstance(valor, bytes | bytearray | memoryview):
            raise TypeError(
                f"{coluna} aceita apenas bytes cifrados, recebeu {type(valor).__name__}"
            )
        return valor


class LeadQualification(Base):
    """Estado estruturado de qualificacao. Esta historia le; TEC-145 escreve.

    Fica **em claro**, ao contrario do resumo, e a assimetria e deliberada:
    TEC-150 e TEC-158 consultam faixa de preco e regiao em SQL, e cifrar
    forcaria carregar a tabela inteira para filtrar em memoria. A cifra da
    TEC-126 protege o que o lead escreveu; isto e o que o sistema concluiu.

    A TEC-147 **nao** consulta: `esta_qualificado` e funcao pura sobre a linha
    ja carregada, e nao ha consulta que filtre por qualificado (e uma lacuna
    declarada no desenho dela). Ela estava nesta lista por engano.
    """

    __tablename__ = "lead_qualification"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    intencao: Mapped[str | None] = mapped_column(String(16), nullable=True)
    faixa_preco_min_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    faixa_preco_max_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    regiao: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tipo_imovel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quartos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vagas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urgencia: Mapped[str | None] = mapped_column(String(32), nullable=True)
    forma_pagamento: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tem_imovel_para_vender: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # TEC-257. Os campos que o agente perguntou e o lead nao respondeu.
    #
    # `NULL` e `{}` nao sao sinonimos: `NULL` e "linha anterior a esta card,
    # ninguem marcava", `{}` e "marcava, e nao havia nada". Quem le tem de
    # tratar os dois iguais **na leitura** (`or ()`), e nunca gravar `NULL`
    # querendo dizer vazio.
    #
    # Em claro, como o resto desta tabela: e o que o sistema concluiu, nao o
    # que o lead escreveu.
    perguntados_sem_resposta: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(32)), nullable=True
    )

    # TEC-148, RN-05.7. Os campos que o lead se negou a informar.
    #
    # O nome vem do modelo de dados do SRS (`campos_recusados text[]`), e nao
    # de `recusados`, que e o nome do PARAMETRO que `esta_qualificado` expoe
    # desde a TEC-147. Coluna e parametro nao precisam coincidir.
    #
    # Coluna propria e nao reuso de `perguntados_sem_resposta`: silencio e
    # recusa sao fatos diferentes. Silencio e "pode ser que ele responda
    # depois"; recusa e "ele disse que nao". Colapsa-los tornaria
    # inqualificavel para sempre todo lead que apenas ainda nao respondeu.
    #
    # `NULL` e `{}` nao sao sinonimos, como na coluna vizinha: `NULL` e
    # "linha anterior a esta card, ninguem registrava", `{}` e "registrava, e
    # nao havia recusa". Quem le trata os dois iguais (`or ()`), e nunca grava
    # `NULL` querendo dizer vazio.
    #
    # Em claro, como o resto desta tabela: e o que o sistema concluiu, nao o
    # que o lead escreveu.
    campos_recusados: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LeadScoreAudit(Base):
    """Um registro por recalculo que mudou o score. Append-only e imutavel.

    TEC-152, RN-06.4. Mesmo molde de `optout_events`: uma linha por evento,
    carimbo pelo relogio do servidor, e sem FK para `messages` nem para
    `lead_qualification` -- a retencao da trilha (12 meses, RNF-18) nao pode
    ser encurtada por cascata da limpeza de outra tabela.

    **So os fatores do score NOVO sao gravados.** Como o registro so entra
    quando o resultado muda, o registro anterior da mesma conversa **e** o
    score anterior; guardar os dois criaria duas fontes para o mesmo fato, que
    e o defeito que a TEC-146 gastou uma card inteira consertando.
    `total_anterior` fica mesmo assim porque e o que a card nomeia e poupa a
    segunda leitura de quem so quer o delta.
    """

    __tablename__ = "lead_score_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # Nulo no primeiro registro do lead, e nao zero. O `score.py` ja faz essa
    # distincao: "o zero e a ausencia de sujeito, nao uma nota sobre ele". Um
    # lead cujo primeiro calculo deu 51 nunca teve score 0, e dizer que teve
    # inventaria uma subida de 51 pontos que nao aconteceu.
    total_anterior: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_novo: Mapped[int] = mapped_column(Integer, nullable=False)

    completude: Mapped[int] = mapped_column(Integer, nullable=False)
    urgencia: Mapped[int] = mapped_column(Integer, nullable=False)
    catalogo: Mapped[int] = mapped_column(Integer, nullable=False)
    engajamento: Mapped[int] = mapped_column(Integer, nullable=False)
    capacidade: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nunca NULL e nunca vazio: tupla vazia e o sinal de nao gravar, entao uma
    # linha sem causa nao deveria ter chegado ao INSERT. O vocabulario mora em
    # `context/auditoria.py`.
    causas: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)

    # So na edicao manual pelo dashboard (TEC-192), que ainda nao existe --
    # hoje e sempre nulo. Mesma forma de `optout_events.autor`, nulo no
    # opt-out pela mesma razao: o ato e do lead, nao de um humano nosso.
    autor: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # `server_default` e nao valor vindo do cliente, pela razao do
    # `optout_events`: `registrar_recalculo` le `ORDER BY created_at DESC LIMIT
    # 1` sem desempate, e com o relogio de cada worker escrevendo a coluna um
    # skew entre duas maquinas inverteria dois registros do mesmo lead.
    #
    # E `clock_timestamp()` e nao `now()`: `now()` e
    # `transaction_timestamp()`, congelado no PRIMEIRO statement da transacao,
    # e este INSERT acontece no fim de um turno longo -- varios statements
    # depois dele. Dois turnos concorrentes da mesma conversa seriam entao
    # ordenados por quando COMECARAM, e nao por quando gravaram, invertendo a
    # trilha em relacao a ordem que o `SELECT ... FOR UPDATE` de
    # `registrar_recalculo` serializa. Como o INSERT ocorre com aquele lock na
    # mao, `clock_timestamp()` produz uma ordem total igual a ordem do lock.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        # A consulta quente e "qual o ultimo registro deste lead?", uma vez por
        # turno. DESC no indice para o LIMIT 1 nao ordenar em memoria. Mesmo
        # formato do `ix_optout_events_lead` e do `ix_messages_timeline`.
        Index(
            "ix_lead_score_audit_lead",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
    )
