"""A busca hibrida chegando ao turno. TEC-265.

Basename distinto de tudo em `tests/unit/`.
"""

import uuid
from typing import Any

from conftest import EmbedadorFake
from sqlalchemy import select

from mobia.domain.agente.ferramenta_de_busca import porta_de_busca
from mobia.domain.catalogo.models import Imovel
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker


async def _imovel(session: Any, codigo: str = "AP-001", **sobrescritas: object) -> uuid.UUID:
    """Um imovel disponivel para venda. Copiado e nao importado de proposito:
    os arquivos de integracao deste repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Vila Mariana",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 74900000,
        "bairro": "Vila Mariana",
        "bairro_busca": "vila mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


async def _texto_entregue(session: Any) -> str:
    """O texto que o turno gravou como fala do agente, decifrado.

    Padrao copiado de `test_turno_optout.py`: a linha AGENTE em `messages`,
    com `text_body` decifrado -- e nao `outbound.entregues`, porque a
    asserta e sobre o que ficou gravado, o mesmo dado que uma auditoria de
    conformidade leria.
    """
    (falada,) = (
        (await session.execute(select(Message).where(Message.role == MessageRole.AGENTE)))
        .scalars()
        .all()
    )
    return decrypt(falada.text_body, aad_de(falada.id, "text_body"))


async def test_a_porta_busca_no_catalogo_de_verdade(session: Any) -> None:
    """Cenario 1 da card: o candidato chega com id e preco vindos do banco.

    E a RN-09.4 primeira metade, que a TEC-161 vai precisar: sem `imovel_id` e
    `preco_centavos` reais nao ha o que validar.
    """
    identificador = await _imovel(session)

    saida = await porta_de_busca(get_sessionmaker(), embedador=EmbedadorFake())(
        {"operacao": "VENDA", "consulta_texto": "apartamento com varanda"}
    )

    (candidato,) = saida["candidatos"]
    assert candidato["imovel_id"] == str(identificador)
    assert candidato["preco_centavos"] == 74900000
    assert saida["total_candidatos"] == 1


async def test_catalogo_sem_resultado_nao_vira_invencao(session: Any) -> None:
    """Cenario 2 da card: o filtro exclui, e excluir nao e erro.

    Semeia um imovel com `quartos=3` -- que satisfaz toda outra condicao
    implicita do filtro -- e pede `quartos_min=9`. Sem essa linha, catalogo
    vazio nao distingue "o filtro excluiu corretamente" de "nao havia nada" ou
    de "um bug curto-circuitou a busca sem consultar nada"; com a linha, o
    vazio prova que `WHERE Imovel.quartos >= filtro.quartos_min` fez o
    trabalho dela. Relaxar o criterio e a TEC-160.
    """
    await _imovel(session, quartos=3)

    saida = await porta_de_busca(get_sessionmaker(), embedador=EmbedadorFake())(
        {"operacao": "VENDA", "quartos_min": 9}
    )

    assert saida["candidatos"] == []
    assert saida["total_candidatos"] == 0
    assert "erro" not in saida


async def test_turno_que_nao_pede_imovel_nao_apresenta_imovel(
    session: Any,
    classificador_fake: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
) -> None:
    """Cenario 4 da card, e o mais fraco dos quatro -- de proposito.

    Com `tool_choice: auto` e o classificador FALSO, quem decide nao chamar a
    ferramenta e o duble, nao o modelo: o teste afirma que o turno nao FORCA
    busca, e nao que o modelo se comporta. A outra metade -- o modelo deixando
    de buscar quando devia -- e a lacuna 3 do desenho, aceita como risco, e
    nenhum teste desta suite a cobre.

    **A asserta de texto e uma tautologia declarada.** Com `ClassificadorFake`,
    o texto entregue e sempre `RESPOSTA_DO_CLASSIFICADOR_FAKE`
    (`tests/conftest.py`), uma constante desacoplada do catalogo -- entao
    `"AP-001" not in entregue` NAO PODE falhar por mudanca nenhuma em
    `porta_de_busca`, em `busca.py` ou no catalogo. So falharia se alguem
    editasse a string do proprio duble. O que este teste de fato garante e que
    o turno completa como `"respondido"` com a porta ligada; a asserta de
    texto e guarda barata contra o dia em que o texto do duble passar a vir do
    catalogo, nao evidencia de que a busca real fica fora da resposta hoje.
    """
    await _imovel(session)
    classificador = classificador_fake()

    resultado = await rodar_turno(
        session, classificador, outbound_fake(), resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    # A assercao e sobre o TEXTO entregue, e nao sobre `classificador.candidatos`
    # -- esse campo e o valor que o proprio duble foi configurado para
    # devolver, e afirmar sobre ele seria afirmar sobre o teste. O imovel
    # existe no catalogo e nao aparece na resposta: e o que o cenario promete.
    async with get_sessionmaker()() as leitura:
        entregue = await _texto_entregue(leitura)
    assert "AP-001" not in entregue
