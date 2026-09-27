"""As versoes da configuracao do agente. TEC-198, D1 do desenho.

**Uma linha por alteracao, com a configuracao INTEIRA, e so de acrescimo.** A
vigente e a mais recente; sem linha nenhuma vale o padrao de `vigente.py`. O
historico que a card pede -- autor, valor anterior, valor novo, instante -- e
a comparacao de cada linha com a anterior, e nao uma segunda tabela de diffs
que pudesse divergir desta.

Os valores ficam em claro: nao sao dado pessoal, e o historico precisa deles.
A trilha de auditoria registra o mesmo evento sem os valores, pela regra da
TEC-206.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Index, Numeric, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.messages.models import Base


class VersaoDaConfiguracao(Base):
    __tablename__ = "configuracoes_do_agente"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    nome_do_assistente: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tom: Mapped[str] = mapped_column(String(16), nullable=False)
    teto_de_perguntas: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    peso_completude: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    peso_urgencia: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    peso_catalogo: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    peso_engajamento: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    peso_capacidade: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Em HORAS, por temperatura: {"QUENTE": [2, 24, 72, 168], ...}. Horas
    # inteiras e nao segundos: e a granularidade que a RN-13.1 escreve, e o
    # que a tela mostra.
    cadencia: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # TEC-191, D3. O orcamento MENSAL de IA, em dolares; nulo e "sem orcamento",
    # e sem orcamento o painel de custo nao acende alerta nenhum. Nulo nas
    # linhas anteriores a `0060`, que e o que elas de fato diziam.
    orcamento_mensal_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # TEC-344, D1. A aparencia do botao do chat web. Nao nulas: o botao sempre
    # tem cor e lado, e a `0064` preencheu as linhas antigas com o padrao.
    cor_primaria: Mapped[str] = mapped_column(String(7), nullable=False)
    posicao_do_botao: Mapped[str] = mapped_column(String(8), nullable=False)
    # TEC-345, D1. Os sites que podem embutir o chat; vazia, nenhum. A `0065`
    # preencheu as linhas antigas com a lista vazia.
    dominios_do_chat: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    autor: Mapped[str] = mapped_column(String(120), nullable=False)
    # `clock_timestamp()` e nao `now()`: duas edicoes na mesma transacao de
    # teste sairiam com o mesmo instante, e "a mais recente" deixaria de ser
    # uma so. Mesma razao de `lead_score_audit.created_at`.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (Index("ix_configuracoes_do_agente_criado_em", text("criado_em DESC")),)
