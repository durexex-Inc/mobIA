"""O teto de 8 perguntas visto do turno inteiro. TEC-149, RN-05.5.

Cenarios 1, 3 e 4 do Gherkin da card. O cenario 2 -- desambiguacao nao conta
-- vive em `tests/unit/`, porque la a garantia e estrutural e nao precisa de
turno em volta.
"""

from typing import Any

from sqlalchemy import select, text

from mobia.domain.agente.schemas import Intencao, Urgencia
from mobia.domain.agente.turno import TEXTO_DO_LIMITE_DE_PERGUNTAS
from mobia.domain.context.models import LeadQualification

# Os mesmos valores que `CANAL_AGENTE`/`CONVERSA_AGENTE` em `tests/conftest.py`,
# porque `rodar_turno` semeia a fala nessa conversa e o estado tem de casar com
# ela. `test_temperatura_no_turno.py` redefine os dois localmente do mesmo
# jeito; e o padrao da casa para constante de fixture.
CANAL = "whatsapp"
CONVERSA = "5511911112222"


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

    assert prosa not in entregador.entregues


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
