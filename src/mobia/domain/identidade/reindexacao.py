"""A reindexacao do lead: a mesma maquina para a migration e para a rotacao. TEC-203, D3.

Troca o `conversation_key` de cada par, em todas as tabelas, e arrasta junto o
que depende dele: identidade, remetente/destinatario das mensagens, evento de
rate limit, `lead_ref` da trilha, AAD do resumo e do vinculo.

Tres modos, e a diferenca entre eles e so DE ONDE vem o valor cru:

- `migracao` (0058, subida): o par que nao tem identidade ainda guarda o valor
  cru na coluna. O que ja tem identidade ja foi reindexado -- e a idempotencia
  que deixa retomar uma subida interrompida.
- `rotacao` (script, chave de indice nova): todo par tem identidade; o valor
  vem dela. Par sem identidade aqui e bug, e reprova.
- `reversao` (0058, descida): o valor vem da identidade e VIRA a chave; nada e
  gravado em `identidades_de_lead`, que a descida apaga em seguida. Par sem
  identidade tambem reprova: nao ha de onde tirar o valor cru.

**Tabelas imutaveis.** `lead_score_audit`, `conversation_intent_audit` e
`eventos_auditoria` recusam UPDATE por trigger. A reindexacao desliga a
trigger de cada uma, reescreve e religa, na mesma transacao. E excecao
declarada: trocar o pseudonimo do lead nao altera o fato registrado, e manter
o telefone em claro numa tabela imutavel seria a violacao que a TEC-203
existe para eliminar.

Sync, sobre `Connection`: a migration roda dentro do `run_sync` do Alembic, e
o script abre a mesma coisa com `engine.begin()` + `run_sync`.
"""

from collections.abc import Callable, Sequence
from typing import Literal

from sqlalchemy import Connection, text

from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.context.models import aad_do_resumo
from mobia.domain.identidade.models import aad_da_identidade, aad_do_vinculo
from mobia.infra.crypto import decrypt, encrypt

# Toda tabela com `conversation_key`. `tests/unit/test_tabelas_com_chave_de_lead.py`
# reprova se aparecer uma fora daqui -- a proxima tabela nao escapa da rotacao
# em silencio. A 0058 NAO usa esta lista: tem copia literal, porque migration
# aplicada nao muda quando o codigo muda.
TABELAS_COM_CHAVE_DE_LEAD = (
    "agendamentos",
    "atendimento_humano",
    "consentimentos",
    "conversas",
    "conversation_intent",
    "conversation_intent_audit",
    "conversation_summaries",
    "followups",
    "handoffs",
    "janelas_propostas",
    "lead_qualification",
    "lead_score_audit",
    "lista_de_espera",
    "messages",
    "moderation_events",
    "optout_events",
    "recomendacoes",
    "referencias_de_lead",
    "tarefas_de_corretor",
    "vinculos_de_sessao",
)

TRIGGERS_DE_IMUTABILIDADE = {
    "lead_score_audit": "lead_score_audit_imutavel",
    "conversation_intent_audit": "conversation_intent_audit_imutavel",
    "eventos_auditoria": "eventos_auditoria_imutavel",
}

Modo = Literal["migracao", "rotacao", "reversao"]


def _pares(conn: Connection, tabelas: Sequence[str]) -> list[tuple[str, str]]:
    uniao = " UNION ".join(
        f"SELECT channel, conversation_key FROM {tabela} WHERE conversation_key IS NOT NULL"
        for tabela in tabelas
    )
    return [(channel, chave) for channel, chave in conn.execute(text(uniao))]


def _identidade(conn: Connection, channel: str, chave: str) -> str | None:
    blob = conn.execute(
        text(
            "SELECT valor_cifrado FROM identidades_de_lead"
            " WHERE channel = :c AND conversation_key = :k"
        ),
        {"c": channel, "k": chave},
    ).scalar()
    return None if blob is None else decrypt(bytes(blob), aad_da_identidade(channel, chave))


def _triggers(conn: Connection, acao: Literal["DISABLE", "ENABLE"]) -> None:
    for tabela, trigger in TRIGGERS_DE_IMUTABILIDADE.items():
        conn.execute(text(f"ALTER TABLE {tabela} {acao} TRIGGER {trigger}"))


def reindexar(
    conn: Connection,
    *,
    tabelas: Sequence[str],
    nova_chave: Callable[[str, str], str],
    modo: Modo,
    chave_do_lead_antiga: str,
    chave_do_lead_nova: str,
) -> int:
    """Leva cada par a `nova_chave(channel, valor)`; devolve quantos pares mudaram.

    "Mudou" conta tambem o par cuja chave ficou, mas cujo `lead_ref` foi
    recalculado porque a chave do `lead_ref` trocou. Nao commita: quem chama e
    dono da transacao, e e ela que torna o desligar das triggers invisivel
    para qualquer outra conexao.
    """
    mudados = 0
    # Uma vez so, e nao por par: na subida da 0058 a coluna ainda nao existe
    # (nasce depois do loop), e na descida ja foi removida antes dele.
    vinculo_cifrado = _tem_coluna(conn, "vinculos_de_sessao", "telefone_cifrado")
    _triggers(conn, "DISABLE")
    try:
        for channel, atual in _pares(conn, tabelas):
            valor = _identidade(conn, channel, atual)
            if valor is None:
                if modo != "migracao":
                    raise RuntimeError(f"par do canal {channel} sem identidade no modo {modo}")
                valor = atual
            novo = nova_chave(channel, valor)
            if novo == atual and chave_do_lead_antiga == chave_do_lead_nova:
                continue
            _mover(conn, tabelas, channel, atual, novo, valor, modo, vinculo_cifrado)
            _recalcular_lead_ref(
                conn, channel, atual, novo, chave_do_lead_antiga, chave_do_lead_nova
            )
            mudados += 1
    finally:
        _triggers(conn, "ENABLE")
    return mudados


