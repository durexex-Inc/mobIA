"""a coluna que diz se o resumo do handoff foi redigido ou montado

TEC-176, RN-15.4. Ver `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` secao 5,
que ja listava `resumo_fallback` no modelo Handoff -- esta migration
implementa o que a spec ja descrevia, nao inventa coluna nova.

**`resumo_fallback` nasce FALSO.** Verdadeiro faria todo handoff nascer
marcado como simplificado, e o painel mostraria a fila inteira como
degradada antes mesmo de a geracao rodar. "Ainda nao gerei" nao e
contingencia -- e o mesmo raciocinio de `aviso_manual_pendente` na
0026_notificacao_do_handoff.py, aplicado a coluna irma.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "handoffs",
        sa.Column(
            "resumo_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("handoffs", "resumo_fallback")
