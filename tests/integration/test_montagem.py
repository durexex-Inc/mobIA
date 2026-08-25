import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from conftest import CANAL, CONVERSA, ContadorFake, ResumidorFake, semear

from mobia.app.config import get_settings
from mobia.domain.context.janela import Marca, literais_apos
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import (
    ContextoIrreducivel,
    _texto_da,
    _truncar_ate_caber,
    montar_contexto,
)
from mobia.domain.context.repositorio import ler_resumo
from mobia.domain.context.resumo import (  # noqa: F401  (documenta a fronteira)
    INSTRUCAO_COMPRIMIR,
    INSTRUCAO_DOBRAR,
    ResumidorPort,
    ResumoGerado,
)
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.domain.messages.status import MessageStatus
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker


def _mensagem_literal(role: MessageRole = MessageRole.LEAD) -> Message:
    """Uma `Message` minima, sem tocar o banco.

    `_texto_da` e `_truncar_ate_caber` so olham para `id`, `role`, `text_body`
    e (no caso de `_texto_da`, via `_texto_das`) `created_at` -- nao precisam
    de uma linha persistida, so de um objeto com esses campos preenchidos.
    """
    identificador = uuid.uuid4()
    return Message(
        id=identificador,
        channel=CANAL,
        provider_message_id=f"wamid.{identificador.hex[:10]}",
        conversation_key=CONVERSA,
        role=role,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt("x", aad_de(identificador, "text_body")),
        raw_payload=None,
        status=MessageStatus.PROCESSED,
        created_at=datetime.now(UTC),
    )


async def test_sem_marca_traz_a_conversa_inteira(session) -> None:
    await semear(session, 5)

    literais = await literais_apos(session, CANAL, CONVERSA, None)

    assert len(literais) == 5


async def test_marca_corta_o_que_ja_foi_resumido(session) -> None:
    criadas = await semear(session, 10)
    marca = Marca(created_at=criadas[3].created_at, message_id=criadas[3].id)

    literais = await literais_apos(session, CANAL, CONVERSA, marca)

    assert len(literais) == 6
    assert literais[0].id == criadas[4].id


async def test_empate_de_timestamp_nao_pula_nem_repete(session) -> None:
    """Duas mensagens no mesmo instante: o desempate e o id, nao a sorte.

    Com comparacao so por `created_at` uma das duas sumiria (se `>`) ou as duas
    voltariam (se `>=`) -- e o resumo perderia ou duplicaria conteudo.
    """
    instante = datetime.now(UTC) - timedelta(minutes=5)
    criadas = await semear(session, 2, base=instante)
    for linha in criadas:
        linha.created_at = instante
    await session.commit()

    primeira, segunda = sorted(criadas, key=lambda m: m.id)
    marca = Marca(created_at=instante, message_id=primeira.id)

    literais = await literais_apos(session, CANAL, CONVERSA, marca)

    assert [linha.id for linha in literais] == [segunda.id]


async def test_conversa_de_outro_lead_nao_entra(session) -> None:
    await semear(session, 3)
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            conversation_key="5511999998888",
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
        )
    )
    await session.commit()

    literais = await literais_apos(session, CANAL, CONVERSA, None)

    assert len(literais) == 3


def test_resumo_gerado_tem_custo_calculavel() -> None:
    """O log de `resumo.gerado` carrega custo; o modelo padrao tem preco."""
    gerado = ResumoGerado(
        texto="lead procura apto na zona sul",
        modelo="claude-opus-5",
        tokens_in=8000,
        tokens_out=500,
        latency_ms=1200,
    )
    custo = custo_em_dolar(gerado.modelo, gerado.tokens_in, gerado.tokens_out)

    assert custo is not None, "modelo padrao do projeto tem de estar na tabela de precos"
    assert custo > 0


