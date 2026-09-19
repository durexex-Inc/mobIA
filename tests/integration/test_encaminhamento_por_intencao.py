"""O encaminhamento de VENDER_IMOVEL e SUPORTE_CONTRATO. TEC-137.

O handoff, a etiqueta, o log e o resumo destas duas intencoes ja existem desde
a TEC-174 e nao sao assunto deste arquivo -- `test_handoff_no_turno.py` cuida
deles. O que se afirma aqui e o que o LEAD recebe: um texto nosso em lugar da
prosa do modelo, que podia carregar a pergunta de qualificacao de COMPRADOR
que a RN-03.4 tira destas duas conversas.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from mobia.app.config import get_settings
from mobia.domain.agente import turno as turno_mod
from mobia.domain.agente.identificacao import (
    SEPARADOR_DA_IDENTIFICACAO,
    TEXTO_DA_IDENTIFICACAO,
    TEXTO_DA_OFERTA_DE_CORRETOR,
)
from mobia.domain.agente.schemas import Intencao
from mobia.domain.agente.turno import (
    SUFIXO_FORA_DA_JANELA,
    TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
    TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
)
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.models import LeadQualification
from mobia.domain.moderacao.port import TEXTO_NEUTRO_DE_SAIDA

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque `rodar_turno` semeia a fala nessa conversa e o estado tem de casar com
# ela. `test_turno_teto_de_perguntas.py` redefine os dois localmente do mesmo
# jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"

# Pergunta de qualificacao de COMPRADOR -- exatamente o que a RN-03.4 tira
# destas duas intencoes. Ate a TEC-137 era isto que saia.
PROSA_DO_MODELO = "Legal! Em que bairro voce procura e qual a sua faixa de preco?"


@pytest.fixture(autouse=True)
def janela_aberta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Congela a janela de atendimento em ABERTA para todo teste deste arquivo.

    Sem isto o arquivo passaria ou reprovaria conforme a HORA em que a suite
    roda: `dentro_da_janela_de_atendimento` le o relogio real, e fora do
    expediente todo texto esperado ganharia o `SUFIXO_FORA_DA_JANELA`. O teste
    de fora da janela desfaz isto localmente, e e o unico que precisa.
    """
    monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: True)


async def _conversa_ja_existe(session: Any) -> None:
    """Semeia uma fala anterior do lead para que `e_conversa_nova` veja a
    conversa como NAO nova (TEC-139).

    Sem isto a identificacao da RN-04.1 e concatenada NO MESMO texto que sai, e
    as assertas de lista exata deste arquivo comparariam contra uma string com
    um prefixo que nao e sobre encaminhamento nenhum. Mesmo recurso, e pela
    mesma razao, que `test_turno_teto_de_perguntas.py`.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


async def _semear_estado(session: Any, *, perguntas_feitas: int, **campos: object) -> None:
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            perguntas_feitas=perguntas_feitas,
            **campos,
        )
    )
    await session.commit()


async def _estado_relido() -> Any:
    """Rele o estado numa sessao NOVA.

    `marcar_perguntados` e `contar_perguntas` escrevem em SQL, numa transacao
    propria do turno; o objeto que a sessao do teste tem em memoria nao sabe
    disso. `test_formato_no_turno.py` rele do mesmo jeito, e pela mesma razao.
    """
    from mobia.domain.context.repositorio import ler_estado
    from mobia.infra.db import get_sessionmaker

    async with get_sessionmaker()() as outra:
        return await ler_estado(outra, CANAL, CONVERSA)


async def _handoffs(session: Any) -> list[dict]:
    resultado = await session.execute(
        text("SELECT gatilho, etiqueta FROM handoffs ORDER BY criado_em")
    )
    return [dict(linha) for linha in resultado.mappings()]


async def test_venda_de_imovel_entrega_o_texto_proprio_e_nao_a_prosa_do_modelo(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O caso da card: o proprietario nao pode ser qualificado como comprador."""
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero colocar meu apartamento a venda com voces",
    )

    # Lista exata, e nao so a negativa: `PROSA_DO_MODELO not in entregues`
    # passaria com `entregues` VAZIO, ou seja com o turno sem entregar nada. A
    # forma de lista fixa que houve entrega, que houve UMA so, e deixa o "a
    # prosa nao saiu" como consequencia dela.
    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert PROSA_DO_MODELO not in entregador.entregues

    linhas = await _handoffs(session)
    assert len(linhas) == 1
    assert linhas[0]["etiqueta"] == "venda-imovel"


