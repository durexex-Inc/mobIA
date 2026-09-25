"""preenche qualificado_em dos leads que qualificaram antes da 0040

TEC-367, RT-FE-02. A `0040` criou a coluna sem backfill e afirmou na propria
docstring que "o instante nunca foi gravado em lugar nenhum, entao nao ha de
onde o backfill sair". **Isso era falso**, e e o que esta migration conserta:
o instante esta em `lead_score_audit`, que existe desde a `0012` -- vinte e
oito revisoes ANTES da `0040`.

**A cadeia que torna a trilha uma fonte, e nao um palpite:**

- `qualificacao.py::esta_qualificado` e verdadeiro quando os quatro de
  `CAMPOS_OBRIGATORIOS` passam por `_preenchido` e nenhum esta recusado.
- `qualificacao.py::campos_obrigatorios_preenchidos` CONTA os mesmos quatro,
  com a mesma funcao e a mesma regra de recusa.
- `score.py::calcular_score` grava `completude = <aquela contagem> *
  PONTOS_POR_CAMPO_OBRIGATORIO`.
- `lead_score_audit` guarda esse valor por linha, com `created_at`, e e
  append-only.

Com quatro campos a cinco pontos, `completude = 20` e exatamente
`esta_qualificado`. O primeiro instante em que a trilha o registra e o
`MIN(created_at)` abaixo.

**O que se grava e o primeiro instante PROVADO, e nao o real.** Os dois
coincidem porque a RN-06.4 emendada manda gravar quando o resultado muda: a
passagem de tres para quatro campos move `completude` e produz a linha
(`CAUSA_CAMPOS_OBRIGATORIOS`); quem ja chega qualificado ganha a linha por
`CAUSA_PRIMEIRO_CALCULO`. Onde eles podem divergir esta na D2 do desenho.

**O 20 e copia literal, e nao import.** Mesma razao que a `0053` escreve por
extenso sobre os vocabularios da auditoria: migration aplicada nao muda
quando o codigo muda. O preco e uma segunda copia, e ela tem guarda --
`tests/unit/test_backfill_de_qualificacao.py` le este arquivo com `ast` e
confere contra `len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO`.

**`WHERE qualificado_em IS NULL`** pela disciplina de `carimbar_qualificacao`:
nao sobrescreve o que a aplicacao ja carimbou. E o que torna esta migration
idempotente.

**Resta um residuo, e ele tem prazo.** Lead que qualificou antes da `0012`
nao tem trilha e continua nulo. E a retencao de 12 meses da RNF-18
(`sweep_retencao_auditoria`) apaga a trilha antiga -- entao a janela em que
este backfill funciona nao e permanente.

Revision ID: 0055
Revises: 0054
"""

import sqlalchemy as sa

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

# `len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO` no instante desta
# migration: quatro campos a cinco pontos. Ver a docstring sobre por que e
# copia e nao import, e qual teste prende as duas.
COMPLETUDE_DE_QUALIFICADO = 20


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE lead_qualification AS lq
               SET qualificado_em = trilha.primeiro
              FROM (
                    SELECT channel,
                           conversation_key,
                           MIN(created_at) AS primeiro
                      FROM lead_score_audit
                     WHERE completude = :completude
                     GROUP BY channel, conversation_key
                   ) AS trilha
             WHERE lq.channel = trilha.channel
               AND lq.conversation_key = trilha.conversation_key
               AND lq.qualificado_em IS NULL
            """
        ).bindparams(completude=COMPLETUDE_DE_QUALIFICADO)
    )


def downgrade() -> None:
    """Nao desfaz, e a recusa e deliberada.

    A coluna nao distingue quem a preencheu: apagar os carimbos aqui levaria
    junto os que `carimbar_qualificacao` escreveu depois desta migration, e
    esses nao tem outra fonte -- a trilha so prova que o lead ESTAVA
    qualificado, nao reconstroi um carimbo que a aplicacao fez.

    Perder dado no downgrade seria pior que a inconsistencia que ele tentaria
    corrigir, e um downgrade que apaga o que nao criou nao e reversao.
    """
