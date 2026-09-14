"""A trilha do investidor vista do turno inteiro. TEC-153, RN-07.1 e RN-07.2.

O que so o turno inteiro consegue afirmar, porque nada disso e sobre uma
funcao isolada: quantas chamadas ao modelo o turno paga, qual das duas
respostas chega ao lead, quem vence quando desambiguacao e virada coincidem, e
o que sobra gravado em `lead_qualification` depois de tudo.

Mais dois que sao as armadilhas desta task. O perfil da RN-07.2 depende de
DOIS campos, e eles podem chegar em turnos diferentes -- classificar so com o
que veio neste turno devolveria `None` para um lead que ja respondeu os dois.
E na virada a chamada 1 foi descartada -- e esse descarte e o assunto do
ultimo bloco. Nada que ela disse pode decidir o que o lead recebe: nem marcar
pergunta, nem substituir a prosa pelo texto do teto, nem escolher as fichas,
nem servir de referencia para a guarda de citacao. Esse ultimo e o pior: o
lead recebe o texto de fallback em lugar de uma resposta correta, que e o
falso positivo que a TEC-161 diz nao poder ter.

E o teto tem um caso proprio, porque a TEC-153 o partiu em dois: quando quem
passa do teto e o subagente, o texto que promete corretor sai de um turno em
que o bloco transacional nao registrou handoff nenhum. Prometer e nao
registrar e a falha da TEC-174, e aqui sem nem a linha para alguem agir --
`test_o_teto_ainda_vale_quando_e_o_investidor_que_pergunta_demais` e quem
guarda isso.
"""

import uuid
from decimal import Decimal
from typing import Any

from conftest import RESPOSTA_DO_INVESTIDOR_FAKE  # type: ignore[import-not-found]
from sqlalchemy import select, text

from mobia.domain.agente.investidor import (
    ExtracaoDoInvestidor,
    Horizonte,
    RetornoEsperadoTipo,
)
from mobia.domain.agente.models import Recomendacao
from mobia.domain.agente.schemas import Intencao
from mobia.domain.agente.turno import (
    SUBAGENTE_INVESTIDOR,
    TEXTO_DA_BUSCA_INCONCLUSIVA,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
)
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.models import LeadQualification
from mobia.domain.messages.models import MessageTelemetry

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque `rodar_turno` semeia a fala nessa conversa e o estado tem de casar com
# ela. `test_turno_teto_de_perguntas.py` redefine os dois localmente do mesmo
# jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"

# Abaixo de `LIMIAR_DE_DESAMBIGUACAO`, que e o que poe o turno no caminho do
# desambiguador. O mesmo valor que `BAIXA` em `test_turno.py`.
CONFIANCA_BAIXA = Decimal("0.45")


async def _semear_estado(session: Any, **campos: object) -> None:
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            **campos,
        )
    )
    await session.commit()


async def _conversa_ja_existe(session: Any) -> None:
    """Semeia uma fala anterior do lead para que `e_conversa_nova` veja a
    conversa como NAO nova (TEC-139).

    Sem isto a identificacao da RN-04.1 e concatenada NO MESMO texto que sai, e
    a asserta de que o texto entregue e o do investidor compararia contra uma
    string com prefixo. Mesmo recurso, e pela mesma razao, que
    `test_turno_teto_de_perguntas.py`.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


async def _gatilhos(session: Any) -> list[str]:
    resultado = await session.execute(text("SELECT gatilho FROM handoffs"))
    return [linha.gatilho for linha in resultado]


def _candidato_de(codigo: str, imovel_id: uuid.UUID) -> dict[str, Any]:
    """Um candidato de busca, no formato que o turno repassa a guarda de citacao
    e a `_apresentar`. Mesmos campos que `_candidato` em
    `tests/unit/test_citacao.py`.

    `imovel_id` e parametro porque quem apresenta precisa achar a linha de
    catalogo; quem so exercita a guarda de citacao pode passar qualquer id.
    """
    return {
        "imovel_id": str(imovel_id),
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "bairro": "Lagoa da Conceicao",
        "preco_centavos": 51_646_430,
        "quartos": 4,
        "vagas": 2,
        "area_util_m2": 54,
    }


async def _linha(session: Any) -> LeadQualification:
    # `expire_all` antes de reler: a gravacao aconteceu noutra sessao, e o
    # objeto que esta aqui em memoria nao sabe disso.
    session.expire_all()
    linha = await session.scalar(
        select(LeadQualification).where(
            LeadQualification.channel == CANAL,
            LeadQualification.conversation_key == CONVERSA,
        )
    )
    assert linha is not None
    return linha


async def test_a_virada_para_investimento_chama_o_subagente(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A virada: o lead nao era investidor e passou a ser NESTE turno.

    E o unico turno com duas chamadas -- a generica, cuja resposta e
    descartada, e a do investidor, que e a entregue.
    """
    await _conversa_ja_existe(session)
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.chamadas == 1
    assert classificador.investidores == 1
    # O que o lead RECEBEU e a resposta da segunda chamada. Sem esta asserta o
    # teste ficaria verde com o subagente rodando e a prosa generica saindo.
    assert RESPOSTA_DO_INVESTIDOR_FAKE in entregador.entregues
    # A ferramenta de busca chega a chamada do investidor: sem ela ele nunca
    # receberia ficha de imovel nenhuma.
    assert classificador.portas_do_investidor[0] is not None