async def test_suporte_de_contrato_entrega_o_outro_texto(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Fila diferente, texto diferente: quem tem duvida de contrato JA e cliente.

    A asserta contra o texto de VENDA nao e enfeite -- com um literal unico
    para as duas intencoes este teste continuaria verde, e o lead de suporte
    ouviria "Que bom que pensou na gente para vender seu imóvel!".
    """
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.SUPORTE_CONTRATO, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="tenho uma duvida sobre a clausula de reajuste do meu contrato",
    )

    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE]
    assert TEXTO_DO_ENCAMINHAMENTO_DE_VENDA not in entregador.entregues
    assert PROSA_DO_MODELO not in entregador.entregues

    linhas = await _handoffs(session)
    assert len(linhas) == 1
    assert linhas[0]["etiqueta"] == "suporte-contrato"


async def test_fora_da_janela_o_texto_nomeia_o_horario(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3: as horas vem de `Settings`, e nao de um literal.

    Por isso a asserta compara contra o valor da configuracao formatado, e nao
    contra "9" e "18" escritos aqui: o Gherkin da card diz "das 9h as 19h"
    enquanto a janela real (TEC-143) e outra, e um numero transcrito neste
    arquivo fixaria a mentira em vez do comportamento.
    """
    monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: False)
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu apartamento",
    )

    settings = get_settings()
    sufixo = SUFIXO_FORA_DA_JANELA.format(
        inicio=settings.atendimento_horario_inicio,
        fim=settings.atendimento_horario_fim,
    )
    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA + sufixo]
    assert entregador.entregues[-1].startswith(TEXTO_DO_ENCAMINHAMENTO_DE_VENDA)
    assert str(settings.atendimento_horario_inicio) in entregador.entregues[-1]
    assert str(settings.atendimento_horario_fim) in entregador.entregues[-1]


