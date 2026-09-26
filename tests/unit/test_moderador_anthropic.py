from typing import Any

import pytest

from mobia.domain.moderacao.port import Direcao, ModeracaoIndisponivel


class RespostaFalsa:
    """Molda o que o SDK devolve, sem tocar a rede."""

    def __init__(
        self,
        texto: str,
        stop_reason: str = "end_turn",
        modelo: str = "claude-haiku-4-5-20251001",
        tokens_in: int = 120,
        tokens_out: int = 3,
    ) -> None:
        class Bloco:
            type = "text"

            def __init__(self, t: str) -> None:
                self.text = t

        class Uso:
            def __init__(self, entrada: int, saida: int) -> None:
                self.input_tokens = entrada
                self.output_tokens = saida

        self.content = [Bloco(texto)]
        self.stop_reason = stop_reason
        # `model` e `usage` vem do SDK e a TEC-249 passou a le-los: sem eles
        # aqui, o molde deixaria de moldar o que o codigo de fato consome.
        # O default e um ID DATADO de proposito -- e o que `modelo_moderacao`
        # configura, e foi o formato que nunca achava preco na tabela.
        self.model = modelo
        self.usage = Uso(tokens_in, tokens_out)


class ClienteFalso:
    def __init__(self, resposta: Any = None, erro: Exception | None = None) -> None:
        self.resposta = resposta
        self.erro = erro
        self.kwargs: dict[str, Any] = {}
        self.messages = self

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.erro is not None:
            raise self.erro
        return self.resposta


def _moderador(monkeypatch: pytest.MonkeyPatch, cliente: ClienteFalso):
    from mobia.infra import moderacao

    monkeypatch.setattr(moderacao, "get_moderation_client", lambda: cliente)
    return moderacao.ModeradorAnthropic()