def test_texto_da_renderiza_o_role_como_texto_nao_como_repr_do_enum() -> None:
    """O role tem de aparecer igual no prompt e na contagem, nos dois caminhos
    possiveis para o valor do campo.

    `role` e `Mapped[str]`, mas `MessageRole` e um `StrEnum` -- uma `Message`
    construida em memoria (como em `semear`, antes de qualquer commit) guarda
    o membro do enum; uma linha lida de volta do banco guarda a string pura.
    Se o f-string de `_texto_da` alguma vez passasse a formatar como
    `repr()`/`__str__` de um Enum comum, o prompt levaria "MessageRole.LEAD"
    em vez de "LEAD" -- o modelo leria nome de tipo Python, e a contagem de
    tokens mediria esse lixo. `StrEnum.__format__` usa o valor (comportamento
    de `str`), entao os dois caminhos tem de bater.
    """
    com_enum = _mensagem_literal(role=MessageRole.LEAD)
    com_string_pura = _mensagem_literal(role=MessageRole.LEAD)
    com_string_pura.role = "LEAD"  # simula a linha como ela volta do banco

    assert _texto_da(com_enum) == "[LEAD] x"
    assert _texto_da(com_string_pura) == "[LEAD] x"
    assert "MessageRole" not in _texto_da(com_enum)


async def test_regenera_ao_atingir_o_gatilho(session) -> None:
    await semear(session, 40)
    resumidor = ResumidorFake()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert len(resumidor.chamadas) == 1, "quarenta literais disparam uma regeneracao"
    assert len(contexto.literais) == 20, "o piso fica intacto depois de dobrar"
    assert contexto.resumo == "resumo do que veio antes"

    async with get_sessionmaker()() as outra:
        gravado = await ler_resumo(outra, CANAL, CONVERSA)
    assert gravado is not None, "a marca avanca no banco, nao so em memoria"
    assert gravado.mensagens_cobertas == 20


async def test_nao_regenera_abaixo_do_gatilho(session) -> None:
    await semear(session, 39)
    resumidor = ResumidorFake()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert resumidor.chamadas == []
    assert len(contexto.literais) == 39, "sem resumo ainda, tudo entra literal"
    assert contexto.resumo is None


async def test_o_piso_vale_em_todo_ponto_entre_regeneracoes(session) -> None:
    """A regressao que os quatro cenarios Gherkin sozinhos nao pegariam.

    Eles testam estados; este testa a transicao. O brief original semeava as 80
    mensagens de uma vez e depois apagava tudo que fosse mais novo que um corte
    crescente -- a primeira iteracao ja apagava as mensagens 42..80 para sempre,
    entao as 39 iteracoes seguintes rodavam contra um banco que nunca mais
    crescia e nao testavam nada.

    Aqui o crescimento e de verdade: comeca com 40 mensagens (o suficiente para
    disparar a primeira regeneracao) e depois acrescenta uma mensagem por vez
    ate 80, chamando `montar_contexto` a cada passo. Isso caminha pela transicao
    inteira, inclusive o turno logo apos cada regeneracao -- e e exatamente ali
    que uma marca colada no presente derrubaria o piso.
    """
    criadas = await semear(session, 40)
    resumidor = ResumidorFake()
    minimas = get_settings().contexto_literais_minimas

    for numero in range(41, 81):
        proxima = criadas[-1].created_at + timedelta(seconds=1)
        nova = (await semear(session, 1, base=proxima))[0]
        criadas.append(nova)

        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=resumidor,
            contador=ContadorFake(),
        )
        assert len(contexto.literais) >= minimas, (
            f"com {numero} mensagens o prompt caiu para {len(contexto.literais)} literais"
        )

    assert len(resumidor.chamadas) >= 2, (
        "se o gatilho parasse de disparar, os literais so cresceriam e o piso "
        "passaria por acidente, sem a regeneracao jamais acontecer de novo"
    )


async def test_estouro_avanca_a_marca_antes_de_comprimir(session, sempre_contar) -> None:
    """A ordem importa: dobrar mensagem e perda normal, re-resumir e cascata."""
    await semear(session, 25)
    resumidor = ResumidorFake()
    # 1a contagem estoura, 2a (depois de dobrar) cabe.
    contador = ContadorFake(roteiro=[13500, 9000])

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert resumidor.chamadas[0] == INSTRUCAO_DOBRAR, "primeiro dobra, so depois comprime"


