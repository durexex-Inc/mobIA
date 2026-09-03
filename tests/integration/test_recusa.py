"""A recusa de campo: coluna, gravacao e as duas leituras.

TEC-148.
"""

from decimal import Decimal

from sqlalchemy import select

from mobia.domain.agente.schemas import Extracao, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.context.repositorio import gravar_estado

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _linha(session, **ajustes: object) -> LeadQualification:
    """Os quatro obrigatorios preenchidos, menos o que o teste mudar."""
    base: dict[str, object] = {
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 50_000_000,
        "regiao": "vila mariana",
        "urgencia": Urgencia.ATE_3_MESES.value,
    }
    linha = LeadQualification(**{**base, **ajustes})
    session.add(linha)
    await session.commit()
    return linha


async def test_a_coluna_aceita_lista_e_devolve_lista(session) -> None:
    await _linha(session, campos_recusados=["faixa_preco_max"])

    gravada = (await session.scalars(select(LeadQualification))).one()
    assert gravada.campos_recusados == ["faixa_preco_max"]


async def test_null_e_vazio_sao_estados_diferentes_na_coluna(session) -> None:
    """`NULL` e "linha anterior a esta card, ninguem registrava"; `{}` e
    "registrava, e nao havia recusa". Quem le trata os dois igual, mas a
    coluna guarda a diferenca."""
    await _linha(session, campos_recusados=None)
    nula = (await session.scalars(select(LeadQualification))).one()
    assert nula.campos_recusados is None

    nula.campos_recusados = []
    await session.commit()
    vazia = (await session.scalars(select(LeadQualification))).one()
    assert vazia.campos_recusados == []


async def test_gravar_estado_acumula_a_recusa(session) -> None:
    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="vila mariana"),
        recusou=["faixa_preco_expressao"],
    )
    await session.commit()

    linha = (await session.scalars(select(LeadQualification))).one()
    assert linha.campos_recusados == ["faixa_preco_max"]


async def test_o_valor_posterior_desfaz_a_recusa(session) -> None:
    """Cenario 2 da card, atravessando turnos: a recusa de um turno anterior
    sai quando o valor chega, e isso e feito no SQL porque so ele ve o array
    acumulado."""
    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=Intencao.COMPRA,
        extracao=Extracao(regiao="vila mariana"),
        recusou=["faixa_preco_expressao"],
    )
    await session.commit()

    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=Intencao.COMPRA,
        extracao=Extracao(faixa_preco_max_centavos=60_000_000),
    )
    await session.commit()

    linha = (await session.scalars(select(LeadQualification))).one()
    assert linha.campos_recusados == []
    assert linha.faixa_preco_max_centavos == 60_000_000


async def test_recusas_de_turnos_diferentes_se_acumulam(session_factory) -> None:
    """Uniao e `array_remove` compoem entre turnos, em sessoes diferentes.

    **O que este teste NAO prova:** que a uniao precisa morar no SQL. As
    operacoes abaixo sao sequenciais, e sob READ COMMITTED a segunda leitura
    ja ve o commit da primeira -- uma uniao feita em Python passaria
    identicamente. A perda concorrente (duas sessoes que leem o mesmo array
    antes de qualquer uma gravar) nao tem teste direto aqui: forcar o
    interleaving exigiria `asyncio.gather` sem garantia de ordem, e teste
    flaky e pior que teste ausente.

    A uniao em SQL segue justificada pela mesma razao que a da coluna irma
    `perguntados_sem_resposta` (TEC-257), cuja corrida tambem nunca foi
    testada. Lacuna declarada no desenho.
    """
    async with session_factory() as a, session_factory() as b:
        await gravar_estado(
            a,
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA,
            extracao=Extracao(regiao="vila mariana"),
            recusou=["faixa_preco_expressao"],
        )
        await a.commit()

        await gravar_estado(
            b,
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA,
            extracao=Extracao(quartos=2),
            recusou=["urgencia"],
        )
        await b.commit()

    async with session_factory() as c:
        linha = (await c.scalars(select(LeadQualification))).one()
        assert sorted(linha.campos_recusados or []) == ["faixa_preco_max", "urgencia"]


async def test_o_turno_grava_a_recusa_que_o_modelo_relatou(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    await rodar_turno(
        session,
        classificador_fake(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            extracao=Extracao(regiao="vila mariana"),
            recusou=("faixa_preco_expressao",),
        ),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    linha = (await session.scalars(select(LeadQualification))).one()
    assert linha.campos_recusados == ["faixa_preco_max"]


async def test_a_trilha_de_score_registra_a_recusa_como_queda_de_completude(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """A consequencia declarada da D5: o score de quem recusa CAI, e a
    auditoria da TEC-152 registra a queda com causa CAMPOS_OBRIGATORIOS.
    Isso e a auditoria funcionando, nao regressao."""

    def turno(extracao, recusou=()):
        return rodar_turno(
            session,
            classificador_fake(
                intencao=Intencao.COMPRA,
                confianca=Decimal("0.95"),
                extracao=extracao,
                recusou=recusou,
            ),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    await turno(
        Extracao(
            regiao="vila mariana",
            urgencia=Urgencia.ATE_3_MESES,
            faixa_preco_max_centavos=50_000_000,
        )
    )
    await turno(Extracao(), recusou=("faixa_preco_expressao",))

    registros = (
        await session.scalars(select(LeadScoreAudit).order_by(LeadScoreAudit.created_at))
    ).all()
    assert len(registros) == 2
    assert registros[-1].causas == ["CAMPOS_OBRIGATORIOS"]
    assert registros[-1].total_anterior - registros[-1].total_novo == 5
