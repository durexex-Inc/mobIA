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

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import structlog

from mobia.domain.agente.apresentacao import Ficha, diferencial_de, reais_de
from mobia.domain.catalogo.enums import EstadoDoRelaxamento, Operacao, TipoImovel
from mobia.domain.catalogo.relaxamento import buscar_com_relaxamento
from mobia.domain.catalogo.repositorio import imoveis_por_ids
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


def _criterios_de(filtro: FiltroDeBusca) -> list[str]:
    """Os criterios que entraram no WHERE, em forma legivel. TEC-163, D4.

    Um por BUSCA e nao por candidato: e a mesma lista para todos os imoveis
    daquela apresentacao, e repeti-la por candidato pagaria tokens no
    `tool_result` para dizer tres vezes a mesma coisa.

    `operacao` fica de fora de proposito: ela nao restringe o que o lead
    pediu, escolhe a coluna de preco. "VENDA" como motivo de match nao
    explica nada a quem le a linha depois.
    """
    criterios: list[str] = []
    if filtro.quartos_min is not None:
        criterios.append(f"{filtro.quartos_min} quartos")
    if filtro.vagas_min is not None:
        criterios.append(f"{filtro.vagas_min} vagas")
    if filtro.tipo is not None:
        criterios.append(filtro.tipo.value.lower())
    if filtro.regioes:
        criterios.extend(filtro.regioes)
    if filtro.preco_max_centavos is not None:
        criterios.append(f"ate {reais_de(filtro.preco_max_centavos)}")
    return criterios