async def test_dentro_da_janela_o_texto_nao_nomeia_horario(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A contraprova do teste acima. Sem ela um sufixo INCONDICIONAL passaria.

    A janela vem aberta pela fixture autouse deste arquivo, entao o unico jeito
    de esta asserta ser verdadeira e o sufixo depender de fato da janela.
    """
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu apartamento",
    )

    settings = get_settings()
    sufixo = SUFIXO_FORA_DA_JANELA.format(
        inicio=settings.atendimento_horario_inicio,
        fim=settings.atendimento_horario_fim,
    )
    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert sufixo not in entregador.entregues[-1]


async def test_o_segundo_turno_com_a_mesma_intencao_entrega_de_novo(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """D2: a substituicao roda em TODO turno com a intencao, nao so no primeiro.

    A alternativa devolveria ao modelo a palavra no segundo turno, e com ela a
    pergunta de qualificacao que a regra proibe. O handoff continua sendo UM --
    `registrar_handoff` acumula em `gatilhos_adicionais` sem duplicar linha.
    """
    await _conversa_ja_existe(session)

    primeiro = outbound_fake()
    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        primeiro,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu apartamento",
    )

    segundo = outbound_fake()
    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        segundo,
        resumidor_fake(),
        contador_fake(),
        texto="e como funciona a avaliacao do imovel?",
    )

    assert primeiro.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert segundo.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert len(await _handoffs(session)) == 1


async def test_a_pergunta_suprimida_pelo_encaminhamento_nao_e_marcada_nem_contada(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O encaminhamento e a QUARTA trilha de supressao da guarda pos-entrega.

    A prosa do modelo perguntou `regiao` e NAO saiu -- o lead recebeu o texto
    de encaminhamento. Marcar ou contar aqui queimaria o campo e gastaria
    orcamento do lead por uma pergunta que ele nunca viu, que e o dano que
    aquela guarda existe para evitar nas outras tres trilhas.

    O estrago nao para nesta conversa de venda: a intencao e POR TURNO e o
    contador e compartilhado entre elas. O lead que fala de venda hoje e volta
    como COMPRA amanha chegaria com `regiao` marcada como ja perguntada -- a
    uniao no SQL nunca remove -- e com `perguntas_feitas` gasto; depois de
    turnos suficientes, o teto da TEC-149 dispararia "Já perguntei bastante"
    contra quem nao foi perguntado de nada.

    **`perguntas_feitas=2`, longe do teto, e a parte que faz o teste valer.**
    Com 8, `teto_da_entrega` ja seria True e a guarda excluiria o bloco pela
    razao PRE-EXISTENTE -- o teste passaria sem afirmar nada sobre o
    encaminhamento.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, perguntas_feitas=2, perguntados_sem_resposta=[])
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, perguntou=("regiao",), resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero colocar meu apartamento a venda",
    )

    # Primeiro fixa que a supressao de fato aconteceu: sem isto as duas
    # assertas de baixo passariam tambem num turno em que a prosa saiu inteira.
    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]

    estado = await _estado_relido()
    assert estado is not None
    assert estado.perguntados_sem_resposta == [], (
        "a pergunta foi suprimida, nao feita -- marca-la queima o campo para sempre"
    )
    assert estado.perguntas_feitas == 2, (
        "o contador nao pode crescer por uma pergunta que o lead nunca viu"
    )


async def test_o_encaminhamento_vence_o_teto_de_perguntas(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Quem vai para a fila de venda nao precisa ouvir "Já perguntei bastante".

    Os dois textos prometem corretor, entao a diferenca nao e de gentileza: o
    do teto fala de qualificacao, que estas duas intencoes nao recebem.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, perguntas_feitas=8)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(
            Intencao.VENDER_IMOVEL, perguntou=("urgencia",), resposta=PROSA_DO_MODELO
        ),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu apartamento",
    )

    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    assert TEXTO_DO_LIMITE_DE_PERGUNTAS not in entregador.entregues


async def test_saida_bloqueada_vence_o_encaminhamento(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    """`TEXTO_NEUTRO_DE_SAIDA` e a resposta declarada da politica de moderacao.

    Sobrepor a nossa a ela tornaria impossivel saber depois qual das duas agiu
    -- e a mesma guarda que o bloco do teto ja carrega, pela mesma razao.
    """
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_saida=True),
        texto="quero vender meu apartamento",
    )

    assert entregador.entregues == [TEXTO_NEUTRO_DE_SAIDA]
    assert TEXTO_DO_ENCAMINHAMENTO_DE_VENDA not in entregador.entregues


async def test_o_suporte_nao_recebe_a_oferta_de_corretor(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Fix da revisao final do TEC-272, Important 1: a precondicao do CA-04.1.

    O criterio de aceite diz "AO CONFIRMAR ser assistente virtual, oferece".
    Aqui a resposta do modelo foi SUBSTITUIDA por texto nosso -- o agente nao
    confirmou coisa nenhuma --, entao nao ha confirmacao a que anexar a
    oferta. `turno.py` marca `texto_substituido` em cada uma das seis
    substituicoes e o append so roda quando ela e False.

    **E esta trilha e a que mais doia:** o texto acabou de dizer "ja coloquei
    sua conversa na fila deles", e uma oferta de corretor colada logo depois
    contradiz o roteamento anunciado uma frase antes. Que o encaminhamento de
    SUPORTE nao fale em corretor (so o de venda) e decisao registrada no
    desenho da TEC-272 -- era ela que o append desfazia.

    A asserta e de lista EXATA de proposito: um `not in` passaria tambem se o
    turno tivesse parado de entregar o texto de suporte.
    """
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.SUPORTE_CONTRATO, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="vc e um robo? tenho uma duvida sobre a clausula de reajuste",
    )

    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE]
    assert TEXTO_DA_OFERTA_DE_CORRETOR not in TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE


async def test_a_saida_bloqueada_nao_recebe_a_oferta_de_corretor(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    """Mesma guarda do teste acima, na trilha em que ela e mais obvia.

    `TEXTO_NEUTRO_DE_SAIDA` diz "Tive um problema para montar a resposta
    agora." O agente nao respondeu nada -- muito menos confirmou ser
    assistente virtual --, e anexar a oferta ali ainda tinha um segundo
    defeito: o texto neutro e a resposta declarada da politica de moderacao, e
    acrescentar frase a ele tornaria impossivel saber depois qual das duas
    agiu, que e exatamente a razao do `not saida_bloqueada` das outras
    guardas.
    """
    await _conversa_ja_existe(session)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_saida=True),
        texto="vc e um robo?",
    )

    assert entregador.entregues == [TEXTO_NEUTRO_DE_SAIDA]