async def test_truncar_reduz_pela_metade_em_vez_de_pular_direto_para_uma(sempre_contar) -> None:
    """Uma falha transitoria nao pode custar o resto da janela.

    Cortar direto para 1 literal garante o teto, mas custa caro: o proximo
    turno do lead carregaria uma unica mensagem de contexto quando a metade da
    janela ja teria coubido. Reduzir pela metade a cada passo da a mesma
    garantia jogando bem menos memoria fora -- aqui a primeira reducao (8
    literais -> 4) ja resolve, e o teste prova que o corte para por ali, sem
    continuar ate sobrar 1.

    Chamada direta em `_truncar_ate_caber`, sem `montar_contexto` em volta:
    o numero exato de literais que sobra depende so desta funcao, e testa-la
    isolada evita que o teste fique refem de `gatilho`/`minimas`/`max_iteracoes`.
    Precisa de `sempre_contar`: as literais aqui sao um unico caractere cada,
    entao sem forcar a contagem real a estimativa barata resolveria sozinha e
    o roteiro nunca seria consultado.
    """
    literais = [_mensagem_literal() for _ in range(8)]
    contador = ContadorFake(roteiro=[9000])  # cabe assim que corta pela metade

    resumo, restantes, tokens = await _truncar_ate_caber(
        contador, CANAL, "resumo qualquer", literais, None, 13500, 12000
    )

    assert len(restantes) == 4, "tem de parar assim que caber pela metade, sem ir ate 1"
    assert tokens == 9000
    assert resumo == "resumo qualquer", (
        "coube reduzindo os literais; nao precisou descartar o resumo"
    )


async def test_truncar_continua_reduzindo_ate_sobrar_uma_e_so_entao_descarta_o_resumo(
    sempre_contar,
) -> None:
    """Se a metade nao bastar, corta de novo -- e so desiste do resumo por ultimo.

    Cada passo do roteiro fica acima do teto ate a janela chegar a 1 literal
    (8 -> 4 -> 2 -> 1); so a contagem seguinte, apos descartar o resumo,
    cabe. Prova os dois degraus da cascata funcionando em sequencia, com
    reducao progressiva no lugar do salto direto para 1. Precisa de
    `sempre_contar` pelo mesmo motivo do teste anterior.
    """
    literais = [_mensagem_literal() for _ in range(8)]
    contador = ContadorFake(roteiro=[13500, 13500, 13500, 9000])

    resumo, restantes, tokens = await _truncar_ate_caber(
        contador, CANAL, "resumo qualquer", literais, None, 13500, 12000
    )

    assert len(restantes) == 1
    assert tokens == 9000
    assert resumo is None, "reduzir ate 1 nao bastou; o resumo teve de cair tambem"


async def test_laco_termina_mesmo_com_resumidor_que_nao_encolhe(session, sempre_contar) -> None:
    """Um `while` aqui gastaria dinheiro em circulo. O teto de iteracoes corta.

    Neste roteiro a contagem nunca baixa do teto -- nem reduzindo a janela
    progressivamente ate 1 literal, nem depois de descartar o resumo -- o
    pior caso possivel. Nesse ponto uma mensagem sozinha, sem memoria
    nenhuma, ainda excede o teto: nao ha contexto valido para mandar, entao o
    modulo levanta em vez de devolver algo acima do limite fisico da chamada.
    """
    await semear(session, 25)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500] * 15)

    with pytest.raises(ContextoIrreducivel):
        await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=resumidor,
            contador=contador,
        )

    assert len(resumidor.chamadas) <= get_settings().contexto_max_iteracoes + 1


async def test_truncar_descarta_o_resumo_quando_uma_mensagem_nao_basta(
    session, sempre_contar
) -> None:
    """Segundo degrau da cascata final, agora fim a fim via `montar_contexto`.

    As quatro primeiras contagens do roteiro cobrem a contagem inicial e as
    tres passadas normais do laco (dobra, comprime, comprime) ate estourar o
    teto de iteracoes com 20 literais. As quatro seguintes cobrem a reducao
    progressiva da janela ate 1 literal (20 -> 10 -> 5 -> 2 -> 1), sempre
    acima do teto. So a nona, apos descartar o resumo tambem, cabe.
    """
    await semear(session, 25)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500] * 8 + [9000])

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert contexto.tokens == 9000
    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert len(contexto.literais) == 1
    assert contexto.resumo is None, "reduzir a janela nao bastou; o resumo teve de cair tambem"
    assert contexto.degradado is True


