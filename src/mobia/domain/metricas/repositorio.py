"""As consultas agregadas do painel. TEC-190, RN-17.1 e RN-17.2.

**Todo numero deste modulo e sobre a COORTE** -- os leads cujo PRIMEIRO
contato caiu no periodo --, e nao sobre eventos ocorridos no periodo. Ver a
D10 do plano: por atividade, um lead recomendado em agosto que nasceu em
julho faria `Recomendado / Em conversa` passar de 100%, e a RN-17.2 pede uma
taxa de conversao, nao um numero acima de um.

**A coorte da o RECORTE comum, e a ACUMULACAO da a inclusao entre etapas**
(TEC-367). Cada etapa conta quem a alcancou ou alcancou uma posterior, entao
`Qualificado` esta contido em `Em conversa` por construcao e a conversao nao
tem como passar de 100%. Ver a D4 do desenho da TEC-367.

**Isto reverte uma decisao da TEC-190, e vale saber qual.** Ate ela, as cinco
contagens eram consultas independentes e a docstring daqui declarava duas
maneiras conhecidas de a conversao estourar:

- **a lacuna L1** -- `Qualificado` contava so quem ganhou `qualificado_em`
  depois da migration `0040`, e `Recomendado` contava tudo. Um periodo antigo
  com 40 recomendados e 1 qualificado dava 4000%. A `0055` fez o backfill
  pela trilha de score, e a lacuna encolheu ao residuo descrito la.
- **o lead que qualifica no primeiro turno** -- despeja intencao, orcamento,
  regiao e urgencia numa mensagem so -- ficava FORA de `Em conversa`, que
  exige mais de uma fala, e DENTRO de `Qualificado`. A acumulacao o poe nas
  duas.

Nenhuma das duas era erro de consulta, e a TEC-190 as tratou como fatos sobre
os dados, pedindo a quem le o painel que soubesse que o funil podia nao
decrescer. **O que mudou o julgamento foi a RN-17.2**: ela pede uma TAXA de
conversao, e taxa acima de 100% nao e taxa -- e sinal de que as etapas nao
estao aninhadas. O piso de "mais de uma fala" em `Em conversa` continua
valendo para quem NAO avancou, que e o caso que ele existe para separar de
`Novo`.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos dez repositorios deste repo.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.models import Recomendacao
from mobia.domain.context.models import LeadQualification
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import Status
from mobia.domain.handoff.models import Handoff
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.metricas.filtros import Recorte
from mobia.domain.metricas.vocabulario import Etapa

# O status de handoff que conta como aceito. Nao e enum importado porque
# `handoff/vocabulario.py` nomeia o ciclo inteiro e so este valor interessa
# aqui.
_ACEITO = "ACEITO"


def _nascimento() -> Any:
    """O instante do primeiro contato de cada conversa.

    `conversas` NAO tem `criado_em` -- as colunas dela sao `channel`,
    `conversation_key`, `status`, `motivo_do_encerramento` e `encerrada_em` --,
    entao o nascimento do lead sai da primeira linha em `messages`, que e a
    unica tabela com esse instante.
    """
    return (
        select(
            Message.channel.label("channel"),
            Message.conversation_key.label("conversation_key"),
            func.min(Message.created_at).label("nasceu_em"),
        )
        .group_by(Message.channel, Message.conversation_key)
        .subquery()
    )


def _coorte(recorte: Recorte) -> Select[Any]:
    """As conversas cujo PRIMEIRO contato caiu no periodo, ja filtradas."""
    nascimento = _nascimento()

    consulta = select(nascimento.c.channel, nascimento.c.conversation_key).where(
        nascimento.c.nasceu_em >= recorte.inicio,
        nascimento.c.nasceu_em < recorte.fim,
    )

    if recorte.canal is not None:
        consulta = consulta.where(nascimento.c.channel == recorte.canal)

    if recorte.intencao is not None or recorte.temperatura is not None:
        consulta = consulta.join(
            LeadQualification,
            (LeadQualification.channel == nascimento.c.channel)
            & (LeadQualification.conversation_key == nascimento.c.conversation_key),
        )
        if recorte.intencao is not None:
            consulta = consulta.where(LeadQualification.intencao == recorte.intencao)
        if recorte.temperatura is not None:
            consulta = consulta.where(LeadQualification.temperatura == recorte.temperatura)

    if recorte.corretor_id is not None:
        # **Este ramo nao e alcancado por producao hoje**, e isso e
        # deliberado: `montar_recorte` RECUSA o filtro por corretor com 422.
        #
        # **A razao da recusa MUDOU, e o texto antigo daqui ficou falso**
        # (corrigido na TEC-367). Ele dizia que `handoffs.corretor_id` "nunca
        # e escrito"; desde a TEC-192 ele e -- `notificacao/envio.py` e o
        # escritor, e a Emenda E-06 da RN-16.2 registra a mudanca. O que
        # sustenta a recusa hoje nao e mais a coluna vazia, e sim que virar a
        # borda e decisao da TEC-316: a coluna so passou a ser preenchida a
        # partir da TEC-192, entao o funil por corretor de qualquer periodo
        # anterior sairia zerado, e a gerente leria isso como fato.
        #
        # A consulta fica escrita e testada (os testes montam o `Recorte` a
        # mao, pulando a borda) porque ela esta CORRETA e e o que passa a valer
        # quando alguem escrever `handoffs.corretor_id`: o funil dos leads que
        # ACABARAM com aquele corretor, contando a mesma conversa nos estagios
        # anteriores ao repasse.
        consulta = consulta.join(
            Handoff,
            (Handoff.channel == nascimento.c.channel)
            & (Handoff.conversation_key == nascimento.c.conversation_key),
        ).where(Handoff.corretor_id == recorte.corretor_id)

    # **`DISTINCT` aqui e nao so em `_quantos`.** `calcular_indicadores`
    # consome esta subconsulta DIRETO, sem passar por `_quantos`, e o JOIN
    # com `handoffs` acima duplica a conversa que tem mais de um handoff do
    # mesmo corretor -- possivel desde que a Emenda E-04 da RN-16.4 deu a
    # `devolver` o poder de CONCLUIR um handoff, liberando o UNIQUE parcial
    # para um segundo. Sem isto, `conversasAtivas` contaria 2 para um lead so
    # e `taxaQualificacao` poderia dar 2.0 -- os 200% que a D10 existe para
    # tornar impossiveis.
    return consulta.distinct()


async def _quantos(session: AsyncSession, consulta: Select[Any]) -> int:
    alvo = consulta.distinct().subquery()
    return int((await session.execute(select(func.count()).select_from(alvo))).scalar_one())


async def _quantos_na_uniao(session: AsyncSession, consultas: Sequence[Select[Any]]) -> int:
    """Quantos pares distintos aparecem em ALGUMA das consultas.

    Irma de `_quantos`, e separada dela porque `union` devolve
    `CompoundSelect` e nao `Select` -- o `.distinct()` daquela nao se aplica
    aqui, e nem precisa: `UNION` (sem `ALL`) ja deduplica, que e exatamente a
    propriedade de que a acumulacao do funil depende.
    """
    if len(consultas) == 1:
        return await _quantos(session, consultas[0])
    alvo = consultas[0].union(*consultas[1:]).subquery()
    return int((await session.execute(select(func.count()).select_from(alvo))).scalar_one())


async def contar_etapas(session: AsyncSession, *, recorte: Recorte) -> dict[Etapa, int]:
    """Quantos da coorte alcancaram cada etapa. `AGENDADO` nao esta aqui.

    A ausencia de `AGENDADO` no dicionario e deliberada e nao um
    esquecimento: nao existe tabela de agendamento, e quem poe o `None` na
    resposta e `montar_funil`, a partir de `SEM_FONTE`. Uma chave com zero
    aqui viraria zero la, que e exatamente o que a D1 recusa.

    **Cada etapa conta quem a alcancou OU alcancou uma POSTERIOR** (TEC-367,
    D4), e e isso que torna o funil monotono. Ver a docstring do modulo: as
    contagens cruas sao conjuntos independentes, e dividir um pelo outro
    produzia taxa acima de 100%.
    """
    coorte = _coorte(recorte).subquery()

    # As cinco condicoes, cada uma o conjunto CRU da sua etapa -- sem
    # acumulacao ainda. Em ordem do funil, que e o que o `UNION` abaixo usa.
    novos = select(coorte.c.channel, coorte.c.conversation_key)

    # "Em conversa" e o lead que falou mais de uma vez: uma fala so e o
    # primeiro contato, que ja e a etapa Novo. Sem este piso, as duas etapas
    # dariam sempre o mesmo numero e a conversao entre elas seria 100% fixo.
    em_conversa = (
        select(coorte.c.channel, coorte.c.conversation_key)
        .join(
            Message,
            (Message.channel == coorte.c.channel)
            & (Message.conversation_key == coorte.c.conversation_key),
        )
        .where(Message.direction == MessageDirection.INBOUND)
        .group_by(coorte.c.channel, coorte.c.conversation_key)
        .having(func.count(Message.id) > 1)
    )

    qualificados = select(coorte.c.channel, coorte.c.conversation_key).join(
        LeadQualification,
        (LeadQualification.channel == coorte.c.channel)
        & (LeadQualification.conversation_key == coorte.c.conversation_key)
        & LeadQualification.qualificado_em.is_not(None),
    )

    recomendados = select(coorte.c.channel, coorte.c.conversation_key).join(
        Recomendacao,
        (Recomendacao.channel == coorte.c.channel)
        & (Recomendacao.conversation_key == coorte.c.conversation_key),
    )

    aceitos = select(coorte.c.channel, coorte.c.conversation_key).join(
        Handoff,
        (Handoff.channel == coorte.c.channel)
        & (Handoff.conversation_key == coorte.c.conversation_key)
        & (Handoff.status == _ACEITO),
    )

    # A acumulacao. `AGENDADO` nao entra na lista de proposito: ele nao tem
    # fonte (`SEM_FONTE`), entao uni-lo seria unir conjunto vazio -- e
    # escreveria aqui uma dependencia que some no dia em que a TEC-376 der
    # numero aquela etapa.
    cruas: list[tuple[Etapa, Select[Any]]] = [
        (Etapa.NOVO, novos),
        (Etapa.EM_CONVERSA, em_conversa),
        (Etapa.QUALIFICADO, qualificados),
        (Etapa.RECOMENDADO, recomendados),
        (Etapa.HANDOFF_ACEITO, aceitos),
    ]

    contagens: dict[Etapa, int] = {}
    for indice, (etapa, _) in enumerate(cruas):
        desta_para_frente = [consulta for _, consulta in cruas[indice:]]
        contagens[etapa] = await _quantos_na_uniao(session, desta_para_frente)

    return contagens


@dataclass(frozen=True)
class Indicadores:
    """Os indicadores da RN-17.1 que tem fonte.

    Os quatro de agendamento NAO estao aqui: nao ha tabela, e quem os poe
    nulos na resposta e a rota, a partir de `INDICADORES_SEM_FONTE`.

    **Nulo e "nao ha o que medir", e nunca zero.** Uma coorte vazia da
    `taxa_qualificacao` nula porque 0/0 nao e 0% -- dizer 0% afirmaria que
    ninguem qualificou, quando nao houve ninguem.
    """

    conversas_ativas: int
    taxa_qualificacao: float | None
    distribuicao_por_temperatura: dict[str, int]
    tempo_medio_primeira_resposta_seg: float | None
    tempo_medio_qualificacao_seg: float | None
    sla_handoff_cumprido_pct: float | None


async def calcular_indicadores(
    session: AsyncSession, *, recorte: Recorte, novos: int
) -> Indicadores:
    """Os indicadores da RN-17.1, todos sobre a mesma coorte da D10.

    `novos` vem de fora, ja contado por `contar_etapas`: e o denominador da
    taxa de qualificacao, e recontar aqui seria uma segunda consulta com a
    mesma resposta.
    """
    coorte = _coorte(recorte).subquery()

    ativas = int(
        (
            await session.execute(
                select(func.count())
                .select_from(coorte)
                .join(
                    Conversa,
                    (Conversa.channel == coorte.c.channel)
                    & (Conversa.conversation_key == coorte.c.conversation_key),
                )
                .where(Conversa.status == Status.ATIVA)
            )
        ).scalar_one()
    )

    qualificados = int(
        (
            await session.execute(
                select(func.count())
                .select_from(coorte)
                .join(
                    LeadQualification,
                    (LeadQualification.channel == coorte.c.channel)
                    & (LeadQualification.conversation_key == coorte.c.conversation_key),
                )
                .where(LeadQualification.qualificado_em.is_not(None))
            )
        ).scalar_one()
    )

    temperaturas = {
        str(faixa): int(quantos)
        for faixa, quantos in (
            await session.execute(
                select(LeadQualification.temperatura, func.count())
                .select_from(coorte)
                .join(
                    LeadQualification,
                    (LeadQualification.channel == coorte.c.channel)
                    & (LeadQualification.conversation_key == coorte.c.conversation_key),
                )
                .where(LeadQualification.temperatura.is_not(None))
                .group_by(LeadQualification.temperatura)
            )
        ).all()
    }

    # Por lead: o instante da primeira fala dele e o da primeira saida nossa.
    # `MIN` dos dois na mesma agregacao, e a media das diferencas so de quem
    # tem os dois -- o lead nunca respondido fica FORA da media, porque
    # conta-lo como zero baixaria o indicador justamente quando o atendimento
    # esta pior.
    por_lead = (
        select(
            Message.channel.label("channel"),
            Message.conversation_key.label("conversation_key"),
            func.min(Message.created_at)
            .filter(Message.direction == MessageDirection.INBOUND)
            .label("falou_em"),
            func.min(Message.created_at)
            .filter(Message.direction == MessageDirection.OUTBOUND)
            .label("respondeu_em"),
        )
        .group_by(Message.channel, Message.conversation_key)
        .subquery()
    )
    primeira_resposta = (
        await session.execute(
            select(func.avg(func.extract("epoch", por_lead.c.respondeu_em - por_lead.c.falou_em)))
            .select_from(coorte)
            .join(
                por_lead,
                (por_lead.c.channel == coorte.c.channel)
                & (por_lead.c.conversation_key == coorte.c.conversation_key),
            )
            .where(por_lead.c.respondeu_em.is_not(None), por_lead.c.falou_em.is_not(None))
        )
    ).scalar_one_or_none()

    nascimento = _nascimento()
    ate_qualificar = (
        await session.execute(
            select(
                func.avg(
                    func.extract("epoch", LeadQualification.qualificado_em - nascimento.c.nasceu_em)
                )
            )
            .select_from(coorte)
            .join(
                nascimento,
                (nascimento.c.channel == coorte.c.channel)
                & (nascimento.c.conversation_key == coorte.c.conversation_key),
            )
            .join(
                LeadQualification,
                (LeadQualification.channel == coorte.c.channel)
                & (LeadQualification.conversation_key == coorte.c.conversation_key),
            )
            .where(LeadQualification.qualificado_em.is_not(None))
        )
    ).scalar_one_or_none()

    # **O denominador exclui `sla_limite_em IS NULL`**, e isto nao e escolha
    # desta card: a Emenda E-01 da RN-16.3 (TEC-178) decidiu e escreveu para
    # quem fosse calcular esta metrica. O handoff escalado sem destinatario
    # tem `sla_limite_em` nulo para sempre, e `dentroDoSla` sai true por
    # VACUIDADE, nunca por pontualidade -- inclui-lo infla a taxa.
    #
    # **O denominador NAO exclui `aceito_em IS NULL`, e essa e a diferenca
    # entre medir e mentir.** `escalada.py` grava `status=ESCALADO` sem tocar
    # `aceito_em`, entao o handoff que venceu o prazo e ninguem pegou tem
    # prazo preenchido e aceite nulo -- e ele e A FALHA de SLA. Excluir esses
    # removeria do denominador exatamente o que a metrica existe para contar:
    # nove estouros e um acerto dariam 100%.
    #
    # Entra no denominador o handoff cujo desfecho ja esta DECIDIDO: ou foi
    # aceito (a qualquer hora), ou o prazo ja passou. Um `PENDENTE` cujo
    # prazo ainda corre nao decidiu nada, e conta-lo como falha puniria a
    # pontualidade de quem ainda esta dentro da janela.
    agora = datetime.now(UTC)
    com_prazo = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(
                    Handoff.aceito_em.is_not(None),
                    Handoff.aceito_em <= Handoff.sla_limite_em,
                ),
            )
            .select_from(coorte)
            .join(
                Handoff,
                (Handoff.channel == coorte.c.channel)
                & (Handoff.conversation_key == coorte.c.conversation_key),
            )
            .where(
                Handoff.sla_limite_em.is_not(None),
                or_(Handoff.aceito_em.is_not(None), Handoff.sla_limite_em < agora),
            )
        )
    ).one()
    total_com_prazo, no_prazo = int(com_prazo[0]), int(com_prazo[1])

    return Indicadores(
        conversas_ativas=ativas,
        taxa_qualificacao=(qualificados / novos) if novos else None,
        distribuicao_por_temperatura=temperaturas,
        tempo_medio_primeira_resposta_seg=(
            float(primeira_resposta) if primeira_resposta is not None else None
        ),
        tempo_medio_qualificacao_seg=(
            float(ate_qualificar) if ate_qualificar is not None else None
        ),
        sla_handoff_cumprido_pct=(no_prazo / total_com_prazo) if total_com_prazo else None,
    )
