"""O ciclo de vida da conversa. TEC-138, RN-03.5 e RN-02.3.

**Esta tabela e a entidade que este sistema nao tinha.** Ate a TEC-138 a
conversa era o par `(channel, conversation_key)` espalhado por oito tabelas --
`atendimento/models.py` diz isso por extenso -- e o encerramento era uma regra
do SRS sem implementacao, reservada para a TEC-130. A TEC-138 chegou antes e
precisou do status, entao a entidade nasce aqui.

**Consequencia para quem pegar a TEC-130:** ela ESTENDE isto, nao cria.
Encerrar por inatividade e acrescentar um motivo ao vocabulario de
`vocabulario.py` e um escritor novo; nao e uma segunda tabela nem uma segunda
nocao de encerrado. A Emenda da RN-02.3 registra isso no SRS.

**E o que se ganha com o motivo novo e a escrituracao, nao a janela de
silencio.** Os 30 dias em que o agente nao responde sao politica da RN-03.5, e
`SituacaoDaConversa.silencia_o_agente` (`repositorio.py`) exige
`FORA_DE_ESCOPO` para aplica-los -- motivo novo entra no silencio so se quem o
acrescentar decidir isso. Por omissao, uma conversa fechada por inatividade
continua sendo respondida na mensagem seguinte, que e o que a RN-02.3 pede.

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
