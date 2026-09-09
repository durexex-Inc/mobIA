"""a indexacao vetorial do catalogo

TEC-157, RN-08.2 e RN-08.3. Fecha a divida que a `0016` declarou: ela deixou
`embedding` de fora porque a imagem do compose nao tinha pgvector, e a troca
de imagem pertence a esta card.

**O indice IVFFlat entra com `lists = 1`, e isso e deliberado.** IVFFlat e um
indice treinado: `lists` particiona o espaco, e a busca varre apenas as
particoes mais proximas. Com 520 a 2.000 imoveis, `lists = 100` colocaria ~5
vetores por particao e o recall despencaria; `lists = 1` degenera para
varredura da lista unica -- recall perfeito, custo de scan sequencial, que
nesta escala resolve em milissegundos e fica muito abaixo dos 400 ms da
RNF-03. **O indice esta aqui por conformidade com o SRS, nao porque a busca
dependa dele hoje.** Quem revisita `lists`, cobra o SLA ou migra para HNSW e
a TEC-159.

**Esta frase vence por volta de 10.000 imoveis, e o numero esta escrito aqui
para que ninguem a leia como atemporal.** A orientacao do proprio pgvector e
`lists ~= linhas / 1000`: em 10.000 linhas ela ja pede `lists = 10`, e a lista
unica passa a significar varredura sequencial de 10.000 vetores a cada
consulta. Quem ler isto com 40.000 imoveis no catalogo esta lendo um
argumento que ja expirou -- `lists` precisa subir, e com `REINDEX`, porque
IVFFlat treina na construcao do indice e nao na insercao.

**Medido pela TEC-159 em 2026-09-09:** com 10.000 imoveis e `lists = 1`, o
p95 da busca ficou em 144.9 ms contra o teto de 400 ms da RNF-03 -- cerca de
2.8x de margem (p50=68.9 ms, p99=255.8 ms). A estimativa acima foi
conservadora na direcao: a lista unica ainda resolve neste volume, e com
folga, nao no limite.

**Mas a revisao de codigo da mesma card achou algo que muda o que fazer a
seguir, e que a frase acima nao previa.** O `ORDER BY` de `buscar()` ordena
por um score computado, `0.6 * similaridade + 0.4 * aderencia`
(`src/mobia/domain/catalogo/busca.py:243-250,279`), e nao pela distancia de
cosseno pura. O caminho rapido do IVFFlat so engata em
`ORDER BY <distancia> LIMIT n`; com o score computado no meio, o planner
provavelmente calcula a distancia de cosseno para cada linha que sobrevive
ao WHERE e so depois ordena. Isso nao invalida a medicao acima -- este
paragrafo ja dizia que `lists = 1` degenera para varredura sequencial, entao
o piso de custo e o mesmo com ou sem o indice, e o benchmark mede fielmente
se esse caminho de custo pleno cabe no orcamento -- mas poe em duvida a
prescricao do paragrafo anterior: se o caminho ANN nunca engata por causa do
`ORDER BY` computado, subir `lists` sozinho pode nao ajudar em volume
nenhum, e o remedio de verdade, quando o catalogo crescer, seria diferente
em tipo -- por exemplo uma consulta em dois estagios, que usa o indice so
para um pre-filtro ANN e reordena os sobreviventes pelo score computado.

Isto fica registrado como pergunta aberta, nao como conclusao: o que
resolveria e instrumentar o plano de execucao (`EXPLAIN ANALYZE`) da consulta
de `buscar()` e ver se o indice aparece. `tests/perf/test_busca_latency.py` e
o comando que responde a pergunta de orcamento de novo, no proximo volume que
preocupar.

As tres colunas sao nulaveis porque hash nulo E a definicao de pendencia: e
o que faz o catalogo ja importado entrar na fila sem caminho de backfill.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

DIMENSOES = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("imoveis", sa.Column("embedding", Vector(DIMENSOES), nullable=True))
    op.add_column(
        "imoveis",
        sa.Column("embedding_atualizado_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("imoveis", sa.Column("documento_hash", sa.Text(), nullable=True))

    op.execute(
        "CREATE INDEX ix_imoveis_embedding ON imoveis "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 1)"
    )


def downgrade() -> None:
    op.drop_index("ix_imoveis_embedding", table_name="imoveis")
    op.drop_column("imoveis", "documento_hash")
    op.drop_column("imoveis", "embedding_atualizado_em")
    op.drop_column("imoveis", "embedding")
    # A extensao NAO cai no downgrade: outra coisa pode ter passado a
    # depender dela, e `DROP EXTENSION` derrubaria em cascata.
