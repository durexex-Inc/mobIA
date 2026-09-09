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

**Mas a revisao de codigo da mesma card fechou o que este paragrafo deixava
em aberto -- e a resposta nao precisava de `EXPLAIN ANALYZE`, so de
leitura.** Ha DOIS bloqueios estruturais independentes para o caminho ANN
do IVFFlat na unica consulta que existe sobre `embedding`, e qualquer um dos
dois ja basta sozinho.

Primeiro: o caminho rapido do IVFFlat so engata em
`ORDER BY <coluna> <=> <constante> LIMIT n`. `buscar()` ordena por um score
computado, `round(cast(0.6 * similaridade + 0.4 * aderencia, numeric), 3)`
(`src/mobia/domain/catalogo/busca.py:243-259`) -- ja nao e a forma que o
indice reconhece, sem precisar de plano nenhum para saber disso.

Segundo, e independente do primeiro: a lista de colunas do SELECT carrega
`func.count().over()` sem `PARTITION BY` (`busca.py:275`). Uma window
function sem particao forca o Postgres a materializar e agregar (`WindowAgg`)
o conjunto inteiro que sobrevive ao WHERE, ANTES do `Sort` e do `Limit` --
entao nao ha `LIMIT` nenhum para um scan ordenado por indice se aproveitar,
mesmo se o `ORDER BY` acima fosse a distancia de cosseno pura.

`grep -rn "cosine_distance\|<=>" src/` devolve exatamente um resultado: este
mesmo score, dentro de `buscar()`. `ix_imoveis_embedding` nao tem outro
consumidor no codigo.

**A consequencia e direta: hoje este indice e custo de escrita sem retorno
de leitura.** Toda insercao e atualizacao de `embedding` paga o custo de
manter o IVFFlat treinado, e a unica consulta que poderia usa-lo
estruturalmente nao consegue, por dois motivos que nao dependem de volume.
Isso nao e argumento contra o indice existir -- o paragrafo original desta
migration ja o justifica por conformidade com o SRS, nunca por ganho de
leitura -- mas e argumento contra ler o benchmark como validacao do indice:
`tests/perf/test_busca_latency.py` mede o piso de custo de uma varredura
sequencial, que e o que a consulta faz de qualquer jeito, com ou sem
`ix_imoveis_embedding` -- e o grupo "sem bairro" daquele benchmark e quem
mede esse piso sobre os 10.000 vetores inteiros; o grupo "com bairro" mede
um caminho mais barato, filtrado por `ix_imoveis_bairro_busca` antes de
chegar no vetor.

Revisitar o indice e o formato da consulta JUNTOS -- por exemplo a consulta
em dois estagios cogitada acima, que pre-filtra por ANN e reordena os
sobreviventes pelo score computado -- e trabalho de card propria, nao algo
que esta nota resolve.

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
