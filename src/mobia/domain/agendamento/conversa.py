"""Os tres turnos que marcam a visita conversando. TEC-371, RF-11, RF-12.

Esta e a peca que faltava ao epico: sete cards construiram o motor de
agendamento e nenhuma o ligou a conversa. Aqui ele ganha chamador.

**O estado e lido do banco, e nao guardado em memoria.** Cada etapa e uma
pergunta, nesta ordem:

  1. ha lembrete de 24h pendente? -> resposta ao lembrete (TEC-372)
  2. ha linha `RESERVADO` desta conversa? -> turno da confirmacao
  3. ha oferta de lista de espera de pe? -> aceite ou recusa (TEC-169)
  4. ha janelas propostas vivas? -> turno da escolha
  5. o lead pediu horario? -> turno da oferta

**O lembrete vem primeiro porque e o contexto mais especifico**: um lead com
visita marcada para amanha que escreve "cancelar" esta falando dela, e nao
pedindo horario novo. As etapas de 2 a 4 so existem quando ha uma conversa de
agendamento em curso, que por sua vez so existe se o lead acabou de pedir.

Entre as de baixo, a reserva vem na frente de proposito: depois de reservar,
as propostas sao apagadas (`propostas.py::apagar`), entao os dois estados
nunca coexistem -- mas a reserva VENCIDA precisa ser vista antes, porque e ela
que transforma um "sim" tardio em oferta nova em vez de em silencio.

**A espera fica entre a reserva e as propostas** (D8 da TEC-169), e nao
depois: ela e as propostas sao mutuamente exclusivas por construcao -- so se
oferece fila quando NAO houve janela, e sem janela nao ha proposta gravada.
Poe-la depois ordenaria duas coisas que nunca coexistem, e sugeriria ao
proximo leitor que coexistem.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.agendamento.alocacao import CriterioDoLead, alocar, criterio_de
from mobia.domain.agendamento.ciclo import Remarcado, Transicionado
from mobia.domain.agendamento.ciclo import cancelar as cancelar_agendamento
from mobia.domain.agendamento.ciclo import remarcar as remarcar_agendamento
from mobia.domain.agendamento.data_falada import (
    Ambigua,
    Dia,
    Instante,
    Periodo,
    data_e_hora_absolutas,
    janelas_para,
    resolver,
)
from mobia.domain.agendamento.deteccao import (
    RespostaAoLembrete,
    confirmou,
    quer_agendar,
    recusou,
    respondeu_ao_lembrete,
)
from mobia.domain.agendamento.escolha import Escolhida, escolher
from mobia.domain.agendamento.espera import (
    HORIZONTE_ESTENDIDO,
    TEXTO_DA_ESPERA_ACEITA,
    TEXTO_DA_LISTA_DE_ESPERA,
)
from mobia.domain.agendamento.fila import aceitar as aceitar_espera
from mobia.domain.agendamento.fila import ler_viva as ler_espera_viva
from mobia.domain.agendamento.fila import oferecer as oferecer_espera
from mobia.domain.agendamento.fila import recusar as recusar_espera
from mobia.domain.agendamento.janelas import (
    AgendaDoCorretor,
    ContadorDeVisitas,
    JanelaAlocada,
    TipoDeCompromisso,
    janelas_alocadas,
)
from mobia.domain.agendamento.mensagens import (
    TEXTO_DA_ESCOLHA,
    TEXTO_DA_PRESENCA_CONFIRMADA,
    TEXTO_DA_REMARCACAO,
    TEXTO_DA_RESERVA_VENCIDA,
    TEXTO_DAS_JANELAS,
    TEXTO_DE_OUTRO_HORARIO,
    TEXTO_DO_CANCELAMENTO_FEITO,
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
from mobia.domain.auditoria.vocabulario import ATOR_AGENTE
from mobia.domain.context.models import LeadQualification
from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.repositorio import listar_corretores
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho

# RN-11.5. O horizonte da busca de janela, e o mesmo numero que define o que
# conta como "sem disponibilidade": nao achar nada aqui e onde a lista de
# espera comeca. Desde a TEC-169 esse caminho tem desfecho -- `_oferecer`
# oferece a fila em vez de cair fora.
#
# **Nao confundir com `espera.py::HORIZONTE_ESTENDIDO`**: aquele so existe
# depois de o lead recusar a fila e pedir datas mais para frente, e nao muda o
# que a RN-11.5 considera indisponibilidade.
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
class PresencaConfirmada:
    """O lead disse que vai. TEC-372, RN-12.2.

    Carimba `presenca_confirmada_em` e **nao** mexe em `status`: o
    compromisso ja era `CONFIRMADO`, e presenca e fato sobre o lead. Ver a D3
    do desenho.
    """

    texto: str


@dataclass(frozen=True)
class Cancelou:
    """O agendamento caiu. Quem chama commita e SO ENTAO enfileira o e-mail.

    Carrega o texto porque o lead precisa saber agora, e o id porque o aviso
    ao corretor e job -- a mesma separacao de `Confirmou`, com a diferenca de
    que aqui o turno FALA: nenhum job manda mensagem ao lead sobre
    cancelamento.
    """

    texto: str
    agendamento_id: uuid.UUID


@dataclass(frozen=True)
class OfereceuEspera:
    """Nao ha janela nas proximas 72 horas, e a lista de espera foi oferecida.

    TEC-169, RN-11.5. Ate esta card o caminho devolvia `NadaAFazer` e o turno
    normal respondia com prosa generica -- a Emenda E-01 da RN-11.5 chama isso
    pelo nome: "nada registra que ele pediu".

    Carrega o id da linha porque o proximo turno precisa dela para aceitar ou
    recusar, e o texto porque a oferta nomeia as DUAS saidas na mesma frase
    (D5): entrar na fila, ou ver datas mais para frente.
    """

    texto: str
    espera_id: uuid.UUID


@dataclass(frozen=True)
class AceitouEspera:
    """O lead entrou na fila, e o handoff dele existe na mesma transacao.

    `handoff_id` nao e enfeite: quem chama commita, e e o commit que torna o
    par fila-mais-handoff atomico. Sem ele nao ha como um chamador conferir
    que as duas coisas sairam juntas.
    """

    texto: str
    espera_id: uuid.UUID
    handoff_id: uuid.UUID


@dataclass(frozen=True)
class NadaAFazer:
    pass


Resultado = (
    Ofereceu
    | Reservou
    | Confirmou
    | PresencaConfirmada
    | Cancelou
    | Perguntou
    | OfereceuEspera
    | AceitouEspera
    | NadaAFazer
)


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
    remarcando_id: uuid.UUID | None = None,
    horizonte: timedelta = HORIZONTE,
    oferecer_fila: bool = True,
) -> Resultado:
    """Uma rodada nova de janelas, gravada e dita ao lead.

    **Lista vazia oferece a lista de espera** (TEC-169, RN-11.5), e este e o
    unico sitio onde a condicao da regra e avaliada -- e o que faz os seis
    chamadores herdarem o comportamento sem cada um lembrar dele. `HORIZONTE`
    ja e as 72 horas da regra, e `janelas.py::propor_janelas` declara que
    "`ate` vem de quem chama".

    Ate a TEC-169 aqui se devolvia `NadaAFazer` e o turno normal respondia com
    prosa generica, porque nao havia texto verdadeiro a dizer: prometer que um
    corretor vai propor horario, ou que a gente avisa quando abrir, sao as
    duas frases que a TEC-174 e a TEC-286 proibiram. O que mudou nao foi a
    proibicao -- foi passar a existir a fila que torna a primeira metade
    verdadeira, e `TEXTO_DA_LISTA_DE_ESPERA` afirma so ela.

    **Quem esta remarcando nao entra na fila** (D2): com `remarcando_id`, a
    lista vazia continua devolvendo `NadaAFazer`. O agendamento original so
    vira `REAGENDADO` na escolha (D4 da TEC-372), entao sem janela ele
    continua `CONFIRMADO` -- e dizer a esse lead que ele esta sem horario
    seria falso.

    `horizonte` e `oferecer_fila` andam juntos e tem um chamador so: a recusa
    da fila (D6), que busca em `HORIZONTE_ESTENDIDO` e passa
    `oferecer_fila=False`. **O segundo nao e redundante com o primeiro.** Sem
    ele, um lead que recusou a fila e tampouco tem janela em catorze dias
    receberia a oferta de novo, no turno seguinte ao de tera recusado -- um
    laco que insiste no que ele acabou de dispensar.
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
        ate=agora + horizonte,
        tipo=TIPO,
    )
    imovel_id = await _imovel_de_interesse(
        session, channel=channel, conversation_key=conversation_key
    )
    if not janelas:
        # A rodada velha nao pode sobreviver a uma oferta que nao houve.
        await apagar_propostas(session, channel=channel, conversation_key=conversation_key)
        if remarcando_id is not None or not oferecer_fila:
            return NadaAFazer()
        espera = await oferecer_espera(
            session,
            channel=channel,
            conversation_key=conversation_key,
            imovel_id=imovel_id,
            agora=agora,
        )
        return OfereceuEspera(texto=TEXTO_DA_LISTA_DE_ESPERA, espera_id=espera.id)
    propostas = await gravar_propostas(
        session,
        channel=channel,
        conversation_key=conversation_key,
        janelas=janelas,
        tipo=TIPO,
        imovel_id=imovel_id,
        agora=agora,
        remarcando_id=remarcando_id,
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


async def _lembrete_pendente(
    session: AsyncSession, *, channel: str, conversation_key: str, agora: datetime
) -> Agendamento | None:
    """O agendamento cujo lembrete de 24 horas ja saiu e cuja visita nao comecou.

    **E este predicado que autoriza ler "cancelar" como cancelamento** (D1).
    Fora dele a palavra e comum -- "cancela aquele outro assunto" -- e nao
    pode derrubar visita nenhuma; o quarto cenario do Gherkin e exatamente
    isso.

    As tres condicoes: `CONFIRMADO` (existe compromisso vivo),
    `lembrete_24h_em` preenchido (a pergunta com as tres opcoes ja foi feita
    -- quem carimba e `sweep_lembretes`), e `inicio > agora` (a visita ainda
    nao comecou).

    **A janela fecha no INICIO da visita, e nao no lembrete de 2 horas.**
    Cancelar noventa minutos antes e legitimo, e e quando mais importa que
    alguem ouca; fechar no marco de 2 h devolveria silencio na hora de maior
    custo. O lembrete de 2 h nao oferece opcao nenhuma, entao ele nao abre
    uma segunda janela -- acontece dentro desta.
    """
    return (
        await session.execute(
            select(Agendamento)
            .where(
                Agendamento.channel == channel,
                Agendamento.conversation_key == conversation_key,
                Agendamento.status == StatusDoAgendamento.CONFIRMADO,
                Agendamento.lembrete_24h_em.is_not(None),
                Agendamento.inicio > agora,
            )
            .order_by(Agendamento.inicio)
            .limit(1)
        )
    ).scalar_one_or_none()


async def _confirmar_presenca(
    session: AsyncSession, agendamento: Agendamento, *, agora: datetime
) -> Resultado:
    """Carimba a coluna e responde. Nao toca em `status` -- ver a D3.

    O `WHERE` repete o status e a ausencia do carimbo: entre ler e gravar,
    outro turno da mesma conversa pode ter cancelado, e confirmar presenca em
    visita cancelada seria gravar um fato sobre algo que nao existe mais.
    """
    await session.execute(
        update(Agendamento)
        .where(
            Agendamento.id == agendamento.id,
            Agendamento.status == StatusDoAgendamento.CONFIRMADO,
        )
        .values(presenca_confirmada_em=agora)
    )
    return PresencaConfirmada(
        texto=TEXTO_DA_PRESENCA_CONFIRMADA.format(quando=data_e_hora_absolutas(agendamento.inicio))
    )


async def _remarcar(
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
    """A escolha do lead move o agendamento que ele ja tinha. D4 e D5.

    **`remarcar` levanta `IntegrityError` na sobreposicao, e isso e
    deliberado do outro lado**: a docstring dela diz que engolir a recusa do
    banco como `Conflito` faria a remarcacao falhar em silencio com o
    original ja `REAGENDADO`. Esta e a card que chega como chamadora, entao a
    decisao e daqui -- capturar, desfazer so o SAVEPOINT e oferecer de novo.

    O `begin_nested` e o mesmo mecanismo de `repositorio.py::reservar`, e pelo
    mesmo motivo que aquela docstring registra: um `rollback` de sessao
    inteira expira todo objeto carregado e explode com `MissingGreenlet` no
    acesso seguinte.

    O lead perdeu a corrida pelo horario novo e **continua com o antigo**,
    que e o desfecho certo: melhor manter a visita que perder as duas.
    """
    assert proposta.remarcando_id is not None  # so chega aqui com destino
    try:
        async with session.begin_nested():
            desfecho = await remarcar_agendamento(
                session,
                agendamento_id=proposta.remarcando_id,
                janela=proposta.janela,
                agora=agora,
                corretor_id=proposta.corretor_id,
            )
            await session.flush()
    except IntegrityError:
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
            remarcando_id=proposta.remarcando_id,
        )
    if not isinstance(desfecho, Remarcado):
        # O original saiu de `CONFIRMADO` entre a oferta e a escolha (outro
        # turno cancelou, ou a visita comecou). Oferecer de novo criaria
        # agendamento novo sem ninguem pedir; cair fora deixa o turno normal
        # responder.
        await apagar_propostas(session, channel=channel, conversation_key=conversation_key)
        return NadaAFazer()
    await apagar_propostas(session, channel=channel, conversation_key=conversation_key)
    return Confirmou(agendamento_id=desfecho.novo_id)


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
    # Etapa 1: a resposta ao lembrete vem ANTES de tudo, e a ordem e decisao
    # (D7). Um lead com visita marcada para amanha que escreve "cancelar"
    # esta falando dela, e nao pedindo horario novo. As etapas abaixo so
    # existem quando ha uma conversa de agendamento em curso, que por sua vez
    # so existe se o lead acabou de pedir.
    lembrete = await _lembrete_pendente(
        session, channel=channel, conversation_key=conversation_key, agora=agora
    )
    if lembrete is not None:
        match respondeu_ao_lembrete(texto):
            case RespostaAoLembrete.CONFIRMA:
                return await _confirmar_presenca(session, lembrete, agora=agora)
            case RespostaAoLembrete.CANCELAR:
                desfecho_do_ciclo = await cancelar_agendamento(
                    session, agendamento_id=lembrete.id, agora=agora
                )
                if isinstance(desfecho_do_ciclo, Transicionado):
                    # As propostas de qualquer rodada aberta caem junto: o
                    # compromisso a que elas se referiam nao existe mais.
                    await apagar_propostas(
                        session, channel=channel, conversation_key=conversation_key
                    )
                    return Cancelou(
                        texto=TEXTO_DO_CANCELAMENTO_FEITO.format(
                            quando=data_e_hora_absolutas(lembrete.inicio)
                        ),
                        agendamento_id=lembrete.id,
                    )
                # Origem ilegal: outro turno mexeu no status entre a leitura e
                # o UPDATE. Cair fora e mais honesto que dizer "cancelei".
                return NadaAFazer()
            case RespostaAoLembrete.REMARCAR:
                return await _oferecer(
                    session,
                    channel=channel,
                    conversation_key=conversation_key,
                    estado=estado,
                    agora=agora,
                    agenda=agenda,
                    visitas=visitas,
                    texto=texto,
                    molde=TEXTO_DA_REMARCACAO,
                    remarcando_id=lembrete.id,
                )
            case None:
                # Nao respondeu ao lembrete -- pode estar falando de outra
                # coisa. Segue para as etapas de agendamento novo.
                pass

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

    # Etapa 3: a oferta de lista de espera de pe (TEC-169, RN-11.5). Entre a
    # reserva e as propostas pela razao que a docstring do modulo guarda -- as
    # duas nunca coexistem, e ordena-las sugeriria que sim.
    #
    # `confirmou`/`recusou` sao reusados, e AQUI isso e seguro, ao contrario
    # do que a D2 da TEC-372 decidiu para o lembrete. La o "nao" ambiguo
    # escolhia entre derrubar uma visita marcada e remarca-la, sem tela para
    # desfazer; aqui os dois desfechos sao baratos e reversiveis -- entrar
    # numa fila, ou ver mais horarios --, e quem caiu no lado errado corrige
    # na fala seguinte.
    espera = await ler_espera_viva(session, channel=channel, conversation_key=conversation_key)
    if espera is not None and espera.aceita_em is None:
        if confirmou(texto):
            handoff = await registrar_handoff(
                session,
                channel=channel,
                conversation_key=conversation_key,
                gatilho=Gatilho.SEM_DISPONIBILIDADE,
                ator=ATOR_AGENTE,
            )
            await aceitar_espera(session, espera_id=espera.id, handoff_id=handoff.id, agora=agora)
            return AceitouEspera(
                texto=TEXTO_DA_ESPERA_ACEITA, espera_id=espera.id, handoff_id=handoff.id
            )
        if recusou(texto):
            await recusar_espera(session, espera_id=espera.id, agora=agora)
            # Sem `oferecer_fila`, a ausencia de janela em catorze dias
            # devolveria a oferta que ele acabou de recusar.
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
                horizonte=HORIZONTE_ESTENDIDO,
                oferecer_fila=False,
            )
        # Nem sim nem nao: NAO intercepta, e segue a cascata. E o que faz o
        # lead que INSISTE ("quero marcar visita", com a oferta de pe)
        # receber a oferta de novo em vez de prosa generica -- a etapa 5
        # chama `_oferecer`, que nao acha janela e cai em `oferecer_espera`,
        # que por sua vez devolve a linha viva sem criar outra.
        #
        # Interceptar com `NadaAFazer` aqui seria devolver ao lead exatamente
        # o silencio que esta card existe para tirar. Quem fala de outra coisa
        # ("quanto e o condominio?") cai fora na etapa 5, onde `quer_agendar`
        # e falso, e a oferta continua de pe para o turno seguinte.

    propostas = await ler_propostas(
        session, channel=channel, conversation_key=conversation_key, agora=agora
    )
    if propostas:
        escolha = escolher(texto, propostas, agora=agora)
        if isinstance(escolha, Escolhida):
            # Dois destinos para a mesma escolha (D4): com `remarcando_id`,
            # ela move o agendamento que o lead ja tem; sem, ela reserva um
            # novo.
            if escolha.proposta.remarcando_id is not None:
                return await _remarcar(
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