async def test_bloquear_vira_veredito_bloqueado(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True


async def test_liberar_vira_veredito_liberado(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso(RespostaFalsa("LIBERAR"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is False


async def test_resposta_fora_do_protocolo_e_indisponibilidade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Palavra que nao e nenhuma das duas nao pode virar "liberado".

    Interpretar o desconhecido como liberado transforma um moderador confuso em
    um moderador desligado, e desligado em silencio -- que e o modo de falha
    que este subsistema existe para nao ter.
    """
    cliente = ClienteFalso(RespostaFalsa("talvez"))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)


async def test_parada_anormal_e_indisponibilidade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Veredito com parada anormal nao e veredito, mesmo que a palavra sirva.

    O texto aqui e `BLOQUEAR` inteiro, e nao truncado, de proposito: com uma
    palavra invalida o `else` final do parser reprovaria sozinho, e o teste
    passaria mesmo sem a checagem de `stop_reason` -- nao guardaria nada. Com a
    palavra valida, so a checagem de parada pode reprovar, e remove-la faz este
    teste falhar.
    """
    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR", stop_reason="max_tokens"))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)


async def test_erro_do_provedor_vira_indisponibilidade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qualquer falha da chamada e "nao deu para moderar", nunca "liberado"."""
    cliente = ClienteFalso(erro=TimeoutError("estourou"))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)


async def test_a_direcao_escolhe_o_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Se a direcao nao trocar o prompt, ela e decoracao e o criterio da saida
    (mais estrito, porque e a empresa falando) nunca e aplicado.
    """
    from mobia.infra.moderacao import SISTEMA_DA_ENTRADA, SISTEMA_DA_SAIDA

    cliente = ClienteFalso(RespostaFalsa("LIBERAR"))
    moderador = _moderador(monkeypatch, cliente)

    await moderador.moderar("x", direcao=Direcao.ENTRADA)
    assert cliente.kwargs["system"] == SISTEMA_DA_ENTRADA

    await moderador.moderar("x", direcao=Direcao.SAIDA)
    assert cliente.kwargs["system"] == SISTEMA_DA_SAIDA
    assert SISTEMA_DA_ENTRADA != SISTEMA_DA_SAIDA


def test_o_cliente_da_moderacao_tem_teto_proprio_e_nao_retenta() -> None:
    """Moderar as duas pontas nao pode custar uma fracao sensivel do turno.

    **A comparacao de retentativas saiu daqui na TEC-228, e a razao e boa
    noticia.** Este teste afirmava `MAX_TENTATIVAS_DA_MODERACAO < MAX_TENTATIVAS`
    quando o cliente do turno ainda retentava; hoje os dois sao 0, porque o
    argumento escrito no comentario deste modulo -- "uma segunda tentativa
    dobraria o teto para ganhar pouco" -- acabou valendo para o turno tambem.
    Manter a desigualdade estrita obrigaria o turno a retentar para este teste
    passar, que e o oposto do que ele quer.

    O que resta e o que sempre importou: o teto daqui e menor que o piso de
    construcao do cliente, e as duas pontas juntas cabem em 15s. Quem quiser
    ver a conta inteira do turno, ela esta em
    `tests/unit/test_orcamento_do_turno.py`, onde esta moderacao entra como um
    dos quatro termos.
    """
    from mobia.infra.anthropic import TIMEOUT_SEGUNDOS
    from mobia.infra.moderacao import (
        MAX_TENTATIVAS_DA_MODERACAO,
        TIMEOUT_DA_MODERACAO_SEGUNDOS,
    )

    assert TIMEOUT_DA_MODERACAO_SEGUNDOS < TIMEOUT_SEGUNDOS
    assert MAX_TENTATIVAS_DA_MODERACAO == 0
    pior_caso = TIMEOUT_DA_MODERACAO_SEGUNDOS * (1 + MAX_TENTATIVAS_DA_MODERACAO)
    assert pior_caso * 2 <= 15


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("BLOQUEAR.", True),
        ("LIBERAR\n.", False),
        ("**LIBERAR**", False),
        ("  bloquear  ", True),
    ],
)
async def test_pontuacao_em_volta_do_veredito_nao_perde_o_turno(
    monkeypatch: pytest.MonkeyPatch, bruto: str, esperado: bool
) -> None:
    """Tolerante na forma, rigido no conteudo.

    O protocolo pede uma palavra sem pontuacao, e o modelo quase sempre
    obedece -- mas "quase" nao serve aqui. Um ponto final que escapa vira
    `ModeracaoIndisponivel`, e na saida a indisponibilidade nao e inofensiva:
    propaga, a linha vira FAILED, o sweeper roda o turno inteiro de novo
    pagando `classificar` outra vez ate `sweep_max_attempts`, e depois disso a
    linha fica em FAILED para sempre. O lead nao recebe nada -- silencio, o
    desfecho que este repositorio trata como o pior de todos. Trocar um turno
    por um ponto final e o negocio errado.
    """
    cliente = ClienteFalso(RespostaFalsa(bruto))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is esperado


@pytest.mark.parametrize("bruto", ["BLOQUEAR LIBERAR", "talvez", "LIBERAR se quiser", ""])
async def test_a_tolerancia_de_forma_nao_afrouxa_o_conteudo(
    monkeypatch: pytest.MonkeyPatch, bruto: str
) -> None:
    """Limpar as pontas nao pode virar "achar a palavra em qualquer lugar".

    A garantia que nao pode ceder e a de que o desconhecido nunca vira
    liberado. Duas palavras nao sao um veredito -- nao da para saber qual
    delas o modelo quis --, e uma resposta que explica em vez de decidir
    tambem nao e. Se a normalizacao passasse a procurar a palavra dentro de
    uma frase, "nao vou BLOQUEAR" e "BLOQUEAR LIBERAR" viravam veredito, e o
    moderador confuso viraria moderador desligado.
    """
    cliente = ClienteFalso(RespostaFalsa(bruto))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)


def test_o_cliente_da_moderacao_e_construido_com_o_teto_curto(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """O teste acima relaciona constantes; este prova que elas chegam ao cliente.

    Sem ele, apagar `timeout=` e `max_retries=` de `get_moderation_client()`
    passa na suite inteira: as constantes continuam la, a relacao entre elas
    continua valendo, e o cliente volta ao default do SDK -- 10 min com
    retentativa interna, ou seja o pior caso que o argumento de custo deste
    card existe para evitar, com o card inteiro parecendo intacto. E o mesmo
    padrao de `test_cliente_falha_tipado_antes_de_o_arq_cancelar`, em
    `tests/unit/test_config.py`, para o cliente do turno.
    """
    from mobia.infra.moderacao import (
        MAX_TENTATIVAS_DA_MODERACAO,
        TIMEOUT_DA_MODERACAO_SEGUNDOS,
        get_moderation_client,
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    cliente = get_moderation_client()

    assert cliente.timeout == TIMEOUT_DA_MODERACAO_SEGUNDOS
    assert cliente.max_retries == MAX_TENTATIVAS_DA_MODERACAO


def test_o_cliente_da_moderacao_recusa_subir_sem_chave(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """Chave ausente falha aqui, com mensagem util, e nao no meio de um turno.

    Mesma guarda que `get_client()` tem desde a TEC-127, e pelo mesmo motivo --
    so que este cliente e chamado na primeira linha do turno, onde a falha nao
    tipada seria confundida com "o moderador caiu" e trataria configuracao
    ausente como indisponibilidade passageira.
    """
    from mobia.app.config import ConfiguracaoInsegura
    from mobia.infra.moderacao import get_moderation_client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    with pytest.raises(ConfiguracaoInsegura, match="ANTHROPIC_API_KEY"):
        get_moderation_client()


async def test_moderacao_registra_custo_nao_nulo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """O custo da moderacao nunca foi registrado, e este teste e a guarda.

    `moderar` tinha a resposta inteira em maos -- com `model` e `usage` -- e
    descartava as duas, devolvendo so o `Veredito`. A moderacao roda nas duas
    pontas de todo turno, entao o caminho mais quente do produto era o unico
    sem custo em lugar nenhum.

    O assert e sobre `custo_usd` nao ser "None": e a forma exata que o buraco
    da tabela de precos produzia, e a que voltaria se alguem trocasse
    `modelo_moderacao` por um ID sem preco cadastrado.
    """
    import logging

    cliente = ClienteFalso(RespostaFalsa("LIBERAR"))
    with caplog.at_level(logging.INFO):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    linha = next(r for r in caplog.records if "moderacao.avaliada" in r.getMessage())
    texto = linha.getMessage()
    assert "custo_usd=None" not in texto
    assert "custo_usd='None'" not in texto
    assert "tokens_in" in texto and "tokens_out" in texto


async def test_veredito_fora_do_protocolo_tambem_registra_custo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A chamada ja foi paga antes de o veredito ser julgado invalido.

    Registrar so no caminho feliz esconderia justamente o gasto que nao
    produziu nada -- e um moderador devolvendo lixo gasta igual a um que
    funciona.
    """
    import logging

    cliente = ClienteFalso(RespostaFalsa("TALVEZ"))
    with caplog.at_level(logging.INFO):
        with pytest.raises(ModeracaoIndisponivel):
            await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)

    assert any("moderacao.avaliada" in r.getMessage() for r in caplog.records)


async def test_log_da_moderacao_nao_carrega_o_texto_julgado(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """O que a moderacao ve e conteudo do lead ou da empresa.

    A regra do log do classificador -- so numeros e id de modelo -- aperta
    aqui: nem o texto julgado, nem o veredito sobre ele.
    """
    import logging

    segredo = "meu telefone e 11999998888"
    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR"))
    with caplog.at_level(logging.INFO):
        await _moderador(monkeypatch, cliente).moderar(segredo, direcao=Direcao.ENTRADA)

    for registro in caplog.records:
        assert segredo not in registro.getMessage()
        assert "BLOQUEAR" not in registro.getMessage()


async def test_o_porque_do_erro_do_provedor_chega_a_indisponibilidade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metade do incidente de 28/08 foi aqui: 41 de 41 casos, todos cegos.

    `ModeracaoIndisponivel` carregava so o nome da classe, entao saldo esgotado
    e schema quebrado ficavam identicos no log (TEC-237).
    """
    import httpx
    from anthropic import BadRequestError

    requisicao = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resposta = httpx.Response(400, request=requisicao)
    cliente = ClienteFalso(
        erro=BadRequestError(
            "erro",
            response=resposta,
            body={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Your credit balance is too low to access the Anthropic API.",
                },
            },
        )
    )

    with pytest.raises(ModeracaoIndisponivel) as capturado:
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert "credit balance is too low" in str(capturado.value)


async def test_excecao_sem_corpo_do_provedor_continua_so_com_o_nome_da_classe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A garantia que a TEC-237 nao podia afrouxar.

    O texto de uma excecao qualquer pode ser o proprio conteudo moderado -- a
    fala do lead ou a resposta da empresa. Sem corpo de erro do servidor, so o
    nome da classe sai daqui.
    """
    segredo = "quero um apartamento de 3 quartos na zona sul"
    cliente = ClienteFalso(erro=TimeoutError(segredo))

    with pytest.raises(ModeracaoIndisponivel) as capturado:
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert str(capturado.value) == "TimeoutError"
    assert segredo not in str(capturado.value)


@pytest.mark.parametrize(
    ("bruto", "categoria"),
    [
        ("BLOQUEAR DISCRIMINACAO", "DISCRIMINACAO"),
        ("BLOQUEAR AMEACA", "AMEACA"),
        ("bloquear discriminacao", "DISCRIMINACAO"),
        ("BLOQUEAR DISCRIMINACAO.", "DISCRIMINACAO"),
    ],
)
async def test_a_segunda_palavra_vira_categoria(
    monkeypatch: pytest.MonkeyPatch, bruto: str, categoria: str
) -> None:
    """A mesma tolerancia de forma da primeira palavra vale para a segunda:
    minuscula e pontuacao nas pontas nao podem custar um turno.
    """
    cliente = ClienteFalso(RespostaFalsa(bruto))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == categoria


@pytest.mark.parametrize("bruto", ["BLOQUEAR ZORGLUB", "BLOQUEAR"])
async def test_categoria_desconhecida_bloqueia_como_outro(
    monkeypatch: pytest.MonkeyPatch, bruto: str
) -> None:
    """Toda folga cai do lado que bloqueia.

    Antes desta card um `BLOQUEAR` enfeitado virava `ModeracaoIndisponivel`, e
    na saida isso propaga: a linha vira FAILED, o sweeper repaga o turno ate
    `sweep_max_attempts` e depois o lead nunca recebe nada. Um rotulo que o
    vocabulario nao reconhece nao desfaz a decisao de bloquear que o modelo ja
    tomou -- vira bloqueio auditado com rotulo de fracasso do protocolo.
    """
    from mobia.domain.moderacao.port import CATEGORIA_OUTRO

    cliente = ClienteFalso(RespostaFalsa(bruto))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)

    assert veredito.bloqueado is True
    assert veredito.categoria == CATEGORIA_OUTRO


async def test_categoria_da_outra_direcao_nao_vale(monkeypatch: pytest.MonkeyPatch) -> None:
    """`OFENSA` e categoria da saida. Vinda da entrada, e rotulo que aquele
    prompt nao ofereceu -- bloqueia, mas como OUTRO.
    """
    from mobia.domain.moderacao.port import CATEGORIA_OUTRO

    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR OFENSA"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == CATEGORIA_OUTRO


async def test_liberar_nao_aceita_segunda_palavra(monkeypatch: pytest.MonkeyPatch) -> None:
    """A invariante do subsistema: o desconhecido nunca vira liberado.

    Se a leitura olhasse so a primeira palavra, `LIBERAR NAO` viraria
    liberacao -- e o custo de errar para esse lado e entregar ao lead o texto
    que a moderacao existia para barrar.
    """
    cliente = ClienteFalso(RespostaFalsa("LIBERAR NAO"))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)


async def test_veredito_liberado_nao_ganha_categoria(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso(RespostaFalsa("LIBERAR"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is False
    assert veredito.categoria is None


def test_o_protocolo_pedido_nomeia_as_categorias_da_direcao() -> None:
    """O que se pede e o que se le nao podem divergir: um prompt que nao lista
    a palavra produz resposta fora do vocabulario, e a leitura devolve OUTRO
    para todo bloqueio -- auditoria cheia de linha sem informacao.
    """
    from mobia.domain.moderacao.port import CATEGORIAS_POR_DIRECAO, Direcao
    from mobia.infra.moderacao import SISTEMA_DA_ENTRADA, SISTEMA_DA_SAIDA

    for categoria in CATEGORIAS_POR_DIRECAO[Direcao.ENTRADA]:
        assert categoria in SISTEMA_DA_ENTRADA
    for categoria in CATEGORIAS_POR_DIRECAO[Direcao.SAIDA]:
        assert categoria in SISTEMA_DA_SAIDA


async def test_liberar_injecao_e_o_achado_sozinho(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEC-204, D3: `INJECAO` sozinha e o turno seguindo normal, e a forma que
    diz isso comeca por `LIBERAR`."""
    cliente = ClienteFalso(RespostaFalsa("LIBERAR INJECAO"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is False
    assert veredito.injecao is True
    assert veredito.categoria is None
    assert veredito.motivo == "ENTRADA:INJECAO"


async def test_bloquear_injecao_bloqueia_como_outro(monkeypatch: pytest.MonkeyPatch) -> None:
    """O buraco medido no eval pago: com `BLOQUEAR INJECAO` liberando, o lead
    ditava esse rotulo ao moderador e o conteudo hostil passava (8/10 bloqueios
    em `entrada_injecao_bloqueia`, contra 10/10 do parser de antes da card).
    Comecar por BLOQUEAR e decidir bloquear -- o rotulo nao desfaz isso."""
    from mobia.domain.moderacao.port import CATEGORIA_OUTRO

    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR INJECAO"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == CATEGORIA_OUTRO
    assert veredito.injecao is True


async def test_injecao_com_outra_categoria_bloqueia_pela_outra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR ASSEDIO INJECAO"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == "ASSEDIO"
    assert veredito.injecao is True


async def test_injecao_antes_da_categoria_tambem_vale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tolerante na forma: a ordem das duas categorias nao muda o veredito."""
    cliente = ClienteFalso(RespostaFalsa("bloquear injecao, assedio."))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == "ASSEDIO"
    assert veredito.injecao is True


async def test_injecao_na_saida_e_rotulo_de_outra_direcao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A saida nao oferece `INJECAO`: depois de BLOQUEAR, bloqueia como OUTRO."""
    from mobia.domain.moderacao.port import CATEGORIA_OUTRO

    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR INJECAO"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)

    assert veredito.bloqueado is True
    assert veredito.categoria == CATEGORIA_OUTRO
    assert veredito.injecao is False


async def test_liberar_injecao_na_saida_e_indisponibilidade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Na saida `LIBERAR INJECAO` e `LIBERAR` com palavra que o prompt nao
    ofereceu -- fora do protocolo, e la a indisponibilidade impede a entrega."""
    cliente = ClienteFalso(RespostaFalsa("LIBERAR INJECAO"))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.SAIDA)


@pytest.mark.parametrize(
    "bruto",
    [
        "BLOQUEAR ASSEDIO AMEACA",
        "BLOQUEAR ASSEDIO INJECAO X",
        "LIBERAR ASSEDIO",
        "LIBERAR INJECAO INJECAO",
        "LIBERAR INJECAO ASSEDIO",
        "LIBERAR ASSEDIO INJECAO",
    ],
)
async def test_tres_palavras_fora_da_forma_sao_indisponibilidade(
    monkeypatch: pytest.MonkeyPatch, bruto: str
) -> None:
    """A terceira palavra so existe para `INJECAO`; duas categorias que
    bloqueiam, ou `LIBERAR` com qualquer coisa alem de um `INJECAO`, sao o
    modelo fora do protocolo. `LIBERAR` nao ganha a tolerancia que `BLOQUEAR`
    tem, porque liberar e o lado caro de errar."""
    cliente = ClienteFalso(RespostaFalsa(bruto))

    with pytest.raises(ModeracaoIndisponivel):
        await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)


def test_o_protocolo_da_entrada_ensina_as_duas_formas_da_injecao() -> None:
    """O que se pede e o que se le: a forma liberada comeca por LIBERAR, e
    `INJECAO` nao aparece na frase do veredito -- la ela seria categoria de
    bloqueio, e `BLOQUEAR INJECAO` voltaria a ser resposta ensinada."""
    from mobia.infra.moderacao import _protocolo_de

    entrada = _protocolo_de(Direcao.ENTRADA)
    assert "LIBERAR INJECAO" in entrada
    assert "BLOQUEAR ASSEDIO INJECAO" in entrada
    assert "BLOQUEAR INJECAO" not in entrada
    decisao = next(linha for linha in entrada.splitlines() if linha.startswith("Primeiro"))
    assert "INJECAO" not in decisao
    assert "nao e categoria de bloqueio" in entrada
    assert "INJECAO" not in _protocolo_de(Direcao.SAIDA)


async def test_bloquear_injecao_repetida_continua_bloqueando(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`BLOQUEAR INJECAO INJECAO` diz o mesmo que `BLOQUEAR INJECAO`: bloqueio
    como OUTRO, com o achado. Tolerancia de forma so do lado que bloqueia."""
    from mobia.domain.moderacao.port import CATEGORIA_OUTRO

    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR INJECAO INJECAO"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.injecao is True
    assert veredito.categoria == CATEGORIA_OUTRO


async def test_injecao_com_rotulo_desconhecido_bloqueia_como_outro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toda folga cai do lado que bloqueia, tambem com o achado junto."""
    from mobia.domain.moderacao.port import CATEGORIA_OUTRO

    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR ZORGLUB INJECAO"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == CATEGORIA_OUTRO
    assert veredito.injecao is True


def _todas_as_respostas_de_ate_tres_palavras() -> list[str]:
    """Todo arranjo de ate tres palavras sobre o vocabulario das duas direcoes,
    os dois vereditos, OUTRO e uma palavra que ninguem ofereceu."""
    import itertools

    from mobia.domain.moderacao.port import CATEGORIA_OUTRO, CATEGORIAS_POR_DIRECAO

    palavras = sorted(
        set().union(*CATEGORIAS_POR_DIRECAO.values())
        | {"LIBERAR", "BLOQUEAR", CATEGORIA_OUTRO, "ZORGLUB"}
    )
    return [
        " ".join(arranjo) for n in (1, 2, 3) for arranjo in itertools.product(palavras, repeat=n)
    ]


@pytest.mark.parametrize("direcao", list(Direcao))
async def test_so_liberar_e_liberar_injecao_liberam(
    monkeypatch: pytest.MonkeyPatch, direcao: Direcao
) -> None:
    """A invariante da correcao, por exaustao: de todas as respostas de ate tres
    palavras sobre o vocabulario, so `LIBERAR` e, na entrada, `LIBERAR INJECAO`
    devolvem veredito liberado. Um terceiro caminho para liberar e um rotulo que
    o lead pode ditar ao moderador."""
    liberam = {"LIBERAR"} | ({"LIBERAR INJECAO"} if direcao is Direcao.ENTRADA else set())
    liberadas: set[str] = set()
    for bruto in _todas_as_respostas_de_ate_tres_palavras():
        cliente = ClienteFalso(RespostaFalsa(bruto))
        try:
            veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=direcao)
        except ModeracaoIndisponivel:
            continue
        if not veredito.bloqueado:
            liberadas.add(bruto)

    assert liberadas == liberam


async def test_categoria_com_acento_e_reconhecida(monkeypatch: pytest.MonkeyPatch) -> None:
    """O modelo escreve em portugues, e `upper()` guarda o `Ç` e o `Ã`: sem
    tirar o acento, `INJEÇÃO` vira tres corridas de letras e o veredito cai
    fora do protocolo -- fail-open na entrada."""
    cliente = ClienteFalso(RespostaFalsa("BLOQUEAR AMEAÇA INJEÇÃO"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == "AMEACA"
    assert veredito.injecao is True


async def test_liberar_injecao_com_acento_e_reconhecido(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = ClienteFalso(RespostaFalsa("LIBERAR INJEÇÃO"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is False
    assert veredito.injecao is True


async def test_assedio_minusculo_com_acento_e_reconhecido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = ClienteFalso(RespostaFalsa("bloquear assédio."))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == "ASSEDIO"


async def test_letra_acentuada_solta_continua_separador(monkeypatch: pytest.MonkeyPatch) -> None:
    """So se tira o acento de dentro de uma palavra que ja tem letra sem
    acento. Solta, a letra acentuada continua fora das corridas, como era
    antes: `É BLOQUEAR AMEACA` bloqueava, e tirar o acento de tudo faria dela
    a palavra `E`, fora do protocolo -- um bloqueio que viraria fail-open."""
    cliente = ClienteFalso(RespostaFalsa("É BLOQUEAR AMEACA"))
    veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=Direcao.ENTRADA)

    assert veredito.bloqueado is True
    assert veredito.categoria == "AMEACA"


_COM_ACENTO = {
    "AMEACA": "AMEAÇA",
    "ASSEDIO": "ASSÉDIO",
    "DISCRIMINACAO": "DISCRIMINAÇÃO",
    "INJECAO": "INJEÇÃO",
    "NEGOCIACAO": "NEGOCIAÇÃO",
    "VIOLENCIA": "VIOLÊNCIA",
}


@pytest.mark.parametrize("direcao", list(Direcao))
async def test_o_acento_nao_muda_veredito_nenhum(
    monkeypatch: pytest.MonkeyPatch, direcao: Direcao
) -> None:
    """Por exaustao: toda resposta de ate tres palavras, escrita com acento,
    devolve o mesmo desfecho que sem ele. O acento so tira resposta de
    "fora do protocolo"; nunca faz uma liberar onde a forma sem acento
    bloqueia."""

    async def desfecho(bruto: str) -> tuple[bool, str | None, bool] | None:
        cliente = ClienteFalso(RespostaFalsa(bruto))
        try:
            veredito = await _moderador(monkeypatch, cliente).moderar("x", direcao=direcao)
        except ModeracaoIndisponivel:
            return None
        return (veredito.bloqueado, veredito.categoria, veredito.injecao)

    for bruto in _todas_as_respostas_de_ate_tres_palavras():
        acentuada = " ".join(_COM_ACENTO.get(p, p) for p in bruto.split())
        assert await desfecho(acentuada) == await desfecho(bruto), acentuada


def test_o_protocolo_diz_quantas_categorias_cabem_em_cada_direcao() -> None:
    """Uma categoria nas duas direcoes: na entrada `INJECAO` nao e categoria de
    bloqueio, e sim o achado acrescentado no fim."""
    from mobia.infra.moderacao import _protocolo_de

    assert "com a categoria depois." in _protocolo_de(Direcao.ENTRADA)
    assert "BLOQUEAR seguido de uma categoria." in _protocolo_de(Direcao.SAIDA)


def test_o_teto_do_veredito_cobre_o_mais_longo_medido() -> None:
    """Truncar o veredito na entrada e fail-open: o conteudo que devia bloquear
    passa calado. Medido em 25/09/2026 com `count_tokens` em
    `claude-haiku-4-5-20251001`, para toda categoria que bloqueia, nua e com o
    enfeite que a leitura tolera, sem e com acento: o mais longo e
    `**BLOQUEAR** AMEAÇA INJEÇÃO.`, com 16 (sem acento, 15). `DISCRIMINACAO`
    tem mais letras e custa menos: 14 com o enfeite. `LIBERAR INJECAO` tem
    duas palavras e nao passa dele. Remedir se `modelo_moderacao` mudar ou se
    o vocabulario ganhar palavra mais longa."""
    from mobia.infra.moderacao import MAX_TOKENS_DO_VEREDITO

    mais_longo_medido = 16
    assert MAX_TOKENS_DO_VEREDITO > mais_longo_medido
