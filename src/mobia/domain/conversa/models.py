"""O ciclo de vida da conversa. TEC-138, RN-03.5 e RN-02.3.

**Esta tabela e a entidade que este sistema nao tinha.** Ate a TEC-138 a
conversa era o par `(channel, conversation_key)` espalhado por oito tabelas --
`atendimento/models.py` diz isso por extenso -- e o encerramento era uma regra
do SRS sem implementacao, reservada para a TEC-130. A TEC-138 chegou antes e
precisou do status, entao a entidade nasce aqui.

**A TEC-130 estendeu isto, e nao criou nada.** Ela acrescentou `INATIVIDADE` e
`OPTOUT` ao vocabulario de `vocabulario.py`, mais dois escritores -- a
varredura diaria (`encerrar_inativas`, em `repositorio.py`) e o bloco de
opt-out do turno. Nenhuma tabela nova, nenhuma segunda nocao de encerrado, e
nenhuma migration: a coluna ja comportava os dois literais. A Emenda E-02 da
RN-02.3 previa a extensao e nomeava `INATIVIDADE`; `OPTOUT` foi decisao desta
card, e a Emenda E-03 registra as duas.

**O que ela NAO trouxe e a janela de silencio.** Os 30 dias em que o agente nao
responde continuam sendo politica da RN-03.5, e
`SituacaoDaConversa.silencia_o_agente` continua exigindo `FORA_DE_ESCOPO`. Uma
conversa fechada por inatividade e respondida na mensagem seguinte -- que e o
que a RN-02.3 pede, e o motivo de o reengajamento existir.

`motivo_do_encerramento` e vocabulario e nao booleano justamente para essa
extensao -- ver `MotivoDoEncerramento` em `vocabulario.py` para a razao por
extenso.

Uma linha por conversa, com UPDATE -- e nao append-only como `optout_events`.
O historico de encerramentos nao existe por esta card, e a lacuna esta
declarada no desenho: quem precisar da serie acrescenta a tabela de eventos.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from mobia.domain.conversa.vocabulario import Status
from mobia.domain.messages.models import Base


class Conversa(Base):
    __tablename__ = "conversas"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Status.ATIVA, server_default=Status.ATIVA.value
    )

    # Os dois andam juntos e sao nulos juntos: `status = ATIVA` significa
    # nenhum dos dois preenchido. Nao ha booleana `encerrada` ao lado, pela
    # razao que `atendimento_humano` ja escreve para si -- uma segunda
    # representacao do mesmo fato e duas coisas que podem divergir.
    motivo_do_encerramento: Mapped[str | None] = mapped_column(String(16), nullable=True)
    encerrada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
