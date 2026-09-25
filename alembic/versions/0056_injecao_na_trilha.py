"""a trilha de auditoria aprende a tentativa de injecao

TEC-204, D6 e RNF-18. `INJECAO_DETECTADA` entra no CHECK de `acao` e
`mensagem` no de `entidade` de `eventos_auditoria`. E a primeira mudanca de
vocabulario da trilha desde que ela nasceu na 0053.

As tuplas abaixo sao, como as da 0053, COPIA literal dos enums de
`domain/auditoria/vocabulario.py`, e nao import: migration aplicada nao muda
quando o codigo muda. `tests/unit/test_auditoria_vocabulario.py` compara o
codigo com a migration mais recente que as redefine -- esta.

**O downgrade recria os CHECKs antigos como `NOT VALID`.** A trilha recusa
DELETE de linha com menos de 12 meses (trigger da 0053), entao um
`INJECAO_DETECTADA` ja gravado nao sai; um CHECK validado reprovaria o
downgrade por causa dele. `NOT VALID` vale para toda linha nova e deixa a
antiga onde esta.

Revision ID: 0056
Revises: 0055
"""

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

_ACOES = (
    "DADO_PESSOAL_ACESSADO",
    "QUALIFICACAO_ALTERADA",
    "HANDOFF_CRIADO",
    "OPTOUT_REGISTRADO",
    "OPTOUT_REATIVADO",
    "PROMPT_PUBLICADO",
    "ACESSO_NEGADO",
    "INJECAO_DETECTADA",
)
_ENTIDADES = (
    "handoff",
    "optout_event",
    "rota",
    "lead_qualification",
    "configuracao_agente",
    "mensagem",
)

_ACOES_ANTERIORES = _ACOES[:-1]
_ENTIDADES_ANTERIORES = _ENTIDADES[:-1]

_CHECKS = (
    ("ck_eventos_auditoria_acao", "acao"),
    ("ck_eventos_auditoria_entidade", "entidade"),
)


def _em(coluna: str, valores: tuple[str, ...]) -> str:
    literais = ", ".join("'" + valor + "'" for valor in valores)
    return f"{coluna} IN ({literais})"


def upgrade() -> None:
    for (nome, coluna), valores in zip(_CHECKS, (_ACOES, _ENTIDADES), strict=True):
        op.drop_constraint(nome, "eventos_auditoria", type_="check")
        op.create_check_constraint(nome, "eventos_auditoria", _em(coluna, valores))


def downgrade() -> None:
    for (nome, coluna), valores in zip(
        _CHECKS, (_ACOES_ANTERIORES, _ENTIDADES_ANTERIORES), strict=True
    ):
        op.drop_constraint(nome, "eventos_auditoria", type_="check")
        op.execute(
            f"ALTER TABLE eventos_auditoria ADD CONSTRAINT {nome} "
            f"CHECK ({_em(coluna, valores)}) NOT VALID"
        )