async def test_falha_no_meio_do_laco_ainda_trunca_ate_caber(session, sempre_contar) -> None:
    """O teto nao negocia: se o provedor falhar no meio do laco, o `break` nao
    pode devolver o contexto do jeito que estava -- ainda acima do teto.

    Vinte e cinco literais e um provedor que so falha estouram a contagem
    inicial (13.500) e disparam a primeira tentativa de dobrar; ela falha, e
    sem o corte de emergencia o contexto voltaria com as 25 literais inteiras
    e 13.500 tokens -- acima do teto que este modulo promete nunca exceder.
    """
    await semear(session, 25)
    resumidor = ResumidorFake(falha=True)
    contador = ContadorFake(roteiro=[13500])

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert len(contexto.literais) < 25, "a falha nao pode deixar o contexto do jeito que estava"
    assert contexto.degradado is True


async def test_sem_resumo_previo_nunca_manda_comprimir_string_vazia(session, sempre_contar) -> None:
    """Sem resumo ainda, o laco nao pode pedir para o provedor comprimir o nada.

    Cinco literais (abaixo do piso) sem nenhum resumo previo, com a contagem
    estourando de cara: sem esta guarda, o laco chamaria
    `resumidor.resumir(INSTRUCAO_COMPRIMIR, "")` -- e o texto que o provedor
    inventasse a partir do vazio viraria memoria da conversa sem nunca ter
    sido ganho, a mesma classe de falha que a Task 4 evita ao recusar um
    resumo vazio. O caminho certo e ir direto para o corte de emergencia.
    """
    await semear(session, 5)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500, 9000])  # estoura, cabe apos reduzir a janela

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert resumidor.chamadas == [], "nunca deve pedir ao provedor para comprimir uma string vazia"
    assert contexto.resumo is None
    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert contexto.degradado is True


async def test_comprimir_persiste_o_resultado(session, sempre_contar) -> None:
    """Sem persistir, o texto comprimido morre com o request.

    Uma conversa presa acima do teto com vinte ou menos literais pagaria ate
    tres chamadas de modelo a cada turno, para sempre, e jogaria o resultado
    fora a cada vez. A marca (`gravar_resumo`) prova que o texto da segunda
    passada -- a compressao, nao a dobra -- e o que fica gravado.
    """
    criadas = await semear(session, 25)
    resumidor = ResumidorFake(roteiro=["resumo dobrado", "resumo comprimido"])
    # 1a conta estoura (dobra), 2a ainda estoura (comprime), 3a cabe.
    contador = ContadorFake(roteiro=[13500, 13500, 9000])

    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert resumidor.chamadas == [INSTRUCAO_DOBRAR, INSTRUCAO_COMPRIMIR]

    async with get_sessionmaker()() as outra:
        gravado = await ler_resumo(outra, CANAL, CONVERSA)
    assert gravado is not None
    assert gravado.texto == "resumo comprimido", (
        "a passada de compressao tem de sobrescrever a de dobrar no banco"
    )
    assert gravado.mensagens_cobertas == 5, "comprimir so encurta o texto, nao cobre mensagem nova"
    # A dobra (25 literais, piso 20) dobra as 5 mais antigas; a marca e a
    # ultima delas -- a 5a mensagem semeada (indice 4). Comprimir nao pode
    # mexer nisso: sem esta checagem, um refatorador que avancasse a marca
    # durante a compressao "orfanaria" cobertura sem nunca ter dobrado nada,
    # e o teste continuaria verde ao olhar so para o texto.
    assert gravado.watermark_created_at == criadas[4].created_at, (
        "comprimir so encurta o texto -- a marca so avanca numa dobra"
    )
    assert gravado.watermark_message_id == criadas[4].id


