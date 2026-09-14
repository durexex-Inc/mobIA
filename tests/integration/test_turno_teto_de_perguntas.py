"""O teto de 8 perguntas visto do turno inteiro. TEC-149, RN-05.5.

Cenarios 1, 3 e 4 do Gherkin da card. A garantia de CONTAGEM do cenario 2 --
desambiguacao nao soma ao contador -- vive em `tests/unit/`, porque la ela e
estrutural e nao precisa de turno em volta.

Mais dois testes de precedencia, que so o turno inteiro consegue exercitar: o
texto do teto nao pode pisar na pergunta do desambiguador nem no
`TEXTO_NEUTRO_DE_SAIDA` da moderacao de saida. Sao as duas guardas que a
substituicao em `turno.py` carrega alem de `teto_atingido`.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.agente.turno import TEXTO_DO_LIMITE_DE_PERGUNTAS
from mobia.domain.context.models import LeadQualification
from mobia.domain.moderacao.port import TEXTO_NEUTRO_DE_SAIDA

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque `rodar_turno` semeia a fala nessa conversa e o estado tem de casar com
# ela. `test_temperatura_no_turno.py` redefine os dois localmente do mesmo
# jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"

# Abaixo de `LIMIAR_DE_DESAMBIGUACAO`, que e o que poe o turno no caminho do
# desambiguador. O mesmo valor que `BAIXA` em `test_turno.py`.
CONFIANCA_BAIXA = Decimal("0.45")


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


async def _conversa_ja_existe(session: Any) -> None:
    """Semeia uma fala anterior do lead para que `e_conversa_nova` veja a
    conversa como NAO nova (TEC-139).

    Sem isto a identificacao da RN-04.1 e concatenada NO MESMO texto que sai,
    e toda asserta deste arquivo compara contra uma string que carrega um
    prefixo que nao e sobre o teto. As positivas simplesmente reprovam; as
    negativas -- `TEXTO_DO_LIMITE_DE_PERGUNTAS not in entregues` e `prosa not
    in entregues` -- e que sao o perigo, porque o prefixo as deixaria VERDES
    com o teto quebrado. Mesmo recurso, e pela mesma razao, que
    `test_apresentacao_no_turno.py`.
    """
    from conftest import _entrada_do_lead  # type: ignore[import-not-found]

    await _entrada_do_lead(session, texto="ja tinha falado com o assistente antes")


async def _gatilhos(session: Any) -> list[str]:
    resultado = await session.execute(text("SELECT gatilho FROM handoffs"))
    return [linha.gatilho for linha in resultado]


async def _contador(session: Any) -> int:
    # `expire_all` antes de reler: o incremento aconteceu em SQL, e o objeto
    # que esta sessao tem em memoria nao sabe disso.
    session.expire_all()
    linha = await session.scalar(
        select(LeadQualification).where(
            LeadQualification.channel == CANAL,
            LeadQualification.conversation_key == CONVERSA,
        )
    )
    assert linha is not None
    return linha.perguntas_feitas


async def test_atingido_o_teto_o_lead_recebe_o_corretor_e_nasce_handoff(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Cenario 1: oito perguntas gastas, urgencia ainda vazia."""
    await _conversa_ja_existe(session)
    await _semear_estado(session, perguntas_feitas=8)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, perguntou=("urgencia",)),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )

    assert TEXTO_DO_LIMITE_DE_PERGUNTAS in entregador.entregues
    assert "LIMITE_DE_PERGUNTAS" in await _gatilhos(session)
    # A pergunta foi SUPRIMIDA, nao feita: o contador nao pode ter crescido,
    # senao o proximo turno nasce acima do teto por uma pergunta que o lead
    # nunca viu.
    assert await _contador(session) == 8


