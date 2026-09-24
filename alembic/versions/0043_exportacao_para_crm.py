"""o estado da exportacao para CRM, no proprio handoff

TEC-180, RN-16.5. Tres colunas em `handoffs` e nenhuma tabela nova: a "fila de
reprocessamento" da regra e a propria linha com `crm_sincronizado_em` nulo.
Guardar o payload exigiria gravar o resumo EM CLARO -- `handoffs.resumo` e
cifrado com AES-GCM e AAD amarrado ao id --, o que moveria PII para fora do
esquema de cifra. Ver a emenda E-01 a RN-16.5 e a D5 do desenho.

`crm_tentativas` existe porque sem contador a varredura nao distingue "nunca
tentei" de "tentei tres vezes e desisti", e reenfileira para sempre. E o mesmo
argumento que `workers/jobs/sweep_importacoes_travadas.py` escreve ao explicar
por que ela NAO reenfileira: `importacoes` nao tem a coluna equivalente.

Backfill nenhum, e a razao e que o default ja e a verdade: nenhum handoff
existente foi exportado para lugar nenhum, entao `crm_sincronizado_em` nulo e
`crm_tentativas` zero descrevem todos eles corretamente. Consequencia
declarada: assim que um webhook for configurado, a varredura vai encontrar
todo o historico como pendente e exporta-lo. E o comportamento desejado -- o
CRM quer os leads que ja existem --, mas quem ligar a integracao numa base
grande vai ver uma rajada, e isso precisa estar escrito em algum lugar.

Revision ID: 0043
Revises: 0042
"""

import sqlalchemy as sa

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "handoffs",
        # Nulo e "ainda nao entregue", NUNCA "entregue sem hora". E o unico
        # sinal de que o CRM tem este lead, e e por ele que o job sai cedo na
        # reentrega (D6 do desenho).
        sa.Column("crm_sincronizado_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "handoffs",
        # Zero e "nunca tentei". O teto de tres e da RN-16.5 e vive em codigo
        # (`domain/crm/port.py`), nao aqui: um CHECK com o numero obrigaria
        # migration para a varredura poder zerar o contador e dar uma rodada
        # nova, que e exatamente o que ela faz.
        sa.Column(
            "crm_tentativas",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "handoffs",
        # So o NOME DA CLASSE da excecao -- a regra que a TEC-222 fixou para
        # `messages.last_error`. A coluna e duravel, em claro e fora da
        # mascara de PII do log; a mensagem de uma excecao de `httpx` carrega
        # a URL, e a URL do webhook e segredo de configuracao. 80 basta para
        # qualquer nome de classe e nao convida ninguem a guardar prosa.
        sa.Column("crm_ultimo_erro", sa.String(80), nullable=True),
    )
    # O caminho unico da varredura: "quais handoffs ainda nao foram para o
    # CRM?". Parcial porque a resposta encolhe ate quase nada em regime --
    # todo handoff entregue sai do indice -- enquanto um indice cheio
    # cresceria com a tabela para sempre.
    op.create_index(
        "ix_handoffs_crm_pendente",
        "handoffs",
        ["criado_em"],
        postgresql_where=sa.text("crm_sincronizado_em IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_handoffs_crm_pendente", table_name="handoffs")
    op.drop_column("handoffs", "crm_ultimo_erro")
    op.drop_column("handoffs", "crm_tentativas")
    op.drop_column("handoffs", "crm_sincronizado_em")
