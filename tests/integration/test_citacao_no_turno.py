"""O bloqueio de citacao dentro do turno. TEC-161.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_apresentacao_no_turno.py`, de onde o harness abaixo foi copiado. Os
arquivos de integracao deste repo sao autocontidos de proposito.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from mobia.domain.agente.schemas import Extracao, Intencao, RespostaDoAgente
from mobia.domain.agente.turno import KINDS_DAS_FICHAS, TEXTO_DA_BUSCA_INCONCLUSIVA
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.montagem import ContextoMontado
from mobia.domain.outbound.models import OutboundDispatch
from mobia.infra.db import get_sessionmaker

PROSA_LIMPA = "Achei tres opcoes que encaixam no que voce falou."
PROSA_INVENTADA = "Achei um otimo por R$ 900 mil."
PRECO = 51_646_430


async def _imovel(session: Any, codigo: str, preco: int) -> uuid.UUID:
    identificador = uuid.uuid4()
    session.add(
        Imovel(
            id=identificador,
            codigo=codigo,
            titulo=f"Apartamento {codigo}",
            descricao="Sala ampla com varanda.",
            tipo="APARTAMENTO",
            operacao="VENDA",
            preco_venda=preco,
            condominio=55000,
            bairro="Lagoa da Conceicao",
            bairro_busca="lagoa da conceicao",
            cidade="Florianopolis",
            uf="SC",
            area_util_m2=54,
            quartos=4,
            suites=1,
            banheiros=2,
            vagas=2,
            caracteristicas=["churrasqueira", "mobiliado"],
            fotos=[f"https://exemplo.com/{codigo}.jpg"],
            status="DISPONIVEL",
        )
    )
    await session.commit()
    return identificador


def _candidato(identificador: uuid.UUID, codigo: str, preco: int) -> dict[str, Any]:
    return {
        "imovel_id": str(identificador),
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "bairro": "Lagoa da Conceicao",
        "preco_centavos": preco,
        "quartos": 4,
        "vagas": 2,
        "area_util_m2": 54,
    }


class _ClassificadorComProsa:
    """Prosa fixa e candidatos fixos: o assunto aqui e a guarda, nao a busca."""

    def __init__(
        self,
        prosa: str,
        candidatos: list[dict[str, Any]],
        perguntou: tuple[str, ...] = (),
    ) -> None:
        self.prosa = prosa
        self.candidatos = candidatos
        self.perguntou = perguntou

    async def classificar(
        self, contexto: ContextoMontado, *, porta: Any = None
    ) -> RespostaDoAgente:
        return RespostaDoAgente(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            resposta=self.prosa,
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=Extracao(),
            perguntou=self.perguntou,
            candidatos=self.candidatos,
        )

    async def desambiguar(self, contexto: ContextoMontado) -> Any:
        raise AssertionError("confianca alta o bastante para nao desambiguar")


async def _kinds_reservados() -> list[str]:
    async with get_sessionmaker()() as leitura:
        return sorted((await leitura.scalars(select(OutboundDispatch.kind))).all())


async def test_prosa_consistente_segue_como_prefixo(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """O caminho feliz nao muda. Sem este teste, uma guarda quebrada que
    bloqueia SEMPRE passaria nos outros dois."""
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_LIMPA, [_candidato(identificador, "AP-1004", PRECO)]
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues[0].startswith(f"{PROSA_LIMPA}\n\n")


async def test_prosa_inventada_vira_ficha_pura(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D8: descarta a prosa, nao o turno.

    O lead recebe o imovel -- que veio do banco e esta certo -- sem a frase
    que inventou um preco. A ficha e o conteudo da RN-10.1; a prosa e
    ornamento, e e ela que cede sob pressao de confianca.
    """
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_INVENTADA, [_candidato(identificador, "AP-1004", PRECO)]
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 1
    assert "900" not in outbound.entregues[0]
    assert not outbound.entregues[0].startswith(PROSA_INVENTADA)
    # A ficha continua inteira: bloquear a prosa nao pode calar o imovel.
    assert "Apartamento AP-1004" in outbound.entregues[0]
    assert await _kinds_reservados() == [KINDS_DAS_FICHAS[0]]


async def test_prosa_inventada_sem_ficha_vira_verificacao_humana(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D8/D9: sem ficha para entregar, o lead recebe o corretor.

    `perguntou` faz o turno NAO apresentar, entao a prosa e a mensagem
    inteira. Descarta-la sozinha deixaria o lead em silencio.
    """
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_INVENTADA,
        [_candidato(identificador, "AP-1004", PRECO)],
        perguntou=("regiao",),
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == [TEXTO_DA_BUSCA_INCONCLUSIVA]
    assert await _kinds_reservados() == ["reply"]


async def test_sem_busca_a_cifra_inventada_bloqueia(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D7: o caso RT-01 mais puro -- o modelo nao chamou a ferramenta e mesmo
    assim citou preco. E a lacuna 3 que a TEC-265 deixou aberta."""
    classificador = _ClassificadorComProsa(PROSA_INVENTADA, [])
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == [TEXTO_DA_BUSCA_INCONCLUSIVA]


async def test_nenhuma_reserva_e_gravada_antes_da_validacao(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """A invariante que a card cobra, travada como teste.

    Bloquear DEPOIS da reserva deixaria linha gravada em `outbound_dispatches`
    e mensagem entregue -- o dano exato que esta card existe para impedir.
    Um unico kind reservado, e nenhum dele carrega a prosa inventada.
    """
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_INVENTADA, [_candidato(identificador, "AP-1004", PRECO)]
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert await _kinds_reservados() == [KINDS_DAS_FICHAS[0]]
    assert all("900" not in entregue for entregue in outbound.entregues)
