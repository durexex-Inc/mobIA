"""As duas tabelas do catalogo: o imovel e a trilha de importacao.

TEC-156. `Base` vem de `messages.models` -- e o unico `DeclarativeBase` deste
projeto, e um segundo faria o Alembic enxergar dois metadados.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class Imovel(Base):
    __tablename__ = "imoveis"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # A chave do upsert, e o que o corretor le e dita ao telefone. Unico por
    # restricao, e nao por convencao: a classificacao inserido/atualizado roda
    # em Python, fora de transacao unica, entao a exclusao mora aqui.
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)

    titulo: Mapped[str] = mapped_column(String(160), nullable=False)

    # Fonte do embedding na TEC-157. E por mudanca NESTE campo (e nos outros
    # textuais) que a RN-08.3 manda regerar; preco e status nao regeram.
    descricao: Mapped[str] = mapped_column(Text, nullable=False)

    tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    operacao: Mapped[str] = mapped_column(String(8), nullable=False)

    # Centavos, como todo dinheiro deste banco. O arquivo carrega reais e a
    # conversao acontece no parser; ver D6 do desenho.
    preco_venda: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    preco_aluguel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    condominio: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    iptu_mensal: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    bairro: Mapped[str] = mapped_column(String(120), nullable=False)
    # TEC-158, D5. O `bairro` dobrado -- caixa e acento --, e e contra ela que
    # a `regiao` do lead compara. DERIVADA de `bairro` e escrita a mao: quem
    # gravar `bairro` tem de gravar esta na mesma instrucao.
    #
    # Nao e `GENERATED ALWAYS AS ... STORED`, e a recusa e do Postgres e nao do
    # gosto: a expressao de coluna gerada tem de ser IMMUTABLE, e dobrar acento
    # em SQL exige `unaccent()`, que e STABLE. O preco declarado dessa
    # impossibilidade e que existe um caminho em que esta coluna fica velha --
    # o escritor novo que esqueca. Hoje ha um escritor (`repositorio.py`); o
    # CRUD da TEC-197 sera o segundo. A guarda e o
    # `test_o_upsert_mantem_a_dobra_do_bairro`.
    bairro_busca: Mapped[str] = mapped_column(Text, nullable=False)
    cidade: Mapped[str] = mapped_column(String(120), nullable=False)
    uf: Mapped[str] = mapped_column(String(2), nullable=False)
    zona: Mapped[str | None] = mapped_column(String(8), nullable=True)

    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    area_util_m2: Mapped[int] = mapped_column(Integer, nullable=False)
    quartos: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    suites: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    banheiros: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    vagas: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # Lista vazia, nunca NULL: o consumidor nao deve precisar distinguir "sem
    # caracteristicas" de "nao informado", e o parser ja normaliza para ().
    caracteristicas: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    fotos: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )

    status: Mapped[str] = mapped_column(String(12), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    # NAO e tocado quando a reimportacao nao muda nada. Bumpar o carimbo numa
    # linha inalterada faria a coluna mentir sobre quando o imovel mudou pela
    # ultima vez -- e e ela que um humano consulta para responder isso.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    # TEC-157. As tres juntas respondem "este vetor ainda vale?" sem que
    # nenhum caminho de escrita precise avisar que o texto mudou.
    #
    # `documento_hash` e o portao preciso: sha256 do documento que gerou o
    # vetor, com o modelo e a dimensao do provedor dentro do material
    # hasheado. Se ele difere do hash de hoje, o vetor esta velho -- e trocar
    # o modelo mantendo a dimensao conta como velho, senao o catalogo
    # guardaria vetores de dois espacos incompativeis sem sintoma nenhum.
    # `embedding_atualizado_em` e o pre-filtro barato para mudanca de TEXTO --
    # comparado contra `updated_at`, evita recalcular hash de linha que
    # ninguem tocou. `embedding_modelo` e o pre-filtro barato para mudanca de
    # CONFIGURACAO, e as duas coisas sao necessarias porque uma troca de
    # modelo no `Settings` nao toca linha nenhuma: sem esta coluna a linha ja
    # indexada nunca viraria candidata, o hash nunca seria recalculado, e o
    # catalogo guardaria vetores de dois espacos incompativeis sem sintoma.
    # O hash segue sendo o portao PRECISO das duas -- cobrir o modelo nos dois
    # lugares nao e redundancia a simplificar: sao os dois estagios do mesmo
    # desenho, barato em SQL e exato em Python.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_atualizado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    documento_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nulavel pelo mesmo motivo das outras tres (`0018`): linha indexada antes
    # da coluna existir entra como candidata, o hash bate, e a varredura so
    # carimba -- conciliacao sem backfill.
    embedding_modelo: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "preco_venda IS NOT NULL OR preco_aluguel IS NOT NULL",
            name="ck_imoveis_ao_menos_um_preco",
        ),
        UniqueConstraint("codigo", name="uq_imoveis_codigo"),
        Index("ix_imoveis_bairro", "bairro"),
        Index("ix_imoveis_cidade", "cidade"),
        Index("ix_imoveis_status", "status"),
        Index("ix_imoveis_bairro_busca", "bairro_busca"),
        # O composto que a secao de indices criticos do SRS nomeia para a
        # RN-09.1. Por conformidade, nao por medicao -- ver a `0019`.
        Index("ix_imoveis_filtro", "status", "tipo", "preco_venda", "quartos"),
    )


class Importacao(Base):
    """O relatorio duravel. E ele, e nao a tabela de imoveis, o produto da card.

    A historia pede "saber exatamente o que falhou, para corrigir as linhas
    ruins sem reimportar tudo as cegas": a tabela de imoveis nao guarda o que
    NAO entrou, e esta guarda.
    """

    __tablename__ = "importacoes"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    origem: Mapped[str] = mapped_column(String(8), nullable=False)
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)

    # Os bytes exatos que geraram este relatorio. Sem eles, "a linha 12 foi
    # rejeitada por X" nao e verificavel depois. Ver D9 do desenho.
    arquivo: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    status: Mapped[str] = mapped_column(String(12), nullable=False)

    processados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    inseridos: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    atualizados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # A emenda E-01 da RN-08.5. Sem esta coluna os quatro totais nao somam no
    # cenario 3 do Gherkin, e 490 linhas ficam sem categoria.
    inalterados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rejeitados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # JSONB e nao tabela filha: a lista so e lida inteira, junto com o resto do
    # relatorio. Nao ha consulta por motivo nem por linha que justifique o JOIN.
    erros: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    criada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
