import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import anthropic
import httpx2
import pytest
from conftest import CANAL, CONVERSA, ContadorFake, ResumidorFake, semear

from mobia.app.config import get_settings
from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE
from mobia.domain.context.janela import Marca, literais_apos
from mobia.domain.context.models import ConversationSummary, LeadQualification, aad_do_resumo
from mobia.domain.context.montagem import (
    SISTEMA,
    ContextoIrreducivel,
    ContextoMontado,
    _estimar,
    _estimar_pessimista,
    _texto_da,
    _texto_das,
    _texto_do_estado,
    _truncar_ate_caber,
    montar_contexto,
    montar_prompt,
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
from mobia.infra.anthropic import TETO_DO_RESUMO
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker


def _mensagem_literal(
    role: MessageRole = MessageRole.LEAD,
    content_type: MessageContentType = MessageContentType.TEXTO,
    corpo: str | None = "x",
) -> Message:
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
        content_type=content_type,
        text_body=encrypt(corpo, aad_de(identificador, "text_body")),
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


def test_mensagem_sem_texto_entra_marcada_pelo_tipo() -> None:
    """Audio, imagem e documento nao podem entrar como turno vazio.

    Essas linhas gravam `text_body` NULL hoje -- transcricao e OCR sao
    historias proprias. Rendendo string vazia, tres audios do lead viram tres
    turnos em branco no prompt, indistinguiveis de tres mensagens vazias, e a
    dobra manda esse nada para o resumo: a memoria permanente da conversa passa
    a dizer que o lead nao falou nada onde ele mandou tres audios.
    """
    audio = _mensagem_literal(content_type=MessageContentType.AUDIO, corpo=None)
    imagem = _mensagem_literal(content_type=MessageContentType.IMAGEM, corpo=None)
    documento = _mensagem_literal(content_type=MessageContentType.DOCUMENTO, corpo=None)
    desconhecido = _mensagem_literal(content_type=MessageContentType.DESCONHECIDO, corpo=None)

    assert _texto_da(audio) == "[LEAD] (audio, sem transcricao)"
    assert _texto_da(imagem) == "[LEAD] (imagem, sem descricao)"
    assert _texto_da(documento) == "[LEAD] (documento, sem texto extraido)"
    assert _texto_da(desconhecido) == "[LEAD] (mensagem sem texto)", (
        "tipo nao mapeado ainda tem de dizer que veio alguma coisa"
    )


def test_campo_marcado_aparece_no_estado() -> None:
    estado = LeadQualification(
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao="COMPRA",
        quartos=3,
        perguntados_sem_resposta=["regiao"],
    )
    texto = _texto_do_estado(estado)

    assert "quartos: 3" in texto
    assert "regiao: (perguntado, sem resposta)" in texto


def test_preco_aparece_em_reais_sob_a_chave_antiga() -> None:
    """TEC-146: o banco guarda centavos, mas o texto que o modelo le nao muda.

    `_texto_do_estado` alimenta o prompt de verdade (`montar_prompt`), entao a
    unidade e o nome da chave sao contrato com o modelo, nao detalhe de
    armazenamento -- ver o docstring de `_em_reais`. `faixa_preco_min_centavos`
    aqui e proposital: 123456 nao e multiplo de 100 (o parser aceita "R$
    1.234,56"), entao "1234.56" prova que a conversao divide por 100 de
    verdade, e nao so troca o nome da chave.
    """
    estado = LeadQualification(
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao="COMPRA",
        faixa_preco_min_centavos=123456,
        faixa_preco_max_centavos=60_000_000,
    )
    linhas = _texto_do_estado(estado).splitlines()

    assert "faixa_preco_min: 1234.56" in linhas
    assert "faixa_preco_max: 600000.00" in linhas
    assert not any("centavos" in linha for linha in linhas), (
        "a chave que o modelo le e a antiga, sem sufixo -- o armazenamento mudou, "
        "o contrato com o modelo nao"
    )


def test_valor_vence_marca() -> None:
    """A marca nunca aparece ao lado de um valor.

    Marca sobre campo ja preenchido e possivel -- `campos_a_marcar` subtrai
    os campos DESTE turno, nao o estado acumulado -- e e inerte por causa
    desta regra.
    """
    estado = LeadQualification(
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao="COMPRA",
        regiao="pinheiros",
        perguntados_sem_resposta=["regiao"],
    )
    texto = _texto_do_estado(estado)

    assert "regiao: pinheiros" in texto
    assert "perguntado" not in texto


def test_valor_falso_tambem_vence_marca() -> None:
    """`0` e `False` sao informacao, e a marca nao pode engoli-los.

    `Extracao.preenchidos` ja documenta isso: o lead que diz "nao tenho nada
    pra vender" respondeu a pergunta, e quem precisa de zero vaga informou
    zero. Um `if valor` em vez de `is not None` mostraria a marca por cima
    dos dois -- o agente reperguntaria o que o lead ja respondeu, e a
    seguranca que `campos_a_marcar` afirma (marca sobre campo preenchido e
    inerte) seria falsa justamente nos dois casos que o projeto ja sabe que
    enganam.
    """
    estado = LeadQualification(
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao="COMPRA",
        vagas=0,
        tem_imovel_para_vender=False,
        perguntados_sem_resposta=["vagas", "tem_imovel_para_vender"],
    )
    texto = _texto_do_estado(estado)

    assert "vagas: 0" in texto
    assert "tem_imovel_para_vender: False" in texto
    assert "perguntado" not in texto


def test_a_ordem_dos_campos_nao_muda_por_causa_da_marca() -> None:
    """A ordem e estavel: o campo marcado sai no lugar dele, nao no fim.

    Ordem instavel no fim do prompt e mudanca de cache e de geracao a cada
    turno, de graca.
    """
    estado = LeadQualification(
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao="COMPRA",
        vagas=1,
        perguntados_sem_resposta=["regiao"],
    )
    linhas = _texto_do_estado(estado).splitlines()

    assert linhas == [
        "intencao: COMPRA",
        "regiao: (perguntado, sem resposta)",
        "vagas: 1",
    ]


def test_campo_recusado_aparece_marcado_mesmo_sem_a_marca_irma() -> None:
    """TEC-148: e a uniao das duas colunas que sustenta a promessa da card.

    A marca da TEC-257 NAO e garantida no turno que pergunta --
    `marcar_perguntados` nao roda quando o turno nao tem nada a gravar, o
    caminho de desambiguacao nunca chega la, e saida bloqueada tambem nao. A
    sequencia da propria historia da card passa por ai: o lead diz "oi"
    (INDEFINIDA, confianca baixa, desambiguacao, nenhuma marca), depois diz
    "prefiro nao falar de dinheiro". Sem a uniao, `perguntados_sem_resposta`
    esta vazio e o orcamento sai do prompt sem marca nenhuma -- o agente
    repergunta exatamente o que o lead acabou de recusar.

    `perguntados_sem_resposta=[]` de proposito: e o estado que prova a
    uniao. Com a lista irma preenchida, o teste passaria com ou sem ela.
    """
    estado = LeadQualification(
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao="COMPRA",
        perguntados_sem_resposta=[],
        campos_recusados=["faixa_preco_max"],
    )
    linhas = _texto_do_estado(estado).splitlines()

    assert linhas == [
        "intencao: COMPRA",
        "faixa_preco_max: (perguntado, sem resposta)",
    ]


def test_valor_vence_a_marca_da_recusa_tambem() -> None:
    """D4 do desenho, declarada: um campo recusado que tenha valor de um turno
    anterior renderiza o valor, e o modelo pode usa-lo na conversa. O lead
    recusou DIZER o valor agora; usar o que ele ja disse antes nao e
    pressiona-lo. A consequencia de qualificacao mora em `esta_qualificado` e
    em `calcular_score`, nunca aqui.
    """
    estado = LeadQualification(
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao="COMPRA",
        regiao="pinheiros",
        campos_recusados=["regiao"],
    )
    texto = _texto_do_estado(estado)

    assert "regiao: pinheiros" in texto
    assert "perguntado" not in texto


def test_recusa_nula_e_recusa_vazia_leem_igual() -> None:
    """`NULL` e `{}` sao fatos diferentes no banco e a mesma coisa na leitura,
    na coluna da recusa como na irma."""
    nula = LeadQualification(channel=CANAL, conversation_key=CONVERSA, intencao="COMPRA")
    vazia = LeadQualification(
        channel=CANAL, conversation_key=CONVERSA, intencao="COMPRA", campos_recusados=[]
    )

    assert _texto_do_estado(nula) == _texto_do_estado(vazia) == "intencao: COMPRA"


def test_marca_nula_e_marca_vazia_leem_igual() -> None:
    """`NULL` e `{}` sao fatos diferentes no banco e a mesma coisa na leitura."""
    nula = LeadQualification(channel=CANAL, conversation_key=CONVERSA, intencao="COMPRA")
    vazia = LeadQualification(
        channel=CANAL, conversation_key=CONVERSA, intencao="COMPRA", perguntados_sem_resposta=[]
    )

    assert _texto_do_estado(nula) == _texto_do_estado(vazia) == "intencao: COMPRA"


def test_a_regra_do_prompt_cobre_o_ignorado() -> None:
    assert "nao repergunte o preenchido nem o ignorado" in SISTEMA_DO_AGENTE


def test_o_prompt_manda_confirmar_orcamento_vago() -> None:
    """D4: o codigo e a correcao (nao grava), o prompt e a economia (pergunta
    no mesmo turno). A camada que garante nao pode depender da que lembra.

    Assercao de posicao, nao so de substring: a frase precisa estar colada ao
    fim do texto, precedida pelo ponto e espaco herdados da frase anterior.
    Um erro de concatenacao comum e realista neste modulo -- string literal
    adjacente sem separador, ou a frase esquecida dentro do comentario que
    documenta o orcamento e nunca chegando a fazer parte do valor de
    `SISTEMA_DO_AGENTE` -- passaria num `in` solto e falha aqui.
    """
    assert SISTEMA_DO_AGENTE.endswith(" Orcamento vago: peca confirmacao.")
    assert "  " not in SISTEMA_DO_AGENTE


def test_montar_prompt_ordena_sistema_resumo_literais_e_estado() -> None:
    """A ordem e a razao de `montar_prompt` existir: sistema e resumo primeiro
    porque mudam devagar e ficam quentes no cache de prompt, estado por
    ultimo porque muda a cada extracao da TEC-145. Nada testava isso antes.
    """
    contexto = ContextoMontado(
        sistema="MARCA-SISTEMA",
        resumo="MARCA-RESUMO",
        literais=[_mensagem_literal(corpo="MARCA-LITERAL")],
        estado=LeadQualification(channel=CANAL, conversation_key=CONVERSA, regiao="MARCA-ESTADO"),
        tokens=10,
        degradado=False,
    )

    prompt = montar_prompt(contexto)

    assert (
        prompt.index("MARCA-SISTEMA")
        < prompt.index("MARCA-RESUMO")
        < prompt.index("MARCA-LITERAL")
        < prompt.index("MARCA-ESTADO")
    )


def test_montar_prompt_omite_resumo_ausente() -> None:
    """Sem resumo (primeiro turno da conversa), a secao nao aparece vazia --
    ela simplesmente nao existe.
    """
    contexto = ContextoMontado(
        sistema="MARCA-SISTEMA",
        resumo=None,
        literais=[_mensagem_literal(corpo="MARCA-LITERAL")],
        estado=None,
        tokens=5,
        degradado=False,
    )

    prompt = montar_prompt(contexto)

    assert "Resumo da conversa" not in prompt


def test_montar_prompt_omite_sistema_quando_o_chamador_ja_tem_um() -> None:
    """`omitir_sistema=True` e o que a TEC-134 usa: ela ja manda a propria
    persona pelo campo `system` dedicado da API, e reenviar `contexto.sistema`
    aqui dentro do turno do usuario duplicaria a mesma instrucao, mais fraca.
    """
    contexto = ContextoMontado(
        sistema="MARCA-SISTEMA",
        resumo="MARCA-RESUMO",
        literais=[_mensagem_literal(corpo="MARCA-LITERAL")],
        estado=None,
        tokens=5,
        degradado=False,
    )

    prompt = montar_prompt(contexto, omitir_sistema=True)

    assert "MARCA-SISTEMA" not in prompt
    assert "MARCA-RESUMO" in prompt


def test_audio_nao_se_confunde_com_mensagem_vazia() -> None:
    """A distincao e o ponto: o modelo tem de poder diferenciar os dois casos."""
    audio = _mensagem_literal(content_type=MessageContentType.AUDIO, corpo=None)
    vazia = _mensagem_literal(content_type=MessageContentType.TEXTO, corpo="")

    assert _texto_da(audio) != _texto_da(vazia)


async def test_audio_no_prompt_e_no_resumo_nao_vira_turno_em_branco(session) -> None:
    """Fim a fim: o marcador chega no que e medido e no que e dobrado.

    A mesma funcao monta o texto do prompt, o texto que a contagem mede e o
    conteudo que vai para o resumidor na dobra -- entao provar o marcador em
    `_texto_das` prova os tres.
    """
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            provider_message_id=f"wamid.{identificador.hex[:10]}",
            conversation_key=CONVERSA,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.AUDIO,
            text_body=None,
            raw_payload=None,
            status=MessageStatus.PROCESSED,
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

    assert len(contexto.literais) == 1
    assert _texto_das(contexto.literais) == "[LEAD] (audio, sem transcricao)"


def test_repr_do_contexto_nao_carrega_conteudo_do_lead() -> None:
    """O repr default de dataclass despejaria o resumo em claro num log.

    A mascara de PII desce por dict, list e tuple, mas nao por dataclass -- um
    `log.info("turno", contexto=contexto)` na TEC-134 renderizaria o resumo sob
    uma chave que nao esta na lista de redigidas. O repr elide o conteudo e
    mantem a forma, que e o que serve para depurar.
    """
    contexto = ContextoMontado(
        sistema="sistema",
        resumo="lead procura apto de 600 mil na zona sul",
        literais=[_mensagem_literal(), _mensagem_literal()],
        estado=None,
        tokens=9000,
        degradado=False,
    )

    texto = repr(contexto)

    assert "zona sul" not in texto
    assert "600 mil" not in texto
    assert "literais=2" in texto, "a forma continua depuravel"
    assert "tokens=9000" in texto
    assert "degradado=False" in texto


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


class ContadorProibido:
    """Um contador que falha se alguem o chamar.

    Existe para o modo sem modelo: o ponto dele e nao pagar round trip
    nenhum, e um contador que apenas devolve um numero nao distingue "nao
    chamou" de "chamou e coube".
    """

    async def contar(self, texto: str) -> int:
        raise AssertionError("o modo sem modelo nao pode falar com o provedor")


def test_a_estimativa_sem_modelo_supoe_o_piso_de_caracteres_por_token() -> None:
    """No modo sem modelo a estimativa e a palavra final, entao ela erra para cima.

    `_estimar` supoe 4 caracteres por token, e o portugues acentuado roda a
    3,2-3,7 (ver `Settings.limiar_de_contagem_efetivo`): ela SUBCONTA. No
    caminho normal isso e inofensivo, porque o limiar so a deixa responder
    onde errar nao muda a decisao. Aqui ela decide sozinha, e subcontar seria
    dizer "cabe" com um texto que estoura.

    O teste afirma a PROPRIEDADE -- a razao de caracteres por token implicita
    fica no piso documentado -- e nao a formula, que seria copiar a
    implementacao para o teste.
    """
    literais = [_mensagem_literal(corpo="x" * 4000)]
    bruto = len(SISTEMA) + len(_texto_das(literais)) + len(_texto_do_estado(None))

    pessimista = _estimar_pessimista(None, literais, None)

    assert bruto / pessimista <= 3.2
    assert pessimista > _estimar(None, literais, None)


async def test_o_truncamento_sem_modelo_corta_sem_falar_com_o_provedor() -> None:
    """O fallback do deadline nao pode pedir ao modelo justamente quando o tempo dele acabou.

    `_truncar_ate_caber` conta a cada volta, e `_contar_se_valer` paga um
    round trip acima do limiar. Chamado do estouro do deadline, isso seria
    gastar a chamada que nao ha mais tempo de fazer.

    5000 caracteres por mensagem, e nao os 4000 do outro teste: com 4000 a
    estimativa pessimista de oito mensagens fica abaixo do
    `teto_de_tokens_efetivo` (10940 hoje) e o laco de truncamento nunca
    dispara -- o teste passaria vazio, sem exercitar `sem_modelo` nenhum.
    """
    literais = [_mensagem_literal(corpo="x" * 5000) for _ in range(8)]
    teto = get_settings().teto_de_tokens_efetivo

    resumo, restantes, tokens = await _truncar_ate_caber(
        ContadorProibido(),
        CANAL,
        "resumo qualquer",
        literais,
        None,
        _estimar_pessimista("resumo qualquer", literais, None),
        teto,
        sem_modelo=True,
    )

    assert len(restantes) < 8, "a janela tinha de encolher"
    assert tokens <= teto
    assert resumo == "resumo qualquer", "coube cortando literais; o resumo nao precisou cair"


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
    """Ultimo degrau da cascata, fim a fim via `montar_contexto`.

    As quatro primeiras contagens do roteiro cobrem a contagem inicial e as
    tres passadas do laco: dobra (25 -> 20 literais), comprime o resumo, e
    dobra abaixo do piso (20 -> 1). Nesse ponto o teto de iteracoes estoura com
    uma unica literal -- nao ha janela para reduzir pela metade -- e so a
    quinta contagem, apos descartar o resumo tambem, cabe.
    """
    await semear(session, 25)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500] * 4 + [9000])

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
    estourando de cara. Comprimir aqui seria chamar
    `resumidor.resumir(INSTRUCAO_COMPRIMIR, "")` -- e o texto que o provedor
    inventasse a partir do vazio viraria memoria da conversa sem nunca ter
    sido ganho, a mesma classe de falha que a Task 4 evita ao recusar um
    resumo vazio.

    O caminho certo nao e o corte de emergencia: e dobrar abaixo do piso. As
    quatro mensagens antigas viram resumo de verdade -- conteudo que existiu --
    em vez de serem descartadas.
    """
    await semear(session, 5)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500, 9000])  # estoura, cabe apos dobrar abaixo do piso

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=contador,
    )

    assert INSTRUCAO_COMPRIMIR not in resumidor.chamadas, (
        "nunca deve pedir ao provedor para comprimir uma string vazia"
    )
    assert resumidor.chamadas == [INSTRUCAO_DOBRAR], "o piso cede dobrando, nao descartando"
    assert contexto.resumo == "resumo do que veio antes"
    assert len(contexto.literais) == 1
    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert contexto.degradado is True


async def test_piso_cede_dobrando_e_nao_descartando(session, caplog, sempre_contar) -> None:
    """O cenario que o spec permite violar o piso -- e o unico.

    Vinte mensagens que sozinhas somam mais de 12.000 tokens (vinte audios
    transcritos longos) sem nenhum resumo previo. O piso nao pode ser
    respeitado e o teto nao negocia, entao o piso cede. A questao e *como*:

    - dobrando, as dezenove mais antigas viram resumo, a marca avanca junto e
      nao existe lacuna entre o resumido e o literal;
    - descartando, elas somem, e o modelo recebe resumo de 1..N + literais
      N+k..M com um buraco no meio -- exatamente o que a arquitetura da marca
      d'agua existe para impedir.

    O teste prende o primeiro comportamento: o resumidor foi chamado, a marca
    esta gravada cobrindo as dezenove, e nenhum `contexto.truncado` aconteceu.
    """
    criadas = await semear(session, 20)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500, 9000])

    with caplog.at_level(logging.WARNING):
        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=resumidor,
            contador=contador,
        )

    assert resumidor.chamadas == [INSTRUCAO_DOBRAR], (
        "sem resumo previo nao ha o que comprimir; o degrau que sobra e dobrar abaixo do piso"
    )
    assert len(contexto.literais) == 1
    assert contexto.resumo == "resumo do que veio antes"
    assert contexto.tokens <= get_settings().contexto_teto_de_tokens
    assert "contexto.truncado" not in caplog.text, "conteudo do lead nao pode ser descartado aqui"
    assert "contexto.piso_violado" in caplog.text, "o piso cedeu; o evento tem de registrar"

    async with get_sessionmaker()() as outra:
        gravado = await ler_resumo(outra, CANAL, CONVERSA)
    assert gravado is not None, "a marca tem de avancar junto -- e o que fecha a lacuna"
    assert gravado.mensagens_cobertas == 19
    assert gravado.watermark_message_id == criadas[18].id


async def test_comprimir_nao_registra_piso_violado(session, caplog, sempre_contar) -> None:
    """O evento so pode disparar quando o piso de fato cede.

    Aqui o laco dobra (25 -> 20 literais) e comprime o resumo justamente para
    *nao* encostar no piso -- as literais ficam intactas nas vinte. Um alerta
    que dispara neste caminho manda o operador investigar um piso saudavel e,
    pior, se acostuma a ser ignorado quando o piso quebrar de verdade.
    """
    await semear(session, 25)
    resumidor = ResumidorFake()
    contador = ContadorFake(roteiro=[13500, 13500, 9000])

    with caplog.at_level(logging.WARNING):
        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=resumidor,
            contador=contador,
        )

    assert resumidor.chamadas == [INSTRUCAO_DOBRAR, INSTRUCAO_COMPRIMIR]
    assert len(contexto.literais) == get_settings().contexto_literais_minimas
    assert "contexto.piso_violado" not in caplog.text


async def test_truncar_registra_o_piso_violado_junto_com_o_descarte(sempre_contar, caplog) -> None:
    """Descartar literais abaixo do piso e violacao de piso, e a mais grave.

    Antes so `contexto.truncado` registrava aqui, com outro nome, enquanto
    `contexto.piso_violado` disparava num caminho em que o piso estava
    intacto. Quem pagina no evento do piso tem de ver este caso.
    """
    literais = [_mensagem_literal() for _ in range(40)]
    contador = ContadorFake(roteiro=[13500, 9000])  # 40 -> 20 ainda estoura, 20 -> 10 cabe

    with caplog.at_level(logging.WARNING):
        _, restantes, _ = await _truncar_ate_caber(
            contador, CANAL, "resumo qualquer", literais, None, 13500, 12000
        )

    assert len(restantes) == 10
    assert "contexto.piso_violado" in caplog.text
    assert caplog.text.count("contexto.piso_violado") == 1, (
        "um aviso por corte encheria o log; o piso quebra uma vez so"
    )


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


async def test_resumo_ilegivel_degrada_em_vez_de_travar_a_conversa(session, caplog) -> None:
    """Uma linha de resumo que nao decifra nao pode brickar o lead para sempre.

    Rotacao de chave, escrita parcial, restore de um ambiente com outra chave:
    o resumo fica ilegivel e, sem guarda, todo turno seguinte deste lead
    levanta `DecryptionError` -- para sempre, porque nada reescreve a linha se
    ninguem consegue montar contexto. Era o unico modo de falha deste modulo
    sem caminho degradado.

    Degradar aqui e barato: sem marca, tudo volta literal (nada some) e a
    proxima dobra sobrescreve a linha ilegivel.
    """
    criadas = await semear(session, 3)
    session.add(
        ConversationSummary(
            channel=CANAL,
            conversation_key=CONVERSA,
            # Cifrado sob o AAD de OUTRA conversa: e exatamente o que uma chave
            # trocada ou um restore cruzado produzem do ponto de vista do
            # `decrypt` -- bytes que nao autenticam.
            resumo=encrypt("resumo de outra conversa", aad_do_resumo(CANAL, "5511999998888")),
            watermark_created_at=criadas[0].created_at,
            watermark_message_id=criadas[0].id,
            mensagens_cobertas=1,
            modelo="claude-opus-5",
        )
    )
    await session.commit()

    with caplog.at_level(logging.WARNING):
        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=ResumidorFake(),
            contador=ContadorFake(),
        )

    assert contexto.resumo is None, "resumo ilegivel vale como resumo inexistente"
    assert len(contexto.literais) == 3, "sem marca, tudo volta literal -- nada some"
    assert contexto.degradado is True
    assert "contexto.resumo_ilegivel" in caplog.text


async def test_resumo_ilegivel_e_sobrescrito_pela_proxima_dobra(session) -> None:
    """O degradado tem de se curar sozinho, senao a conversa fica degradada."""
    criadas = await semear(session, 40)
    session.add(
        ConversationSummary(
            channel=CANAL,
            conversation_key=CONVERSA,
            resumo=encrypt("ilegivel", aad_do_resumo(CANAL, "5511999998888")),
            watermark_created_at=criadas[0].created_at,
            watermark_message_id=criadas[0].id,
            mensagens_cobertas=1,
            modelo="claude-opus-5",
        )
    )
    await session.commit()

    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=ContadorFake(),
    )

    async with get_sessionmaker()() as outra:
        gravado = await ler_resumo(outra, CANAL, CONVERSA)
    assert gravado is not None, "a linha ilegivel tem de ter sido reescrita"
    assert gravado.texto == "resumo do que veio antes"


async def test_teto_e_comparado_ja_com_a_reserva_descontada(session, sempre_contar) -> None:
    """Uma contagem entre o teto efetivo e o nominal tem de acionar o laco.

    11.800 esta abaixo dos 12.000 nominais e acima do teto efetivo. E
    exatamente a faixa que a reserva existe para pegar: o contador mede uma
    mensagem plana, e o overhead estrutural do array multi-turno que a TEC-134
    vai montar cabe dentro dessa diferenca. Sem a reserva, este contexto seria
    aceito aqui e recusado pelo provedor la.
    """
    await semear(session, 25)
    resumidor = ResumidorFake()

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(roteiro=[11800, 9000]),
    )

    assert resumidor.chamadas == [INSTRUCAO_DOBRAR], (
        "11.800 cabe no teto nominal e nao no efetivo -- o laco tem de rodar"
    )
    assert contexto.tokens <= get_settings().teto_de_tokens_efetivo


async def test_estimativa_acima_do_teto_paga_a_contagem_real(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backstop duro: a estimativa nunca responde "cabe" ao passar do teto.

    Com o limiar levantado para alem do teto -- o unico jeito de este caminho
    ser o gatilho -- um texto grande o suficiente para a propria estimativa
    passar do teto ainda tem de acionar a contagem real. Decidir que cabe a
    partir do unico numero disponivel, que diz o contrario, seria devolver um
    contexto acima do limite fisico da chamada com um palpite por tras.
    """
    monkeypatch.setenv("CONTEXTO_LIMIAR_DE_CONTAGEM", "999999")
    get_settings.cache_clear()
    try:
        # 20 x 2.500 caracteres: `len//4` ja passa do teto efetivo sozinho.
        await semear(session, 20, texto="a" * 2500)
        contador = ContadorFake()

        await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=ResumidorFake(),
            contador=contador,
        )

        assert contador.chamadas >= 1, (
            "estimativa acima do teto tem de ceder a vez para a contagem real, "
            "mesmo com o limiar desligado"
        )
    finally:
        get_settings.cache_clear()


