"""Anonimizar o lead: trocar o par por um pseudonimo sem volta. TEC-207, D1.

**O pseudonimo e aleatorio** (`secrets.token_hex(32)`, 64 hex, o tamanho do
`String(64)` de sempre) e nao e derivado de nada -- e isso que o separa do
HMAC da TEC-203, que tem volta pela identidade e pela chave de indice. Aqui
nenhuma identidade nova e gravada: a do par antigo e apagada, e nada liga o
pseudonimo ao telefone.

**A trilha de auditoria nao e tocada.** O `lead_ref` antigo continua em
`eventos_auditoria` e deixa de bater com o par, que agora e aleatorio -- e o
que `auditoria/referencia.py::lead_ref` promete ("sobrevive a eliminacao").
Por isso so as triggers de `lead_score_audit` e `conversation_intent_audit`
sao desligadas, e nao a de `eventos_auditoria`.

**O que fica, e por que.** Eliminar nao e apagar linhas: as metricas contam
linhas, nao conteudo. A coorte do funil nasce em `min(messages.created_at)`
(`metricas/repositorio.py::_nascimento`), entao as mensagens ficam, sem
`text_body`, `raw_payload` e `envelope_context`; o custo historico mora em
`message_telemetry`, que cai em cascata se a mensagem cair. Qualificacao,
handoffs, agendamentos, recomendacoes, consentimentos e as trilhas de score e
intencao ficam sob o pseudonimo -- sem conteudo que identifique, exceto o
`resumo` do handoff, derivado da transcricao, que vira nulo.

**O que sai.** Identidade, vinculo de sessao (o telefone digitado no widget),
resumo da conversa, apelido de `referencias_de_lead` (o `leadId` do painel
passa a dar 404) e a linha de `midias_recebidas`. O arquivo de midia em si
esta fora do banco: a funcao devolve as chaves, e quem chama apaga depois do
commit -- apagar antes deixaria um rollback com linha apontando para blob
que nao existe.

**Toda solicitacao ABERTA do par e fechada como ATENDIDA**, nao so a que
disparou a anonimizacao: depois dela nao ha dado a entregar num pedido de
acesso, e `solicitacoes_de_titular` esta em `TABELAS_COM_CHAVE_DE_LEAD` --
uma ABERTA seria arrastada para o pseudonimo pela troca de chave, e a fila
mostraria um pedido que ninguem mais consegue atender.

Sync, sobre `Connection`, como a reindexacao: serve o job da eliminacao a
pedido (`titular/eliminacao.py`) e o sweep de retencao, e nao commita.
"""

import secrets

from sqlalchemy import Connection, text

from mobia.domain.identidade.reindexacao import (
    TABELAS_COM_CHAVE_DE_LEAD,
    desligar_triggers,
    mover_referencias_fora_da_chave,
    religar_triggers,
)

# As tabelas imutaveis que a troca de chave reescreve. `eventos_auditoria`
# fica de fora: a trilha nao e tocada (ver a docstring do modulo).
TABELAS_IMUTAVEIS_REESCRITAS = ("lead_score_audit", "conversation_intent_audit")

# O que identifica ou e conteudo, e nao tem valor para metrica nenhuma.
TABELAS_APAGADAS = (
    "conversation_summaries",
    "vinculos_de_sessao",
    "identidades_de_lead",
    "referencias_de_lead",
)


def anonimizar_lead(conn: Connection, *, channel: str, conversation_key: str) -> list[str]:
    """Troca o par por um pseudonimo aleatorio; devolve as chaves de midia.

    As chaves (`midias_recebidas.chave_no_armazem`) sao do armazem, fora do
    banco: quem chama as apaga depois do commit. **Nao commita** -- o
    desligar das triggers so e invisivel para as outras conexoes porque
    acontece dentro da transacao de quem chama.
    """
    novo = secrets.token_hex(32)
    par = {"c": channel, "k": conversation_key, "novo": novo}

    chaves_de_midia: list[str] = list(
        conn.execute(
            text(
                "SELECT mr.chave_no_armazem FROM midias_recebidas mr"
                " JOIN messages m ON m.id = mr.message_id"
                " WHERE m.channel = :c AND m.conversation_key = :k"
                " AND mr.chave_no_armazem IS NOT NULL"
            ),
            par,
        ).scalars()
    )
    conn.execute(
        text(
            "DELETE FROM midias_recebidas WHERE message_id IN"
            " (SELECT id FROM messages WHERE channel = :c AND conversation_key = :k)"
        ),
        par,
    )
    for tabela in TABELAS_APAGADAS:
        conn.execute(
            text(f"DELETE FROM {tabela} WHERE channel = :c AND conversation_key = :k"), par
        )

    conn.execute(
        text(
            "UPDATE messages SET text_body = NULL, raw_payload = NULL, envelope_context = NULL"
            " WHERE channel = :c AND conversation_key = :k"
        ),
        par,
    )
    # O resumo do handoff e derivado da transcricao: e conteudo, como ela.
    conn.execute(
        text("UPDATE handoffs SET resumo = NULL WHERE channel = :c AND conversation_key = :k"),
        par,
    )
    # Antes da troca de chave, e num UPDATE so: status e par mudam juntos, e
    # o CHECK `ck_solicitacoes_de_titular_par_com_status` nunca ve metade.
    conn.execute(
        text(
            "UPDATE solicitacoes_de_titular"
            " SET status = 'ATENDIDA', atendida_em = now(), channel = NULL,"
            " conversation_key = NULL"
            " WHERE channel = :c AND conversation_key = :k AND status = 'ABERTA'"
        ),
        par,
    )

    desligar_triggers(conn, TABELAS_IMUTAVEIS_REESCRITAS)
    # As tabelas apagadas acima continuam na volta, sem linha do par: o
    # UPDATE nelas nao casa nada, e manter a lista inteira poupa uma segunda
    # lista que teria de acompanhar `TABELAS_COM_CHAVE_DE_LEAD`.
    for tabela in TABELAS_COM_CHAVE_DE_LEAD:
        conn.execute(
            text(
                f"UPDATE {tabela} SET conversation_key = :novo"
                " WHERE channel = :c AND conversation_key = :k"
            ),
            par,
        )
    mover_referencias_fora_da_chave(conn, channel=channel, atual=conversation_key, novo=novo)
    # So no caminho de sucesso, pela razao escrita no fim de
    # `reindexacao.py::reindexar`: numa transacao abortada o ENABLE reprovaria
    # e esconderia a causa, e o rollback de quem chama ja desfaz o DISABLE.
    religar_triggers(conn, TABELAS_IMUTAVEIS_REESCRITAS)
    return chaves_de_midia
