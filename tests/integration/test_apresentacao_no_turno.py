"""A apresentacao de imoveis dentro do turno. TEC-162.

Basename distinto de tudo em `tests/unit/`, e rima com
`test_busca_no_turno.py`.
"""

import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from mobia.domain.agente.schemas import (
    LIMIAR_DE_DESAMBIGUACAO,
    Extracao,
    Intencao,
    PerguntaDeDesambiguacao,
    RespostaDoAgente,
)
from mobia.domain.agente.turno import KINDS_DAS_FICHAS
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
    ) -> None:
        self.candidatos = candidatos
        self.perguntou = perguntou
        self.confianca = confianca

    async def classificar(self, contexto: ContextoMontado, *, porta=None) -> RespostaDoAgente:
        return RespostaDoAgente(
            intencao=Intencao.COMPRA,
            confianca=self.confianca,
            resposta=PROSA,
            modelo="claude-opus-5",
            tokens_in=500,
            tokens_out=80,
            latency_ms=50,
            extracao=Extracao(),
            perguntou=self.perguntou,
            candidatos=self.candidatos,
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
