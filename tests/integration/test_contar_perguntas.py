"""O contador do teto cresce por campo entregue. TEC-149, D2 e D3."""

import asyncio
from typing import Any

from sqlalchemy import select

from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import contar_perguntas
from mobia.infra.db import get_sessionmaker

# Constantes locais, como nos outros arquivos de integracao: eles sao
# autocontidos de proposito.
CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def _semear(session: Any) -> None:
    session.add(LeadQualification(channel=CANAL, conversation_key=CONVERSA))
    await session.commit()


async def _contador(session: Any) -> int:
    # `expire_all` antes de reler: o incremento aconteceu em SQL, e o objeto
    # que esta sessao tem em memoria nao sabe disso.
    session.expire_all()
    linha = await session.scalar(
        select(LeadQualification).where(
            LeadQualification.channel == CANAL,
            LeadQualification.conversation_key == CONVERSA,
        )
    )
    assert linha is not None
    return linha.perguntas_feitas


async def test_um_campo_perguntado_soma_um(session: Any) -> None:
    await _semear(session)

    await contar_perguntas(
        session, channel=CANAL, conversation_key=CONVERSA, perguntou=("urgencia",)
    )
    await session.commit()

    assert await _contador(session) == 1


async def test_dois_turnos_somam(session: Any) -> None:
    """O que a coluna compra: o numero sobrevive ao turno em vez de viver na
    memoria dele."""
    await _semear(session)

    for campo in ("urgencia", "regiao"):
        await contar_perguntas(
            session, channel=CANAL, conversation_key=CONVERSA, perguntou=(campo,)
        )
        await session.commit()

    assert await _contador(session) == 2


async def test_turno_sem_pergunta_nao_mexe_no_contador(session: Any) -> None:
    await _semear(session)

    await contar_perguntas(session, channel=CANAL, conversation_key=CONVERSA, perguntou=())
    await session.commit()

    assert await _contador(session) == 0


async def test_nome_desconhecido_nao_conta(session: Any) -> None:
    """O modelo as vezes devolve o TEXTO da pergunta em vez do nome do campo."""
    await _semear(session)

    await contar_perguntas(
        session, channel=CANAL, conversation_key=CONVERSA, perguntou=("qual o seu prazo?",)
    )
    await session.commit()

    assert await _contador(session) == 0


async def test_lead_sem_linha_nao_e_contado_por_decisao_nao_por_acidente(session: Any) -> None:
    """O UPDATE e no-op quando o lead nao tem linha, e isso e o comportamento
    escolhido -- nao um bug a corrigir.

    `gravar_estado` recusa de proposito criar linha para um lead que nao
    extraiu nada ("Deliberadamente NAO cria linha", no docstring dela), e
    `contar_perguntas` roda sobre um UPDATE simples que so acha linha para
    atualizar. A alternativa -- fazer esta funcao criar a linha -- moveria o
    score do lead do zero para o piso documentado e geraria entrada na
    trilha de score por causa de uma pergunta feita a um lead que ainda nao
    disse nada, um efeito colateral maior que a subcontagem aceita aqui. Ver
    o paragrafo de consequencia declarada no docstring de `contar_perguntas`.

    Sem `_semear`: e exatamente a ausencia de linha que este teste tranca.
    """
    await contar_perguntas(
        session, channel=CANAL, conversation_key=CONVERSA, perguntou=("urgencia",)
    )
    await session.commit()

    session.expire_all()
    linha = await session.scalar(
        select(LeadQualification).where(
            LeadQualification.channel == CANAL,
            LeadQualification.conversation_key == CONVERSA,
        )
    )
    assert linha is None


async def test_dois_turnos_concorrentes_nao_perdem_incremento(session: Any) -> None:
    """A razao de o incremento ser SQL, e nao leitura em Python seguida de
    escrita (D2).

    Duas SESSOES, e nao duas chamadas na mesma: e a corrida real entre dois
    turnos da mesma conversa, que a docstring de `marcar_perguntados` ja
    descreve para as colunas de valor. Com `perguntas_feitas + 1` o Postgres
    serializa os dois UPDATE na mesma linha e o total e 2. Com um
    read-modify-write, os dois leriam 0 e gravariam 1 -- e este teste
    reprovaria com 1, que e o bug que ninguem veria em producao ate o lead
    ser cortado cedo ou tarde demais.
    """
    await _semear(session)

    async def _incrementar(campo: str) -> None:
        async with get_sessionmaker()() as sessao:
            await contar_perguntas(
                sessao, channel=CANAL, conversation_key=CONVERSA, perguntou=(campo,)
            )
            await sessao.commit()

    await asyncio.gather(_incrementar("urgencia"), _incrementar("regiao"))

    assert await _contador(session) == 2
