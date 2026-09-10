"""O bloqueio de citacao dentro do turno. TEC-161.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_apresentacao_no_turno.py`, de onde o harness abaixo foi copiado. Os
arquivos de integracao deste repo sao autocontidos de proposito.
"""

import json
import uuid
from decimal import Decimal
from typing import Any

from conftest import CANAL_AGENTE, CONVERSA_AGENTE
from sqlalchemy import select

from mobia.domain.agente.schemas import Extracao, Intencao, RespostaDoAgente
from mobia.domain.agente.turno import KINDS_DAS_FICHAS, TEXTO_DA_BUSCA_INCONCLUSIVA
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.montagem import ContextoMontado
from mobia.domain.context.repositorio import ler_estado
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
    """Prosa fixa e candidatos fixos: o assunto aqui e a guarda, nao a busca.

    `intencao` e `extracao` tem default que preserva o comportamento original
    (COMPRA, sem campo nenhum). O teste da faixa ja declarada precisa dos
    dois: INDEFINIDA sem extracao e o unico jeito de `gravar_estado` devolver
    `None` sem tambem gravar coisa nenhuma, e e exatamente o turno que expoe
    o ramo nao-`None` de `_faixa_declarada`.
    """

    def __init__(
        self,
        prosa: str,
        candidatos: list[dict[str, Any]],
        perguntou: tuple[str, ...] = (),
        *,
        intencao: Intencao = Intencao.COMPRA,
        extracao: Extracao | None = None,
    ) -> None:
        self.prosa = prosa
        self.candidatos = candidatos
        self.perguntou = perguntou
        self.intencao = intencao
        self.extracao = extracao if extracao is not None else Extracao()

    async def classificar(
        self, contexto: ContextoMontado, *, porta: Any = None
    ) -> RespostaDoAgente:
        return RespostaDoAgente(
            intencao=self.intencao,
            confianca=Decimal("0.95"),
            resposta=self.prosa,
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=self.extracao,
            perguntou=self.perguntou,
            candidatos=self.candidatos,
        )

    async def desambiguar(self, contexto: ContextoMontado) -> Any:
        raise AssertionError("confianca alta o bastante para nao desambiguar")


async def _kinds_reservados() -> list[str]:
    async with get_sessionmaker()() as leitura:
        return sorted((await leitura.scalars(select(OutboundDispatch.kind))).all())


def _eventos_de_log(caplog: Any, evento: str) -> list[tuple[str, dict[str, Any]]]:
    """(nivel, corpo) de cada registro JSON do structlog que carrega `evento`.

    Mesmo molde de `_eventos_de_log` em `test_apresentacao_no_turno.py`, copiado
    e nao importado -- os arquivos de integracao deste repo sao autocontidos.
    """
    encontrados = []
    for registro in caplog.records:
        try:
            dados = json.loads(registro.getMessage())
        except (json.JSONDecodeError, TypeError):
            continue
        if dados.get("event") == evento:
            encontrados.append((registro.levelname, dados))
    return encontrados


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
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
    caplog: Any,
) -> None:
    """D8: descarta a prosa, nao o turno.

    O lead recebe o imovel -- que veio do banco e esta certo -- sem a frase
    que inventou um preco. A ficha e o conteudo da RN-10.1; a prosa e
    ornamento, e e ela que cede sob pressao de confianca.

    Tambem trava o D10 inteiro, hoje sem asserta nenhuma: o evento
    `citacao.bloqueada` tem de sair com o valor que o modelo inventou, e a
    prosa barrada nao pode aparecer no log -- a mesma regra que vale para a
    moderacao de saida, aqui sobre o proprio evento que a guarda gera.
    """
    identificador = await _imovel(session, "AP-1004", PRECO)
    classificador = _ClassificadorComProsa(
        PROSA_INVENTADA, [_candidato(identificador, "AP-1004", PRECO)]
    )
    outbound = outbound_fake()

    with caplog.at_level("ERROR"):
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

    ((nivel, evento),) = _eventos_de_log(caplog, "citacao.bloqueada")
    assert nivel == "ERROR"
    assert "R$ 900.000" in evento["citados"]
    assert PROSA_INVENTADA not in caplog.text, (
        "a prosa barrada nao pode aparecer no log -- registra-la criaria ali "
        "exatamente o que a guarda impediu de sair"
    )


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

    async with get_sessionmaker()() as leitura:
        estado = await ler_estado(leitura, CANAL_AGENTE, CONVERSA_AGENTE)
    assert estado is not None
    assert "regiao" not in (estado.perguntados_sem_resposta or []), (
        "a guarda de citacao substituiu o texto pelo fallback -- o lead nunca "
        "recebeu a pergunta sobre regiao, e marca-la queimaria a chance de "
        "perguntar de verdade, para sempre e em silencio"
    )


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


async def test_faixa_ja_declarada_absorve_o_eco_do_orcamento(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D5 do desenho: ecoar o orcamento que o lead ja deu nao e invencao.

    `_faixa_declarada` so tinha cobertura do ramo `estado is None` -- os
    outros quatro testes deste arquivo usam intencao COMPRA, que faz
    `gravar_estado` sempre devolver linha (o dict de `campos_a_gravar` nunca
    fica vazio so por causa de `extracao`, porque a propria intencao entra
    nele). `gravar_estado` so devolve `None` para INDEFINIDA sem extracao (ou
    FORA_DE_ESCOPO) -- exatamente o turno em que o modelo so comenta, sem
    extrair nada novo, e e o turno em que o lead mais frequentemente ouve o
    proprio orcamento de volta ("beleza, vou procurar ate X").

    Sem o fallback para `contexto.estado`, este turno perderia a faixa que a
    linha ja tinha (gravada num turno anterior) so porque este turno em
    particular nao gravou nada, e a guarda bloquearia o eco como se fosse
    numero inventado.
    """
    identificador = await _imovel(session, "AP-1004", PRECO)
    # Turno 1: estabelece a faixa. Prosa limpa -- o que importa aqui e o
    # `lead_qualification` que este turno grava, nao a entrega dele.
    primeiro_turno = _ClassificadorComProsa(
        PROSA_LIMPA,
        [],
        intencao=Intencao.COMPRA,
        extracao=Extracao(faixa_preco_max_centavos=60_000_000),
    )
    await rodar_turno(session, primeiro_turno, outbound_fake(), resumidor_fake(), contador_fake())

    # Turno 2: INDEFINIDA sem extracao -- `gravar_estado` devolve None. A
    # cifra citada (R$ 300 mil) fica fora da tolerancia de 10% do candidato
    # (R$ 516.464,30), entao so a faixa do turno 1 pode absolver a prosa.
    eco_do_orcamento = "Beleza, vou procurar ate R$ 300 mil, entao."
    segundo_turno = _ClassificadorComProsa(
        eco_do_orcamento,
        [_candidato(identificador, "AP-1004", PRECO)],
        intencao=Intencao.INDEFINIDA,
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, segundo_turno, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues[0].startswith(f"{eco_do_orcamento}\n\n")