async def _imovel(session: Any, codigo: str = "AP-1001") -> uuid.UUID:
    """Uma linha de catalogo para a ficha ter de onde sair.

    Copiado e nao importado de proposito: os arquivos de integracao deste repo
    sao autocontidos, como `test_turno_investidor.py` e `test_citacao_no_turno.py`
    tambem registram. `operacao="VENDA"` nao e detalhe -- e o catalogo de VENDA
    que o proprietario nao pode receber de volta como se fosse comprador.
    """
    identificador = uuid.uuid4()
    session.add(
        Imovel(
            id=identificador,
            codigo=codigo,
            titulo=f"Apartamento {codigo}",
            descricao="Sala ampla com varanda.",
            tipo="APARTAMENTO",
            operacao="VENDA",
            preco_venda=51_646_430,
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
            caracteristicas=["churrasqueira"],
            fotos=[f"https://exemplo.com/{codigo}.jpg"],
            status="DISPONIVEL",
        )
    )
    await session.commit()
    return identificador


def _candidato_de(codigo: str, imovel_id: uuid.UUID) -> dict[str, Any]:
    """Um candidato de busca, no formato que o turno repassa a `_apresentar`."""
    return {
        "imovel_id": str(imovel_id),
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "bairro": "Lagoa da Conceicao",
        "preco_centavos": 51_646_430,
        "quartos": 4,
        "vagas": 2,
    }


async def test_a_venda_com_candidatos_nao_apresenta_ficha_do_catalogo(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """R6 da revisao final: `apresentando` tambem tem de excluir o encaminhamento.

    `tool_choice` e `auto` e o enum de `operacao` da ferramenta tem VENDA, entao
    nada impede o modelo de buscar no mesmo turno em que classifica
    `VENDER_IMOVEL`. Com candidatos e sem pergunta, `apresentando` era True e o
    texto do encaminhamento virava PREFIXO de legenda -- `prosa_que_cabe` o
    truncaria com reticencia, ou o devolveria VAZIO quando a ficha nao deixasse
    espaco. O proprietario recebia ate tres fichas do catalogo de venda: o
    defeito da propria card, so que mais forte -- o dono tratado como comprador
    e com o catalogo na mao.
    """
    await _conversa_ja_existe(session)
    imovel = await _imovel(session)
    classificador = classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO)
    classificador.candidatos = [_candidato_de("AP-1001", imovel)]
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador,
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero colocar meu apartamento a venda",
    )

    assert entregador.entregues == [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA]
    # A negativa explicita, porque a lista exata acima ja falharia por varias
    # razoes: o que se afirma e que NENHUMA ficha do catalogo de venda saiu.
    assert not any("AP-1001" in entregue for entregue in entregador.entregues)


async def test_o_primeiro_contato_de_venda_recebe_identificacao_e_encaminhamento(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A forma mais comum da card, e a unica sem `_conversa_ja_existe`.

    "quero vender meu imovel" como PRIMEIRA mensagem e o caso real; os outros
    testes deste arquivo semeiam uma fala anterior justamente para isolar o
    encaminhamento do prefixo da RN-04.1, e com isso ninguem afirmava o que o
    lead de fato le.

    A justaposicao que a asserta expoe -- o assistente se oferece para ajudar a
    encontrar um imovel e em seguida diz que isso nao e com ele -- e decisao de
    produto, nao defeito: esta fixada aqui como ESTA, e a R8 da revisao final
    manda registra-la na card em vez de reescrever o texto.
    """
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO),
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu imovel",
    )

    assert entregador.entregues == [
        f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{TEXTO_DO_ENCAMINHAMENTO_DE_VENDA}"
    ]


async def test_o_primeiro_contato_de_venda_com_candidatos_tambem_se_identifica(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A intersecao dos dois testes acima, e o que a R6 DESTRAVA.

    Enquanto `apresentando` era True neste turno, `identificar` era False por
    construcao (`not apresentando and ...`) e a identificacao saia como mensagem
    propria de dentro do `if apresentando:`, junto das fichas. Com a exclusao no
    lugar, o turno cai no caminho de texto e as duas coisas viram UMA mensagem
    -- que e o comportamento pretendido, e nao efeito colateral.
    """
    imovel = await _imovel(session)
    classificador = classificador_fake(Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO)
    classificador.candidatos = [_candidato_de("AP-1001", imovel)]
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador,
        entregador,
        resumidor_fake(),
        contador_fake(),
        texto="quero vender meu imovel",
    )

    assert entregador.entregues == [
        f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{TEXTO_DO_ENCAMINHAMENTO_DE_VENDA}"
    ]
    assert not any("AP-1001" in entregue for entregue in entregador.entregues)
