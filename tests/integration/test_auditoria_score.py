"""A trilha de recalculos de score: tabela, imutabilidade e o gancho no turno.

TEC-152.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from mobia.domain.agente.schemas import Extracao, FormaPagamento, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.context.repositorio import (
    Recalculo,
    contar_mensagens_do_lead,
    registrar_recalculo,
)
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt

CANAL = "whatsapp"
CONVERSA = "5511911112222"


def linha(**ajustes: object) -> LeadScoreAudit:
    """Um registro valido, com os cinco fatores somando o total."""
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "channel": CANAL,
        "conversation_key": CONVERSA,
        "total_anterior": None,
        "total_novo": 51,
        "completude": 20,
        "urgencia": 15,
        "catalogo": 0,
        "engajamento": 10,
        "capacidade": 6,
        "causas": ["PRIMEIRO_CALCULO"],
    }
    return LeadScoreAudit(**{**base, **ajustes})


async def test_a_tabela_aceita_um_registro_valido(session) -> None:
    session.add(linha())
    await session.commit()

    gravado = (await session.scalars(select(LeadScoreAudit))).one()
    assert gravado.total_novo == 51
    assert gravado.total_anterior is None
    assert gravado.causas == ["PRIMEIRO_CALCULO"]
    assert gravado.autor is None
    assert gravado.created_at is not None


async def test_o_check_recusa_um_total_que_nao_soma(session) -> None:
    """O total e denormalizado de proposito -- e por ele que se ordena --, e a
    restricao e o que impede a denormalizacao de mentir."""
    session.add(linha(total_novo=99))

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_o_check_recusa_causas_vazias(session) -> None:
    """Tupla vazia e o sinal de NAO gravar, entao uma linha sem causa nunca
    deveria ter chegado ao INSERT.

    `nullable=False` so cobre metade do que o modelo afirma ("nunca NULL e
    nunca vazio"). Uma linha que diz que o score mudou sem nomear o que se
    moveu e a mesma forma de mentira que o CHECK do total impede.
    """
    session.add(linha(causas=[]))

    with pytest.raises(IntegrityError):
        await session.commit()

    await session.rollback()


async def test_update_e_recusado_pela_trigger(session) -> None:
    """Cenario 3 da card: "quando se tenta altera-lo, a operacao e recusada"."""
    session.add(linha())
    await session.commit()

    with pytest.raises(DBAPIError, match="imutavel"):
        await session.execute(text("UPDATE lead_score_audit SET total_novo = 99"))

    # A transacao fica abortada depois da excecao do Postgres; sem isto o
    # teardown da fixture reclama em vez de fechar limpo.
    await session.rollback()


async def test_delete_continua_livre(session) -> None:
    """Imutavel e "nao se altera o que foi registrado". A RNF-18 pede retencao
    de 12 meses, ou seja, pede que apagar seja possivel."""
    session.add(linha())
    await session.commit()

    await session.execute(text("DELETE FROM lead_score_audit"))
    await session.commit()

    assert (await session.scalars(select(LeadScoreAudit))).all() == []


async def _mensagem(
    session,
    *,
    direction: MessageDirection = MessageDirection.INBOUND,
    bloqueada: bool = False,
) -> None:
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            sender_external_id=CONVERSA,
            recipient_external_id="222222222",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD if direction is MessageDirection.INBOUND else MessageRole.AGENTE,
            direction=direction,
            content_type=MessageContentType.TEXTO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            raw_payload=None,
            status=MessageStatus.PROCESSED,
            bloqueada_em=datetime.now(UTC) if bloqueada else None,
        )
    )
    await session.commit()


async def test_a_contagem_ignora_a_fala_do_agente(session) -> None:
    """Fala do agente nao e engajamento do lead, e contar as duas direcoes
    quase dobra o numero e empurra MORNO para QUENTE de graca."""
    await _mensagem(session)
    await _mensagem(session, direction=MessageDirection.OUTBOUND)

    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key=CONVERSA) == 1


async def test_a_contagem_ignora_a_fala_bloqueada(session) -> None:
    """Um turno que o resto do produto trata como nao-dito nao pode virar ponto
    aqui: `literais_apos` ja filtra `bloqueada_em IS NULL` desde a TEC-236."""
    await _mensagem(session)
    await _mensagem(session, bloqueada=True)

    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key=CONVERSA) == 1


async def test_a_contagem_de_um_lead_sem_mensagem_e_zero(session) -> None:
    assert await contar_mensagens_do_lead(session, channel=CANAL, conversation_key="ninguem") == 0


async def _qualificacao(session) -> None:
    """Os quatro obrigatorios preenchidos."""
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            intencao=Intencao.COMPRA.value,
            faixa_preco_max_centavos=50_000_000,
            regiao="vila mariana",
            urgencia=Urgencia.ATE_3_MESES.value,
        )
    )
    await session.commit()


async def test_o_primeiro_recalculo_grava_com_anterior_nulo(session) -> None:
    """Quatro obrigatorios (20), ATE_3_MESES (15), uma mensagem (10), sem forma
    de pagamento (6) = 51."""
    await _qualificacao(session)
    await _mensagem(session)

    recalculo: Recalculo | None = await registrar_recalculo(
        session, channel=CANAL, conversation_key=CONVERSA
    )
    await session.commit()

    assert recalculo is not None
    gravada = recalculo.trilha
    assert gravada is not None
    assert gravada.total_anterior is None
    assert gravada.total_novo == 51
    assert (gravada.completude, gravada.urgencia, gravada.catalogo) == (20, 15, 0)
    assert (gravada.engajamento, gravada.capacidade) == (10, 6)
    assert gravada.causas == ["PRIMEIRO_CALCULO"]


async def test_o_recalculo_que_nao_move_nada_nao_grava(session) -> None:
    await _qualificacao(session)
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    segundo = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    assert segundo is not None and segundo.trilha is None
    await session.commit()

    assert len((await session.scalars(select(LeadScoreAudit))).all()) == 1


async def test_informar_a_vista_grava_o_delta_da_capacidade(session) -> None:
    """O cenario 1 da card, no equivalente alcancavel: 51 -> 60.

    A card diz 48 -> 63, um delta de 15. A vista move `capacidade` de 6 para
    15 -- delta de 9 --, e na escala da TEC-150 nenhum dos dois numeros e
    alcancavel hoje: 63 nao existe com `imoveis_compativeis=0`, e 48 so existe
    para quem JA paga a vista. Ver a secao correspondente do desenho.
    """
    await _qualificacao(session)
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    estado = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert estado is not None
    estado.forma_pagamento = FormaPagamento.A_VISTA.value
    await session.commit()

    recalculo = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert recalculo is not None
    gravada = recalculo.trilha
    assert gravada is not None
    assert (gravada.total_anterior, gravada.total_novo) == (51, 60)
    assert gravada.causas == ["FORMA_DE_PAGAMENTO"]


async def test_sem_linha_de_qualificacao_nao_ha_o_que_auditar(session) -> None:
    """Sem linha em `LeadQualification`, `registrar_recalculo` devolve `None`
    antes mesmo de calcular -- o `SELECT ... FOR UPDATE` nao acha a linha, e o
    `if estado is None: return None` sai dali. Nao ha score zerado para
    auditar: a ausencia de sujeito nao e uma nota igual a zero."""
    await _mensagem(session)

    assert await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA) is None
    assert (await session.scalars(select(LeadScoreAudit))).all() == []


async def test_populate_existing_rele_o_estado_por_baixo_da_instancia_em_maos(session) -> None:
    """Reproduz o perigo que `.execution_options(populate_existing=True)`
    existe para evitar, e nao so o afirma.

    `infra/db.py` monta a sessionmaker com `expire_on_commit=False`, entao
    nada expira esta linha por conta propria: uma vez carregada, a sessao
    devolve a MESMA instancia Python de novo para qualquer leitura futura na
    mesma sessao, com os atributos que ela tinha quando foi carregada -- a
    menos que algo peca explicitamente para os atualizar. E isso que
    `populate_existing` pede.

    O UPDATE abaixo passa por `text()`, por baixo do ORM de proposito: e o
    unico jeito de o banco mudar sem que o objeto Python que o identity map
    guarda mude junto -- exatamente a divergencia entre "o que a sessao acha
    que a linha diz" e "o que a linha diz" que a releitura de
    `registrar_recalculo` existe para fechar.
    """
    await _qualificacao(session)
    await _mensagem(session)

    # Carrega a linha no identity map desta sessao. E esta copia que ficaria
    # obsoleta sem `populate_existing`.
    carregada = await session.get(LeadQualification, (CANAL, CONVERSA))
    assert carregada is not None
    assert carregada.forma_pagamento is None

    # Muda o banco por baixo da instancia carregada, sem passar pelo ORM.
    await session.execute(
        text(
            "UPDATE lead_qualification SET forma_pagamento = 'A_VISTA' "
            "WHERE channel = :channel AND conversation_key = :conversa"
        ),
        {"channel": CANAL, "conversa": CONVERSA},
    )
    # A instancia em maos continua mentindo -- e o estado que a releitura tem
    # de corrigir.
    assert carregada.forma_pagamento is None

    recalculo = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    assert recalculo is not None
    gravada = recalculo.trilha
    assert gravada is not None
    # 60 e capacidade 15 (a vista), e nao 51 e capacidade 6 (sem forma de
    # pagamento): sem `populate_existing`, `registrar_recalculo` calcularia
    # sobre a instancia velha do identity map, e este teste ficaria vermelho.
    assert gravada.total_novo == 60
    assert gravada.capacidade == 15


async def test_o_turno_grava_a_trilha(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """O turno passa a recalcular, e o primeiro registro do lead aparece."""
    await rodar_turno(
        session,
        classificador_fake(
            intencao=Intencao.COMPRA,
            confianca=Decimal("0.95"),
            extracao=Extracao(regiao="vila mariana", urgencia=Urgencia.ATE_3_MESES),
        ),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    registros = (await session.scalars(select(LeadScoreAudit))).all()
    assert len(registros) == 1
    assert registros[0].total_anterior is None
    assert registros[0].causas == ["PRIMEIRO_CALCULO"]
    # Tres dos quatro obrigatorios -- intencao, regiao, urgencia; falta
    # `faixa_preco` -- sao 15 de completude, mais urgencia ATE_3_MESES (15),
    # uma mensagem (10) e nenhuma forma de pagamento (6).
    assert registros[0].total_novo == 46


async def test_o_turno_que_nao_move_o_score_nao_grava_de_novo(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """O engajamento fica em 10 da primeira mensagem ate a quinta -- a faixa
    de baixo comeca em UMA mensagem, nao na segunda -- e so sobe na sexta,
    entao um segundo turno que repete a mesma extracao nao move fator
    nenhum."""

    def turno():
        return rodar_turno(
            session,
            classificador_fake(
                intencao=Intencao.COMPRA,
                confianca=Decimal("0.95"),
                extracao=Extracao(regiao="vila mariana", urgencia=Urgencia.ATE_3_MESES),
            ),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    await turno()
    antes = len((await session.scalars(select(LeadScoreAudit))).all())
    await turno()
    depois = len((await session.scalars(select(LeadScoreAudit))).all())

    assert antes == 1
    assert depois == 1


async def test_a_trilha_reconstroi_a_evolucao_em_ordem(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """Cenario 4 da card: os registros aparecem em ordem cronologica com os
    respectivos motivos."""
    extracoes = [
        Extracao(regiao="vila mariana"),
        Extracao(urgencia=Urgencia.ATE_3_MESES),
        Extracao(forma_pagamento=FormaPagamento.A_VISTA),
    ]
    for extracao in extracoes:
        await rodar_turno(
            session,
            classificador_fake(
                intencao=Intencao.COMPRA, confianca=Decimal("0.95"), extracao=extracao
            ),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    registros = (
        await session.scalars(select(LeadScoreAudit).order_by(LeadScoreAudit.created_at))
    ).all()

    assert [r.causas for r in registros][0] == ["PRIMEIRO_CALCULO"]
    assert [r.total_novo for r in registros] == sorted(r.total_novo for r in registros)
    assert registros[-1].causas == ["FORMA_DE_PAGAMENTO"]
    # A cadeia fecha: o `total_novo` de cada registro e o `total_anterior` do
    # seguinte.
    for anterior, seguinte in zip(registros, registros[1:], strict=False):
        assert seguinte.total_anterior == anterior.total_novo


async def test_um_turno_sem_campo_nenhum_ainda_grava_a_travessia_de_engajamento(
    session,
    rodar_turno,
    classificador_fake,
    outbound_fake,
    resumidor_fake,
    contador_fake,
) -> None:
    """D2 do desenho: o gancho roda em todo turno com estado, e nao so quando
    `gravar_estado` devolveu linha.

    O engajamento depende da contagem de mensagens, que sobe em todo turno --
    inclusive um em que o lead nao informou nada de novo e o classificador nao
    da nenhuma intencao aproveitavel. `campos_a_gravar` devolve dict vazio (e
    `gravar_estado` devolve `None`) quando a intencao e INDEFINIDA e a
    extracao nao trouxe nenhum campo -- e esse e o turno 6 abaixo. Se o gancho
    so disparasse quando ha campo gravado, a travessia de 5 para 6 mensagens
    (10 -> 15 pontos, `_pontos_do_engajamento`) ficaria fora da trilha.
    """

    async def turno_com_campo():
        await rodar_turno(
            session,
            classificador_fake(
                intencao=Intencao.COMPRA,
                confianca=Decimal("0.95"),
                extracao=Extracao(regiao="vila mariana", urgencia=Urgencia.ATE_3_MESES),
            ),
            outbound_fake(),
            resumidor_fake(),
            contador_fake(),
        )

    # Turnos 1 a 5: o primeiro cria a linha de qualificacao e o primeiro
    # registro da trilha; os quatro seguintes repetem a mesma extracao --
    # nada novo para gravar, e o engajamento segue em 10 (faixa de 1 a 5
    # mensagens) -- entao nenhum deles acrescenta registro.
    for _ in range(5):
        await turno_com_campo()

    antes = (await session.scalars(select(LeadScoreAudit))).all()
    assert len(antes) == 1

    # Turno 6: INDEFINIDA e extracao vazia -- `campos_a_gravar` devolve {},
    # `gravar_estado` devolve `None`, nenhum campo e escrito. A sexta mensagem
    # do lead e a unica coisa que muda: o engajamento cruza de 10 para 15.
    await rodar_turno(
        session,
        classificador_fake(
            intencao=Intencao.INDEFINIDA, confianca=Decimal("0.95"), extracao=Extracao()
        ),
        outbound_fake(),
        resumidor_fake(),
        contador_fake(),
    )

    depois = (
        await session.scalars(select(LeadScoreAudit).order_by(LeadScoreAudit.created_at))
    ).all()
    assert len(depois) == 2
    assert depois[-1].causas == ["ENGAJAMENTO"]
    assert depois[-1].total_anterior == depois[0].total_novo
    assert depois[-1].total_novo - depois[-1].total_anterior == 5


async def test_a_ordem_da_trilha_segue_a_escrita_e_nao_o_inicio_da_transacao(
    session, session_factory
) -> None:
    """`created_at` e `clock_timestamp()`, e a diferenca para `now()` e visivel.

    `now()` e `transaction_timestamp()`: congelado no PRIMEIRO statement da
    transacao, que num turno e o `ler_intencao` -- varios statements antes de
    `registrar_recalculo` tomar o lock. Um turno que COMECA antes pode gravar
    DEPOIS, e com `now()` sairia carimbado como o mais antigo dos dois: a
    trilha ficaria na ordem inversa da ordem em que o lock foi concedido, e o
    turno seguinte leria como "ultimo registro" uma linha que nao e a atual,
    encadeando `total_anterior` a partir dela.

    Aqui `antiga` abre a transacao primeiro e grava por ultimo.
    """
    await _qualificacao(session)
    await _mensagem(session)
    await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    async with session_factory() as antiga, session_factory() as recente:
        # Abre a transacao de `antiga` -- e este o instante que `now()`
        # congelaria para tudo que ela escrever depois.
        comeco_da_antiga = await antiga.scalar(text("SELECT transaction_timestamp()"))

        await recente.execute(
            text(
                "UPDATE lead_qualification SET forma_pagamento = 'A_VISTA' "
                "WHERE channel = :channel AND conversation_key = :conversa"
            ),
            {"channel": CANAL, "conversa": CONVERSA},
        )
        escrita_antes = (
            await registrar_recalculo(recente, channel=CANAL, conversation_key=CONVERSA)
        ).trilha
        await recente.commit()

        await antiga.execute(
            text(
                "UPDATE lead_qualification SET urgencia = 'SEM_PRESSA' "
                "WHERE channel = :channel AND conversation_key = :conversa"
            ),
            {"channel": CANAL, "conversa": CONVERSA},
        )
        escrita_depois = (
            await registrar_recalculo(antiga, channel=CANAL, conversation_key=CONVERSA)
        ).trilha
        await antiga.commit()

    assert escrita_antes is not None and escrita_depois is not None
    # A montagem e mesmo a que o teste diz que e: a transacao que gravou por
    # ultimo comecou antes de a outra ter gravado.
    assert comeco_da_antiga < escrita_antes.created_at
    # 60 (a vista) e depois 45 (sem pressa): a ordem de escrita.
    assert (escrita_antes.total_novo, escrita_depois.total_novo) == (60, 45)
    # O carimbo segue a escrita. Com `now()` esta comparacao se inverte.
    assert escrita_depois.created_at > escrita_antes.created_at

    # E a consequencia que importa: o proximo recalculo encadeia a partir da
    # linha realmente atual. Cinco mensagens a mais cruzam a sexta e movem so
    # o engajamento (10 -> 15).
    for _ in range(5):
        await _mensagem(session)

    async with session_factory() as seguinte:
        terceira = (
            await registrar_recalculo(seguinte, channel=CANAL, conversation_key=CONVERSA)
        ).trilha
        await seguinte.commit()

    assert terceira is not None
    # Com `now()`, o "ultimo registro" seria o de 60 -- que tem urgencia 15 --
    # e daria `total_anterior=60` com causas URGENCIA e ENGAJAMENTO.
    assert terceira.total_anterior == 45
    assert terceira.causas == ["ENGAJAMENTO"]


async def test_sem_o_for_update_dois_turnos_da_mesma_conversa_nao_se_serializam(
    session, session_factory
) -> None:
    """D7: o `SELECT ... FOR UPDATE` e o unico ponto que serializa dois turnos
    concorrentes da mesma conversa, e sem teste ele pode sumir em silencio.

    A deduplicacao do ARQ e por mensagem, nao por conversa: duas falas do
    mesmo lead chegando juntas produzem dois jobs em paralelo. Sem o lock, os
    dois leem o mesmo "ultimo registro", ambos veem mudanca e ambos gravam --
    dois registros com o mesmo `total_anterior`.

    Aqui `segurando` faz o papel do turno que ja esta dentro da secao critica.
    Com o lock, `registrar_recalculo` bloqueia no primeiro statement e o
    `wait_for` estoura; sem ele, a chamada atravessa na hora e nao ha
    `TimeoutError`.
    """
    await _qualificacao(session)
    await _mensagem(session)

    async with session_factory() as segurando, session_factory() as bloqueada:
        await segurando.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == CANAL,
                LeadQualification.conversation_key == CONVERSA,
            )
            .with_for_update()
        )
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(
                    registrar_recalculo(bloqueada, channel=CANAL, conversation_key=CONVERSA),
                    timeout=1,
                )
        finally:
            # Solta o lock antes de qualquer outra coisa: sem isto o proximo
            # teste do arquivo esperaria por ele ate o timeout do pytest.
            await segurando.rollback()
            await bloqueada.rollback()

    assert (await session.scalars(select(LeadScoreAudit))).all() == []


async def test_o_none_significa_ausencia_de_sujeito_e_nunca_ausencia_de_mudanca(
    session,
) -> None:
    """As duas respostas negativas de `registrar_recalculo` deixam de ser a
    mesma coisa, e a distincao e a que `score.py` ja faz entre ausencia de
    sujeito e nota igual a zero.

    Sem linha de qualificacao: `None`, e nao ha temperatura a resolver.
    Com linha e sem mudanca: um `Recalculo` cujo `trilha` e `None` -- porque
    a temperatura pode ter se movido num turno em que nenhum fator se moveu.
    """
    await _mensagem(session)
    assert await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA) is None

    await _qualificacao(session)
    primeiro = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert primeiro is not None and primeiro.trilha is not None

    segundo = await registrar_recalculo(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()
    assert segundo is not None
    assert segundo.trilha is None
