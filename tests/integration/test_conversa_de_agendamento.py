"""Os tres turnos que marcam a visita, contra o banco. TEC-371, D3.

`agora` e literal em todo teste: "reservado ha 6 minutos" e aritmetica sobre
ele, sem dormir. A agenda e a `AgendaPostgres` de verdade -- e ela le so o
que ja foi commitado, que e o que o motor de janelas precisa enxergar.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from mobia.domain.agendamento.conversa import (
    Cancelou,
    Confirmou,
    NadaAFazer,
    Ofereceu,
    Perguntou,
    PresencaConfirmada,
    Reservou,
    atender,
)
from mobia.domain.agendamento.janelas import TipoDeCompromisso
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.agendamento.propostas import ler as ler_propostas
from mobia.domain.agendamento.repositorio import AgendaPostgres
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.schemas import ReacaoLead
from mobia.domain.catalogo.models import Imovel
from mobia.domain.corretores.models import Corretor

SP = ZoneInfo("America/Sao_Paulo")
# Terca-feira, 29 de setembro de 2026, as 10h. A antecedencia minima de 3h
# joga a primeira janela para as 13h do mesmo dia.
AGORA = datetime(2026, 9, 29, 10, 0, tzinfo=SP)
CANAL = "whatsapp"
LEAD = "5511999990000"


async def _atender(session, session_factory, texto: str, *, agora=AGORA, lead=LEAD):
    agenda = AgendaPostgres(session_factory)
    return await atender(
        session,
        channel=CANAL,
        conversation_key=lead,
        texto=texto,
        estado=None,
        agora=agora,
        agenda=agenda,
        visitas=agenda,
    )


async def _corretor(semear_corretor, *, email: str = "corretor@x.com") -> Corretor:
    return await semear_corretor(email=email, plantao=True)


async def _imovel(session) -> uuid.UUID:
    """Um imovel disponivel. Copiado de test_confirmacao_do_agendamento.py --
    os arquivos de integracao deste repo sao autocontidos."""
    identificador = uuid.uuid4()
    session.add(
        Imovel(
            id=identificador,
            codigo="AP-371",
            titulo="Apartamento na Vila Mariana",
            descricao="Sala ampla com varanda.",
            tipo="APARTAMENTO",
            operacao="VENDA",
            preco_venda=74900000,
            bairro="Moema",
            bairro_busca="moema",
            cidade="São Paulo",
            uf="SP",
            area_util_m2=78,
            quartos=3,
            suites=1,
            banheiros=2,
            vagas=2,
            caracteristicas=["varanda"],
            fotos=[],
            status="DISPONIVEL",
        )
    )
    await session.commit()
    return identificador


async def _linhas(session, *, lead: str = LEAD) -> list[Agendamento]:
    return list(
        (
            await session.execute(
                select(Agendamento).where(
                    Agendamento.channel == CANAL, Agendamento.conversation_key == lead
                )
            )
        )
        .scalars()
        .all()
    )


async def test_o_pedido_de_horario_vira_ate_tres_janelas(
    session, session_factory, semear_corretor
) -> None:
    await _corretor(semear_corretor)
    await session.commit()

    resultado = await _atender(session, session_factory, "quero agendar uma visita")

    assert isinstance(resultado, Ofereceu)
    assert 1 <= len(resultado.propostas) <= 3
    assert "1." in resultado.texto
    await session.commit()
    assert len(await ler_propostas(session, channel=CANAL, conversation_key=LEAD, agora=AGORA)) == (
        len(resultado.propostas)
    )


async def test_sem_corretor_ativo_nao_faz_nada(session, session_factory) -> None:
    assert isinstance(
        await _atender(session, session_factory, "quero agendar uma visita"), NadaAFazer
    )


async def test_a_escolha_vira_reserva_de_cinco_minutos(
    session, session_factory, semear_corretor
) -> None:
    await _corretor(semear_corretor)
    await session.commit()
    oferta = await _atender(session, session_factory, "quero agendar uma visita")
    assert isinstance(oferta, Ofereceu)
    await session.commit()

    escolha = await _atender(session, session_factory, "a primeira")

    assert isinstance(escolha, Reservou)
    await session.commit()
    linhas = await _linhas(session)
    assert [linha.status for linha in linhas] == [StatusDoAgendamento.RESERVADO]
    assert linhas[0].reservado_ate == AGORA + timedelta(minutes=5)
    assert linhas[0].inicio == oferta.propostas[0].janela.inicio
    # As propostas saem de cena: daqui em diante o estado e a reserva.
    assert await ler_propostas(session, channel=CANAL, conversation_key=LEAD, agora=AGORA) == []
    # A pergunta repete o horario por extenso -- RN-11.3.
    assert "de outubro" in escolha.texto or "de setembro" in escolha.texto


async def test_o_sim_confirma(session, session_factory, semear_corretor) -> None:
    await _corretor(semear_corretor)
    await session.commit()
    await _atender(session, session_factory, "quero agendar uma visita")
    await session.commit()
    await _atender(session, session_factory, "a primeira")
    await session.commit()

    resultado = await _atender(session, session_factory, "isso, pode marcar")

    assert isinstance(resultado, Confirmou)
    await session.commit()
    linhas = await _linhas(session)
    assert [linha.status for linha in linhas] == [StatusDoAgendamento.CONFIRMADO]
    assert linhas[0].id == resultado.agendamento_id
    assert linhas[0].confirmado_em == AGORA


async def test_o_sim_tarde_demais_oferece_de_novo(
    session, session_factory, semear_corretor
) -> None:
    """O terceiro cenario do Gherkin: a reserva venceu e o lead nao fica sem resposta."""
    await _corretor(semear_corretor)
    await session.commit()
    await _atender(session, session_factory, "quero agendar uma visita")
    await session.commit()
    await _atender(session, session_factory, "a primeira")
    await session.commit()

    tarde = AGORA + timedelta(minutes=6)
    resultado = await _atender(session, session_factory, "isso, pode marcar", agora=tarde)

    assert isinstance(resultado, Ofereceu)
    assert "expirou" in resultado.texto
    await session.commit()
    # A reserva morta nao pode voltar no proximo turno.
    linhas = await _linhas(session)
    assert [linha.status for linha in linhas] == [StatusDoAgendamento.EXPIRADO]


async def test_a_recusa_oferece_outro_horario(session, session_factory, semear_corretor) -> None:
    await _corretor(semear_corretor)
    await session.commit()
    await _atender(session, session_factory, "quero agendar uma visita")
    await session.commit()
    await _atender(session, session_factory, "a primeira")
    await session.commit()

    resultado = await _atender(session, session_factory, "nao, prefiro outro dia")

    assert isinstance(resultado, Ofereceu)
    await session.commit()
    assert [linha.status for linha in await _linhas(session)] == [StatusDoAgendamento.EXPIRADO]


async def test_pergunta_fora_do_assunto_nao_sequestra_a_conversa(
    session, session_factory, semear_corretor
) -> None:
    """O custo do falso positivo fica limitado a um turno, e este e o teste disso."""
    await _corretor(semear_corretor)
    await session.commit()
    await _atender(session, session_factory, "quero agendar uma visita")
    await session.commit()

    assert isinstance(
        await _atender(session, session_factory, "quanto e o condominio?"), NadaAFazer
    )
    await session.commit()
    # E as propostas continuam de pe para o turno seguinte.
    assert len(await ler_propostas(session, channel=CANAL, conversation_key=LEAD, agora=AGORA)) >= 1


async def test_com_reserva_viva_o_que_nao_e_sim_nem_nao_cai_fora(
    session, session_factory, semear_corretor
) -> None:
    await _corretor(semear_corretor)
    await session.commit()
    await _atender(session, session_factory, "quero agendar uma visita")
    await session.commit()
    await _atender(session, session_factory, "a primeira")
    await session.commit()

    assert isinstance(
        await _atender(session, session_factory, "o imovel tem vaga de garagem?"), NadaAFazer
    )
    await session.commit()
    assert [linha.status for linha in await _linhas(session)] == [StatusDoAgendamento.RESERVADO]


async def test_dois_leads_no_mesmo_slot(session, session_factory, semear_corretor) -> None:
    """CA-11.2: um agendamento e criado, o outro recebe alternativas."""
    await _corretor(semear_corretor)
    await session.commit()
    outro = "5511888880000"

    for chave in (LEAD, outro):
        await _atender(session, session_factory, "quero agendar uma visita", lead=chave)
        await session.commit()

    primeiro = await _atender(session, session_factory, "a primeira", lead=LEAD)
    assert isinstance(primeiro, Reservou)
    await session.commit()

    segundo = await _atender(session, session_factory, "a primeira", lead=outro)
    await session.commit()

    assert isinstance(segundo, Ofereceu)
    assert "preenchido" in segundo.texto
    # As alternativas nao incluem o horario perdido.
    perdido = (await _linhas(session, lead=LEAD))[0].inicio
    assert all(p.janela.inicio != perdido for p in segundo.propostas)
    assert await _linhas(session, lead=outro) == []


async def test_o_imovel_de_interesse_viaja_ate_a_reserva(
    session, session_factory, semear_corretor
) -> None:
    await _corretor(semear_corretor)
    imovel_id = await _imovel(session)
    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=LEAD,
            imovel_id=imovel_id,
            score_match=0.9,
            motivo_match="teste",
            reacao_lead=ReacaoLead.INTERESSE,
            motivo_descarte=None,
            apresentado_em=AGORA - timedelta(minutes=5),
        )
    )
    await session.commit()

    await _atender(session, session_factory, "quero agendar uma visita")
    await session.commit()
    await _atender(session, session_factory, "a primeira")
    await session.commit()

    assert (await _linhas(session))[0].imovel_id == imovel_id


async def test_a_data_ambigua_vira_pergunta_e_nao_chute(
    session, session_factory, semear_corretor
) -> None:
    """RN-11.3 e RT-10: chutar a data e visita no dia errado.

    A pergunta ja vem pronta da TEC-167 -- `resolver` devolve `Ambigua` com o
    texto exato --, e nada e gravado.
    """
    await _corretor(semear_corretor)
    await session.commit()

    resultado = await _atender(session, session_factory, "pode ser domingo?")

    assert isinstance(resultado, Perguntou)
    assert "domingos" in resultado.texto
    await session.commit()
    assert await ler_propostas(session, channel=CANAL, conversation_key=LEAD, agora=AGORA) == []


async def test_a_data_falada_recorta_a_oferta_naquele_dia(
    session, session_factory, semear_corretor
) -> None:
    """CA-11.1: "quinta de manha" responde com horarios daquela quinta.

    Sem o recorte, `janelas_alocadas` daria uma janela por dia a partir de
    hoje -- resposta correta para quem nao nomeou dia, e errada para quem
    nomeou.
    """
    await _corretor(semear_corretor)
    await session.commit()

    resultado = await _atender(session, session_factory, "pode ser quinta de manha?")

    assert isinstance(resultado, Ofereceu)
    # 1 de outubro de 2026 e a quinta seguinte a `AGORA`.
    quinta = datetime(2026, 10, 1, tzinfo=SP).date()
    locais = [p.janela.inicio.astimezone(SP) for p in resultado.propostas]
    assert locais and all(inicio.date() == quinta for inicio in locais)
    assert all(9 <= inicio.hour < 12 for inicio in locais)


# --- TEC-372: a resposta ao lembrete de 24 horas -----------------------------


async def _com_lembrete(
    session, semear_corretor, *, lembrete_enviado: bool = True, daqui_a_horas: int = 20
) -> Agendamento:
    """Um agendamento CONFIRMADO, com ou sem o lembrete de 24 h ja carimbado."""
    # De plantao: sem qualificacao gravada o criterio nasce vazio, e
    # criterio vazio so casa plantao (RN-11.2). Sem isso nao ha candidato
    # e a oferta de remarcacao sai vazia.
    corretor = await semear_corretor(
        email=f"lembrete{daqui_a_horas}{lembrete_enviado}@x.com", plantao=True
    )
    inicio = AGORA + timedelta(hours=daqui_a_horas)
    agendamento = Agendamento(
        id=uuid.uuid4(),
        corretor_id=corretor.id,
        channel=CANAL,
        conversation_key=LEAD,
        imovel_id=None,
        tipo=str(TipoDeCompromisso.VISITA_PRESENCIAL),
        inicio=inicio,
        fim=inicio + timedelta(hours=1),
        status=StatusDoAgendamento.CONFIRMADO,
        reservado_ate=AGORA,
        criado_em=AGORA,
        confirmado_em=AGORA,
        motivo_da_alocacao=str(MotivoDaAlocacao.MATCH_EXATO),
        lembrete_24h_em=AGORA - timedelta(minutes=5) if lembrete_enviado else None,
    )
    session.add(agendamento)
    await session.commit()
    return agendamento


async def test_a_presenca_confirmada_carimba_a_coluna_e_nao_o_status(
    session, session_factory, semear_corretor
) -> None:
    agendamento = await _com_lembrete(session, semear_corretor)

    resultado = await _atender(session, session_factory, "sim, estarei la")

    assert isinstance(resultado, PresencaConfirmada)
    await session.commit()
    await session.refresh(agendamento)
    assert agendamento.presenca_confirmada_em == AGORA
    assert agendamento.status == StatusDoAgendamento.CONFIRMADO


async def test_o_cancelamento_pela_conversa_derruba_e_libera(
    session, session_factory, semear_corretor
) -> None:
    agendamento = await _com_lembrete(session, semear_corretor)

    resultado = await _atender(session, session_factory, "preciso cancelar")

    assert isinstance(resultado, Cancelou)
    assert resultado.agendamento_id == agendamento.id
    await session.commit()
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.CANCELADO
    assert agendamento.cancelado_em == AGORA


async def test_remarcar_oferece_janelas_e_nao_derruba_o_original(
    session, session_factory, semear_corretor
) -> None:
    """O terceiro cenario do Gherkin, na metade que afirma o que NAO mudou."""
    agendamento = await _com_lembrete(session, semear_corretor)

    resultado = await _atender(session, session_factory, "podemos remarcar?")

    assert isinstance(resultado, Ofereceu)
    assert all(p.remarcando_id == agendamento.id for p in resultado.propostas)
    await session.commit()
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.CONFIRMADO


async def test_a_escolha_na_remarcacao_move_o_agendamento(
    session, session_factory, semear_corretor
) -> None:
    agendamento = await _com_lembrete(session, semear_corretor)
    await _atender(session, session_factory, "podemos remarcar?")
    await session.commit()

    resultado = await _atender(session, session_factory, "a primeira")

    assert isinstance(resultado, Confirmou)
    await session.commit()
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.REAGENDADO
    novo = await session.get(Agendamento, resultado.agendamento_id)
    assert novo is not None
    assert novo.status == StatusDoAgendamento.CONFIRMADO
    assert novo.origem_id == agendamento.id


@pytest.mark.parametrize(
    ("fala", "razao"),
    [
        ("cancela aquele outro assunto", "sem agendamento nenhum"),
        ("quero cancelar", "sem agendamento nenhum"),
    ],
)
async def test_sem_agendamento_a_palavra_nao_derruba_nada(
    session, session_factory, semear_corretor, fala: str, razao: str
) -> None:
    await _corretor(semear_corretor)
    await session.commit()

    assert isinstance(await _atender(session, session_factory, fala), NadaAFazer), razao
    await session.commit()
    assert await _linhas(session) == []


async def test_sem_lembrete_enviado_a_palavra_nao_derruba_nada(
    session, session_factory, semear_corretor
) -> None:
    """O lembrete e o que abre a janela: antes dele, "cancelar" nao e resposta a nada."""
    agendamento = await _com_lembrete(session, semear_corretor, lembrete_enviado=False)

    assert isinstance(await _atender(session, session_factory, "quero cancelar"), NadaAFazer)
    await session.commit()
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.CONFIRMADO


async def test_depois_do_inicio_da_visita_a_janela_fechou(
    session, session_factory, semear_corretor
) -> None:
    agendamento = await _com_lembrete(session, semear_corretor)
    depois = agendamento.inicio + timedelta(minutes=1)

    assert isinstance(
        await _atender(session, session_factory, "quero cancelar", agora=depois), NadaAFazer
    )
    await session.commit()
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.CONFIRMADO


async def test_o_nao_sozinho_nao_cancela(session, session_factory, semear_corretor) -> None:
    """A assimetria da D2: cancelar por engano custa uma visita e nao tem desfazer."""
    agendamento = await _com_lembrete(session, semear_corretor)

    assert isinstance(await _atender(session, session_factory, "nao"), NadaAFazer)
    await session.commit()
    await session.refresh(agendamento)
    assert agendamento.status == StatusDoAgendamento.CONFIRMADO