async def test_a_prosa_do_modelo_nao_vaza_no_turno_do_teto(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A outra metade do cenario 1, num teste proprio porque e outra coisa:
    nao basta o texto do teto SAIR, a prosa do modelo tem de NAO sair -- ela
    carrega a pergunta que o teto proibe."""
    await _conversa_ja_existe(session)
    await _semear_estado(session, perguntas_feitas=8)
    entregador = outbound_fake()
    prosa = "E qual a sua urgencia para decidir?"

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, perguntou=("urgencia",), resposta=prosa),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )

    # Lista exata, e nao so a negativa: `prosa not in entregues` passaria com
    # `entregues` VAZIO, ou seja com o turno sem entregar nada. A forma de
    # lista fixa que houve entrega, que houve UMA so, e deixa o "a prosa nao
    # saiu" como consequencia dela.
    assert entregador.entregues == [TEXTO_DO_LIMITE_DE_PERGUNTAS]
    assert prosa not in entregador.entregues


async def test_turno_de_desambiguacao_no_teto_entrega_a_pergunta_do_desambiguador(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """A RN-05.5 limita pergunta de QUALIFICACAO, e a do desambiguador nao e uma.

    O que sai neste caminho e a pergunta do desambiguador; `gerada.perguntou`
    fala da chamada 1, que foi DESCARTADA. Sem a guarda `not desambiguando` na
    substituicao, um lead que gastou as oito nunca mais poderia ser
    desambiguado: toda mensagem vaga receberia o texto do corretor em lugar da
    pergunta que teria resolvido a intencao.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, perguntas_feitas=8)
    entregador = outbound_fake()
    pergunta = "Voce procura para comprar ou para alugar?"
    classificador = classificador_fake(
        Intencao.COMPRA,
        confianca=CONFIANCA_BAIXA,
        perguntou=("urgencia",),
        pergunta=pergunta,
    )

    await rodar_turno(session, classificador, entregador, resumidor_fake(), contador_fake())

    assert classificador.desambiguacoes == 1, "o turno de fato desambiguou"
    # A precondicao, fixada: o teto FOI atingido neste turno -- o handoff e a
    # prova, porque ele nasce no caminho de desambiguacao tambem (a
    # assimetria aceita). Sem esta linha, o dia em que `teto_atingido`
    # parasse de ser True para 8 + `urgencia` deixaria a negativa abaixo
    # verde pelo motivo errado, e o teste pararia de guardar a guarda que da
    # nome a ele.
    assert "LIMITE_DE_PERGUNTAS" in await _gatilhos(session)
    assert pergunta in entregador.entregues
    assert TEXTO_DO_LIMITE_DE_PERGUNTAS not in entregador.entregues
    # O contador nao anda, e isso ja valia antes desta card: a guarda
    # pos-entrega exclui `desambiguando` desde a TEC-257.
    assert await _contador(session) == 8


async def test_saida_bloqueada_no_teto_entrega_o_neutro_da_moderacao(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
    moderador_fake,
) -> None:
    """`TEXTO_NEUTRO_DE_SAIDA` e a resposta declarada da moderacao de saida.

    Sobrepor o texto do teto a ele tornaria impossivel saber depois qual das
    duas politicas agiu. O teto nao se perde: nada foi contado neste turno, e
    ele dispara normalmente no proximo turno sem bloqueio.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, perguntas_feitas=8)
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, perguntou=("urgencia",)),
        entregador,
        resumidor_fake(),
        contador_fake(),
        moderador_fake(bloqueia_saida=True),
    )

    assert TEXTO_NEUTRO_DE_SAIDA in entregador.entregues
    assert TEXTO_DO_LIMITE_DE_PERGUNTAS not in entregador.entregues
    # O handoff nasce mesmo assim, e e o comportamento aceito: ele e registrado
    # no bloco transacional, que roda antes de a moderacao de saida ter
    # veredito, entao `saida_bloqueada` nem existe naquele ponto.
    assert "LIMITE_DE_PERGUNTAS" in await _gatilhos(session)
    assert await _contador(session) == 8


async def test_lead_qualificado_antes_do_teto_segue_o_fluxo_normal(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Cenario 3: quatro perguntas feitas e os quatro obrigatorios preenchidos."""
    await _conversa_ja_existe(session)
    await _semear_estado(
        session,
        perguntas_feitas=4,
        intencao=Intencao.COMPRA.value,
        faixa_preco_max_centavos=50_000_000,
        regiao="centro",
        urgencia=Urgencia.ATE_3_MESES.value,
    )
    entregador = outbound_fake()

    await rodar_turno(
        session,
        classificador_fake(Intencao.COMPRA, perguntou=("vagas",)),
        entregador,
        resumidor_fake(),
        contador_fake(),
    )

    assert TEXTO_DO_LIMITE_DE_PERGUNTAS not in entregador.entregues
    assert "LIMITE_DE_PERGUNTAS" not in await _gatilhos(session)
    # Contou: o turno nao extraiu campo nenhum, e a pergunta contou mesmo
    # assim. E o que separa `contar_perguntas` de `marcar_perguntados` (D2).
    assert await _contador(session) == 5


async def test_o_contador_sobrevive_ao_turno(
    session, rodar_turno, classificador_fake, outbound_fake, resumidor_fake, contador_fake
) -> None:
    """Cenario 4: o contador continua de onde estava.

    O Gherkin fala em "worker reiniciado". O que um teste pode observar disso
    e que o numero veio do BANCO e nao da memoria do processo: dois turnos
    independentes, e o segundo enxerga o que o primeiro somou.
    """
    await _conversa_ja_existe(session)
    await _semear_estado(session, perguntas_feitas=6)

    for campo in ("regiao", "vagas"):
        await rodar_turno(
            session,
            classificador_fake(Intencao.COMPRA, perguntou=(campo,)),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    # 6 + 1 + 1. O segundo turno ainda passa: sete gastas mais uma sao oito, e
    # a regra diz "nao mais de 8".
    assert await _contador(session) == 8
