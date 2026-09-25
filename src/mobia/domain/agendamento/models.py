"""Os agendamentos, e a garantia de que dois nao se sobrepoem. TEC-168, RT-07.

**A garantia nao mora aqui.** A constraint de exclusao por intervalo
(`EXCLUSAO_DE_SOBREPOSICAO`) e criada em SQL pela migration 0044 e nao e
declarada no modelo: o `ExcludeConstraint` do SQLAlchemy nao expressa bem o
`tstzrange(inicio, fim, '[)')`, e o que importa para o RT-07 e o banco
recusar -- ver `tests/integration/test_agendamento_schema.py`, que prova com
insert cru, sem passar por este modelo. Consequencia pratica: um `alembic
revision --autogenerate` pode propor derrubar o indice gist e a constraint
por tras de `ex_agendamentos_sem_sobreposicao`, por nao os encontrar aqui --
essa proposta tem de ser descartada, as migrations deste repo sao escritas
a mao.

O lead e o par `(channel, conversation_key)`, como em `handoffs` e
`optout_events`: nao existe tabela de lead.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

# Importados para registrar as tabelas-alvo das FKs no mesmo metadata: sem
# eles o flush nao sabe ordenar `agendamentos` depois de `corretores` e
# `imoveis`.
from mobia.domain.catalogo.models import Imovel  # noqa: F401
from mobia.domain.corretores.models import Corretor  # noqa: F401
from mobia.domain.messages.models import Base


class StatusDoAgendamento(StrEnum):
    """O vocabulario da RN-12.5, com dois desvios declarados (TEC-172, D1).

    **`PROPOSTO` nao existe aqui, e e `RESERVADO`.** A RN-12.5 nomeia de
    `PROPOSTO` o mesmo fato que a TEC-168 chamou de `RESERVADO` -- a reserva
    com lock otimista de 5 minutos da RN-11.4. Acrescentar o segundo nome
    criaria um valor que nenhum caminho escreve e que toda consulta teria de
    lembrar de incluir: entrada morta de vocabulario, e uma segunda grafia do
    mesmo estado que o CHECK passaria a aceitar em silencio.

    **`EXPIRADO` existe e nao esta na RN-12.5.** E a reserva atropelada por
    outra, um fato que aquela lista nao modela.
    """

    RESERVADO = "RESERVADO"
    CONFIRMADO = "CONFIRMADO"
    # A reserva que venceu e foi atropelada por outra (D3 do desenho). Uma
    # vencida que ninguem disputou continua RESERVADO: quem le filtra por
    # `reservado_ate`, e nao por este status.
    EXPIRADO = "EXPIRADO"

    # TEC-172. Os quatro desfechos do ciclo. **Nenhum deles entra na
    # constraint de exclusao** (migration 0044), e e isso que libera o slot:
    # o WHERE de la e allowlist de RESERVADO e CONFIRMADO, entao um UPDATE
    # para qualquer um destes quatro tira a linha do indice no mesmo
    # statement. Ver a docstring da migration 0050.
    CANCELADO = "CANCELADO"
    REAGENDADO = "REAGENDADO"
    REALIZADO = "REALIZADO"
    NO_SHOW = "NO_SHOW"


EXCLUSAO_DE_SOBREPOSICAO = "ex_agendamentos_sem_sobreposicao"


class Agendamento(Base):
    __tablename__ = "agendamentos"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    corretor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("corretores.id", name="fk_agendamentos_corretor"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nulo: reuniao remota pode nao ter imovel. O contrato do SRS (6.4) tem
    # `imovelId`, e a FK impede apontar para imovel que nao existe.
    imovel_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("imoveis.id", name="fk_agendamentos_imovel"),
        nullable=True,
    )
    tipo: Mapped[str] = mapped_column(String(24), nullable=False)
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reservado_ate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # TEC-166. Categoria de `MotivoDaAlocacao` (`agendamento/vocabulario.py`):
    # por que este corretor, e nao outro. NOT NULL sem padrao -- ver a
    # docstring da migration 0045.
    motivo_da_alocacao: Mapped[str] = mapped_column(String(24), nullable=False)

    # TEC-170. Uma marca por passo da confirmacao (D2): nula e "nao aconteceu",
    # preenchida e o que impede a reexecucao de repetir. Ver a migration 0047.
    calendar_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    corretor_avisado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lead_avisado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # TEC-171, RN-12.2. Uma coluna por lembrete, e o que ela guarda e
    # "resolvido", nao "entregue" -- quem registra entrega e a linha em
    # `outbound_dispatches`. Nula na falha de canal, que e o caso em que a
    # passagem seguinte tenta de novo; preenchida tambem quando a guarda
    # recusou, e essa e a diferenca deliberada em relacao as tres colunas da
    # TEC-170 logo acima. Ver a migration 0049, que guarda o porque.
    lembrete_24h_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lembrete_2h_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # TEC-172, RN-12.3. O vinculo da remarcacao: o novo agendamento aponta
    # para o que ele substitui, e o original fica REAGENDADO. E o que torna a
    # metrica de remarcacao possivel -- a razao que a card da. Sem teto de
    # cadeia: A -> B -> C encadeia por aqui.
    origem_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agendamentos.id", name="fk_agendamentos_origem"),
        nullable=True,
    )

    # TEC-172. Um carimbo por desfecho: `status` diz o que e, e estes dizem
    # QUANDO passou a ser. `cancelado_em` nao e conveniencia -- e dele que a
    # varredura do convite de remarcacao mede as 24 horas da RN-12.3.
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    realizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nao_compareceu_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # TEC-172. Marcas de resolvido, mesma semantica das duas da TEC-171: nula
    # e "ainda nao resolvido", nao "nao entregue". Ver a migration 0049.
    #
    # `corretor_avisado_do_cancelamento_em` e coluna PROPRIA e nao reuso de
    # `corretor_avisado_em` (TEC-170) de proposito: com uma coluna so, o aviso
    # do cancelamento seria suprimido porque o da confirmacao ja tinha
    # acontecido -- e sao dois fatos diferentes sobre o mesmo agendamento.
    remarcacao_convidada_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    corretor_avisado_do_cancelamento_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "tipo IN ('VISITA_PRESENCIAL','REUNIAO_REMOTA')", name="ck_agendamentos_tipo"
        ),
        CheckConstraint(
            "status IN ('RESERVADO','CONFIRMADO','EXPIRADO','CANCELADO',"
            "'REAGENDADO','REALIZADO','NO_SHOW')",
            name="ck_agendamentos_status",
        ),
        CheckConstraint("inicio < fim", name="ck_agendamentos_intervalo"),
        CheckConstraint(
            "motivo_da_alocacao IN ('MATCH_EXATO','SEM_MATCH','MATCH_SEM_CAPACIDADE')",
            name="ck_agendamentos_motivo_da_alocacao",
        ),
        Index("ix_agendamentos_conversa", "channel", "conversation_key"),
    )
