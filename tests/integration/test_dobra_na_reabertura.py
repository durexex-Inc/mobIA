"""A dobra forcada: a conversa nova ve o resumo, nunca a transcricao. TEC-130, D4.

**A fronteira e a marca do resumo**, e nao uma coluna nova nem um filtro por
`encerrada_em`: dobrando tudo o que ficou para tras, a marca passa a cobrir a
conversa anterior inteira e `literais_apos` devolve so o que e novo.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.montagem import montar_contexto
from mobia.domain.context.resumo import ResumoGerado
from mobia.domain.messages.enums import (
    MessageContentType,
    MessageDirection,
    MessageRole,
)
from mobia.domain.messages.models import Message
from mobia.infra.db import get_sessionmaker


class _ResumidorFalso:
    """Devolve um texto fixo e registra o que lhe pediram para dobrar."""

    def __init__(self) -> None:
        self.conteudos: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.conteudos.append(conteudo)
        return ResumoGerado(
            texto="Lead procurava apartamento de dois quartos na zona sul.",
            modelo="falso",
            tokens_in=10,
            tokens_out=10,
            latency_ms=1,
        )


class _ResumidorQuebrado:
    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        raise RuntimeError("provedor fora do ar")


class _ContadorFalso:
    async def contar(self, texto: str) -> int:
        return 10


async def _semear_conversa(session: AsyncSession, chave: str, quantas: int) -> None:
    """Uma conversa velha, alternando lead e agente.

    `channel`, `conversation_key`, `role`, `direction` e `content_type` sao
    NOT NULL. `text_body` fica nulo: `_texto_das` (em `montagem.py`) lida com
    isso, e o que este teste afirma e sobre QUANTAS mensagens sobram, nao
    sobre o que elas diziam.
    """
    base = datetime.now(UTC) - timedelta(days=60)
    for n in range(quantas):
        do_lead = n % 2 == 0
        session.add(
            Message(
                id=uuid.uuid4(),
                channel="whatsapp",
                conversation_key=chave,
                role=MessageRole.LEAD if do_lead else MessageRole.AGENTE,
                direction=(MessageDirection.INBOUND if do_lead else MessageDirection.OUTBOUND),
                content_type=MessageContentType.TEXTO,
                created_at=base + timedelta(minutes=n),
            )
        )
    await session.commit()


@pytest.mark.usefixtures("banco_limpo")
async def test_a_dobra_forcada_nao_deixa_literal_nenhum(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """**O criterio da card ao pe da letra**: por meio do resumo, nao pela
    transcricao inteira.

    Cinco mensagens ficam MUITO abaixo do gatilho de regeneracao (40) e do
    piso de literais (20) -- sem a dobra forcada, as cinco iriam inteiras
    para o prompt da conversa nova.
    """
    await _semear_conversa(session, "lead-reabre", quantas=5)
    resumidor = _ResumidorFalso()

    with caplog.at_level(logging.WARNING):
        montado = await montar_contexto(
            get_sessionmaker(),
            channel="whatsapp",
            conversation_key="lead-reabre",
            resumidor=resumidor,
            contador=_ContadorFalso(),
            forcar_dobra=True,
        )

    assert montado.literais == []
    assert montado.resumo is not None
    assert len(resumidor.conteudos) == 1
    # Negativa que da sentido a afirmacao positiva no teste da degradacao: o
    # alarme so aparece quando a dobra forcada de fato falha, nunca no
    # caminho feliz.
    assert "contexto.dobra_forcada_falhou" not in caplog.text


@pytest.mark.usefixtures("banco_limpo")
async def test_sem_a_flag_o_piso_preserva_os_literais(session: AsyncSession) -> None:
    """A contraprova: o comportamento de sempre nao mudou."""
    await _semear_conversa(session, "lead-normal", quantas=5)
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-normal",
        resumidor=resumidor,
        contador=_ContadorFalso(),
    )

    assert len(montado.literais) == 5
    assert resumidor.conteudos == []


@pytest.mark.usefixtures("banco_limpo")
async def test_resumo_falho_degrada_e_nao_mata_o_turno(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """**A degradacao declarada da D4.**

    Perder resumo E literais deixaria o agente cego diante de um lead que ele
    ja atendeu. Ver demais e menos ruim que nao ver nada -- entao os literais
    voltam, e o warning denuncia.

    `len(montado.literais) == 5` sozinho nao prova degradacao nenhuma: uma
    implementacao que aceita `forcar_dobra` e nunca repassa `dobrar_tudo` para
    `_dobrar` produz o MESMO numero, porque `dividir(5, 20)` ja devolve tudo
    como "a manter" e o early return de `_dobrar` nem chega a chamar
    `resumidor.resumir` -- o `_ResumidorQuebrado` nunca levanta. As duas
    checagens de log abaixo sao o que de fato fixa que a degradacao
    aconteceu.
    """
    await _semear_conversa(session, "lead-quebrado", quantas=5)

    with caplog.at_level(logging.WARNING):
        montado = await montar_contexto(
            get_sessionmaker(),
            channel="whatsapp",
            conversation_key="lead-quebrado",
            resumidor=_ResumidorQuebrado(),
            contador=_ContadorFalso(),
            forcar_dobra=True,
        )

    assert len(montado.literais) == 5
    assert montado.degradado is True
    assert "contexto.dobra_forcada_falhou" in caplog.text


async def test_o_turno_de_uma_conversa_velha_nao_leva_a_transcricao_dela(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    contador_fake,
    rodar_turno,
) -> None:
    """**O cenario Gherkin da card, ponta a ponta.**

    "Dada uma conversa encerrada por inatividade de um lead que buscava
    apartamento na zona sul, quando esse lead envia uma nova mensagem, entao
    uma nova conversa e criada para o mesmo lead e o resumo da conversa
    anterior esta disponivel para o agente."

    Cinco mensagens de 60 dias atras ficam MUITO abaixo do gatilho de
    regeneracao (40) e do piso de literais (20): sem a dobra forcada elas
    iriam inteiras para o prompt deste turno.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE  # type: ignore[import-not-found]

    from mobia.domain.context.janela import literais_apos, marca_de
    from mobia.domain.context.repositorio import ler_resumo

    await _semear_conversa(session, CONVERSA_AGENTE, quantas=5)
    resumidor = _ResumidorFalso()

    resultado = await rodar_turno(
        session, classificador_fake(), outbound_fake(), resumidor, contador_fake()
    )

    assert resultado == "respondido"
    # A dobra rodou, e uma vez so.
    assert len(resumidor.conteudos) == 1

    async with get_sessionmaker()() as leitura:
        resumo = await ler_resumo(leitura, CANAL_AGENTE, CONVERSA_AGENTE)
        assert resumo is not None
        sobraram = await literais_apos(leitura, CANAL_AGENTE, CONVERSA_AGENTE, marca_de(resumo))

    # **O criterio da card**: nenhuma das cinco falas velhas esta atras da
    # marca. O que sobrou e deste turno -- a fala do lead e a resposta do
    # agente --, nunca da conversa anterior.
    velhas = {m.id for m in sobraram if m.created_at < resumo.watermark_created_at}
    assert velhas == set()