def _mover(
    conn: Connection,
    tabelas: Sequence[str],
    channel: str,
    atual: str,
    novo: str,
    valor: str,
    modo: Modo,
    vinculo_cifrado: bool,
) -> None:
    if novo == atual:
        return
    parametros = {"c": channel, "atual": atual, "novo": novo}
    # O resumo e o vinculo sao lidos com o AAD da chave velha antes de a linha
    # mudar de chave; depois do UPDATE, esse AAD ja nao se reconstroi da linha.
    resumo = conn.execute(
        text(
            "SELECT resumo FROM conversation_summaries"
            " WHERE channel = :c AND conversation_key = :atual"
        ),
        parametros,
    ).scalar()
    telefone_do_vinculo = (
        conn.execute(
            text(
                "SELECT telefone_cifrado FROM vinculos_de_sessao"
                " WHERE channel = :c AND conversation_key = :atual"
            ),
            parametros,
        ).scalar()
        if vinculo_cifrado
        else None
    )

    for tabela in tabelas:
        conn.execute(
            text(
                f"UPDATE {tabela} SET conversation_key = :novo"
                " WHERE channel = :c AND conversation_key = :atual"
            ),
            parametros,
        )
    # Remetente na entrada, destinatario na saida: e o lead nas duas pontas. A
    # outra ponta e o `phone_number_id` do canal, que nunca e igual a `atual`.
    for coluna in ("sender_external_id", "recipient_external_id"):
        conn.execute(
            text(
                f"UPDATE messages SET {coluna} = :novo "
                f"WHERE channel = :c AND conversation_key = :novo AND {coluna} = :atual"
            ),
            parametros,
        )
    conn.execute(
        text(
            "UPDATE rate_limit_events SET chave = :novo"
            " WHERE escopo = 'numero' AND channel = :c AND chave = :atual"
        ),
        parametros,
    )
    if resumo is not None:
        texto = decrypt(bytes(resumo), aad_do_resumo(channel, atual))
        conn.execute(
            text(
                "UPDATE conversation_summaries SET resumo = :r"
                " WHERE channel = :c AND conversation_key = :novo"
            ),
            {**parametros, "r": encrypt(texto, aad_do_resumo(channel, novo))},
        )
    if telefone_do_vinculo is not None:
        telefone = decrypt(bytes(telefone_do_vinculo), aad_do_vinculo(channel, atual))
        conn.execute(
            text(
                "UPDATE vinculos_de_sessao SET telefone_cifrado = :t"
                " WHERE channel = :c AND conversation_key = :novo"
            ),
            {**parametros, "t": encrypt(telefone, aad_do_vinculo(channel, novo))},
        )

    conn.execute(
        text("DELETE FROM identidades_de_lead WHERE channel = :c AND conversation_key = :atual"),
        parametros,
    )
    if modo != "reversao":
        conn.execute(
            text(
                "INSERT INTO identidades_de_lead (channel, conversation_key, valor_cifrado) "
                "VALUES (:c, :novo, :v) ON CONFLICT DO NOTHING"
            ),
            {**parametros, "v": encrypt(valor, aad_da_identidade(channel, novo))},
        )


def _recalcular_lead_ref(
    conn: Connection, channel: str, atual: str, novo: str, antiga: str, nova: str
) -> None:
    conn.execute(
        text("UPDATE eventos_auditoria SET lead_ref = :novo WHERE lead_ref = :antigo"),
        {
            "antigo": lead_ref(channel, atual, chave=antiga),
            "novo": lead_ref(channel, novo, chave=nova),
        },
    )


def _tem_coluna(conn: Connection, tabela: str, coluna: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_schema = current_schema()"
                " AND table_name = :t AND column_name = :c"
            ),
            {"t": tabela, "c": coluna},
        ).scalar()
    )


def reindexar_telefones_dos_vinculos(conn: Connection, indice: Callable[[str], str]) -> None:
    """Rotacao: o `telefone_indice` depende da chave de indice, e o par do
    vinculo nao muda por isso -- entao nao passa pelo loop de `reindexar`."""
    linhas = conn.execute(
        text("SELECT channel, conversation_key, telefone_cifrado FROM vinculos_de_sessao")
    ).all()
    for channel, chave, blob in linhas:
        telefone = decrypt(bytes(blob), aad_do_vinculo(channel, chave))
        assert telefone is not None
        conn.execute(
            text(
                "UPDATE vinculos_de_sessao SET telefone_indice = :i"
                " WHERE channel = :c AND conversation_key = :k"
            ),
            {"i": indice(telefone), "c": channel, "k": chave},
        )
