"""A reindexacao do lead: a mesma maquina para a migration e para a rotacao. TEC-203, D3.

Troca o `conversation_key` de cada par, em todas as tabelas, e arrasta junto o
que depende dele: identidade, remetente/destinatario das mensagens, evento de
rate limit, `lead_ref` da trilha, AAD do resumo e do vinculo, e o prefixo do
`provider_message_id` do widget (`api/routes/widget.py::_chave_do_id`), que
carrega a mesma chave da sessao.

Tres modos, e a diferenca entre eles e so DE ONDE vem o valor cru:

- `migracao` (0062, subida): o par que nao tem identidade ainda guarda o valor
  cru na coluna. O que ja tem identidade ja foi reindexado -- e a idempotencia
  que deixa retomar uma subida interrompida.
- `rotacao` (script, chave de indice nova): o valor vem da identidade.
- `reversao` (0062, descida): o valor vem da identidade e VIRA a chave; nada e
  gravado em `identidades_de_lead`, que a descida apaga em seguida.

**Par sem identidade na rotacao e na reversao e pulado, nao reprova.** Nao ha
de onde tirar o valor cru, entao a chave dele fica como esta -- sob a chave de
indice velha, na rotacao; em HMAC depois da descida, na reversao. Reprovar
deixaria um par orfao (bug antigo, erro de operador) travar a rotacao de todo
mundo. O resultado conta os pulados, e o log `reindexacao.par_sem_identidade`
diz quantos por canal -- so o canal, nunca a chave.

**Tabelas imutaveis.** `lead_score_audit`, `conversation_intent_audit` e
`eventos_auditoria` recusam UPDATE por trigger. A reindexacao desliga a
trigger de cada uma, reescreve e religa, na mesma transacao. E excecao
declarada: trocar o pseudonimo do lead nao altera o fato registrado, e manter
o telefone em claro numa tabela imutavel seria a violacao que a TEC-203
existe para eliminar.

Sync, sobre `Connection`: a migration roda dentro do `run_sync` do Alembic, e
o script abre a mesma coisa com `engine.begin()` + `run_sync`.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

import structlog
from sqlalchemy import Connection, text

from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.context.models import aad_do_resumo
from mobia.domain.identidade.models import aad_da_identidade, aad_do_vinculo
from mobia.infra.crypto import decrypt, encrypt

# Toda tabela com `conversation_key`. `tests/unit/test_tabelas_com_chave_de_lead.py`
# reprova se aparecer uma fora daqui -- a proxima tabela nao escapa da rotacao
# em silencio. A 0062 NAO usa esta lista: tem copia literal, porque migration
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
    # TEC-207. Guarda o par so enquanto ABERTA (D2 do desenho); a rotacao a
    # arrasta junto como qualquer outra tabela com `conversation_key`.
    "solicitacoes_de_titular",
    "tarefas_de_corretor",
    "vinculos_de_sessao",
)

TRIGGERS_DE_IMUTABILIDADE = {
    "lead_score_audit": "lead_score_audit_imutavel",
    "conversation_intent_audit": "conversation_intent_audit_imutavel",
    "eventos_auditoria": "eventos_auditoria_imutavel",
}

log = structlog.get_logger(__name__)

Modo = Literal["migracao", "rotacao", "reversao"]


@dataclass(frozen=True)
class Reindexacao:
    """O que `reindexar` fez.

    `mudados` conta os pares movidos ou com `lead_ref` recalculado;
    `sem_identidade`, os pulados por nao ter identidade (so rotacao e
    reversao); `lead_refs_recalculados`, as linhas de `eventos_auditoria`
    cujo `lead_ref` trocou.
    """

    mudados: int
    sem_identidade: int
    lead_refs_recalculados: int


def _pares(conn: Connection, tabelas: Sequence[str], modo: Modo) -> list[tuple[str, str]]:
    """Todo par que guarda o lead, tambem os que nao aparecem nas `tabelas`.

    O evento de rate limit por numero sobrevive a mensagem que o gerou (a
    retencao de `messages` e mais curta), entao pode ser o unico lugar com
    aquele telefone -- e fora daqui ele ficaria em claro depois da 0062. Na
    rotacao entram tambem as identidades: a do lead que so deixou a trilha
    nao tem linha em tabela nenhuma, e seu `lead_ref` ficaria na chave velha.
    """
    selecoes = [
        f"SELECT channel, conversation_key FROM {tabela} WHERE conversation_key IS NOT NULL"
        for tabela in tabelas
    ]
    selecoes.append("SELECT channel, chave FROM rate_limit_events WHERE escopo = 'numero'")
    if modo == "rotacao":
        selecoes.append("SELECT channel, conversation_key FROM identidades_de_lead")
    return [(channel, chave) for channel, chave in conn.execute(text(" UNION ".join(selecoes)))]


def _identidade(conn: Connection, channel: str, chave: str) -> str | None:
    blob = conn.execute(
        text(
            "SELECT valor_cifrado FROM identidades_de_lead"
            " WHERE channel = :c AND conversation_key = :k"
        ),
        {"c": channel, "k": chave},
    ).scalar()
    return None if blob is None else decrypt(bytes(blob), aad_da_identidade(channel, chave))


def desligar_triggers(conn: Connection, tabelas: Iterable[str]) -> None:
    """Desliga a trigger de imutabilidade de cada uma das `tabelas`.

    Recebe a lista, e nao desliga as tres sempre: a reindexacao reescreve
    `eventos_auditoria` (o `lead_ref`), a anonimizacao da TEC-207 nao -- a
    trilha dela fica intocada, e desligar uma trigger sem precisar seria
    abrir a tabela a toa. Quem chama religa com `religar_triggers` so no
    caminho de sucesso; ver o comentario no fim de `reindexar`.
    """
    _alternar_triggers(conn, tabelas, "DISABLE")


def religar_triggers(conn: Connection, tabelas: Iterable[str]) -> None:
    """O inverso de `desligar_triggers`, sobre as mesmas `tabelas`."""
    _alternar_triggers(conn, tabelas, "ENABLE")


def _alternar_triggers(
    conn: Connection, tabelas: Iterable[str], acao: Literal["DISABLE", "ENABLE"]
) -> None:
    for tabela in tabelas:
        trigger = TRIGGERS_DE_IMUTABILIDADE[tabela]
        conn.execute(text(f"ALTER TABLE {tabela} {acao} TRIGGER {trigger}"))


def reindexar(
    conn: Connection,
    *,
    tabelas: Sequence[str],
    nova_chave: Callable[[str, str], str],
    modo: Modo,
    chave_do_lead_antiga: str,
    chave_do_lead_nova: str,
) -> Reindexacao:
    """Leva cada par a `nova_chave(channel, valor)`; devolve o que fez.

    "Mudou" conta tambem o par cuja chave ficou, mas cujo `lead_ref` foi
    recalculado porque a chave do `lead_ref` trocou. Nao commita: quem chama e
    dono da transacao, e e ela que torna o desligar das triggers invisivel
    para qualquer outra conexao.
    """
    mudados = 0
    lead_refs = 0
    sem_identidade: Counter[str] = Counter()
    # Uma vez so, e nao por par: na subida da 0062 a coluna ainda nao existe
    # (nasce depois do loop), e na descida ja foi removida antes dele.
    vinculo_cifrado = _tem_coluna(conn, "vinculos_de_sessao", "telefone_cifrado")
    desligar_triggers(conn, TRIGGERS_DE_IMUTABILIDADE)
    for channel, atual in _pares(conn, tabelas, modo):
        valor = _identidade(conn, channel, atual)
        if valor is None:
            if modo != "migracao":
                sem_identidade[channel] += 1
                continue
            valor = atual
        novo = nova_chave(channel, valor)
        if novo == atual and chave_do_lead_antiga == chave_do_lead_nova:
            continue
        _mover(conn, tabelas, channel, atual, novo, valor, modo, vinculo_cifrado)
        lead_refs += _recalcular_lead_ref(
            conn, channel, atual, novo, chave_do_lead_antiga, chave_do_lead_nova
        )
        mudados += 1
    # Religa so no caminho de sucesso, e nao num `finally`: se um statement
    # falhou, a transacao esta abortada, o ENABLE reprovaria com
    # `InFailedSqlTransaction` e esconderia a causa. O rollback de quem chama
    # ja desfaz o DISABLE -- ALTER TABLE e transacional no Postgres.
    religar_triggers(conn, TRIGGERS_DE_IMUTABILIDADE)
    for channel, quantos in sorted(sem_identidade.items()):
        log.warning("reindexacao.par_sem_identidade", channel=channel, pares=quantos, modo=modo)
    return Reindexacao(
        mudados=mudados,
        sem_identidade=sum(sem_identidade.values()),
        lead_refs_recalculados=lead_refs,
    )


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
    mover_referencias_fora_da_chave(conn, channel=channel, atual=atual, novo=novo)
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


def mover_referencias_fora_da_chave(
    conn: Connection, *, channel: str, atual: str, novo: str
) -> None:
    """Leva a `novo` o que guarda `atual` fora da coluna `conversation_key`.

    Remetente e destinatario das mensagens, prefixo do `provider_message_id`
    do widget e `rate_limit_events.chave`. **Supoe `messages` ja movida para
    `novo`**: os UPDATEs de mensagem filtram por `conversation_key = :novo`,
    o que limita a reescrita as linhas deste par. Serve a reindexacao
    (`_mover`) e a anonimizacao da TEC-207 (`titular/anonimizacao.py`), que
    trocam a chave por motivos diferentes e precisam arrastar o mesmo resto.
    """
    parametros = {"c": channel, "atual": atual, "novo": novo}
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
    # O `provider_message_id` do widget carrega `atual` na frente
    # (`_chave_do_id`), e so ele -- o `LIKE` com `atual` escapado casa
    # exatamente esse prefixo e nada do WhatsApp, cujo wamid nunca tem essa
    # forma. `substr` a partir de `length(:atual) + 1` preserva o separador
    # ':' e o id que vem depois, entao o resultado e `novo:id`, o mesmo
    # formato que `_chave_do_id` grava hoje.
    escapado = atual.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    conn.execute(
        text(
            "UPDATE messages SET provider_message_id ="
            " :novo || substr(provider_message_id, length(:atual) + 1)"
            " WHERE channel = :c AND conversation_key = :novo"
            " AND provider_message_id LIKE :atual_prefixo ESCAPE '\\'"
        ),
        {**parametros, "atual_prefixo": f"{escapado}:%"},
    )
    conn.execute(
        text(
            "UPDATE rate_limit_events SET chave = :novo"
            " WHERE escopo = 'numero' AND channel = :c AND chave = :atual"
        ),
        parametros,
    )


def _recalcular_lead_ref(
    conn: Connection, channel: str, atual: str, novo: str, antiga: str, nova: str
) -> int:
    """Devolve quantas linhas trocaram de `lead_ref`."""
    resultado = conn.execute(
        text("UPDATE eventos_auditoria SET lead_ref = :novo WHERE lead_ref = :antigo"),
        {
            "antigo": lead_ref(channel, atual, chave=antiga),
            "novo": lead_ref(channel, novo, chave=nova),
        },
    )
    return int(resultado.rowcount)


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
