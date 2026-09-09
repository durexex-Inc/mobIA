"""A apresentacao de imoveis dentro do turno. TEC-162.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_busca_no_turno.py`.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from mobia.domain.agente.schemas import Extracao, Intencao, RespostaDoAgente
from mobia.domain.agente.turno import KINDS_DAS_FICHAS
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.montagem import ContextoMontado
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import EnvioRecusado
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker

PROSA = "Achei tres opcoes que encaixam no que voce falou."


async def _imovel(session: Any, codigo: str, preco: int, **sobrescritas: object) -> uuid.UUID:
    """Copiado e nao importado de proposito: os arquivos de integracao deste
    repo sao autocontidos."""
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": preco,
        "condominio": 55000,
        "bairro": "Lagoa da Conceicao",
        "bairro_busca": "lagoa da conceicao",
        "cidade": "Florianopolis",
        "uf": "SC",
        "area_util_m2": 54,
        "quartos": 4,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["churrasqueira", "mobiliado"],
        "fotos": [f"https://exemplo.com/{codigo}.jpg"],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


class _ClassificadorComCandidatos:
    """Devolve candidatos prontos, sem passar pela busca real.

    Diferente de `_ClassificadorQuePedeAFerramenta` em `test_busca_no_turno.py`,
    que existe para provar que a busca de VERDADE atravessa: aqui o assunto e
    a APRESENTACAO, e fixar os candidatos deixa a asserta sobre quais fichas
    sairam livre da ordenacao por score.
    """

    def __init__(self, candidatos: list[dict[str, Any]], perguntou: tuple[str, ...] = ()) -> None:
        self.candidatos = candidatos
        self.perguntou = perguntou

    async def classificar(self, contexto: ContextoMontado, *, porta=None) -> RespostaDoAgente:
        return RespostaDoAgente(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            resposta=PROSA,
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=Extracao(),
            perguntou=self.perguntou,
            candidatos=self.candidatos,
        )

    async def desambiguar(self, contexto: ContextoMontado):
        raise AssertionError("confianca alta o bastante para nao desambiguar")


def _candidato(identificador: uuid.UUID, preco: int) -> dict[str, Any]:
    """O que `porta_de_busca._candidato_serializavel` devolve hoje."""
    return {
        "imovel_id": str(identificador),
        "codigo": "AP-001",
        "titulo": "Apartamento AP-001",
        "bairro": "Lagoa da Conceicao",
        "preco_centavos": preco,
        "quartos": 4,
        "vagas": 2,
        "area_util_m2": 54,
    }


async def _kinds_reservados() -> list[str]:
    async with get_sessionmaker()() as leitura:
        return sorted((await leitura.scalars(select(OutboundDispatch.kind))).all())


async def _texto_gravado() -> str:
    async with get_sessionmaker()() as leitura:
        (falada,) = (
            (await leitura.execute(select(Message).where(Message.role == MessageRole.AGENTE)))
            .scalars()
            .all()
        )
        return decrypt(falada.text_body, aad_de(falada.id, "text_body"))


async def test_dez_candidatos_produzem_exatamente_tres_fichas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """RN-10.2: maximo de 3 por turno, mesmo com 10 candidatos."""
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(10)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 3
    assert await _kinds_reservados() == sorted(KINDS_DAS_FICHAS)


async def test_a_prosa_vira_prefixo_da_primeira_e_as_outras_sao_ficha_pura(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D5. A voz do agente sobrevive no turno mais importante da conversa."""
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    primeira, segunda, terceira = outbound.entregues
    assert primeira.startswith(f"{PROSA}\n\n")
    assert PROSA not in segunda
    assert PROSA not in terceira


async def test_pergunta_no_turno_adia_as_fichas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D4. Candidatos nao-vazios NAO significam que o agente quis apresentar.

    Com `perguntou` preenchido, a prosa sai como texto e as fichas esperam o
    proximo turno -- senao o lead recebe tres fotos e uma pergunta sobre zona
    no mesmo turno, que e a parede que a RN-04.2 existe para evitar.
    """
    identificador = await _imovel(session, "AP-001", 50000000)
    classificador = _ClassificadorComCandidatos(
        [_candidato(identificador, 50000000)], perguntou=("regiao",)
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == [PROSA]
    assert await _kinds_reservados() == ["reply"]


async def test_a_retentativa_nao_reentrega_nenhuma_ficha(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any
) -> None:
    """D9. A idempotencia por posicao: a retentativa nao duplica a ficha_1.

    Sem os kinds fixos por posicao, a segunda tentativa mandaria as imagens
    de novo -- e o criterio de aceite da TEC-134 proibe resposta duplicada.

    **Nao usa `rodar_turno`**, e a razao e o proprio contrato dele: ele semeia
    uma entrada NOVA a cada chamada, entao dois `rodar_turno` dariam
    `message_id` diferentes e a reserva nunca colidiria -- o teste passaria
    sem provar nada. A idempotencia e por (message_id, kind), entao a mesma
    Message tem de rodar duas vezes.
    """
    from conftest import ModeradorFake, _entrada_do_lead  # type: ignore[import-not-found]

    from mobia.domain.agente.turno import executar_turno

    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()
    linha = await _entrada_do_lead(session)

    async def _turno() -> str:
        return await executar_turno(
            get_sessionmaker(),
            message=linha,
            classificador=classificador,
            resumidor=resumidor_fake(),
            contador=contador_fake(),
            outbound=outbound,
            moderador=ModeradorFake(),
        )

    assert await _turno() == "respondido"
    assert len(outbound.entregues) == 3

    # Segunda passada sobre a MESMA Message: as tres reservas ja existem.
    segundo = await _turno()

    assert len(outbound.entregues) == 3, "reentregou ficha que ja tinha reserva"
    assert segundo == "reentrega_suprimida"
    assert await _kinds_reservados() == sorted(KINDS_DAS_FICHAS)


async def test_recusa_permanente_numa_ficha_nao_cala_as_outras(
    session: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D10. A recusa mais provavel aqui e a Meta rejeitando a URL da midia, e
    as URLs do catalogo sao o campo mais fragil que temos. Uma foto ruim nao
    pode apagar dois imoveis bons.
    """
    # `from conftest import ...` e nao `from tests.conftest import ...`: o
    # conftest da raiz e importavel direto, e e assim que
    # `test_busca_no_turno.py` importa o `EmbedadorFake`.
    from conftest import OutboundFake  # type: ignore[import-not-found]

    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )

    class _RecusaASegunda(OutboundFake):
        async def _deliver(self, message_id, kind, payload) -> None:
            if kind == KINDS_DAS_FICHAS[1]:
                raise EnvioRecusado("http 400 codigo 131053")
            await super()._deliver(message_id, kind, payload)

    outbound = _RecusaASegunda(get_sessionmaker())

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 2


async def test_a_linha_do_tempo_grava_as_tres_legendas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D16. O que se grava e o que o lead recebeu.

    Gravar so a prosa faria o turno seguinte reapresentar os mesmos tres
    imoveis por nao saber que ja os mostrou.
    """
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    gravado = await _texto_gravado()
    for legenda in outbound.entregues:
        assert legenda in gravado


async def test_imovel_sem_foto_sai_como_texto(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D13, quarto cenario do Gherkin: a ausencia de imagem nao esconde o
    imovel."""
    identificador = await _imovel(session, "AP-001", 50000000, fotos=[])
    classificador = _ClassificadorComCandidatos([_candidato(identificador, 50000000)])
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    (entregue,) = outbound.entregues
    assert "Apartamento AP-001" in entregue
