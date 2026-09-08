"""A ferramenta de busca do agente, e a porta que a executa.

TEC-265. **Este e o unico arquivo em que `domain/agente` toca
`domain/catalogo`**, e o acoplamento fica aqui de proposito: o agente consome
o catalogo, o catalogo nao sabe que existe agente. Espalhar a importacao pelos
outros modulos do agente tornaria a direcao invisivel.

A traducao do input do tool call em `FiltroDeBusca` mora aqui pelo mesmo
motivo (D3 do desenho): `classificar` nao conhece `FiltroDeBusca` e
`busca.py` nao conhece o formato do tool call. Com a traducao num lugar so,
ela tem nome nos testes.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from mobia.domain.catalogo.busca import buscar as buscar_de_verdade
from mobia.domain.catalogo.enums import Operacao, TipoImovel
from mobia.domain.catalogo.schemas import COLUNA_DE_PRECO, Candidato, FiltroDeBusca

log = structlog.get_logger(__name__)

PortaDeBusca = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# `operacao` e `enum` e `tipo` nao e, e a assimetria e a D11 do desenho:
# `tipo` e dimensao DESCARTAVEL (valor ilegivel sai do filtro e a busca
# acontece), `operacao` escolhe a coluna de preco e `FiltroDeBusca` recusa
# default para ela. O `enum` custa +7,5 tokens do orcamento do prompt e faz o
# modelo traduzir COMPRA -> VENDA sozinho -- o vocabulario do agente
# (`Intencao.COMPRA`) e o do catalogo (`Operacao.VENDA`) discordam, e sem isso
# `Operacao("COMPRA")` levantaria em turno normal.
#
# Alongar a `description` ou acrescentar propriedade aqui gasta reserva de
# contexto: cada caractere e enviado em toda chamada. Antes de mexer, rode
# `pytest -q -k margem_do_orcamento -s`.
FERRAMENTA_DE_BUSCA: dict[str, Any] = {
    "name": "buscar_imoveis",
    "description": "Busca no catalogo. Nunca cite imovel que nao veio dela.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "operacao": {"type": "string", "enum": ["VENDA", "ALUGUEL"]},
            "tipo": {"type": "string"},
            "regioes": {"type": "array", "items": {"type": "string"}},
            "preco_max_centavos": {"type": "integer"},
            "quartos_min": {"type": "integer"},
            "vagas_min": {"type": "integer"},
            "consulta_texto": {"type": "string"},
        },
        "required": ["operacao"],
        "additionalProperties": False,
    },
}


def _tipo_de(bruto: object) -> TipoImovel | None:
    """O tipo pedido, ou None quando o dominio nao le o valor.

    D6: derrubar a dimensao e nao a busca. Um filtro que o dominio nao entende
    nao pode ESTREITAR o resultado em silencio -- alargar produz candidatos que
    alguem ve e um evento que alguem conta; estreitar produz zero resultados
    que parecem catalogo vazio.
    """
    if bruto is None:
        return None
    try:
        return TipoImovel(str(bruto))
    except ValueError:
        log.info("catalogo.tool_call_tipo_ilegivel", valor=str(bruto))
        return None


def _candidato_serializavel(candidato: Candidato) -> dict[str, Any]:
    """O que o modelo ve de um candidato.

    D7: `score` e `tem_vetor` NAO entram. Sao diagnostico do nosso lado, e
    `score` no prompt convida o modelo a dizer "97% de compatibilidade" ao
    lead -- dado inventado com aparencia de numero. `preco_centavos` vai como
    inteiro porque formatar e apresentacao (TEC-162) e porque inteiro e o que
    a TEC-161 vai comparar.
    """
    return {
        "imovel_id": str(candidato.imovel_id),
        "codigo": candidato.codigo,
        "titulo": candidato.titulo,
        "bairro": candidato.bairro,
        "preco_centavos": candidato.preco_centavos,
        "quartos": candidato.quartos,
        "vagas": candidato.vagas,
        "area_util_m2": candidato.area_util_m2,
    }


def porta_de_busca(
    session_factory: Any,
    *,
    buscar: Any = None,
    embedador: Any = None,
) -> PortaDeBusca:
    """A porta que o classificador chama quando o modelo pede a ferramenta.

    `buscar` e `embedador` sao injetaveis para o teste unitario nao precisar de
    banco nem de chave -- o mesmo molde do `embedador` que `indexar_catalogo`
    recebe pelo `ctx`.
    """
    executar = buscar or buscar_de_verdade

    async def porta(entrada: dict[str, Any]) -> dict[str, Any]:
        operacao_bruta = str(entrada.get("operacao"))
        try:
            operacao: Operacao | None = Operacao(operacao_bruta)
        except ValueError:
            operacao = None

        # D11: sem operacao BUSCAVEL nao existe busca -- ela escolhe a coluna
        # de preco. Dois valores chegam aqui sem coluna: um que o enum nem
        # reconhece (`Operacao(...)` levanta acima, ex.: "COMPRA") e um que o
        # enum reconhece mas `FiltroDeBusca` recusa (`AMBOS`, que e o que um
        # imovel pode SER e nunca o que uma busca pede -- ver o comentario de
        # `__post_init__` em catalogo/schemas.py). `COLUNA_DE_PRECO` e a unica
        # definicao de "operacao buscavel"; checar contra ela em vez de
        # nomear `AMBOS` aqui evita duplicar aquela regra numa segunda copia
        # que poderia divergir dela. Sem esta checagem, `AMBOS` passava pelo
        # `except` acima e so levantava dentro de `FiltroDeBusca`, fora dos
        # dois `try` da porta -- exatamente o `raise` que a D9 proibe.
        if operacao is None or operacao not in COLUNA_DE_PRECO:
            log.warning("catalogo.tool_call_operacao_ilegivel", valor=operacao_bruta)
            return {"erro": "operacao invalida: use VENDA ou ALUGUEL"}

        regioes = tuple(str(regiao) for regiao in entrada.get("regioes") or ())
        filtro = FiltroDeBusca(
            operacao=operacao,
            preco_max_centavos=entrada.get("preco_max_centavos"),
            tipo=_tipo_de(entrada.get("tipo")),
            quartos_min=entrada.get("quartos_min"),
            vagas_min=entrada.get("vagas_min"),
            regioes=regioes,
        )

        consulta = entrada.get("consulta_texto")

        try:
            async with session_factory() as session:
                resultado = await executar(
                    session,
                    filtro,
                    consulta_texto=consulta,
                    embedador=embedador,
                )
        except Exception as erro:
            # D9: `erro` no `tool_result`, nunca excecao. Excecao aqui mataria o
            # turno inteiro por causa de uma busca, e a regra que o
            # `indexar_catalogo` documenta e a oposta.
            log.warning("catalogo.tool_call_falhou", tipo=type(erro).__name__)
            return {"erro": "a busca nao pode ser feita agora"}

        return {
            "candidatos": [_candidato_serializavel(c) for c in resultado.candidatos],
            # RN-09.2: o agente precisa saber que ve 10 de 40.
            "total_candidatos": resultado.total_candidatos,
        }

    return porta
