"""A dobra forcada: a conversa nova ve o resumo, nunca a transcricao. TEC-130, D4.

**A fronteira e a marca do resumo**, e nao uma coluna nova nem um filtro por
`encerrada_em`: dobrando tudo o que ficou para tras, a marca passa a cobrir a
conversa anterior inteira e `literais_apos` devolve so o que e novo.

**O gatilho sao os proprios literais**, e nao um predicado sobre a mensagem
que carrega o turno (`_reabriu_depois_do_silencio`, em `context/montagem.py`).
Por isso nenhum teste deste arquivo liga uma flag: eles semeiam o tempo, que
e a unica entrada da decisao.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.context.montagem import montar_contexto
from mobia.domain.context.resumo import ResumoGerado
from mobia.domain.conversa.regras import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
from mobia.domain.messages.enums import (
    MessageContentType,
    MessageDirection,
    MessageRole,
)
from mobia.domain.messages.models import Message
from mobia.infra.db import get_sessionmaker


class _ResumidorFalso:
    """Devolve um texto fixo e registra o que lhe pediram para dobrar."""

    def __init__(self) -> None:
        self.conteudos: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.conteudos.append(conteudo)
        return ResumoGerado(
            texto="Lead procurava apartamento de dois quartos na zona sul.",
            modelo="falso",
            tokens_in=10,
            tokens_out=10,
            latency_ms=1,
        )


class _ResumidorQuebrado:
    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        raise RuntimeError("provedor fora do ar")


class _ContadorFalso:
    async def contar(self, texto: str) -> int:
        return 10


async def _semear(
    session: AsyncSession, chave: str, quantas: int, *, base: datetime
) -> list[uuid.UUID]:
    """Mensagens da mesma conversa, uma por minuto a partir de `base`.

    Devolve os ids na ordem em que foram semeados, alternando lead e agente.

    `channel`, `conversation_key`, `role`, `direction` e `content_type` sao
    NOT NULL. `text_body` fica nulo: `_texto_das` (em `montagem.py`) lida com
    isso, e o que estes testes afirmam e sobre QUANTAS mensagens sobram, nao
    sobre o que elas diziam.

    **`base` e a entrada que importa**: o gatilho da dobra forcada e o corte
    de `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` caindo no meio dos literais, e e
    so posicionando as mensagens dos dois lados desse corte que se liga ou
    desliga o mecanismo.
    """
    ids: list[uuid.UUID] = []
    for n in range(quantas):
        do_lead = n % 2 == 0
        identificador = uuid.uuid4()
        ids.append(identificador)
        session.add(
            Message(
                id=identificador,
                channel="whatsapp",
                conversation_key=chave,
                role=MessageRole.LEAD if do_lead else MessageRole.AGENTE,
                direction=(MessageDirection.INBOUND if do_lead else MessageDirection.OUTBOUND),
                content_type=MessageContentType.TEXTO,
                created_at=base + timedelta(minutes=n),
            )
        )
    await session.commit()
    return ids


def _ha_muito_tempo() -> datetime:
    """O comeco de uma conversa que morreu bem antes da janela de silencio."""
    return datetime.now(UTC) - timedelta(days=2 * DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA)


def _agora_mesmo() -> datetime:
    """O comeco da conversa nova. Minutos, nao dias: tem de ficar deste lado
    do corte mesmo com a suite demorando para chegar aqui."""
    return datetime.now(UTC) - timedelta(minutes=5)


@pytest.mark.usefixtures("banco_limpo")
async def test_a_dobra_forcada_deixa_so_a_fala_do_turno(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """**O criterio da card ao pe da letra**: por meio do resumo, nao pela
    transcricao inteira -- com uma excecao deliberada, a mais recente.

    Cinco mensagens velhas ficam MUITO abaixo do gatilho de regeneracao (40)
    e do piso de literais (20) -- sem a dobra forcada, as cinco iriam
    inteiras para o prompt da conversa nova. Com a dobra forcada, as cinco
    viram resumo e so a fala deste turno fica literal: e o piso de
    `minimas=1` que `_dobrar` aplica quando `dobrar_tudo=True` (fix da
    TEC-130, rodada de revisao -- a versao anterior deste teste afirmava
    `literais == []`, que so era verdade por causa de um bug que apagava a
    fala do proprio turno junto com a conversa velha).
    """
    await _semear(session, "lead-reabre", 5, base=_ha_muito_tempo())
    (da_volta,) = await _semear(session, "lead-reabre", 1, base=_agora_mesmo())
    resumidor = _ResumidorFalso()

    with caplog.at_level(logging.WARNING):
        montado = await montar_contexto(
            get_sessionmaker(),
            channel="whatsapp",
            conversation_key="lead-reabre",
            resumidor=resumidor,
            contador=_ContadorFalso(),
        )

    assert [m.id for m in montado.literais] == [da_volta]
    assert montado.resumo is not None
    assert len(resumidor.conteudos) == 1
    # Negativa que da sentido a afirmacao positiva no teste da degradacao: o
    # alarme so aparece quando a dobra forcada de fato falha, nunca no
    # caminho feliz.
    assert "contexto.dobra_forcada_falhou" not in caplog.text


@pytest.mark.usefixtures("banco_limpo")
async def test_a_rajada_de_volta_tambem_dobra(session: AsyncSession) -> None:
    """**O defeito que derrubou o gatilho anterior.**

    O lead volta depois de dois meses e manda DUAS mensagens no mesmo
    envelope. A ingestao commita as duas antes de qualquer turno rodar: a
    primeira fecha como `agrupado` sem rodar turno e quem carrega o turno e a
    segunda. O gatilho anterior perguntava `e_conversa_nova(message)`, que
    encontra a irma de segundos atras e devolve False -- nenhuma dobra, e a
    transcricao velha inteira no prompt de uma conversa que a RN-02.3 diz ser
    nova. O gatilho por literais enxerga as duas pontas da mesma lista e nao
    tem como ser enganado assim.

    As duas falas novas nao ficam as duas literais, e isso e o custo declarado
    da D4: com `minimas=1` so a mais recente sobra, a outra entra no resumo
    junto com a conversa velha. Perda de fidelidade, nao de dado.
    """
    velhas = await _semear(session, "lead-rajada", 5, base=_ha_muito_tempo())
    rajada = await _semear(session, "lead-rajada", 2, base=_agora_mesmo())
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-rajada",
        resumidor=resumidor,
        contador=_ContadorFalso(),
    )

    assert len(resumidor.conteudos) == 1
    assert [m.id for m in montado.literais] == [rajada[-1]]
    assert montado.resumo is not None
    # Nenhuma das cinco velhas sobrou literal -- e a promessa da card, e o
    # que o gatilho antigo nao entregava neste cenario.
    assert set(velhas).isdisjoint({m.id for m in montado.literais})


@pytest.mark.usefixtures("banco_limpo")
async def test_a_conversa_que_nao_reabriu_respeita_o_piso_normal(session: AsyncSession) -> None:
    """**A contraprova, e a nao-regressao do caminho que NAO e desta card.**

    Quarenta e um literais, todos deste lado do corte de silencio: a dobra
    forcada nao tem por que ligar, e o gatilho de acumulo liga sozinho. O que
    se afirma e que o piso NORMAL (`contexto_literais_minimas`, 20) foi
    respeitado -- e nao o piso de 1 da reabertura.

    **A versao anterior deste teste semeava cinco literais e afirmava que os
    cinco sobreviviam.** Com o gatilho em 40 a dobra nem era tentada, entao
    ele passava tambem numa implementacao que ignorasse o piso por completo:
    provava que nada acontece, nao que o piso vale.
    """
    settings = get_settings()
    quantas = settings.contexto_gatilho_de_regeneracao + 1
    # Uma por minuto, terminando ha um minuto: todas deste lado do corte, e
    # nenhuma no futuro.
    await _semear(
        session,
        "lead-normal",
        quantas,
        base=datetime.now(UTC) - timedelta(minutes=quantas + 1),
    )
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-normal",
        resumidor=resumidor,
        contador=_ContadorFalso(),
    )

    assert len(resumidor.conteudos) == 1
    assert len(montado.literais) == settings.contexto_literais_minimas


@pytest.mark.usefixtures("banco_limpo")
async def test_a_conversa_so_velha_nao_dobra(session: AsyncSession) -> None:
    """Sem literal do lado de ca do corte nao ha conversa nova a separar.

    E o mesmo ramo que poupa o lead novo: la nao ha literal VELHO, aqui nao ha
    literal NOVO, e nos dois casos a dobra forcada nao tem o que fazer. Sem
    esta afirmacao, uma implementacao que dobrasse a partir de um unico
    literal velho passaria -- e faria todo turno de uma conversa dormente
    pagar um resumo antes mesmo de o lead voltar.
    """
    ids = await _semear(session, "lead-dormente", 5, base=_ha_muito_tempo())
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-dormente",
        resumidor=resumidor,
        contador=_ContadorFalso(),
    )

    assert [m.id for m in montado.literais] == ids
    assert resumidor.conteudos == []
    assert montado.resumo is None


@pytest.mark.usefixtures("banco_limpo")
async def test_o_lead_novo_nao_paga_resumo_do_primeiro_oi(session: AsyncSession) -> None:
    """Quem nunca falou nao tem conversa anterior para dobrar.

    O gatilho anterior (`e_conversa_nova`) devolvia True tambem quando nao
    havia mensagem nenhuma antes, e so o piso de `minimas=1` impedia o "oi"
    de virar resumo. O gatilho por literais nao alcanca este caso de saida:
    sem literal mais velho que o corte, nao ha dobra -- e nem a chamada paga
    ao resumidor acontece.
    """
    ids = await _semear(session, "lead-novinho", 1, base=_agora_mesmo())
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-novinho",
        resumidor=resumidor,
        contador=_ContadorFalso(),
    )

    assert [m.id for m in montado.literais] == ids
    assert resumidor.conteudos == []
    assert montado.resumo is None


@pytest.mark.usefixtures("banco_limpo")
async def test_resumo_falho_degrada_e_nao_mata_o_turno(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """**A degradacao declarada da D4.**

    Perder resumo E literais deixaria o agente cego diante de um lead que ele
    ja atendeu. Ver demais e menos ruim que nao ver nada -- entao os literais
    voltam, e o warning denuncia.

    `len(montado.literais) == 6` sozinho nao prova degradacao nenhuma: uma
    implementacao que decide dobrar e nunca repassa `dobrar_tudo` para
    `_dobrar` produz o MESMO numero, porque `dividir(6, 20)` ja devolve tudo
    como "a manter" e o early return de `_dobrar` nem chega a chamar
    `resumidor.resumir` -- o `_ResumidorQuebrado` nunca levanta. As duas
    checagens de log abaixo sao o que de fato fixa que a degradacao
    aconteceu.
    """
    await _semear(session, "lead-quebrado", 5, base=_ha_muito_tempo())
    await _semear(session, "lead-quebrado", 1, base=_agora_mesmo())

    with caplog.at_level(logging.WARNING):
        montado = await montar_contexto(
            get_sessionmaker(),
            channel="whatsapp",
            conversation_key="lead-quebrado",
            resumidor=_ResumidorQuebrado(),
            contador=_ContadorFalso(),
        )

    assert len(montado.literais) == 6
    assert montado.degradado is True
    assert "contexto.dobra_forcada_falhou" in caplog.text


async def test_o_turno_de_uma_conversa_velha_nao_leva_a_transcricao_dela(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    contador_fake,
    rodar_turno,
) -> None:
    """**O cenario Gherkin da card, ponta a ponta.**

    "Dada uma conversa encerrada por inatividade de um lead que buscava
    apartamento na zona sul, quando esse lead envia uma nova mensagem, entao
    uma nova conversa e criada para o mesmo lead e o resumo da conversa
    anterior esta disponivel para o agente."

    Cinco mensagens de dois meses atras ficam MUITO abaixo do gatilho de
    regeneracao (40) e do piso de literais (20): sem a dobra forcada elas
    iriam inteiras para o prompt deste turno.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE  # type: ignore[import-not-found]

    from mobia.domain.context.janela import literais_apos, marca_de
    from mobia.domain.context.repositorio import ler_resumo

    ids_semeados = await _semear(session, CONVERSA_AGENTE, 5, base=_ha_muito_tempo())
    resumidor = _ResumidorFalso()

    resultado = await rodar_turno(
        session, classificador_fake(), outbound_fake(), resumidor, contador_fake()
    )

    assert resultado == "respondido"
    # A dobra rodou, e uma vez so.
    assert len(resumidor.conteudos) == 1

    async with get_sessionmaker()() as leitura:
        resumo = await ler_resumo(leitura, CANAL_AGENTE, CONVERSA_AGENTE)
        assert resumo is not None
        sobraram = await literais_apos(leitura, CANAL_AGENTE, CONVERSA_AGENTE, marca_de(resumo))
        # `rodar_turno` nao devolve a linha que semeou -- so o resultado do
        # turno --, entao a entrada e identificada pela mais recente das
        # INBOUND do par: as cinco semeadas ficam dois meses no passado, e so
        # esta e de agora.
        entrada = (
            await leitura.execute(
                select(Message)
                .where(
                    Message.channel == CANAL_AGENTE,
                    Message.conversation_key == CONVERSA_AGENTE,
                    Message.direction == MessageDirection.INBOUND,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one()

    # **O criterio da card**, ao pe da letra: nenhuma das cinco falas velhas
    # esta atras da marca -- `literais_apos` so devolve o que esta DEPOIS
    # dela, entao `isdisjoint` contra os ids semeados e o que de fato prova
    # isso (um `sobraram` vazio tambem passaria numa checagem so de
    # continencia, sem provar nada sobre o resumo ter rodado direito).
    ids_sobrantes = {m.id for m in sobraram}
    assert ids_sobrantes.isdisjoint(ids_semeados)
    # E a fala DESTE turno sobrevive como literal -- e a fala a que o
    # modelo respondeu; se ela tivesse ido para o resumo junto com a
    # conversa velha, o prompt chegaria sem a pergunta do lead.
    assert entrada.id in ids_sobrantes


async def test_a_rajada_de_volta_dobra_no_turno_de_verdade(
    session: AsyncSession,
    classificador_fake,
    outbound_fake,
    contador_fake,
    rodar_turno,
    semear_entrada,
) -> None:
    """**O teste que teria pego o defeito, no caminho de producao.**

    A irma da rajada e semeada ANTES do turno, exatamente como a ingestao a
    commita: as duas linhas existem quando o worker roda, e quem roda o turno
    e a mais nova. Com o gatilho anterior -- `e_conversa_nova(message)` --
    esta mensagem encontrava a irma de segundos atras, devolvia False e a
    dobra nao acontecia, deixando a transcricao de dois meses atras no prompt
    da conversa nova.

    A irma nao precisa estar marcada como `agrupado` para o teste valer: o
    que decide a dobra e `literais_apos`, que devolve toda linha nao
    bloqueada pela moderacao, e o agrupamento so muda quem roda o turno.
    """
    from conftest import CANAL_AGENTE, CONVERSA_AGENTE  # type: ignore[import-not-found]

    from mobia.domain.context.janela import literais_apos, marca_de
    from mobia.domain.context.repositorio import ler_resumo

    ids_semeados = await _semear(session, CONVERSA_AGENTE, 5, base=_ha_muito_tempo())
    irma_da_rajada = await semear_entrada(session, texto="oi")
    resumidor = _ResumidorFalso()

    resultado = await rodar_turno(
        session, classificador_fake(), outbound_fake(), resumidor, contador_fake()
    )

    assert resultado == "respondido"
    assert len(resumidor.conteudos) == 1

    async with get_sessionmaker()() as leitura:
        resumo = await ler_resumo(leitura, CANAL_AGENTE, CONVERSA_AGENTE)
        assert resumo is not None
        sobraram = await literais_apos(leitura, CANAL_AGENTE, CONVERSA_AGENTE, marca_de(resumo))

    ids_sobrantes = {m.id for m in sobraram}
    assert ids_sobrantes.isdisjoint(ids_semeados)
    # A irma da rajada entra no resumo junto com a conversa velha, e nao fica
    # literal: e o custo declarado da D4, com o piso de 1 preservando so a
    # fala que carregou o turno.
    assert irma_da_rajada.id not in ids_sobrantes