async def test_segunda_chamada_nao_repete_a_compressao_ja_persistida(
    session, sempre_contar
) -> None:
    """Persistido o resumo comprimido, o proximo turno nao paga o mesmo trabalho.

    A primeira chamada dobra e comprime ate caber; a segunda, com o resumo ja
    curto no banco e a mesma contagem que a primeira usou para aceitar o
    resultado, cabe de primeira e nao aciona o resumidor de novo.
    """
    await semear(session, 25)
    resumidor = ResumidorFake(roteiro=["resumo dobrado", "resumo comprimido"])

    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(roteiro=[13500, 13500, 9000]),
    )
    chamadas_apos_primeira = list(resumidor.chamadas)

    contexto2 = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(roteiro=[9000]),
    )

    assert resumidor.chamadas == chamadas_apos_primeira, (
        "resumo comprimido ja persistido cabe sozinho; a segunda chamada nao repete o trabalho"
    )
    assert contexto2.tokens <= get_settings().contexto_teto_de_tokens


async def test_falha_do_provedor_degrada_sem_derrubar(session, caplog, sempre_contar) -> None:
    """A Marina esta esperando: o turno segue, o teto e respeitado, o log grita."""
    await semear(session, 40)

    with caplog.at_level(logging.WARNING):
        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=ResumidorFake(falha=True),
            contador=ContadorFake(),
        )

    assert contexto.degradado is True
    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert "contexto.degradado" in caplog.text


async def test_estado_de_qualificacao_entra_no_contexto(session) -> None:
    await semear(session, 3)
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            faixa_preco_max=Decimal("600000.00"),
            regiao="zona sul",
        )
    )
    await session.commit()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=ContadorFake(),
    )

    assert contexto.estado is not None
    assert contexto.estado.faixa_preco_max == Decimal("600000.00")


async def test_limiar_de_contagem_cede_a_vez_para_a_contagem_real(session) -> None:
    """0.6 do teto, derivado -- nao um numero redondo fixo e desligado dele.

    `len/4` supoe 4 caracteres por token; portugues acentuado roda mais perto
    de 3.2-3.7. Vinte literais de ~1.900 caracteres cada formam uma conversa
    grande o bastante para que a estimativa barata (por volta de 9.487) cruze
    o limiar efetivo (0.6 * 12.000 = 7.200) e ceda a vez para a contagem real,
    em vez de decidir sozinha que cabe. Nao forca `sempre_contar`: o que este
    teste prova e que o limiar *default* ja cede a vez sozinho para conteudo
    deste tamanho. (Este teste e sobre acentuacao, nao sobre emoji -- ver
    `test_limiar_nao_protege_conteudo_denso_em_emoji` logo abaixo para o que
    este limiar deliberadamente nao cobre.)
    """
    texto_grande = "conteudo em portugues acentuado: nao, coracao, qualificacao, imovel. " * 27
    await semear(session, 20, texto=texto_grande)
    contador = ContadorFake()

    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=contador,
    )

    assert contador.chamadas >= 1, (
        "com mensagens deste tamanho a estimativa barata tem de ceder a vez "
        "para a contagem real, nao decidir sozinha que cabe"
    )


async def test_limiar_nao_protege_conteudo_denso_em_emoji(session) -> None:
    """Documenta o risco aceito: `len/4` nao sabe que emoji custa mais token
    por caractere.

    Poucas mensagens cheias de emoji ficam curtas em CARACTERES -- a
    estimativa so olha para `len()` -- entao a estimativa barata decide
    sozinha que cabe e a contagem real nunca e chamada, mesmo que na API de
    verdade esse texto custe bem mais tokens do que a estimativa supoe (a
    conta completa esta em `Settings.limiar_de_contagem_efetivo`). Este teste
    nao prova o numero real de tokens -- o dublê tambem mede por `len/4`, e
    nenhum teste desta suite toca a rede -- mas prova o mecanismo: conteudo
    curto em caracteres nunca aciona a contagem real, seja lá o que ele
    contenha. E o gap que o comentario do limiar documenta, nao um bug
    escondido.
    """
    emoji_denso = "\U0001f3e0" * 200  # curto em len(), denso em tokens de verdade
    await semear(session, 3, texto=emoji_denso)
    contador = ContadorFake()

    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=contador,
    )

    assert contador.chamadas == 0, (
        "conteudo curto em caracteres nunca passa pela contagem real, mesmo "
        "sendo emoji denso -- risco aceito e documentado, nao coberto por "
        "este limiar"
    )
