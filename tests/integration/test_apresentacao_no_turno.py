"""A apresentacao de imoveis dentro do turno. TEC-162.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_busca_no_turno.py`.
"""

import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from mobia.domain.agente.apresentacao import (
    MAX_CARACTERES_DA_LEGENDA,
    Ficha,
    diferencial_de,
    legenda_de,
)
from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO
from mobia.domain.agente.schemas import (
    LIMIAR_DE_DESAMBIGUACAO,
    Extracao,
    Intencao,
    PerguntaDeDesambiguacao,
    RespostaDoAgente,
)
from mobia.domain.agente.turno import (
    KIND_DO_CRITERIO_AMPLIADO,
    KINDS_DAS_FICHAS,
    aviso_de_ampliacao,
)
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.montagem import ContextoMontado
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRecusado
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.db import get_sessionmaker

PROSA = "Achei tres opcoes que encaixam no que voce falou."
PERGUNTA_DO_DESAMBIGUADOR = "Voce procura para morar ou para investir?"


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

    def __init__(
        self,
        candidatos: list[dict[str, Any]],
        perguntou: tuple[str, ...] = (),
        confianca: Decimal = Decimal("0.95"),
        prosa: str = PROSA,
        relaxou_e_achou: bool = False,
        relaxou_preco: bool = False,
        relaxou_bairro: bool = False,
    ) -> None:
        self.candidatos = candidatos
        self.perguntou = perguntou
        self.confianca = confianca
        self.prosa = prosa
        # TEC-160, Task 9. Os quatro booleanos que `_relaxamento_de` extrairia
        # do `tool_result` num turno de verdade -- aqui fixados direto, pelo
        # mesmo motivo que `candidatos` ja e fixado direto: o assunto destes
        # testes e o que o TURNO faz com o fato, nao como o classificador
        # extrai o fato do laco de tool use (isso ja tem cobertura propria em
        # `test_relaxamento_alargar.py` e em `test_busca_no_turno.py`).
        self.relaxou_e_achou = relaxou_e_achou
        self.relaxou_preco = relaxou_preco
        self.relaxou_bairro = relaxou_bairro

    async def classificar(self, contexto: ContextoMontado, *, porta=None) -> RespostaDoAgente:
        return RespostaDoAgente(
            intencao=Intencao.COMPRA,
            confianca=self.confianca,
            resposta=self.prosa,
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=Extracao(),
            perguntou=self.perguntou,
            candidatos=self.candidatos,
            relaxou_e_achou=self.relaxou_e_achou,
            relaxou_preco=self.relaxou_preco,
            relaxou_bairro=self.relaxou_bairro,
        )

    async def desambiguar(self, contexto: ContextoMontado) -> PerguntaDeDesambiguacao:
        if self.confianca >= LIMIAR_DE_DESAMBIGUACAO:
            raise AssertionError("confianca alta o bastante para nao desambiguar")
        return PerguntaDeDesambiguacao(
            texto=PERGUNTA_DO_DESAMBIGUADOR,
            modelo="claude-opus-5",
            tokens_in=200,
            tokens_out=30,
            latency_ms=40,
        )


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


async def _conversa_ja_existe(session: Any) -> None:
    """Semeia uma entrada anterior para que `e_conversa_nova` veja a
    conversa como NAO nova (TEC-139).

    Os testes que chamam isto provam coisas sobre FICHAS (RN-10.2, D5, D6,
    D9, D10, D13, D16) ou sobre a trilha de texto comum (D4) -- nenhum e
    sobre identificacao, que tem arquivo proprio
    (`test_identificacao_no_turno.py`). Sem isto, `banco_limpo` (autouse)
    deixa cada teste comecar em silencio total, `e_conversa_nova` devolveria
    True e a mensagem de identificacao extra contaminaria contagens e
    unpacking que nao sao sobre ela.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


async def test_dez_candidatos_produzem_exatamente_tres_fichas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """RN-10.2: maximo de 3 por turno, mesmo com 10 candidatos."""
    await _conversa_ja_existe(session)
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
    await _conversa_ja_existe(session)
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


async def test_prosa_longa_na_apresentacao_nao_vira_mensagem_de_texto_extra(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """Na apresentacao a prosa vira prefixo da legenda, e `legenda_de` tem teto
    e regra de corte proprios (D14 da TEC-162). A quebra da TEC-140 nao pode
    alcancar este caminho: duas regras de tamanho disputando o mesmo texto
    discordariam na primeira vez que alguem mexesse numa delas.
    """
    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA

    await _conversa_ja_existe(session)
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)],
        prosa="Uma prosa bem longa para forcar o corte da legenda. " * 15,
    )
    outbound = outbound_fake()

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    assert len(outbound.entregues) == 3
    reservados = await _kinds_reservados()
    assert not set(reservados) & set(KINDS_DA_RESPOSTA)


async def test_pergunta_no_turno_adia_as_fichas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D4. Candidatos nao-vazios NAO significam que o agente quis apresentar.

    Com `perguntou` preenchido, a prosa sai como texto e as fichas esperam o
    proximo turno -- senao o lead recebe tres fotos e uma pergunta sobre zona
    no mesmo turno, que e a parede que a RN-04.2 existe para evitar.
    """
    await _conversa_ja_existe(session)
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


