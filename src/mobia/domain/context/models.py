import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, Numeric, String, func
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
    TEC-147, TEC-150 e TEC-158 consultam faixa de preco e regiao em SQL, e
    cifrar forcaria carregar a tabela inteira para filtrar em memoria. A cifra
    da TEC-126 protege o que o lead escreveu; isto e o que o sistema concluiu.
    """

    __tablename__ = "lead_qualification"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    intencao: Mapped[str | None] = mapped_column(String(16), nullable=True)
    faixa_preco_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    faixa_preco_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
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

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
