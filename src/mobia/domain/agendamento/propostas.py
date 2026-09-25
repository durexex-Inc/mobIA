"""As janelas oferecidas ao lead, gravadas e lidas de volta. TEC-371, D4.

Recebe a sessao e **nao commita** -- o commit e de quem chama, como em
`repositorio.py::reservar` e em `registrar_handoff`.

`ler` devolve dataclasses e nao objetos do ORM de proposito: quem consome e
`escolha.py::escolher`, que e pura e nao pode depender de sessao viva. Um
`JanelaProposta` com a sessao ja fechada explode no acesso ao atributo, e o
erro apareceria dentro de uma funcao que nao toca banco -- o pior lugar
possivel para procura-lo.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agendamento.janelas import Intervalo, JanelaAlocada, TipoDeCompromisso
from mobia.domain.agendamento.models import JanelaProposta
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao


@dataclass(frozen=True)
class Proposta:
    """Uma janela oferecida, do jeito que o lead a leu.

    `ordinal` e a posicao na frase, comecando em 1 -- e a mesma convencao de
    `ReacaoDoImovel.ordinal` (`agente/schemas.py`), pela mesma razao: e o que
    o lead consegue nomear ("a segunda").
    """

    ordinal: int
    janela: Intervalo
    corretor_id: uuid.UUID
    imovel_id: uuid.UUID | None
    tipo: TipoDeCompromisso
    motivo: MotivoDaAlocacao
    # TEC-372, D4. Preenchido, a escolha desta janela remarca aquele
    # agendamento em vez de reservar um novo. `None` e o caso da TEC-371.
    remarcando_id: uuid.UUID | None = None


async def gravar(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    janelas: Sequence[JanelaAlocada],
    tipo: TipoDeCompromisso,
    imovel_id: uuid.UUID | None,
    agora: datetime,
    remarcando_id: uuid.UUID | None = None,
) -> list[Proposta]:
    """Substitui a rodada anterior desta conversa pela nova, e devolve o que gravou.

    **Apaga antes de inserir, e nao atualiza no lugar.** Uma rodada de duas
    janelas depois de uma de tres deixaria o ordinal 3 da rodada velha vivo,
    e o lead que respondesse "a terceira" escolheria um horario que a ultima
    frase nao ofereceu. O `UNIQUE (channel, conversation_key, ordinal)` recusa
    a versao errada disso, mas so quando os ordinais colidem -- apagar e o
    que cobre o caso em que nao colidem.

    Lista vazia apaga e nao insere nada, que e o desfecho certo para "nao ha
    janela": a rodada velha nao pode sobreviver a uma oferta que nao houve.
    """
    await session.execute(
        delete(JanelaProposta).where(
            JanelaProposta.channel == channel,
            JanelaProposta.conversation_key == conversation_key,
        )
    )
    propostas: list[Proposta] = []
    for ordinal, alocada in enumerate(janelas, start=1):
        session.add(
            JanelaProposta(
                id=uuid.uuid4(),
                channel=channel,
                conversation_key=conversation_key,
                ordinal=ordinal,
                corretor_id=alocada.corretor_id,
                imovel_id=imovel_id,
                tipo=str(tipo),
                inicio=alocada.janela.inicio,
                fim=alocada.janela.fim,
                motivo_da_alocacao=str(alocada.motivo),
                proposto_em=agora,
                remarcando_id=remarcando_id,
            )
        )
        propostas.append(
            Proposta(
                ordinal=ordinal,
                janela=alocada.janela,
                corretor_id=alocada.corretor_id,
                imovel_id=imovel_id,
                tipo=tipo,
                motivo=alocada.motivo,
                remarcando_id=remarcando_id,
            )
        )
    await session.flush()
    return propostas


async def ler(
    session: AsyncSession, *, channel: str, conversation_key: str, agora: datetime
) -> list[Proposta]:
    """As propostas vivas desta conversa, na ordem do ordinal.

    **Viva e `inicio > agora`, e nao "gravada".** O lead que responde tres
    dias depois nao pode escolher um horario que ja passou, e uma reserva no
    passado seria gravada sem que nada reclamasse: a exclusao por intervalo
    da 0044 nao olha o relogio. A antecedencia minima de 3 horas nao entra
    nesta consulta de proposito -- quem a aplica e `reservar_ou_alternativas`
    pelo motor de janelas, e duplica-la aqui daria dois lugares para manter
    em sincronia com a RN-11.1.

    Lista vazia significa as duas coisas ao mesmo tempo -- nunca houve oferta,
    ou a oferta venceu -- e quem chama trata as duas igual: oferece de novo.
    """
    linhas = (
        (
            await session.execute(
                select(JanelaProposta)
                .where(
                    JanelaProposta.channel == channel,
                    JanelaProposta.conversation_key == conversation_key,
                    JanelaProposta.inicio > agora,
                )
                .order_by(JanelaProposta.ordinal)
            )
        )
        .scalars()
        .all()
    )
    return [
        Proposta(
            ordinal=linha.ordinal,
            janela=Intervalo(linha.inicio, linha.fim),
            corretor_id=linha.corretor_id,
            imovel_id=linha.imovel_id,
            tipo=TipoDeCompromisso(linha.tipo),
            motivo=MotivoDaAlocacao(linha.motivo_da_alocacao),
            remarcando_id=linha.remarcando_id,
        )
        for linha in linhas
    ]


async def apagar(session: AsyncSession, *, channel: str, conversation_key: str) -> None:
    """Esquece a rodada desta conversa, sem oferecer outra.

    Chamada quando a escolha vira reserva: a partir dai o estado da conversa
    e a linha `RESERVADO`. A leitura de `conversa.py::atender` poe a reserva
    na frente das propostas, entao nao e a ordem que quebra -- e o que
    acontece quando a reserva VENCE. Com as propostas ainda de pe, o lead que
    responde tarde demais cairia no ramo da escolha e reservaria por ordinal
    sem nunca ler o horario de novo; apagar aqui e o que faz a reserva
    vencida virar oferta nova, que e o terceiro cenario da card.
    """
    await session.execute(
        delete(JanelaProposta).where(
            JanelaProposta.channel == channel,
            JanelaProposta.conversation_key == conversation_key,
        )
    )