async def test_estado_de_qualificacao_entra_no_contexto(session) -> None:
    await semear(session, 3)
    session.add(
        LeadQualification(
            channel=CANAL,
            conversation_key=CONVERSA,
            faixa_preco_max_centavos=60_000_000,
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
    assert contexto.estado.faixa_preco_max_centavos == 60_000_000


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


async def test_conteudo_curto_em_caracteres_nunca_aciona_a_contagem_real(session) -> None:
    """O mecanismo, nao o emoji: a decisao de medir olha `len()` e mais nada.

    Este teste nao mede tokens de verdade -- o duble tambem conta por `len/4`
    e nenhum teste desta suite toca a rede. O que ele prende e o gatilho:
    conteudo curto em CARACTERES nunca paga a contagem real, seja la o que ele
    contenha. Emoji e so o exemplo mais afiado (cada um e 1 caractere Python e
    2-4 tokens); base64 e URL sao a versao comum. A conta completa esta em
    `Settings.limiar_de_contagem_efetivo`.

    NOTA PARA QUEM VIER DEPOIS: este teste ficar vermelho e o desfecho
    esperado, nao uma regressao. Ele descreve um risco aceito, nao uma
    garantia do produto -- no dia em que existir um estimador que leve
    densidade de caracteres nao-ASCII em conta (ticket proprio, fora do
    TEC-127), este conteudo passara a acionar a contagem real e a assercao
    abaixo tem de ser invertida junto com a mudanca, nao "consertada".
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


class _ResumidorEspiao(ResumidorFake):
    """Registra o `conteudo` que recebeu, e nao so a instrucao.

    `ResumidorFake` guarda `chamadas` com a instrucao; para a TEC-236 o que
    importa e o outro argumento -- e nele que as falas literais viajam para
    dentro do resumo permanente.
    """

    def __init__(self) -> None:
        super().__init__()
        self.conteudos: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str):
        self.conteudos.append(conteudo)
        return await super().resumir(instrucao, conteudo)


async def _bloquear(session, mensagem: Message) -> None:
    from mobia.domain.messages.bloqueio import marcar_bloqueada

    # channel/conversation_key vem da propria linha semeada, e nao de um
    # literal, para o helper nao fixar valores que o teste em volta pode
    # mudar. A categoria e indiferente aqui -- estes testes sao sobre a fala
    # bloqueada nao entrar no contexto, nao sobre qual categoria bloqueou.
    await marcar_bloqueada(
        get_sessionmaker(),
        mensagem.id,
        channel=mensagem.channel,
        conversation_key=mensagem.conversation_key,
        categoria="DISCRIMINACAO",
    )
    await session.refresh(mensagem)


async def test_fala_bloqueada_nao_entra_na_janela(session) -> None:
    """O filtro na origem, no menor nivel possivel.

    `literais_apos` e onde a correcao mora, e nao no chamador: tudo o que monta
    contexto ou resumo passa por aqui, entao o que nao sai daqui nao chega a
    lugar nenhum.
    """
    criadas = await semear(session, 5)
    await _bloquear(session, criadas[2])

    janela = await literais_apos(session, CANAL, CONVERSA, None)

    assert len(janela) == 4
    assert criadas[2].id not in {m.id for m in janela}


async def test_fala_bloqueada_nao_entra_no_contexto_do_turno_seguinte(session) -> None:
    """O defeito que a TEC-236 conserta, no caminho que o expunha.

    A TEC-233 impedia que a fala bloqueada virasse **resposta naquele turno**.
    O turno seguinte montava contexto decifrando-a inteira para dentro do
    prompt -- e era exatamente esse turno que ninguem testava.
    """
    criadas = await semear(session, 3, texto=None)
    bloqueada = criadas[1]
    await _bloquear(session, bloqueada)

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorFake(),
        contador=ContadorFake(),
    )

    literais = {m.id for m in contexto.literais}
    assert len(contexto.literais) == 2
    assert bloqueada.id not in literais, "a fala bloqueada foi montada no contexto"
    assert {criadas[0].id, criadas[2].id} == literais, "as outras continuam"


async def test_fala_bloqueada_nao_entra_no_resumo_na_dobra(session) -> None:
    """A metade permanente do defeito, e a que nao tem volta.

    Contexto e efemero: a fala sai da janela quando a conversa anda. O resumo
    nao -- o que entra na dobra fica gravado e viaja em todo turno seguinte,
    para sempre. Se a fala bloqueada atravessa aqui, ela sobrevive a propria
    janela.
    """
    # 41 e nao 40: a mensagem bloqueada sai da janela, entao ela deixa de
    # contar para o gatilho. E consequencia correta -- o gatilho conta o que
    # vai virar prompt --, mas o teste tem de semear uma a mais para a dobra
    # ainda acontecer.
    criadas = await semear(session, 41)
    # Uma das mais antigas: sao essas que a dobra consome.
    bloqueada = criadas[3]
    await _bloquear(session, bloqueada)
    resumidor = _ResumidorEspiao()

    await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=resumidor,
        contador=ContadorFake(),
    )

    assert len(resumidor.conteudos) == 1, "40 literais nao bloqueados disparam a dobra"
    assert "mensagem 3" not in resumidor.conteudos[0]
    assert "mensagem 2" in resumidor.conteudos[0], "as outras foram dobradas normalmente"


async def test_o_timeout_do_resumo_diz_contra_que_teto_estourou(
    session, caplog, sempre_contar
) -> None:
    """TEC-228: `reason` ja separava o timeout; `teto_s` diz de qual teto.

    A card pedia que o estouro do resumo deixasse de ser indistinguivel das
    outras degradacoes, e `reason=type(exc).__name__` ja fazia isso --
    `APITimeoutError` tem nome proprio. O que faltava chegou junto com o teto
    por tipo: desde que cada fatia do turno tem o seu, o mesmo
    `APITimeoutError` significa 25s aqui e 35s no investidor, e quem le o log
    nao tinha como saber contra qual deles a chamada morreu.
    """
    await semear(session, 40)
    estouro = anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.exemplo"))

    with caplog.at_level(logging.WARNING):
        contexto = await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=ResumidorFake(erro=estouro),
            contador=ContadorFake(),
        )

    assert contexto.degradado is True
    linha = json.loads(
        next(r.getMessage() for r in caplog.records if "contexto.degradado" in r.getMessage())
    )
    assert linha["reason"] == "APITimeoutError"
    assert linha["teto_s"] == TETO_DO_RESUMO


async def test_degradacao_que_nao_foi_timeout_nao_afirma_teto(
    session, caplog, sempre_contar
) -> None:
    """`teto_s` e `None` quando a causa nao foi tempo, e nao o teto sempre.

    O campo diz "estourou ESTE teto". Numa falha de schema ou de conexao
    recusada nenhum teto foi estourado, e carimbar 25,0 ali faria o campo
    mentir sobre o que aconteceu -- pior que nao existir, porque um log que
    mente e lido como se fosse verdade.
    """
    await semear(session, 40)

    with caplog.at_level(logging.WARNING):
        await montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=ResumidorFake(falha=True),
            contador=ContadorFake(),
        )

    linha = json.loads(
        next(r.getMessage() for r in caplog.records if "contexto.degradado" in r.getMessage())
    )
    assert linha["reason"] == "RuntimeError"
    assert linha["teto_s"] is None


class ResumidorQueTrava:
    """Um resumidor que nunca devolve, e que avisa quando entrou.

    O aviso (`entrou`) e o que torna o teste de cancelamento deterministico:
    sem ele, `tarefa.cancel()` pode chegar antes de a corrotina alcancar o
    await do provedor, e o teste passaria sem exercitar nada.
    """

    def __init__(self) -> None:
        self.entrou = asyncio.Event()
        self.chamadas: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.chamadas.append(instrucao)
        self.entrou.set()
        await asyncio.Event().wait()
        raise AssertionError("inalcancavel")


async def test_deadline_estourado_degrada_em_vez_de_esperar(
    session, caplog, sempre_contar, caches_de_cliente_limpos, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fase inteira tem relogio proprio, e estourar nao pode devolver contexto acima do teto.

    E o ponto da TEC-290: teto por requisicao nao limita uma fase que faz N
    requisicoes. Com o resumidor travado, so o deadline termina o turno.

    O contador e o `ContadorProibido`: depois do estouro nao pode haver
    round trip nenhum, e um contador que responde nao distinguiria
    "nao chamou" de "chamou e coube".
    """
    monkeypatch.setenv("CONTEXTO_DEADLINE_DE_MONTAGEM_SEGUNDOS", "0.05")
    get_settings.cache_clear()
    await semear(session, 45)

    contexto = await montar_contexto(
        get_sessionmaker(),
        channel=CANAL,
        conversation_key=CONVERSA,
        resumidor=ResumidorQueTrava(),
        contador=ContadorProibido(),
    )

    assert contexto.degradado is True
    assert contexto.tokens <= get_settings().teto_de_tokens_efetivo
    assert "contexto.deadline_estourado" in caplog.text


async def test_cancelamento_de_fora_nao_vira_degradacao(
    session, sempre_contar, caches_de_cliente_limpos, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O `CancelledError` do `job_timeout` atravessa a fase inteira.

    E o contrato que a TEC-227 construiu: quem tem de receber o cancelamento
    e a clausula de `process_message`, que marca FAILED, incrementa
    `attempts` e loga `message.cancelled`. Engoli-lo aqui devolveria a
    mensagem perdida em silencio que aquela card veio acabar.

    O deadline e folgado de proposito: se ele disparasse antes do
    `cancel()`, o teste passaria pela razao errada.
    """
    monkeypatch.setenv("CONTEXTO_DEADLINE_DE_MONTAGEM_SEGUNDOS", "30")
    get_settings.cache_clear()
    await semear(session, 45)
    resumidor = ResumidorQueTrava()

    tarefa = asyncio.create_task(
        montar_contexto(
            get_sessionmaker(),
            channel=CANAL,
            conversation_key=CONVERSA,
            resumidor=resumidor,
            contador=ContadorProibido(),
        )
    )
    await resumidor.entrou.wait()
    tarefa.cancel()

    with pytest.raises(asyncio.CancelledError):
        await tarefa
