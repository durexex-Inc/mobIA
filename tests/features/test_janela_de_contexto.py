"""Criterios de aceite do TEC-127 como testes executaveis.

Cada teste corresponde a um cenario Gherkin da historia. Ha sobreposicao
deliberada com os testes de integracao: estes existem para que o criterio tenha
um endereco, nao para cobrir codigo novo.
"""

from decimal import Decimal

from conftest import CANAL, CONVERSA, ContadorFake, ResumidorFake, semear

from mobia.app.config import get_settings
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import montar_contexto
from mobia.domain.context.resumo import INSTRUCAO_DOBRAR
from mobia.infra.db import get_sessionmaker


async def test_conversa_longa_cabe_no_limite_de_tokens(session) -> None:
    """Cenario: Conversa longa cabe no limite de tokens."""
    await semear(session, 60)

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=ContadorFake(),
    )

    assert len(contexto.literais) >= get_settings().contexto_literais_minimas
    assert contexto.resumo is not None, "as anteriores viraram resumo"
    assert contexto.tokens <= 12000


async def test_estado_estruturado_nao_e_reconstruido_pelo_modelo(session) -> None:
    """Cenario: Estado estruturado nao e reconstruido pelo modelo."""
    await semear(session, 5)
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            faixa_preco_max=Decimal("600000.00"),
            regiao="zona sul",
        )
    )
    await session.commit()

    resumidor = ResumidorFake()
    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert contexto.estado is not None
    assert contexto.estado.faixa_preco_max == Decimal("600000.00")
    assert resumidor.chamadas == [], "o estado vem do banco; nenhuma chamada ao modelo o reconstroi"


async def test_resumo_e_comprimido_ao_estourar_o_limite(session, sempre_contar) -> None:
    """Cenario: Resumo e comprimido ao estourar o limite.

    O teto sozinho nao prova compressao -- um roteiro de contagem pode fazer
    `contexto.tokens` caber mesmo que nada tenha sido dobrado. As tres
    asserts abaixo verificam o que o codigo de fato fez: que o resumidor foi
    chamado para dobrar, que a janela literal encolheu ate o piso, e que o
    resumo deixou de ser vazio -- as tres quebram sob um `_dobrar` neutralizado
    que reporta sucesso sem dobrar nada.
    """
    await semear(session, 25)
    resumidor = ResumidorFake()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(roteiro=[13500, 9000]),
    )

    assert contexto.tokens <= 12000
    assert resumidor.chamadas == [INSTRUCAO_DOBRAR], (
        "o estouro tem de acionar o resumidor para dobrar as mensagens antigas"
    )
    assert len(contexto.literais) == get_settings().contexto_literais_minimas, (
        "dobrar reduz a janela literal ate o piso"
    )
    assert contexto.resumo == "resumo do que veio antes", (
        "o resumo tem de vir do que o resumidor devolveu, nao ficar vazio"
    )


async def test_resumo_e_regerado_na_cadencia_definida(session) -> None:
    """Cenario: Resumo e regerado na cadencia definida."""
    await semear(session, 39)
    resumidor = ResumidorFake()

    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )
    assert resumidor.chamadas == [], "trinta e nove nao dispara"

    await semear(session, 1)
    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )
    assert len(resumidor.chamadas) == 1, "a quadragesima dispara"