async def test_desambiguacao_com_candidatos_nao_manda_ficha(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D4, o terceiro conjunto do gatilho -- o que nenhum outro teste cobre.

    Aqui `gerada.perguntou` esta VAZIO e os candidatos existem, entao sem o
    `not desambiguando` o turno apresentaria fichas. Mas o texto que sai e a
    pergunta do desambiguador, e `gerada.perguntou` fala da chamada 1, que foi
    descartada -- mandar tres fotos junto com "morar ou investir?" e a mesma
    parede que a RN-04.2 fecha. Sem este teste, apagar `not desambiguando`
    passa nos outros sete.
    """
    await _conversa_ja_existe(session)
    identificador = await _imovel(session, "AP-001", 50000000)
    classificador = _ClassificadorComCandidatos(
        [_candidato(identificador, 50000000)], confianca=Decimal("0.4")
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == [PERGUNTA_DO_DESAMBIGUADOR]
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

    await _conversa_ja_existe(session)
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

    await _conversa_ja_existe(session)
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


async def test_janela_fechada_na_primeira_ficha_expira_o_turno(
    session: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """A ordem das duas clausulas `except` em `_apresentar` e carregada.

    `EnvioForaDaJanela` HERDA de `EnvioRecusado`, entao inverter as clausulas
    faria a janela de 24h fechada cair no ramo da D10: o turno seguiria e
    devolveria "sem_resposta" -- ou "respondido" com as fichas restantes, se a
    janela fechasse no meio -- em vez de "expirado", e o alerta que observa
    janela fechada ficaria cego. Sem este teste a inversao passa em todos os
    outros: nada mais aqui levanta `EnvioForaDaJanela`.
    """
    from conftest import OutboundFake  # type: ignore[import-not-found]

    await _conversa_ja_existe(session)
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )

    class _JanelaFechada(OutboundFake):
        async def _deliver(self, message_id, kind, payload) -> None:
            if kind == KINDS_DAS_FICHAS[0]:
                raise EnvioForaDaJanela("re-engagement window closed")
            await super()._deliver(message_id, kind, payload)

    outbound = _JanelaFechada(get_sessionmaker())

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "expirado"
    assert outbound.entregues == [], "janela fechada interrompe a apresentacao inteira"


def _eventos_de_log(caplog: Any, evento: str) -> list[tuple[str, dict[str, Any]]]:
    """(nivel, corpo) de cada registro JSON do structlog que carrega `evento`.

    Mesmo molde de `eventos_de_log` em `tests/features/test_dedup_por_message_id.py`,
    com o nivel junto porque aqui a asserta e sobre ele.
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


async def test_candidato_que_sumiu_do_catalogo_nao_vira_turno_mudo_sem_log(
    session: Any,
    outbound_fake: Any,
    resumidor_fake: Any,
    contador_fake: Any,
    rodar_turno: Any,
    caplog: Any,
) -> None:
    """D6: `imoveis_por_ids` derruba id sem linha, e isso e caminho normal.

    Quando derruba TODOS, o laco de `_apresentar` nunca roda: zero entrega,
    zero `ficha_recusada`, e a prosa ja moderada jogada fora. O turno e
    silencio para o lead, e sem o log de `fichas_sumiram_do_catalogo` seria
    silencio tambem para quem opera -- por isso a asserta e sobre o evento, e
    nao so sobre o desfecho.
    """
    await _conversa_ja_existe(session)
    fantasma = uuid.uuid4()  # nenhuma linha em `imoveis` com este id
    classificador = _ClassificadorComCandidatos([_candidato(fantasma, 50000000)])
    outbound = outbound_fake()

    with caplog.at_level("WARNING"):
        resultado = await rodar_turno(
            session, classificador, outbound, resumidor_fake(), contador_fake()
        )

    assert resultado == "sem_resposta"
    assert outbound.entregues == []
    assert await _kinds_reservados() == []
    ((nivel, evento),) = _eventos_de_log(caplog, "apresentacao.fichas_sumiram_do_catalogo")
    assert nivel == "ERROR", "zero ficha e turno mudo para o lead: tem de acordar alguem"
    assert (evento["pedidas"], evento["encontradas"]) == (1, 0)
    # Fix wave da TEC-162 (Minor): o id que sumiu tem de aparecer no proprio
    # evento -- e o unico log da arvore que sabe qual imovel foi.
    assert evento["imovel_ids_faltantes"] == [str(fantasma)]


async def test_a_linha_do_tempo_grava_as_tres_legendas(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D16. O que se grava e o que o lead recebeu.

    Gravar so a prosa faria o turno seguinte reapresentar os mesmos tres
    imoveis por nao saber que ja os mostrou.
    """
    await _conversa_ja_existe(session)
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
    imovel.

    Fix wave da TEC-162 (Important): a asserta sobre `entregue` (a string
    colapsada) passava mesmo se `_apresentar` mandasse
    `{"tipo": "imagem", "link": None, "legenda": ...}` -- payload que o
    adaptador de verdade repassaria para a Meta como `image.link: null` e
    tomaria 400. Checar o `payload` cru pina a decisao real da D13: sem foto,
    o payload nao tem `tipo` nenhum e cai no mesmo formato que o texto comum.
    """
    await _conversa_ja_existe(session)
    identificador = await _imovel(session, "AP-001", 50000000, fotos=[])
    classificador = _ClassificadorComCandidatos([_candidato(identificador, 50000000)])
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    (entregue,) = outbound.entregues
    assert "Apartamento AP-001" in entregue
    (payload,) = outbound.payloads
    assert "tipo" not in payload
    assert "texto" in payload


async def test_imovel_com_foto_sai_como_imagem_com_link(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """Espelho do teste acima (fix wave da TEC-162, Important). Sem este
    teste, `_apresentar` podia mandar `link: None` mesmo com foto cadastrada e
    nenhuma asserta desta suite pegaria -- `outbound.entregues` so guarda a
    legenda, nunca o link."""
    await _conversa_ja_existe(session)
    identificador = await _imovel(session, "AP-001", 50000000)
    classificador = _ClassificadorComCandidatos([_candidato(identificador, 50000000)])
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    (payload,) = outbound.payloads
    assert payload["tipo"] == "imagem"
    assert payload["link"] == "https://exemplo.com/AP-001.jpg"


async def test_apresentacao_em_conversa_nova_identifica_sem_perder_ficha(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """A ficha e o que a RN-10.1 exige; a identificacao e o que a RN-04.1 exige.
    Nenhuma e ornamento da outra, entao nenhuma pode despejar a outra.

    O titulo tem 160 caracteres DE PROPOSITO -- o maximo que `imoveis.titulo`
    aceita (`String(160)` em `catalogo/models.py`) --, e as duas
    `caracteristicas` da PRIMEIRA ficha sao longas de proposito. Nenhum dos
    dois sozinho bastava: o titulo capado em 160 (Fix 1 deste teste) so daria
    um corpo de ~237 caracteres, que cabe do lado da identificacao mesmo
    dentro do teto de 600 -- a pre-condicao abaixo existe para nunca deixar
    isso passar em silencio de novo. Com as caracteristicas longas, o CORPO
    da legenda (titulo + bairro/preco + quartos/vagas/area + condominio +
    `Destaque: ...`) passa dos 467 caracteres que a identificacao (131
    caracteres) mais o separador (2) precisariam para caber junto dentro do
    teto de 600.

    Prefixar a identificacao a prosa a submeteria ao corte de
    `_prosa_que_cabe`, que devolve string vazia quando nao sobra espaco -- e
    o turno mais comum de uma conversa nova (o lead diz o que procura, o
    agente busca e apresenta) sairia sem identificacao nenhuma, em silencio.
    """
    titulo_longo = "Apartamento reformado com vista " + "A" * 128
    caracteristica_longa_1 = "vista panoramica para o mar e para a lagoa " + "B" * 80
    caracteristica_longa_2 = "reforma completa recente com acabamento premium " + "C" * 80

    primeiro_id = await _imovel(
        session,
        "AP-000",
        50000000,
        titulo=titulo_longo,
        caracteristicas=[caracteristica_longa_1, caracteristica_longa_2],
    )
    outros_ids = [
        await _imovel(session, f"AP-{n:03d}", 50000000 + n, titulo=titulo_longo)
        for n in range(1, 3)
    ]
    ids = [primeiro_id, *outros_ids]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    # Pre-condicao: sem ela este teste e um falso guarda. Reconstroi, pelas
    # mesmas funcoes puras que a producao usa, o CORPO da primeira ficha --
    # sem prosa nem identificacao -- e confere que nem a identificacao
    # sozinha caberia do lado dele dentro do teto de 600. Se esta asserta
    # falhar, o cenario deixou de ser de estouro e as asserta abaixo
    # passariam mesmo com a identificacao viajando ERRADA, prefixada a
    # prosa (o defeito que este teste existe para pegar).
    corpo_da_primeira_ficha = legenda_de(
        Ficha(
            id=primeiro_id,
            titulo=titulo_longo,
            bairro="Lagoa da Conceicao",
            preco_centavos=50000000,
            quartos=4,
            vagas=2,
            area_util_m2=54,
            condominio_centavos=55000,
            diferencial=diferencial_de([caracteristica_longa_1, caracteristica_longa_2]),
            foto=None,
        )
    )
    # 2 == o tamanho do separador entre prosa e ficha em `legenda_de`
    # (`_SEPARADOR_DA_PROSA`, privado -- repetido aqui como literal comentado
    # em vez de importado).
    assert (
        len(corpo_da_primeira_ficha) + 2 + len(TEXTO_DA_IDENTIFICACAO) > MAX_CARACTERES_DA_LEGENDA
    ), "cenario nao esta em estouro: este teste passaria mesmo com a implementacao errada"

    await rodar_turno(session, classificador, outbound, resumidor_fake(), contador_fake())

    tudo = "\n".join(outbound.entregues)
    assert TEXTO_DA_IDENTIFICACAO in tudo, "a identificacao foi cortada pela legenda"
    assert titulo_longo in tudo, "a ficha foi truncada para caber a identificacao"


async def test_o_aviso_de_ampliacao_sai_como_mensagem_propria(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """CA-09.3. Kind proprio, antes das fichas, nunca prefixo de legenda.

    `_conversa_ja_existe` mantem a identificacao fora do caminho -- o assunto
    aqui e o aviso, nao a interacao dele com a TEC-139 (que tem teste
    proprio acima). Sem prefixo: o aviso e a PRIMEIRA mensagem entregue e a
    prosa (`PROSA`) continua sendo o prefixo da legenda da primeira ficha,
    como em `test_a_prosa_vira_prefixo_da_primeira_e_as_outras_sao_ficha_pura`.
    """
    await _conversa_ja_existe(session)
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)],
        relaxou_e_achou=True,
        relaxou_preco=True,
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 4, "aviso + tres fichas"
    assert outbound.entregues[0] == aviso_de_ampliacao(True, False)
    assert outbound.entregues[1].startswith(f"{PROSA}\n\n")
    assert KIND_DO_CRITERIO_AMPLIADO in await _kinds_reservados()


async def test_identificacao_e_aviso_saem_juntos_e_na_ordem_numa_conversa_nova(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """O caso real que amarra as duas trilhas de texto da RN-04.2, TEC-160.

    O teste acima chama `_conversa_ja_existe` de proposito, para isolar o
    aviso da identificacao -- e por isso nunca prova nada sobre a ORDEM entre
    os dois. Este teste NAO chama `_conversa_ja_existe`: e o primeiro lead
    novo cuja primeira busca ja relaxou e achou algo, e as duas mensagens de
    texto (`turno.py`, dentro do mesmo `if apresentando:`) disparam
    incondicionais e em sequencia, uma depois da outra, sem nada que force a
    ordem alem da posicao do codigo.

    **E o turno em que o orcamento da RN-04.2 fica exatamente no limite.** A
    E-02 da TEC-162 permite ate 2 mensagens de TEXTO e ate 3 de APRESENTACAO
    por turno; identificacao + aviso ja gastam as duas de texto, sobrando so
    as fichas para a cota de apresentacao. Uma card futura que queira uma
    TERCEIRA trilha de texto (identificacao, aviso, e mais alguma) precisa
    emendar a RN-04.2 antes -- e e aqui, se alguem prefixar o aviso a
    identificacao ou trocar a ordem sem querer, que a regressao vai aparecer:
    silenciosa, do mesmo jeito que o comentario de `turno.py` sobre a TEC-139
    descreve para o par identificacao/prosa.
    """
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)],
        relaxou_e_achou=True,
        relaxou_bairro=True,
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 5, "identificacao + aviso + tres fichas"
    assert outbound.entregues[0] == TEXTO_DA_IDENTIFICACAO, "identificacao vem primeiro"
    assert outbound.entregues[1] == aviso_de_ampliacao(False, True), "aviso vem logo depois"
    assert outbound.entregues[2].startswith(f"{PROSA}\n\n"), "so entao a primeira ficha"
    assert KIND_DO_CRITERIO_AMPLIADO in await _kinds_reservados()


async def test_o_aviso_nao_sai_quando_o_modelo_perguntou(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """D10. Pergunta adia as fichas, e avisar "ampliei o criterio" sem mostrar
    alternativa e aviso sobre nada. A CA-09.3 diz "o lead recebe alternativas
    COM aviso": os dois andam juntos ou nenhum anda.
    """
    await _conversa_ja_existe(session)
    identificador = await _imovel(session, "AP-001", 50000000)
    classificador = _ClassificadorComCandidatos(
        [_candidato(identificador, 50000000)],
        perguntou=("regiao",),
        relaxou_e_achou=True,
        relaxou_preco=True,
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert outbound.entregues == [PROSA]
    assert KIND_DO_CRITERIO_AMPLIADO not in await _kinds_reservados()


async def test_busca_sem_relaxamento_nao_avisa(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """Cenario 3 do Gherkin: "nenhum aviso de ampliacao e enviado"."""
    await _conversa_ja_existe(session)
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)]
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 3, "so as fichas, sem aviso"
    assert KIND_DO_CRITERIO_AMPLIADO not in await _kinds_reservados()


async def test_relaxou_e_achou_sem_dimensao_nenhuma_nao_quebra_o_turno(
    session: Any, outbound_fake: Any, resumidor_fake: Any, contador_fake: Any, rodar_turno: Any
) -> None:
    """Ruling do controller sobre o Task 9: o estado impossivel (`relaxou_e_achou`
    True com as duas dimensoes False) nao pode matar o turno.

    `aviso_de_ampliacao` levanta `ValueError` para este par -- ver
    `test_relaxamento_alargar.py` --, e a guarda em `executar_turno`
    (`relaxou_preco or relaxou_bairro`) existe exatamente para nunca chamar a
    funcao com este par. Sem este teste, remover a guarda so quebraria em
    producao, no dia em que o estado impossivel de fato ocorresse.
    """
    await _conversa_ja_existe(session)
    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    classificador = _ClassificadorComCandidatos(
        [_candidato(i, 50000000 + n) for n, i in enumerate(ids)],
        relaxou_e_achou=True,
    )
    outbound = outbound_fake()

    resultado = await rodar_turno(
        session, classificador, outbound, resumidor_fake(), contador_fake()
    )

    assert resultado == "respondido"
    assert len(outbound.entregues) == 3, "so as fichas, sem aviso"
    assert KIND_DO_CRITERIO_AMPLIADO not in await _kinds_reservados()
