"""a referencia opaca ao lead, e o `lead` no vocabulario da trilha

TEC-195, RN-18.5, RT-08.

**Por que esta tabela existe, que e o que nao se le do DDL.** O lead deste
sistema e o par `(channel, conversation_key)`, e no WhatsApp a
`conversation_key` E o telefone dele. Entao o identificador do lead e o dado
pessoal do lead, e `GET /api/v1/leads` devolvia esse par em claro -- no item e
no cursor -- para todo papel com `VER_LEADS`, inclusive os que nao tem
`VER_DADOS_COMPLETOS`.

Mascarar o telefone e deixar o par sair ao lado dele seria teatro. Entao o par
para de sair, e esta tabela da a API outra coisa para devolver: um apelido
estavel, sem atributo proprio, que nao diz nada sobre quem o lead e.

**Nao e a entidade `lead` que a TEC-192 recusou.** A D2 daquela card decidiu
que "nao existe `leadId`" porque nao ha tabela de lead, nao ha dono e inventar
uma faria o sistema afirmar uma identidade que ele nao apura. Isto nao afirma
identidade nenhuma: e uma referencia ao par, no mesmo espirito do `lead_ref`
que a trilha ja guarda. A diferenca para aquele e que este precisa ser
REVERSIVEL, porque a revelacao tem de voltar ao par -- por isso uma linha, e
nao um HMAC.

**Por que nao cifrar o par em vez de guardar linha.** `infra/crypto.py` usa
`os.urandom` no nonce, entao o blob muda a cada chamada. Identificador que
muda a cada chamada nao e endereco: nao sobrevive a um F5 nem vira URL.

**O CHECK da trilha e recriado aqui**, e nao estendido: o Postgres nao estende
CHECK. O vocabulario abaixo e COPIA literal do enum de
`domain/auditoria/vocabulario.py`, pela mesma razao que a 0053 escreve por
extenso -- migration aplicada nao muda quando o codigo muda --, e
`tests/unit/test_auditoria_vocabulario.py` prende as duas copias.

Revision ID: 0056
Revises: 0055
"""

import sqlalchemy as sa

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

# Copia literal de `Entidade`, com `lead` acrescentado pela TEC-195.
_ENTIDADES = (
    "handoff",
    "optout_event",
    "rota",
    "lead_qualification",
    "configuracao_agente",
    "lead",
)

_CHECK_DA_ENTIDADE = "ck_eventos_auditoria_entidade"


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    op.create_table(
        "referencias_de_lead",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("conversation_key", sa.String(64), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        # O UNIQUE e o que torna o `get-or-create` seguro sob concorrencia:
        # duas requisicoes simultaneas para o mesmo lead nao podem produzir
        # dois apelidos, senao o mesmo lead teria dois enderecos e a trilha
        # registraria os dois como entidades diferentes.
        sa.UniqueConstraint("channel", "conversation_key", name="uq_referencias_de_lead_conversa"),
    )

    op.drop_constraint(_CHECK_DA_ENTIDADE, "eventos_auditoria", type_="check")
    op.create_check_constraint(_CHECK_DA_ENTIDADE, "eventos_auditoria", _em("entidade", _ENTIDADES))


def downgrade() -> None:
    # A ordem inversa da subida, e o CHECK volta SEM `lead`. Linha de auditoria
    # com `entidade = 'lead'` faz este downgrade reprovar, e e o comportamento
    # certo: apagar a trilha para caber num CHECK antigo seria destruir o
    # registro que ela existe para guardar.
    op.drop_constraint(_CHECK_DA_ENTIDADE, "eventos_auditoria", type_="check")
    op.create_check_constraint(
        _CHECK_DA_ENTIDADE, "eventos_auditoria", _em("entidade", _ENTIDADES[:-1])
    )
    op.drop_table("referencias_de_lead")