class _PortaComScore:
    """A porta de busca, com um canal de scores que o `tool_result` nao carrega.

    TEC-163, D17. `porta_de_busca` e fabrica chamada UMA VEZ POR TURNO (ver
    `turno.py`) -- o dict de scores desta instancia nasce vazio a cada
    chamada e morre com o turno que a criou.

    **Por que um canal separado, e nao a rota obvia.** O obvio seria devolver
    `score` dentro do dict que `__call__` retorna, porque e dali que o
    classificador pega tudo o mais. A TEC-265 (D7) proibiu isso de proposito:
    `score` no prompt convida o modelo a dizer "97% de compatibilidade" ao
    lead, um numero inventado com aparencia de fato. Escrever `0.0` no lugar
    do score real evitaria o prompt mas tornaria a coluna `score_match`
    decorativa -- e falsificaria a premissa do D4 ("o que distingue os
    candidatos e o `score_match`"). Por isso o score viaja por um metodo que
    o modelo nunca chama: quem le e o turno, depois da busca, para montar a
    `Recomendacao` (Task 3). Se algum dia isto for "arrumado" para voltar ao
    dict devolvido, o D7 volta a valer e o motivo de ele existir se repete.

    Continua servindo de `PortaDeBusca` (`Callable[[dict], Awaitable[dict]]`)
    para o classificador, que so sabe chamar um callable -- D3 nao muda.
    """

    def __init__(self, chamar: PortaDeBusca, scores: dict[uuid.UUID, float]) -> None:
        self._chamar = chamar
        self._scores = scores

    async def __call__(self, entrada: dict[str, Any]) -> dict[str, Any]:
        return await self._chamar(entrada)

    def score_de(self, imovel_id: uuid.UUID) -> float | None:
        """O `score_match` do candidato, da ultima busca deste turno que o
        trouxe. `None` se este imovel nunca apareceu numa busca desta porta.
        """
        return self._scores.get(imovel_id)


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

    Devolve um `_PortaComScore` e nao a funcao `porta` diretamente: TEC-163
    precisa que o turno recupere o `score` de cada candidato para gravar
    `Recomendacao`, sem que esse numero passe pelo `tool_result` que o modelo
    le (D7 da TEC-265). O dict `scores` e criado aqui, por chamada de
    `porta_de_busca`, para que duas portas (dois turnos) nunca compartilhem
    score um do outro -- ver `test_duas_portas_nao_compartilham_scores`.
    """
    executar = buscar or buscar_com_relaxamento
    scores: dict[uuid.UUID, float] = {}

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

        # TEC-163, D17. Guarda o score de cada candidato desta busca no dict
        # da porta -- NUNCA no `saida` abaixo, que e o `tool_result` que o
        # modelo le. O turno recupera via `_PortaComScore.score_de` depois da
        # busca, para gravar `Recomendacao.score_match`.
        for candidato in resultado.candidatos:
            scores[candidato.imovel_id] = candidato.score

        saida: dict[str, Any] = {
            "candidatos": [_candidato_serializavel(c) for c in resultado.candidatos],
            # RN-09.2: o agente precisa saber que ve 10 de 40.
            "total_candidatos": resultado.total_candidatos,
            # RN-09.3, D6. Booleanos derivados do tri-estado do dominio, num
            # lugar so -- o estado impossivel ("nao tentei, mas apliquei") fica
            # irrepresentavel tambem aqui.
            "relaxamento_aplicado": resultado.relaxamento is EstadoDoRelaxamento.APLICADO,
            "relaxamento_sem_resultado": (
                resultado.relaxamento is EstadoDoRelaxamento.SEM_RESULTADO
            ),
            # D11. QUAIS dimensoes cederam. Nao explicado ao modelo: ele nao
            # redige o aviso, o turno redige (Task 9).
            "relaxamento_de_preco": resultado.relaxou_preco,
            "relaxamento_de_bairro": resultado.relaxou_bairro,
            # TEC-163, D4. Um campo por busca: o turno monta o `motivo_match`
            # a partir daqui, em Python. Sem isto, ou o motivo seria escrito
            # pelo modelo (D5 recusa) ou o turno nao teria como saber o que
            # o filtro pediu -- ele so ve os candidatos.
            "criterios": _criterios_de(filtro),
        }

        if saida["relaxamento_aplicado"]:
            # A frase abaixo NAO entra em SISTEMA_DO_AGENTE (classificador.py),
            # de proposito -- decisao da TEC-160. Medido nesta card: o teto
            # fixo tinha 6,2 tokens de margem contra os ~19,25 tokens desta
            # frase, e o teto derivado (contexto_headroom_de_tokens * 0,75)
            # ficava so 2 tokens acima do fixo -- subir o fixo o tornaria
            # decorativo, e toda linha cortavel do prompt vem de uma card
            # anterior. Aqui dentro o aviso e `tool_result`, contado por
            # `montar_contexto`: nunca toca o teto fixo e custa zero nos
            # turnos (~99%) em que nada relaxou.
            saida["aviso"] = (
                "criterio ampliado: estes imoveis passam do que o lead pediu; "
                "nao afirme que atendem"
            )

        return saida

    return _PortaComScore(porta, scores)


async def fichas_do_catalogo(
    session_factory: Any,
    *,
    ids: Sequence[uuid.UUID],
    precos: Mapping[uuid.UUID, int],
) -> tuple[Ficha, ...]:
    """As fichas dos imoveis pedidos, na ordem pedida. TEC-162.

    Mora NESTE arquivo, e nao em `apresentacao.py`, pela invariante do
    docstring do modulo: aqui e o unico lugar em que `domain/agente` importa
    `domain/catalogo`. Esta funcao e a unica peca que precisa ver `Imovel` e
    `Ficha` ao mesmo tempo, e `apresentacao.py` fica puro por causa dela.

    `precos` vem do dict do candidato e NAO da linha rebuscada: a linha tem
    `preco_venda` e `preco_aluguel` e nao diz qual usar, porque a operacao
    buscada so existe dentro de `porta_de_busca`. Ler a coluna aqui faria
    toda busca de aluguel mostrar preco de venda ao lead -- ver a D7 do
    desenho.
    """
    async with session_factory() as session:
        imoveis = await imoveis_por_ids(session, ids)

    return tuple(
        Ficha(
            id=imovel.id,
            titulo=imovel.titulo,
            bairro=imovel.bairro,
            preco_centavos=precos[imovel.id],
            quartos=imovel.quartos,
            vagas=imovel.vagas,
            area_util_m2=imovel.area_util_m2,
            condominio_centavos=imovel.condominio,
            diferencial=diferencial_de(imovel.caracteristicas),
            foto=imovel.fotos[0] if imovel.fotos else None,
        )
        for imovel in imoveis
    )