async def test_investidor_ja_conhecido_nao_paga_segunda_chamada(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Do SEGUNDO turno em diante a chamada volta a ser uma so.

    A intencao ja esta no estado que `montar_contexto` leu, entao o prompt do
    investidor e escolhido ANTES da chamada e a generica nem acontece.

    O estado e semeado SEM `conversation_intent` de proposito, e nao por
    economia de fixture: e o retrato das duas fontes divergindo, que e o
    cenario real de um investidor que mandou um "obrigado" no meio da conversa
    -- `gravar_intencao` guarda INDEFINIDA, `campos_a_gravar` nao deixa
    INDEFINIDA sobrescrever a coluna do estado. Sem a guarda `not
    ja_e_investidor` em `virou_investidor`, o turno pede DUAS chamadas do
    investidor aqui, a primeira paga e descartada.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.INVESTIMENTO.value)
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.chamadas == 0
    assert classificador.investidores == 1
    assert RESPOSTA_DO_INVESTIDOR_FAKE in entregador.entregues


async def test_desambiguacao_vence_a_virada(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Ambiguo E investidor ao mesmo tempo: desambigua.

    Sem intencao confiavel nao ha trilha a escolher (D1), e gastar a chamada do
    investidor sobre um palpite que a confianca nao sustenta erraria a trilha
    alem de pagar por ela.
    """
    await _conversa_ja_existe(session)
    classificador = classificador_fake(Intencao.INVESTIMENTO, confianca=CONFIANCA_BAIXA)
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 1
    assert classificador.investidores == 0
    assert classificador.pergunta in entregador.entregues


async def test_o_perfil_e_gravado_a_partir_dos_campos(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Horizonte LONGO + ALUGUEL viram RENDA na coluna, gravados pelo turno."""
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.INVESTIMENTO.value)
    classificador = classificador_fake(
        Intencao.INVESTIMENTO,
        investidor=ExtracaoDoInvestidor(
            ticket_expressao="uns 800 mil",
            horizonte=Horizonte.LONGO,
            retorno_esperado_tipo=RetornoEsperadoTipo.ALUGUEL,
        ),
    )

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    linha = await _linha(session)
    assert linha.horizonte == "LONGO"
    assert linha.retorno_esperado_tipo == "ALUGUEL"
    assert linha.perfil_investidor == "RENDA"
    # `ticket_de` normaliza a fala do lead; o modelo nunca devolve centavos.
    assert linha.ticket_investimento_centavos == 80_000_000


async def test_a_virada_nao_marca_a_pergunta_da_chamada_descartada(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Na virada, `gerada.perguntou` descreve um texto que ninguem leu.

    A chamada 1 foi descartada e o lead recebeu a prosa do subagente. Marcar
    aquela pergunta queimaria PARA SEMPRE a chance de perguntar o campo -- a
    uniao no SQL nunca remove --, e contar gastaria orcamento do teto da
    RN-05.5 por uma pergunta que nao saiu. E o mesmo dano que o caminho da
    desambiguacao ja evita, pela mesma causa.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.COMPRA.value)
    classificador = classificador_fake(Intencao.INVESTIMENTO, perguntou=("regiao",))

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    assert classificador.investidores == 1, "sem a virada o teste nao afirma nada"
    linha = await _linha(session)
    assert "regiao" not in (linha.perguntados_sem_resposta or ())
    assert linha.perguntas_feitas == 0


