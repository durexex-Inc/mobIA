"""A deduplicacao do handoff: o que so o Postgres prova."""

import asyncio
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.vocabulario import ATOR_AGENTE
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _linhas(session: AsyncSession) -> list[dict]:
    resultado = await session.execute(
        text(
            "SELECT gatilho, etiqueta, prioridade, status, gatilhos_adicionais "
            "FROM handoffs ORDER BY criado_em"
        )
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_o_gatilho_quente_cria_com_etiqueta_e_prioridade(session: AsyncSession) -> None:
    registro = await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    assert registro.criado is True
    linhas = await _linhas(session)
    assert len(linhas) == 1
    assert linhas[0]["etiqueta"] == "lead-quente"
    assert linhas[0]["prioridade"] == "NORMAL"
    assert linhas[0]["status"] == "PENDENTE"


async def test_gatilho_repetido_nao_duplica_e_acumula(session: AsyncSession) -> None:
    """Cenario 2 do Gherkin."""
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    registro = await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.VENDA_IMOVEL,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    assert registro.criado is False
    linhas = await _linhas(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilhos_adicionais"] == ["VENDA_IMOVEL"]
    # A etiqueta e do gatilho que criou, e nao muda.
    assert linhas[0]["etiqueta"] == "lead-quente"


async def test_pedido_de_humano_escala_a_prioridade_de_um_aberto(session: AsyncSession) -> None:
    """Emenda E-01 da RN-16.1, e o caso que a RN-04.6 exige."""
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    linhas = await _linhas(session)
    assert linhas[0]["prioridade"] == "ALTA"


async def test_a_prioridade_nunca_desce(session: AsyncSession) -> None:
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    linhas = await _linhas(session)
    assert linhas[0]["prioridade"] == "ALTA"


async def test_gatilhos_distintos_acumulam_na_ordem(session: AsyncSession) -> None:
    """Fix wave, Important 3. Tres gatilhos diferentes entram um a um, na ordem."""
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.VENDA_IMOVEL,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.SUPORTE_CONTRATO,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    linhas = await _linhas(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilhos_adicionais"] == ["VENDA_IMOVEL", "SUPORTE_CONTRATO"]


async def test_gatilho_repetido_nao_acumula_alem_de_um(session: AsyncSession) -> None:
    """Fix wave, Important 3.

    O gatilho de intencao dispara em todo turno com a classificacao certa,
    sem condicao de borda -- ao contrario do QUENTE. Repetido tres vezes,
    `gatilhos_adicionais` fica com um elemento so. E o gatilho que CRIOU o
    handoff, se voltar, nao entra nos adicionais -- ele ja esta na coluna
    `gatilho`.
    """
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    for _ in range(3):
        await registrar_handoff(
            session,
            channel=CANAL,
            conversation_key=CONVERSA,
            gatilho=Gatilho.VENDA_IMOVEL,
            ator=ATOR_AGENTE,
        )
        await session.commit()
    # O gatilho que criou o handoff, repetido, nao entra nos adicionais.
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    linhas = await _linhas(session)
    assert len(linhas) == 1
    assert linhas[0]["gatilhos_adicionais"] == ["VENDA_IMOVEL"]


async def test_conversas_diferentes_tem_handoffs_diferentes(session: AsyncSession) -> None:
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await registrar_handoff(
        session,
        channel=CANAL,
        conversation_key="5511900000000",
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()
    assert len(await _linhas(session)) == 2


async def test_duas_escritas_concorrentes_produzem_uma_linha(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """A corrida e prevista: `lead.esquentou` reemite para o mesmo lead.

    Duas sessoes de verdade, e nao duas chamadas em sequencia -- o que se quer
    provar e que quem arbitra e o indice parcial, nao a ordem do codigo.

    `total == 1` sozinho nao prova isso: um `ON CONFLICT DO UPDATE` tambem
    produz uma linha so se as duas chamadas rodassem em sequencia, sem
    concorrencia nenhuma. Quem fecha a prova e o par de retornos -- exatamente
    um `True` (quem criou) e um `False` (quem so atualizou) -- porque isso so
    acontece se o xmax do Postgres, e nao uma coincidencia de carimbo de
    tempo, decidiu quem venceu. Tambem nao basta rodar `gather` com
    `return_exceptions=True` e ignorar o resultado: uma excecao engolida
    esconderia um gatilho perdido em silencio e o teste continuaria verde.
    """
    gatilhos = (Gatilho.LEAD_QUENTE, Gatilho.VENDA_IMOVEL)

    async def escrever(gatilho: Gatilho) -> bool:
        async with session_factory() as propria:
            registro = await registrar_handoff(
                propria, channel=CANAL, conversation_key=CONVERSA, gatilho=gatilho, ator=ATOR_AGENTE
            )
            await propria.commit()
            return registro.criado

    resultados = await asyncio.gather(
        *(escrever(gatilho) for gatilho in gatilhos),
        return_exceptions=True,
    )
    assert not any(isinstance(resultado, BaseException) for resultado in resultados)
    booleanos = cast("list[bool]", resultados)
    assert sorted(booleanos) == [False, True]

    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 1

    perdedor = gatilhos[booleanos.index(False)]
    linhas = await _linhas(session)
    assert linhas[0]["gatilhos_adicionais"] == [perdedor.value]


async def test_registrar_devolve_o_id_da_linha_criada(session: AsyncSession) -> None:
    registro = await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911112222",
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    assert registro.criado is True
    gravado = (await session.execute(select(Handoff.id))).scalar_one()
    assert registro.id == gravado


async def test_o_gatilho_adicional_devolve_o_id_do_handoff_ABERTO(
    session: AsyncSession,
) -> None:
    """O id e o da linha que sobreviveu, nao o do INSERT que perdeu.

    O `ON CONFLICT DO UPDATE` gera um id novo no `values()` a cada chamada e o
    descarta quando cai no UPDATE. Devolver o descartado daria ao chamador um
    id que nao existe no banco -- e o job de resumo procuraria um handoff
    fantasma.
    """
    primeiro = await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911112222",
        gatilho=Gatilho.LEAD_QUENTE,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    segundo = await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911112222",
        gatilho=Gatilho.PEDIDO_DE_HUMANO,
        ator=ATOR_AGENTE,
    )
    await session.commit()

    assert segundo.criado is False
    assert segundo.id == primeiro.id
