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
dependa dele hoje.** Quem cobra o SLA e a TEC-159; quem revisita `lists` e
a TEC-266, logo abaixo.

**Esta frase venceria por volta de 10.000 imoveis -- mas a receita que ela
dava para esse dia nao funciona, e a TEC-266 a retirou daqui.** A orientacao
do proprio pgvector e `lists ~= linhas / 1000`: em 10.000 linhas ela ja pede
`lists = 10`, e a lista unica passa a significar varredura sequencial de
10.000 vetores a cada consulta. Ate aqui o paragrafo original estava certo.
Dali ele concluia que `lists` precisava subir, com `REINDEX`, porque IVFFlat
treina na construcao do indice e nao na insercao.

**Nao suba.** Subir `lists` so ajuda quem consegue usar o indice, e a unica
consulta que existe sobre `embedding` nao consegue -- por dois bloqueios
estruturais que os paragrafos abaixo nomeiam e que nao dependem de volume.
Quem seguir a receita paga o `REINDEX`, perde recall e nao ganha latencia
nenhuma. A refutacao ja estava neste arquivo -- a nota da TEC-159, mais
abaixo, descreve os dois bloqueios -- e mesmo assim a receita sobreviveu,
porque quem le de cima para baixo encontrava a instrucao antes da refutacao
e nada aqui mandava nao segui-la. Agora manda, e
`tests/integration/test_migracao_vetorial.py::test_o_indice_continua_com_lists_1`
reprova se alguem subir `lists` sem antes mudar a forma da consulta.

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
-- o `score` montado dentro de `buscar()`
(`src/mobia/domain/catalogo/busca.py`) e aplicado no `.order_by` logo abaixo
dele -- ja nao e a forma que o indice reconhece, sem precisar de plano nenhum
para saber disso.

Segundo, e independente do primeiro: a lista de colunas do SELECT carrega
`func.count().over()` sem `PARTITION BY` -- o `total_candidatos` do mesmo
SELECT. Uma window function sem particao forca o Postgres a materializar e
agregar (`WindowAgg`)
o conjunto inteiro que sobrevive ao WHERE, ANTES do `Sort` e do `Limit` --
entao nao ha `LIMIT` nenhum para um scan ordenado por indice se aproveitar,
mesmo se o `ORDER BY` acima fosse a distancia de cosseno pura.

`grep -rn "cosine_distance\|<=>" src/` devolve uma mencao em comentario e
uma chamada no codigo de `buscar()` -- um site de consumo para o indice.
`ix_imoveis_embedding` nao tem outro consumidor no codigo.

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

**A card propria que esta nota pedia foi a TEC-266, e ela decidiu manter o
indice como esta.** Indice e forma da consulta foram revisitados juntos, e
das tres saidas nenhuma paga: a consulta em dois estagios cogitada acima
inverte a ordem que a RN-09.1 fixa (filtro estruturado ANTES da similaridade,
e filtro numerico nunca delegado ao embedding) e dropa toda linha com
`embedding IS NULL`, que e o candidato garantido por
`test_imovel_sem_embedding_ainda_e_candidato`; remover o indice contradiz o
SRS, que o nomeia no dicionario de dados e entre os indices criticos; e a
latencia que os dois estagios comprariam nao e precisa, porque a TEC-159
mediu p95 de 232.9 ms no pior caminho com 10.000 imoveis -- cinco vezes o
teto de 2.000 da PR-02 -- contra os 400 ms da RNF-03. O que a TEC-266 mudou
foi so o que enganava: a receita de subir `lists`, retirada acima.

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