async def test_o_perfil_sai_do_estado_mesclado_e_nao_so_deste_turno(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O horizonte veio num turno anterior e so o tipo de retorno chega agora.

    Classificar so com os campos deste turno daria `None` -- `perfil_de` exige
    os dois -- e o lead que ja respondeu os dois ficaria sem perfil para
    sempre. E o mesmo cuidado que impede `None` de apagar campo antigo: nada
    que o lead ja disse pode sumir por causa do turno seguinte.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(
        session, intencao=Intencao.INVESTIMENTO.value, horizonte=Horizonte.LONGO.value
    )
    classificador = classificador_fake(
        Intencao.INVESTIMENTO,
        investidor=ExtracaoDoInvestidor(retorno_esperado_tipo=RetornoEsperadoTipo.ALUGUEL),
    )

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    linha = await _linha(session)
    # O horizonte antigo SOBREVIVEU: este turno nao o trouxe, e `None` nao apaga.
    assert linha.horizonte == "LONGO"
    assert linha.perfil_investidor == "RENDA"


async def test_a_virada_e_rotulada_como_investidor_e_o_turno_seguinte_tambem(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O rotulo do subagente diz qual PROMPT gerou o texto, nao qual ramo rodou.

    **Dois turnos em sequencia, e nao um estado semeado**, porque a afirmacao e
    sobre os DOIS ramos: o `elif` da virada e o `else` do turno seguinte. Com
    um turno so, um deles ficaria por conta da leitura -- e um teste cujo nome
    promete dois casos e afirma um e a mesma classe de defeito que este repo
    trata comentario desatualizado.

    O turno 1 e a virada (o `elif`). Ele grava `intencao=INVESTIMENTO` em
    `lead_qualification` e em `conversation_intent`, entao o turno 2 nasce com
    `ja_e_investidor` verdadeiro e cai no `else`. Rotular o turno 2 de
    "classificador" faria a telemetria mostrar a trilha do investidor
    acontecendo uma vez por lead -- so na virada -- e ninguem conseguiria medir
    o que ela custa.
    """
    await _conversa_ja_existe(session)
    classificador = classificador_fake(Intencao.INVESTIMENTO)

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())
    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    # Uma generica (a do turno 1, descartada) e duas do investidor: a virada e
    # a chamada unica do turno seguinte. Sem isto o teste nao saberia dizer que
    # os dois rotulos vieram de ramos diferentes.
    assert classificador.chamadas == 1
    assert classificador.investidores == 2

    session.expire_all()
    rotulos = list(await session.scalars(select(MessageTelemetry.subagent)))
    assert rotulos == [SUBAGENTE_INVESTIDOR, SUBAGENTE_INVESTIDOR]


async def test_a_citacao_do_investidor_nao_e_bloqueada_pelos_candidatos_descartados(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O falso positivo que a TEC-161 diz nao poder ter.

    Na virada, `texto` e a prosa do INVESTIDOR e os candidatos da chamada 1
    foram descartados junto com ela. Comparar um contra o outro bloqueia como
    alucinacao um imovel que a busca do investidor de fato achou, e o lead
    recebe `TEXTO_DA_BUSCA_INCONCLUSIVA` em lugar da resposta certa.

    `perguntou_do_investidor` nao-vazio mantem `apresentando` False de
    proposito: o assunto aqui e a guarda de citacao sobre a prosa, e um turno
    de apresentacao exigiria semear o imovel no catalogo sem acrescentar nada
    a afirmacao.
    """
    await _conversa_ja_existe(session)
    prosa = "O AP-1004 te atende."
    classificador = classificador_fake(
        Intencao.INVESTIMENTO,
        resposta_do_investidor=prosa,
        # A chamada 1 (generica) nao achou este imovel; a do investidor achou.
        candidatos_do_investidor=[_candidato_de("AP-1004", uuid.uuid4())],
        perguntou_do_investidor=("horizonte",),
    )
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.investidores == 1, "sem a virada o teste nao afirma nada"
    assert prosa in entregador.entregues
    assert TEXTO_DA_BUSCA_INCONCLUSIVA not in entregador.entregues


async def test_o_teto_nao_substitui_a_prosa_do_investidor_por_pergunta_descartada(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A pergunta que estouraria o teto estava na chamada DESCARTADA.

    O lead nunca a recebeu: quem saiu foi a prosa do subagente, que aqui nao
    pergunta nada. Substituir por `TEXTO_DO_LIMITE_DE_PERGUNTAS` calaria uma
    resposta que nao gasta orcamento nenhum.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.COMPRA.value, perguntas_feitas=8)
    classificador = classificador_fake(
        Intencao.INVESTIMENTO,
        perguntou=("urgencia",),
        perguntou_do_investidor=(),
    )
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.investidores == 1, "sem a virada o teste nao afirma nada"
    assert RESPOSTA_DO_INVESTIDOR_FAKE in entregador.entregues
    assert TEXTO_DO_LIMITE_DE_PERGUNTAS not in entregador.entregues


async def test_o_teto_ainda_vale_quando_e_o_investidor_que_pergunta_demais(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """O outro sentido da mesma troca, e o que impede a correcao de virar buraco.

    Ler a resposta ENTREGUE nao e so deixar de suprimir: quando quem passa do
    teto e o subagente -- e a chamada 1 nao perguntou nada --, a RN-05.5
    continua valendo e a prosa dele e que tem de ser substituida.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, intencao=Intencao.COMPRA.value, perguntas_feitas=8)
    classificador = classificador_fake(
        Intencao.INVESTIMENTO,
        perguntou=(),
        perguntou_do_investidor=("urgencia",),
    )
    entregador = outbound_fake()

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.investidores == 1, "sem a virada o teste nao afirma nada"
    assert TEXTO_DO_LIMITE_DE_PERGUNTAS in entregador.entregues
    assert RESPOSTA_DO_INVESTIDOR_FAKE not in entregador.entregues
    # **O texto promete um corretor, entao tem de existir um handoff.** Este e
    # o unico estado em que os dois tetos divergem para o lado que machuca: a
    # chamada 1 nao perguntou nada, entao o bloco transacional nao registrou
    # nada, e sem o registro do bloco de substituicao o lead sairia com a
    # promessa e ninguem com a tarefa. E a falha da TEC-174 outra vez, so que
    # sem nem a linha para alguem agir.
    assert "LIMITE_DE_PERGUNTAS" in await _gatilhos(session)


async def _imovel(session: Any, codigo: str) -> uuid.UUID:
    """Uma linha de catalogo para a ficha ter de onde sair.

    Copiado de `test_citacao_no_turno.py`: os arquivos de integracao deste repo
    sao autocontidos de proposito.
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
            caracteristicas=["churrasqueira", "mobiliado"],
            fotos=[f"https://exemplo.com/{codigo}.jpg"],
            status="DISPONIVEL",
        )
    )
    await session.commit()
    return identificador


async def test_a_virada_apresenta_as_fichas_da_busca_do_investidor(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """As fichas entregues saem da busca do INVESTIDOR, nao da descartada.

    `apresentando`, os `scores` e o `candidatos=` de `_apresentar` liam a
    chamada 1 ate a correcao. Um turno de virada entregaria fichas de uma busca
    ao lado da prosa de outra -- e o lead nao tem como saber que as duas nao
    se conversam.

    A linha em `recomendacoes` e a evidencia mais direta: ela guarda o
    `imovel_id` do que foi de fato apresentado.
    """
    await _conversa_ja_existe(session)
    do_generico = await _imovel(session, "AP-1001")
    do_investidor = await _imovel(session, "AP-1004")
    classificador = classificador_fake(Intencao.INVESTIMENTO)
    classificador.candidatos = [_candidato_de("AP-1001", do_generico)]
    classificador.candidatos_do_investidor = [_candidato_de("AP-1004", do_investidor)]

    await rodar_turno(session, classificador, outbound_fake(), resumidor_fake(), contador_fake())

    assert classificador.investidores == 1, "sem a virada o teste nao afirma nada"
    session.expire_all()
    apresentados = list(await session.scalars(select(Recomendacao.imovel_id)))
    assert apresentados == [do_investidor]
