"""A ferramenta de busca do agente e a porta que a executa.

Basename distinto de tudo em `tests/integration/`.
"""

import json
import uuid
from typing import Any

from mobia.domain.agente.ferramenta_de_busca import FERRAMENTA_DE_BUSCA, porta_de_busca
from mobia.domain.catalogo.enums import EstadoDoRelaxamento, Operacao, TipoImovel
from mobia.domain.catalogo.schemas import Candidato, ResultadoDaBusca

CANDIDATO = Candidato(
    imovel_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    codigo="AP-001",
    titulo="Apartamento na Vila Mariana",
    bairro="Vila Mariana",
    preco_centavos=74900000,
    quartos=3,
    vagas=2,
    area_util_m2=78,
    score=0.87,
    tem_vetor=True,
)


class _BuscaEspia:
    """Substitui `buscar`: guarda o filtro recebido e devolve um resultado fixo."""

    def __init__(self, resultado: ResultadoDaBusca | None = None) -> None:
        self.filtros: list[Any] = []
        self.consultas: list[str | None] = []
        self.resultado = resultado or ResultadoDaBusca(
            candidatos=(CANDIDATO,), total_candidatos=40, consulta_vetorizada=True
        )

    async def __call__(self, session, filtro, consulta_texto=None, **_: object):
        self.filtros.append(filtro)
        self.consultas.append(consulta_texto)
        return self.resultado


def _porta(busca: Any) -> Any:
    """A porta com a busca trocada e sem fabrica de sessao de verdade.

    `session_factory` e um callable que devolve um contexto assincrono; o falso
    aqui nunca e usado porque `_BuscaEspia` ignora a sessao.
    """
    return porta_de_busca(_FabricaFalsa(), buscar=busca)


class _FabricaFalsa:
    def __call__(self) -> "_FabricaFalsa":
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


async def test_a_porta_traduz_o_tool_call_em_filtro() -> None:
    busca = _BuscaEspia()

    saida = await _porta(busca)(
        {
            "operacao": "VENDA",
            "tipo": "APARTAMENTO",
            "regioes": ["Vila Mariana"],
            "preco_max_centavos": 80000000,
            "quartos_min": 3,
            "vagas_min": 1,
            "consulta_texto": "varanda gourmet",
        }
    )

    filtro = busca.filtros[0]
    assert filtro.operacao is Operacao.VENDA
    assert filtro.tipo is TipoImovel.APARTAMENTO
    assert filtro.regioes == ("Vila Mariana",)
    assert filtro.preco_max_centavos == 80000000
    assert filtro.quartos_min == 3
    assert filtro.vagas_min == 1
    assert busca.consultas[0] == "varanda gourmet"
    assert saida["total_candidatos"] == 40


async def test_o_tool_result_leva_fato_do_imovel_e_nao_diagnostico_nosso() -> None:
    """D7: `score` e `tem_vetor` sao nossos, nao do imovel.

    Mandar `score` convida o modelo a dizer "97% de compatibilidade" ao lead --
    numero inventado com aparencia de fato.
    """
    saida = await _porta(_BuscaEspia())({"operacao": "VENDA"})

    (candidato,) = saida["candidatos"]
    assert candidato["imovel_id"] == "11111111-1111-1111-1111-111111111111"
    assert candidato["preco_centavos"] == 74900000
    assert candidato["codigo"] == "AP-001"
    assert "score" not in candidato
    assert "tem_vetor" not in candidato
    # Serializavel: o bloco `tool_result` vai como JSON.
    json.dumps(saida)


async def test_tipo_que_o_dominio_nao_le_derruba_a_dimensao_e_nao_a_busca() -> None:
    """D6: filtro ilegivel nao pode ESTREITAR em silencio.

    Alargar produz candidatos que alguem ve; estreitar produz zero resultados
    que parecem catalogo vazio.
    """
    busca = _BuscaEspia()

    saida = await _porta(busca)({"operacao": "VENDA", "tipo": "LOFT"})

    assert busca.filtros[0].tipo is None
    assert saida["candidatos"]


async def test_operacao_que_o_dominio_nao_le_e_erro_e_nao_dimensao_derrubada() -> None:
    """D11: `operacao` escolhe a coluna de preco -- sem ela nao existe busca.

    O `enum` do schema deveria impedir, mas a garantia depende de `strict`; a
    porta e o que sobra se ele sair.
    """
    busca = _BuscaEspia()

    saida = await _porta(busca)({"operacao": "COMPRA"})

    assert "erro" in saida
    assert busca.filtros == []


