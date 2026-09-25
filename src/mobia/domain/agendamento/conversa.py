"""Os tres turnos que marcam a visita conversando. TEC-371, RF-11, RF-12.

Esta e a peca que faltava ao epico: sete cards construiram o motor de
agendamento e nenhuma o ligou a conversa. Aqui ele ganha chamador.

**O estado dos tres turnos e lido do banco, e nao guardado em memoria.** Cada
um deles e uma pergunta:

  - ha linha `RESERVADO` desta conversa? -> turno da confirmacao
  - ha janelas propostas vivas? -> turno da escolha
  - o lead pediu horario? -> turno da oferta

A ordem e essa, e a reserva vem na frente de proposito: depois de reservar,
as propostas sao apagadas (`propostas.py::apagar`), entao os dois estados
nunca coexistem -- mas a reserva VENCIDA precisa ser vista antes de qualquer
outra coisa, porque e ela que transforma um "sim" tardio em oferta nova em
vez de em silencio.

**Nos dois ultimos, texto que nao case nada cai fora** (`NadaAFazer`) e o
turno segue normal. E isso que limita o custo de um falso positivo do
detector: o sequestro da conversa dura um turno, nao uma sessao. O lead que
pergunta "quanto e o condominio?" no meio da escolha recebe o valor do
condominio.

**Nao commita.** A sessao e emprestada, como em todo o resto de
`domain/agendamento/`. Quem chama commita e so entao enfileira o aviso da
RN-12.1 -- ver a D6 do desenho.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agendamento.alocacao import CriterioDoLead, alocar, criterio_de
from mobia.domain.agendamento.data_falada import (
    Ambigua,
    Dia,
    Instante,
    Periodo,
    data_e_hora_absolutas,
    janelas_para,
    resolver,
)
from mobia.domain.agendamento.deteccao import confirmou, quer_agendar, recusou
from mobia.domain.agendamento.escolha import Escolhida, escolher
from mobia.domain.agendamento.janelas import (
    AgendaDoCorretor,
    ContadorDeVisitas,
    JanelaAlocada,
    TipoDeCompromisso,
    janelas_alocadas,
)
from mobia.domain.agendamento.mensagens import (
    TEXTO_DA_ESCOLHA,
    TEXTO_DA_RESERVA_VENCIDA,
    TEXTO_DAS_JANELAS,
    TEXTO_DE_OUTRO_HORARIO,
    TEXTO_DO_CONFLITO,
    linhas_das_janelas,
)
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.propostas import Proposta
from mobia.domain.agendamento.propostas import apagar as apagar_propostas
from mobia.domain.agendamento.propostas import gravar as gravar_propostas
from mobia.domain.agendamento.propostas import ler as ler_propostas
from mobia.domain.agendamento.repositorio import Confirmado, Reserva, reservar_ou_alternativas
from mobia.domain.agendamento.repositorio import confirmar as confirmar_reserva
from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.schemas import ReacaoLead
from mobia.domain.context.models import LeadQualification
from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.repositorio import listar_corretores

# RN-11.5. O horizonte da busca de janela, e o mesmo numero que define o que
# conta como "sem disponibilidade": nao achar nada aqui e onde a TEC-169
# comeca. Esta card so cai fora (D8).
HORIZONTE = timedelta(hours=72)

# O unico tipo que a conversa marca. Reuniao remota nao tem vocabulario
# proprio no detector (D2 do desenho), entao nenhum caminho de conversa a
# produz -- e gravar `REUNIAO_REMOTA` sem que nada a peca seria um dado que
# nenhuma fala justifica.
TIPO = TipoDeCompromisso.VISITA_PRESENCIAL

# O kind mora no modulo que possui o comportamento, como manda a docstring de
# `outbound/kinds.py`. Um so para as quatro variantes de texto: a
# `UNIQUE (message_id, kind)` de `outbound_dispatches` e por mensagem, e o
# agendamento manda no maximo um texto por turno -- kinds separados por
# variante nao protegeriam nada e multiplicariam o vocabulario.
KIND_DO_AGENDAMENTO = "agendamento"

# Sem ele a telemetria deste caminho ficaria rotulada "moderacao", que e o
# default de `_entregar_texto_fixo` e o defeito que a docstring daquela
# funcao ja registra.
SUBAGENTE_AGENDAMENTO = "agendamento"


@dataclass(frozen=True)
class Ofereceu:
    """Janelas novas para o lead, com o texto que explica de onde elas vem.

    O texto vem pronto de proposito. As quatro variantes -- oferta, conflito,
    reserva vencida e recusa -- so se distinguem aqui dentro, e devolver so o
    tipo obrigaria quem chama a refazer a mesma arvore de decisao.
    """

    texto: str
    propostas: list[Proposta]


@dataclass(frozen=True)
class Reservou:
    texto: str
    reserva_id: uuid.UUID


@dataclass(frozen=True)
class Confirmou:
    """O agendamento existe. Quem chama commita e SO ENTAO enfileira o aviso.

    Sem texto, e a ausencia e decisao (D6): quem manda a mensagem de
    confirmacao ao lead e o job da RN-12.1, que ja a monta com data, hora,
    endereco e nome do corretor. Um texto nosso aqui seria a segunda mensagem
    dizendo a mesma coisa, com menos dados.
    """

    agendamento_id: uuid.UUID


@dataclass(frozen=True)
class Perguntou:
    """A data falada nao decide, e a pergunta ja vem pronta da TEC-167.

    `data_falada::resolver` devolve `Ambigua` com o texto exato a fazer --
    "Aos domingos nao ha atendimento. Pode ser {dia}?", "Esse horario ja
    passou...". Chutar uma data no lugar de perguntar e o RT-10: visita
    marcada no dia errado.
    """

    texto: str


@dataclass(frozen=True)
class NadaAFazer:
    pass


Resultado = Ofereceu | Reservou | Confirmou | Perguntou | NadaAFazer


async def _reserva_pendente(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> Agendamento | None:
    """A linha `RESERVADO` desta conversa, **vencida ou nao**.

    Sem filtro por `reservado_ate` de proposito. Quem julga a validade e
    `repositorio.py::confirmar`, num UPDATE so com a condicao inteira no
    WHERE -- e e justamente a reserva vencida que precisa ser encontrada
    aqui, senao o "sim" tardio do lead cairia no turno normal e ele ficaria
    sem saber que o horario se perdeu.
    """
    return (
        await session.execute(
            select(Agendamento)
            .where(
                Agendamento.channel == channel,
                Agendamento.conversation_key == conversation_key,
                Agendamento.status == StatusDoAgendamento.RESERVADO,
            )
            .order_by(Agendamento.criado_em.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _expirar(session: AsyncSession, reserva_id: uuid.UUID) -> None:
    """Marca EXPIRADO a reserva que nao vingou, para ela nao voltar no proximo turno.

    **`EXPIRADO` e nao `CANCELADO`, e a escolha tem consequencia visivel.**
    `ciclo.py::cancelar` aceita `RESERVADO` como origem e liberaria o slot do
    mesmo jeito -- mas `sweep_remarcacoes` varre exatamente os `CANCELADO` e
    convidaria o lead a remarcar uma visita que nunca existiu. `EXPIRADO` e
    inerte para as duas varreduras, que e o que se quer de uma reserva que o
    lead recusou ou deixou vencer.

    O `WHERE` repete o status: entre ler e gravar, outro turno da mesma
    conversa pode ter confirmado.
    """
    await session.execute(
        update(Agendamento)
        .where(
            Agendamento.id == reserva_id,
            Agendamento.status == StatusDoAgendamento.RESERVADO,
        )
        .values(status=StatusDoAgendamento.EXPIRADO)
    )


async def _imovel_de_interesse(
    session: AsyncSession, *, channel: str, conversation_key: str
) -> uuid.UUID | None:
    """O ultimo imovel que o lead marcou com interesse, se houver.

    `None` e resultado legitimo e nao falta de dado: a visita acontece assim
    mesmo, e `TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL` existe desde a
    TEC-170 exatamente para esse caso. Forcar o lead a escolher um imovel
    antes de marcar horario seria inventar uma etapa que a RF-11 nao tem.
    """
    return (
        await session.execute(
            select(Recomendacao.imovel_id)
            .where(
                Recomendacao.channel == channel,
                Recomendacao.conversation_key == conversation_key,
                Recomendacao.reacao_lead == ReacaoLead.INTERESSE,
            )
            .order_by(Recomendacao.apresentado_em.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _janelas_da_data_falada(
    *,
    texto: str,
    criterio: CriterioDoLead,
    corretores: Sequence[Corretor],
    agenda: AgendaDoCorretor,
    visitas: ContadorDeVisitas,
    agora: datetime,
) -> list[JanelaAlocada] | Ambigua | None:
    """As janelas DAQUELE dia, quando o lead nomeou um.

    **E a CA-11.1 inteira**: "pode ser quinta de manha?" tem de responder com
    horarios daquela quinta, e nao com a grade dos proximos tres dias. Quem
    faz a ponte entre a data falada e o motor e `data_falada::janelas_para`,
    que a TEC-167 construiu exatamente para isto e ficou sem chamador.

    A diferenca em relacao a `janelas_alocadas` nao e so o recorte: aquela da
    UMA janela por dia, para espalhar a escolha entre datas; esta da ate tres
    no mesmo dia, porque o lead ja escolheu o dia e o que falta e a hora.

    `None` significa "a fala nao nomeia data, ou nao ha janela naquele dia" --
    quem chama cai para a grade dos proximos tres dias em vez de deixar o lead
    sem nada.
    """
    resolucao = resolver(texto, agora=agora)
    if isinstance(resolucao, Ambigua):
        return resolucao
    if not isinstance(resolucao, Dia | Periodo | Instante):
        # `Semana` e `NaoReconhecida`. A semana inteira nao e um recorte de
        # dia, e a grade de tres dias ja e a resposta certa para ela.
        return None

    fuso = get_settings().fuso_de_envio
    if isinstance(resolucao, Instante):
        dia = resolucao.momento.astimezone(fuso).date()
    else:
        dia = resolucao.dia

    contagem = await visitas.visitas_por_dia(
        [corretor.id for corretor in corretores], de=dia, ate=dia, agora=agora
    )
    visitas_na_data = {corretor_id: n for (corretor_id, data), n in contagem.items() if data == dia}
    fim_do_dia = datetime.combine(dia, time(0), tzinfo=fuso) + timedelta(days=1)

    # Desce pelos candidatos ate um ter horario livre naquele dia, o mesmo que
    # `janelas_alocadas` faz -- capacidade cheia ou agenda cheia nao pode
    # encerrar a busca no primeiro nome.
    for alocacao in alocar(
        criterio=criterio, corretores=corretores, visitas_na_data=visitas_na_data
    ):
        ocupados = await agenda.ocupados(alocacao.corretor.id, agora, fim_do_dia)
        encontradas = janelas_para(
            resolucao,
            agora=agora,
            jornada_inicio=alocacao.corretor.horario_inicio,
            jornada_fim=alocacao.corretor.horario_fim,
            ocupados=ocupados,
            tipo=TIPO,
        )
        if isinstance(encontradas, list) and encontradas:
            return [
                JanelaAlocada(
                    janela=janela, corretor_id=alocacao.corretor.id, motivo=alocacao.motivo
                )
                for janela in encontradas
            ]
    return None


async def _oferecer(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    estado: LeadQualification | None,
    agora: datetime,
    agenda: AgendaDoCorretor,
    visitas: ContadorDeVisitas,
    texto: str,
    molde: str,
) -> Resultado:
    """Uma rodada nova de janelas, gravada e dita ao lead.

    Lista vazia devolve `NadaAFazer`, e o turno segue normal. E a D8: nao ha
    texto verdadeiro para "sem horario nas proximas 72 horas" que esta card
    possa dizer -- prometer que um corretor vai propor horario, ou que a
    gente avisa quando abrir, sao as duas frases que a TEC-174 e a TEC-286
    proibiram. Quem fecha a lacuna e a lista de espera da TEC-169.
    """
    corretores = await listar_corretores(session, apenas_ativos=True)
    if not corretores:
        return NadaAFazer()
    # Sem qualificacao gravada o criterio nasce vazio, e criterio vazio nunca
    # tem match exato: `alocar` cai no plantao generalista, que e o que a
    # RN-11.2 manda fazer. Nao e motivo para recusar o agendamento.
    criterio = criterio_de(estado) if estado is not None else CriterioDoLead(None, None)
    # A data que o lead falou manda, quando ele falou uma (CA-11.1).
    da_data = await _janelas_da_data_falada(
        texto=texto,
        criterio=criterio,
        corretores=corretores,
        agenda=agenda,
        visitas=visitas,
        agora=agora,
    )
    if isinstance(da_data, Ambigua):
        return Perguntou(texto=da_data.pergunta)
    janelas = da_data or await janelas_alocadas(
        criterio=criterio,
        corretores=corretores,
        agenda=agenda,
        visitas=visitas,
        agora=agora,
        ate=agora + HORIZONTE,
        tipo=TIPO,
    )
    if not janelas:
        # A rodada velha nao pode sobreviver a uma oferta que nao houve.
        await apagar_propostas(session, channel=channel, conversation_key=conversation_key)
        return NadaAFazer()
    imovel_id = await _imovel_de_interesse(
        session, channel=channel, conversation_key=conversation_key
    )
    propostas = await gravar_propostas(
        session,
        channel=channel,
        conversation_key=conversation_key,
        janelas=janelas,
        tipo=TIPO,
        imovel_id=imovel_id,
        agora=agora,
    )
    resposta = molde.format(janelas=linhas_das_janelas([p.janela.inicio for p in propostas]))
    return Ofereceu(texto=resposta, propostas=propostas)


async def _reservar(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    proposta: Proposta,
    estado: LeadQualification | None,
    agora: datetime,
    agenda: AgendaDoCorretor,
    visitas: ContadorDeVisitas,
    texto: str,
) -> Resultado:
    """A escolha do lead vira reserva de 5 minutos, ou alternativas.

    `reservar_ou_alternativas` e nao `reservar`: em conflito ela ja devolve
    as janelas que sobraram no mesmo corretor, respeitando a capacidade
    diaria dele. E dali que sai a CA-11.2 sem uma linha de codigo nova.
    """
    corretor = await session.get(Corretor, proposta.corretor_id)
    if corretor is None or not corretor.ativo:
        # O corretor saiu entre a oferta e a escolha. Oferecer de novo
        # realoca; insistir naquele corretor gravaria visita com quem nao
        # atende mais.
        return await _oferecer(
            session,
            channel=channel,
            conversation_key=conversation_key,
            estado=estado,
            agora=agora,
            agenda=agenda,
            visitas=visitas,
            texto=texto,
            molde=TEXTO_DO_CONFLITO,
        )
    resultado = await reservar_ou_alternativas(
        session,
        corretor=corretor,
        agenda=agenda,
        visitas=visitas,
        channel=channel,
        conversation_key=conversation_key,
        janela=proposta.janela,
        tipo=proposta.tipo,
        imovel_id=proposta.imovel_id,
        agora=agora,
        ate=agora + HORIZONTE,
        motivo=proposta.motivo,
    )
    if isinstance(resultado, Reserva):
        # As propostas saem de cena: daqui em diante o estado da conversa e a
        # reserva, e deixa-las de pe faria o "sim" tardio ser lido como
        # escolha de janela em vez de virar oferta nova.
        await apagar_propostas(session, channel=channel, conversation_key=conversation_key)
        return Reservou(
            texto=TEXTO_DA_ESCOLHA.format(
                quando=data_e_hora_absolutas(resultado.janela.inicio), corretor=corretor.nome
            ),
            reserva_id=resultado.id,
        )
    alternativas = [
        JanelaAlocada(janela=janela, corretor_id=corretor.id, motivo=proposta.motivo)
        for janela in resultado
    ]
    if not alternativas:
        await apagar_propostas(session, channel=channel, conversation_key=conversation_key)
        return NadaAFazer()
    imovel_id = proposta.imovel_id
    novas = await gravar_propostas(
        session,
        channel=channel,
        conversation_key=conversation_key,
        janelas=alternativas,
        tipo=proposta.tipo,
        imovel_id=imovel_id,
        agora=agora,
    )
    return Ofereceu(
        texto=TEXTO_DO_CONFLITO.format(
            janelas=linhas_das_janelas([p.janela.inicio for p in novas])
        ),
        propostas=novas,
    )


async def atender(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    texto: str,
    estado: LeadQualification | None,
    agora: datetime,
    agenda: AgendaDoCorretor,
    visitas: ContadorDeVisitas,
) -> Resultado:
    """O que a conversa de agendamento faz com esta fala do lead.

    Devolve `NadaAFazer` sempre que a fala nao e sobre agendamento, e e esse
    o desfecho mais comum: quem chama segue o turno normal.
    """
    reserva = await _reserva_pendente(session, channel=channel, conversation_key=conversation_key)
    if reserva is not None:
        # `confirmou` antes de `recusou`, e a ordem e decisao: "nao, pode ser"
        # e o lead se corrigindo, e a guarda de pausa do detector ja a le como
        # assentimento. Ver a docstring de `deteccao.py::confirmou`.
        if confirmou(texto):
            desfecho = await confirmar_reserva(session, reserva_id=reserva.id, agora=agora)
            if isinstance(desfecho, Confirmado):
                return Confirmou(agendamento_id=desfecho.id)
            await _expirar(session, reserva.id)
            return await _oferecer(
                session,
                channel=channel,
                conversation_key=conversation_key,
                estado=estado,
                agora=agora,
                agenda=agenda,
                visitas=visitas,
                texto=texto,
                molde=TEXTO_DA_RESERVA_VENCIDA,
            )
        if recusou(texto):
            await _expirar(session, reserva.id)
            return await _oferecer(
                session,
                channel=channel,
                conversation_key=conversation_key,
                estado=estado,
                agora=agora,
                agenda=agenda,
                visitas=visitas,
                texto=texto,
                molde=TEXTO_DE_OUTRO_HORARIO,
            )
        return NadaAFazer()

    propostas = await ler_propostas(
        session, channel=channel, conversation_key=conversation_key, agora=agora
    )
    if propostas:
        escolha = escolher(texto, propostas, agora=agora)
        if isinstance(escolha, Escolhida):
            return await _reservar(
                session,
                channel=channel,
                conversation_key=conversation_key,
                proposta=escolha.proposta,
                estado=estado,
                agora=agora,
                agenda=agenda,
                visitas=visitas,
                texto=texto,
            )
        # Nao escolheu. Pode ser que esteja pedindo horario de novo -- e ai
        # vale uma rodada nova --, e pode ser que esteja falando de outra
        # coisa, e ai o turno normal e a resposta certa.

    if not quer_agendar(texto, agora=agora):
        return NadaAFazer()
    return await _oferecer(
        session,
        channel=channel,
        conversation_key=conversation_key,
        estado=estado,
        agora=agora,
        agenda=agenda,
        visitas=visitas,
        texto=texto,
        molde=TEXTO_DAS_JANELAS,
    )
