"""A geracao de ponta a ponta, com redator falso."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.contingencia import TEXTO_DE_CONTINGENCIA
from mobia.domain.handoff.geracao import gerar_resumo
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.resumo import MARCADORES, ResumoDeHandoffGerado, ResumoDeHandoffInvalido
from mobia.infra.crypto import decrypt


class _RedatorFalso:
    """Ecoa o dossie que recebeu, dentro dos seis marcadores.

    Ecoar e o ponto: e o que deixa o teste afirmar que o numero do banco
    chegou ate o modelo, que e o mais longe que se pode ir sem o modelo real.
    """

    def __init__(self) -> None:
        self.recebeu: str | None = None

    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        self.recebeu = dossie_em_texto
        return ResumoDeHandoffGerado(
            texto="\n".join(f"{m}\nconteudo" for m in MARCADORES),
            modelo="claude-sonnet-5",
            tokens_in=900,
            tokens_out=400,
            latency_ms=120,
            comprimiu=False,
        )


class _RedatorQueFalha:
    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        raise ResumoDeHandoffInvalido("bloco ausente: '## Proxima acao'")


class _RedatorQueOProvedorDerrubou:
    """O provedor fora do ar: uma excecao que NAO e ResumoDeHandoffInvalido."""

    async def redigir(self, dossie_em_texto: str) -> ResumoDeHandoffGerado:
        raise RuntimeError("connection reset by peer")


async def test_gera_e_grava_o_resumo(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], semear_lead_completo
) -> None:
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)
    redator = _RedatorFalso()

    assert await gerar_resumo(session_factory, redator=redator, handoff_id=handoff_id) is True

    # Os numeros do banco chegaram ao modelo -- segundo cenario do Gherkin.
    assert redator.recebeu is not None
    assert "72" in redator.recebeu
    assert "R$ 600.000" in redator.recebeu
    assert "3 imoveis apresentados" in redator.recebeu

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert decrypt(linha.resumo, aad_do_resumo_de_handoff(handoff_id)) is not None
    assert linha.resumo_modelo == "claude-sonnet-5"
    assert linha.resumo_gerado_em is not None
    # D5: o caminho feliz precisa provar a AUSENCIA da marca, ou a asserta
    # de que o fallback fica limpo na regeneracao fica meio testada.
    assert linha.resumo_fallback is False


async def test_handoff_que_sumiu_nao_e_erro(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert (
        await gerar_resumo(session_factory, redator=_RedatorFalso(), handoff_id=uuid.uuid4())
        is False
    )


async def test_provedor_fora_do_ar_grava_o_template(
    session, session_factory, semear_lead_completo
) -> None:
    """Primeiro cenario do Gherkin. D2: sem retentativa, template na hora."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=3)

    assert await gerar_resumo(
        session_factory, redator=_RedatorQueOProvedorDerrubou(), handoff_id=handoff_id
    )

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.resumo_fallback is True
    assert linha.resumo_modelo is None
    assert TEXTO_DE_CONTINGENCIA in decrypt(linha.resumo, aad_do_resumo_de_handoff(handoff_id))


async def test_resumo_malformado_tambem_grava_o_template(
    session, session_factory, semear_lead_completo
) -> None:
    """D1: a emenda E-01 alarga o fallback para alem da falha do provedor.

    Antes desta card este caminho terminava com `resumo` nulo, e a RN-15.4
    seguia violada pela metade.
    """
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)

    assert await gerar_resumo(session_factory, redator=_RedatorQueFalha(), handoff_id=handoff_id)

    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.resumo_fallback is True


async def test_regenerar_com_o_provedor_de_volta_limpa_a_marca(
    session, session_factory, semear_lead_completo
) -> None:
    """Terceiro cenario do Gherkin, com a limpeza da D5."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)
    await gerar_resumo(session_factory, redator=_RedatorQueFalha(), handoff_id=handoff_id)

    assert await gerar_resumo(session_factory, redator=_RedatorFalso(), handoff_id=handoff_id)

    session.expire_all()
    linha = (await session.execute(select(Handoff).where(Handoff.id == handoff_id))).scalar_one()
    assert linha.resumo_fallback is False
    assert linha.resumo_modelo == "claude-sonnet-5"


async def test_dossie_ausente_continua_sem_resumo(session_factory) -> None:
    """A excecao declarada da D1: sem fatos nao ha template possivel."""
    assert not await gerar_resumo(session_factory, redator=_RedatorFalso(), handoff_id=uuid.uuid4())


async def test_regenerar_substitui_o_resumo_anterior(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], semear_lead_completo
) -> None:
    """Quarto cenario do Gherkin, no nivel da funcao."""
    handoff_id = await semear_lead_completo(score=72, faixa_max_centavos=60_000_000, imoveis=1)
    await gerar_resumo(session_factory, redator=_RedatorFalso(), handoff_id=handoff_id)

    primeiro = (
        await session.execute(select(Handoff.resumo_gerado_em).where(Handoff.id == handoff_id))
    ).scalar_one()

    assert await gerar_resumo(session_factory, redator=_RedatorFalso(), handoff_id=handoff_id)

    segundo = (
        await session.execute(select(Handoff.resumo_gerado_em).where(Handoff.id == handoff_id))
    ).scalar_one()
    assert segundo > primeiro
