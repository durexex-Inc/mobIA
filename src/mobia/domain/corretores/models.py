"""O corretor: a pessoa para quem o handoff aponta.

TEC-196, RF-19 e RN-19.2. Ver `alembic/versions/0024_corretores.py` para o
porque do contato em claro, do UNIQUE no e-mail e da FK que esta migration
enfim acrescenta a `handoffs`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class Corretor(Base):
    __tablename__ = "corretores"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # **Em claro, e nao cifrado como a regra dos campos DP do SRS manda.** Ver
    # a emenda E-01 do modelo Corretor e a D1 do desenho. Em resumo: este repo
    # cifra CONTEUDO e nao IDENTIFICADOR -- o telefone do proprio lead esta em
    # claro em `messages.conversation_key` --, e cifrar aqui destruiria o
    # UNIQUE do e-mail logo abaixo, que e a unica defesa contra corretor
    # duplicado.
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False)
    telefone: Mapped[str] = mapped_column(String(20), nullable=False)

    # Registro profissional. Sem leitor hoje, e de proposito: quem o preenche
    # e o administrador no cadastro, entao ele tem escritor desde o primeiro
    # POST -- nao e a coluna sem escritor que a D1 da TEC-174 recusou.
    creci: Mapped[str | None] = mapped_column(String(20), nullable=True)

    especialidades: Mapped[list[str]] = mapped_column(ARRAY(String(28)), nullable=False)

    # Dobradas na escrita com `dobrar()`, a mesma funcao que produz
    # `bairro_busca` no catalogo -- sem isso "Zona Sul" e "zona sul" viram
    # duas regioes e a alocacao da TEC-166 falha por acidente de digitacao.
    regioes_atuacao: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False)

    # Uma janela, e nao `jsonb` por dia da semana. Ver a emenda E-02 do modelo
    # Corretor: e a forma que `app/config.py` ja usa, e a que o criterio de
    # aceite exercita. Sabado meio periodo nao cabe, e isso esta declarado.
    horario_inicio: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    horario_fim: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    capacidade_diaria: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # O generalista que recebe o que nao tem match. **Pode haver mais de um**,
    # e escolher entre eles e a TEC-166 -- ver a D7. Um indice parcial
    # forcando um so inventaria regra que a card nao escreveu e quebraria
    # plantao por turno.
    plantao: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    # Desativar e isto, e nao apagar a linha: a FK de `handoffs` a referencia,
    # e o historico tem de sobreviver (D6).
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("email", name="uq_corretores_email"),
        CheckConstraint(
            "horario_inicio >= 0 AND horario_fim <= 23 AND horario_inicio < horario_fim",
            name="ck_corretores_jornada",
        ),
        CheckConstraint("capacidade_diaria >= 1", name="ck_corretores_capacidade"),
        # Guarda o vocabulario no banco, como `ck_handoffs_status` faz para o
        # status. `<@` testa continencia de array em Postgres; a cardinalidade
        # recusa o corretor sem especialidade nenhuma, que nao seria alocavel.
        CheckConstraint(
            "cardinality(especialidades) > 0 AND especialidades <@ ARRAY["
            "'COMPRA','ALUGUEL','INVESTIMENTO','INVESTIMENTO_ALTO_TICKET']::varchar[]",
            name="ck_corretores_especialidades",
        ),
        CheckConstraint("cardinality(regioes_atuacao) > 0", name="ck_corretores_regioes"),
    )
