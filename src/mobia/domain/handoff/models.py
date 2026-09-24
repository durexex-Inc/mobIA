"""O handoff: a tarefa que o lead pronto vira para o corretor.

TEC-174. Ver `alembic/versions/0023_handoffs.py` para o porque do par como
identidade e do UNIQUE parcial. A FK de `corretor_id` para `corretores.id`
entrou na migration da TEC-196.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from mobia.domain.corretores.models import Corretor
from mobia.domain.messages.models import Base
from mobia.infra.crypto import aad_de


def aad_do_resumo_de_handoff(handoff_id: uuid.UUID) -> str:
    """Amarra o resumo ao handoff que ele descreve.

    Diferente do `aad_do_resumo` de `context/models.py`, que precisa compor o
    par `(channel, conversation_key)` e por isso prefixa cada parte pelo
    tamanho: aqui a identidade da linha e um UUID, que nao tem como colidir
    com outro por concatenacao ambigua. `aad_de` basta.
    """
    return aad_de(handoff_id, "resumo_handoff")


class Handoff(Base):
    __tablename__ = "handoffs"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # O gatilho que CRIOU o handoff. Os que chegarem depois vao para
    # `gatilhos_adicionais` -- a etiqueta nao muda, porque e por ela que a fila
    # do dashboard e filtrada (TEC-192) e etiqueta movel embaralha filtro salvo.
    gatilho: Mapped[str] = mapped_column(String(32), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(32), nullable=False)

    # Escala para ALTA e nunca desce -- emenda E-01 da RN-16.1. Sem isso, um
    # pedido explicito de humano sobre um handoff aberto ficaria NORMAL, o que
    # contraria a RN-04.6.
    prioridade: Mapped[str] = mapped_column(String(8), nullable=False)

    # Nasce PENDENTE (TEC-174). Desde a TEC-278 os quatro valores tem
    # escritor: ACEITO vem de DOIS lugares -- a rota de aceite
    # (`api/routes/handoffs.py`) e, desde a TEC-179, o `assumir` de
    # `api/routes/conversas.py` (D6: assumir a conversa aceita junto o
    # handoff PENDENTE ou ESCALADO dela). ESCALADO vem de dois lugares --
    # `handoff/escalada.py`, quando o prazo vence, e `notificacao/envio.py`,
    # quando nao ha destinatario nenhum a quem cobrar. CONCLUIDO vem do
    # `devolver` da TEC-278 (`api/routes/conversas.py`), o unico escritor dele.
    #
    # O enum nasceu completo na TEC-174 porque mudar valor de enum depois
    # custa migration, e o `IN` do CHECK e o unico lugar a mexer.
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    # FK para `corretores.id` desde a TEC-196. Continua NULAVEL, mas agora
    # por outra razao -- nao falta mais tabela alvo, falta quem aloque, e
    # alocar e a TEC-166.
    #
    # `ForeignKey(Corretor.id)` em vez da string "corretores.id": o alvo
    # precisa estar no mesmo `MetaData` para o SQLAlchemy resolver a FK, e a
    # string so funciona se ALGUEM MAIS ja tiver importado `Corretor` antes
    # (o que a suite inteira faz por acidente). Sem o import explicito acima,
    # `test_handoff_schema.py` reprova com `NoReferencedTableError` quando
    # roda sozinho -- e "rodar o arquivo sozinho" e o proprio procedimento que
    # este repo usa para separar flake de regressao.
    corretor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey(Corretor.id), nullable=True
    )

    gatilhos_adicionais: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
    )

    # Cifrado com AES-GCM, AAD de `aad_do_resumo_de_handoff`. Nulavel por
    # construcao: a geracao e assincrona (ver a D1 do desenho), entao todo
    # handoff existe por alguns segundos sem resumo. Desde a TEC-176 (RN-15.4)
    # so duas causas deixam `resumo` nulo por muito tempo: dossie ausente, e
    # o template de contingencia (`contingencia.montar`) tendo estourado o
    # limite mesmo depois de todo campo entrar com teto -- a rede de
    # seguranca de `geracao._montar_ou_none`, que so deveria disparar por
    # defeito de montagem. Toda falha do redator (invalido ou excecao do
    # provedor), por si so, grava o template em vez de deixar a coluna vazia.
    resumo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    resumo_gerado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Qual modelo escreveu. Nulo quando o resumo veio do template -- nenhum
    # modelo o escreveu, e e `resumo_fallback` que diz por que.
    resumo_modelo: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # RN-15.4. Nasce FALSO -- verdadeiro faria todo handoff nascer marcado
    # como simplificado, e o painel mostraria a fila inteira como degradada
    # antes mesmo de a geracao rodar. "Ainda nao gerei" nao e contingencia.
    # `gravar_resumo` grava esta coluna nos dois sentidos: um handoff que caiu
    # no template e depois foi regenerado com sucesso precisa ver a marca
    # LIMPA, ou o painel mostraria "simplificado" sobre um texto redigido.
    resumo_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    @validates("resumo")
    def _recusar_texto_claro(self, coluna: str, valor: object) -> object:
        """Mesma guarda de `Message` e de `ConversationSummary`.

        O driver embute o argumento recusado na propria mensagem de excecao,
        antes de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log.
        """
        if valor is not None and not isinstance(valor, bytes | bytearray | memoryview):
            raise TypeError(
                f"{coluna} aceita apenas bytes cifrados, recebeu {type(valor).__name__}"
            )
        return valor

    # Quando ao menos um canal aceitou a mensagem. Nulo enquanto ninguem
    # tentou -- e continua nulo quando os dois recusam, caso em que a coluna
    # ao lado e que conta a historia.
    notificado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # O "pendente de aviso manual" do terceiro cenario da TEC-177: nenhum
    # canal aceitou, ou nao havia destinatario. Nasce FALSO -- ver a migration.
    aviso_manual_pendente: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # Quando o prazo de aceite vence -- `handoff.sla.limite_de_aceite`, contado
    # dentro da jornada do corretor DESTINATARIO. NULAVEL contra o "Sim" do
    # modelo da secao 5 do SRS: a emenda E-01 da RN-16.3 explica que a jornada
    # so e conhecida no job de notificacao (TEC-177), entao a coluna e gravada
    # alguns segundos depois da criacao do handoff e fica nula nesse
    # intervalo. Fica nula PARA SEMPRE no handoff sem destinatario, que escala
    # na hora e nao tem prazo porque nao ha a quem cobrar (emenda E-02). Nulo
    # significa "ainda nao notificado" ou "nao havia a quem cobrar" -- NUNCA
    # "prazo zero". Ver a migration 0028 para o detalhe.
    sla_limite_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Quando o corretor aceitou o handoff. Nulo ate a rota de aceite (TEC-178,
    # Task 6) ou o `assumir` de conversas.py (TEC-179, D6) gravarem -- ou seja,
    # na maior parte da vida de um handoff: nao so todo PENDENTE, como ESCALADO
    # e ate CONCLUIDO sem aceite formal tambem ficam sem este carimbo.
    aceito_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Quando o CRM confirmou o recebimento deste lead (TEC-180, RN-16.5). Nulo
    # e "ainda nao entregue" -- nunca "entregue sem hora" --, e e essa a
    # condicao que define a fila de reprocessamento: nao ha tabela de payloads,
    # a fila e esta coluna. Ver a emenda E-01 a RN-16.5 e a D5 do desenho.
    #
    # Fica nulo PARA SEMPRE em toda maquina onde `CRM_WEBHOOK_URL` nao estiver
    # configurada, porque ali a exportacao nem e tentada (emenda E-02).
    crm_sincronizado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Quantas vezes a exportacao ja falhou nesta rodada. Zero e "nunca tentei",
    # e a varredura o zera de novo a cada rodada que abre -- entao este numero
    # NAO e o total historico de tentativas, e ninguem deve le-lo como tal.
    #
    # A contagem mora aqui, e nao no `max_tries` do ARQ, porque o ARQ nao chama
    # a nossa corrotina quando o teto dele estoura: ele loga um `warning`
    # proprio e encerra o job. Contar por la faria a terceira falha passar sem
    # alerta e sem marca -- a perda silenciosa que a RN-16.5 proibe. Ver a D3
    # do desenho e o docstring de `workers/jobs/exportar_crm.py`.
    crm_tentativas: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # O nome da classe da ultima excecao, e so -- a regra que a TEC-222 fixou
    # para `messages.last_error` e que `workers/jobs/process_message.py`
    # documenta em `_detalhe_para_a_coluna`: coluna duravel, em claro, fora da
    # mascara de PII do log. A mensagem de uma excecao de `httpx` carrega a
    # URL, e a URL do webhook e segredo de configuracao.
    crm_ultimo_erro: Mapped[str | None] = mapped_column(String(80), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("prioridade IN ('ALTA', 'NORMAL')", name="ck_handoffs_prioridade"),
        CheckConstraint(
            "status IN ('PENDENTE', 'ACEITO', 'ESCALADO', 'CONCLUIDO')",
            name="ck_handoffs_status",
        ),
        # TEC-278: o handoff bloqueia a conversa ate ser CONCLUIDO, nao ate
        # sair de PENDENTE. ACEITO e ESCALADO tambem contam como aberto --
        # CONCLUIDO ganhou o primeiro escritor em `POST
        # /api/v1/conversas/devolver`, e e ele que separa "aberto" de
        # "encerrado". O nome do indice ficou impreciso de proposito: ele
        # aparece em comentario e na migration 0023, e renomear e churn sem
        # ganho. Ver `alembic/versions/0030_handoff_aberto.py`.
        Index(
            "uq_handoffs_conversa_pendente",
            "channel",
            "conversation_key",
            unique=True,
            postgresql_where=text("status <> 'CONCLUIDO'"),
        ),
    )