async def test_operacao_ambos_e_erro_e_nao_levanta() -> None:
    """D9 e D11: `AMBOS` e membro valido do enum, mas nao tem coluna de preco.

    `Operacao("AMBOS")` passa incolume pelo `except ValueError` da porta --
    quem barra `AMBOS` e o `FiltroDeBusca.__post_init__`, que levanta
    `ValueError` por fora de qualquer `try` da porta se ninguem checar antes.
    Excecao aqui violaria a D9 ("falha de busca devolve erro, nunca levanta")
    e derrubaria o turno inteiro por uma operacao que o proprio catalogo diz
    que "e o que um imovel pode ser, nunca o que uma busca pede".
    """
    busca = _BuscaEspia()

    saida = await _porta(busca)({"operacao": "AMBOS"})

    assert "erro" in saida
    assert busca.filtros == []


async def test_busca_que_levanta_vira_erro_e_nao_derruba_o_turno() -> None:
    async def explode(*_: object, **__: object) -> None:
        raise RuntimeError("banco fora")

    saida = await _porta(explode)({"operacao": "VENDA"})

    assert "erro" in saida


async def test_consulta_texto_ausente_busca_sem_vetor() -> None:
    busca = _BuscaEspia()

    await _porta(busca)({"operacao": "VENDA"})

    assert busca.consultas[0] is None


def test_a_ferramenta_declara_operacao_como_enum() -> None:
    """D11, e o `enum` custa +7,5 tokens de proposito."""
    propriedades = FERRAMENTA_DE_BUSCA["input_schema"]["properties"]
    assert propriedades["operacao"]["enum"] == ["VENDA", "ALUGUEL"]
    assert "enum" not in propriedades["tipo"]
    assert FERRAMENTA_DE_BUSCA["input_schema"]["additionalProperties"] is False


async def test_o_tool_result_diz_que_relaxou_e_avisa_o_modelo() -> None:
    """D6 e D12. O modelo precisa saber, senao afirma ao lead que achou o
    pedido exato sobre um imovel fora do criterio original."""
    busca = _BuscaEspia(
        ResultadoDaBusca(
            candidatos=(CANDIDATO,),
            total_candidatos=1,
            consulta_vetorizada=True,
            relaxamento=EstadoDoRelaxamento.APLICADO,
        )
    )

    saida = await _porta(busca)({"operacao": "VENDA"})

    assert saida["relaxamento_aplicado"] is True
    assert saida["relaxamento_sem_resultado"] is False
    assert saida["aviso"] == (
        "criterio ampliado: estes imoveis passam do que o lead pediu; nao afirme que atendem"
    )


async def test_o_tool_result_distingue_relaxou_e_nao_achou() -> None:
    """Regra 4 da card: o turno precisa dos tres estados, e dois booleanos
    derivados de um enum os carregam sem permitir o estado impossivel.

    Sem resultado mesmo apos relaxar nao carrega `aviso` -- o modelo nao
    redige esse aviso, o turno redige (Task 9), a partir do proprio enum.
    """
    busca = _BuscaEspia(
        ResultadoDaBusca(
            candidatos=(),
            total_candidatos=0,
            consulta_vetorizada=True,
            relaxamento=EstadoDoRelaxamento.SEM_RESULTADO,
        )
    )

    saida = await _porta(busca)({"operacao": "VENDA"})

    assert saida["relaxamento_aplicado"] is False
    assert saida["relaxamento_sem_resultado"] is True
    assert "aviso" not in saida


async def test_o_tool_result_sem_relaxamento_nao_carrega_aviso() -> None:
    """`NAO_HOUVE` e o caso comum (~99% dos turnos): nenhum dos dois booleanos
    e verdadeiro, e a chave `aviso` nem aparece -- custo zero no tool_result."""
    saida = await _porta(_BuscaEspia())({"operacao": "VENDA"})

    assert saida["relaxamento_aplicado"] is False
    assert saida["relaxamento_sem_resultado"] is False
    assert "aviso" not in saida


async def test_o_tool_result_leva_as_duas_dimensoes_do_relaxamento() -> None:
    """D11: o aviso ao lead tem variantes por dimensao, e o turno (Task 9) e
    quem escolhe -- os dois booleanos precisam viajar independentes."""
    busca = _BuscaEspia(
        ResultadoDaBusca(
            candidatos=(CANDIDATO,),
            total_candidatos=1,
            consulta_vetorizada=True,
            relaxamento=EstadoDoRelaxamento.APLICADO,
            relaxou_preco=True,
            relaxou_bairro=False,
        )
    )

    saida = await _porta(busca)({"operacao": "VENDA"})

    assert saida["relaxamento_de_preco"] is True
    assert saida["relaxamento_de_bairro"] is False
