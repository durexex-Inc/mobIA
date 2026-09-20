"""O adaptador de e-mail, contra um servidor SMTP de verdade em processo.

Servidor real e nao monkeypatch de `aiosmtplib.send`: um monkeypatch prova que
chamamos uma funcao com certos argumentos, e este teste precisa provar que a
MENSAGEM chega -- com o endereco certo e com o corpo inteiro. E' tambem a
unica forma de pegar acento estropiado no transporte, que e defeito de
codificacao e nao de chamada. Ver a D7 do desenho.
"""

import email
import logging
import socket
from email.message import Message

import pytest
from aiosmtpd.controller import Controller

from mobia.app.config import get_settings
from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.outbound.email import EmailSmtp

RESUMO = (
    "## Quem e o lead\nPaulo procura apartamento no Condominio Acacia, orcamento ate R$ 450 mil."
)


def _porta_livre() -> int:
    """Uma porta efemera, ja resolvida.

    O brief pedia `port=0` direto no `Controller`, mas nesta versao do
    aiosmtpd o atributo `self.port` nunca e atualizado com a porta real que o
    SO escolheu -- so o bind usa `port=0`, e o `_trigger_server` que segue
    tenta conectar em `(host, 0)` mesmo assim. Nesta maquina isso e
    `OSError [WinError 10049]`, e o `controlador.start()` nunca completa. Achar
    a porta livre aqui, fora do `Controller`, e devolve-la ja resolvida evita
    o `self.port` que o `Controller` nao atualiza sozinho.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Caixa:
    """Guarda o que o servidor recebeu, para o teste ler depois."""

    def __init__(self) -> None:
        self.recebidas: list[Message] = []
        self.destinatarios: list[str] = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        self.destinatarios.extend(envelope.rcpt_tos)
        self.recebidas.append(email.message_from_bytes(envelope.content))
        return "250 OK"


@pytest.fixture
def servidor():
    caixa = _Caixa()
    controlador = Controller(caixa, hostname="127.0.0.1", port=_porta_livre())
    controlador.start()
    yield controlador, caixa
    controlador.stop()


def _canal_em(host: str, porta: int, monkeypatch: pytest.MonkeyPatch) -> EmailSmtp:
    """Um adaptador apontado para este endereco, sem TLS e sem autenticacao.

    Via variavel de ambiente e `cache_clear()` porque `get_settings` e
    `@lru_cache`: e' assim que o resto da suite troca configuracao, e um
    caminho proprio aqui divergiria do que a aplicacao de fato le.
    """
    monkeypatch.setenv("SMTP_HOST", host)
    monkeypatch.setenv("SMTP_PORTA", str(porta))
    monkeypatch.setenv("SMTP_REMETENTE", "mobia@localhost")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("SMTP_USUARIO", "")
    monkeypatch.setenv("SMTP_SENHA", "")
    get_settings.cache_clear()
    return EmailSmtp()


def _canal_apontando_para(controlador: Controller, monkeypatch: pytest.MonkeyPatch) -> EmailSmtp:
    return _canal_em(controlador.hostname, controlador.port, monkeypatch)


async def test_a_mensagem_chega_com_destino_resumo_e_link(
    servidor, monkeypatch, caches_de_cliente_limpos: None
) -> None:
    controlador, caixa = servidor
    canal = _canal_apontando_para(controlador, monkeypatch)

    await canal.enviar(
        destino="paulo@imobiliaria.com.br",
        assunto="Lead pronto [quente] prioridade alta",
        corpo=f"{RESUMO}\n\nConversa completa: https://exemplo/conversas/whatsapp/5511",
    )

    assert caixa.destinatarios == ["paulo@imobiliaria.com.br"]
    # D4: "uma tentativa, sem retentativa". Uma entrega feliz nao pode virar
    # duas mensagens na caixa do corretor.
    assert len(caixa.recebidas) == 1
    (mensagem,) = caixa.recebidas
    texto = mensagem.get_payload(decode=True).decode("utf-8")
    assert "Condominio Acacia" in texto
    assert "https://exemplo/conversas/whatsapp/5511" in texto


async def test_o_acento_sobrevive_ao_transporte(
    servidor, monkeypatch, caches_de_cliente_limpos: None
) -> None:
    """O resumo vem do modelo e vem acentuado. E' o teste que paga a D7.

    Montar cabecalho a mao em vez de usar `EmailMessage` passa neste teste so
    por acaso; quebra com assunto acentuado e com corpo longo, que o
    quoted-printable parte em linhas.
    """
    controlador, caixa = servidor
    canal = _canal_apontando_para(controlador, monkeypatch)
    corpo = "O lead procura no Condomínio Acácia, três dormitórios, até R$ 450 mil."

    await canal.enviar(
        destino="p@x.com", assunto="Lead pronto [morno] prioridade média", corpo=corpo
    )

    (mensagem,) = caixa.recebidas
    assert mensagem.get_payload(decode=True).decode("utf-8").strip() == corpo
    assert "média" in str(email.header.make_header(email.header.decode_header(mensagem["Subject"])))


async def test_servidor_indisponivel_vira_falha_de_canal(
    monkeypatch, caches_de_cliente_limpos: None
) -> None:
    """Porta fechada: o adaptador traduz para a excecao que o orquestrador trata."""
    canal = _canal_em("127.0.0.1", 1, monkeypatch)  # porta 1: recusa conexao

    with pytest.raises(FalhaDeCanal):
        await canal.enviar(destino="p@x.com", assunto="a", corpo="b")


@pytest.mark.parametrize("excecao", [TypeError, AttributeError])
async def test_defeito_de_programacao_sobe(
    servidor, monkeypatch, caches_de_cliente_limpos: None, excecao: type[Exception]
) -> None:
    """A D5, travada: `except Exception` aqui reintroduz o problema que
    `FalhaDeCanal` existe para resolver -- o handoff sairia como pendente de
    aviso manual por causa de um bug que ninguem veria.

    A D5 nomeia os dois -- `TypeError` E `AttributeError` -- porque sao as
    duas formas mais provaveis de um defeito de programacao aparecer aqui:
    argumento errado para `aiosmtplib.send` (`TypeError`) ou atributo que
    `configuracao` nao tem (`AttributeError`).
    """
    controlador, _ = servidor
    canal = _canal_apontando_para(controlador, monkeypatch)

    async def explode(*args, **kwargs):
        raise excecao("defeito de programacao")

    monkeypatch.setattr("mobia.domain.outbound.email.aiosmtplib.send", explode)

    with pytest.raises(excecao):
        await canal.enviar(destino="p@x.com", assunto="a", corpo="b")


async def test_o_log_nunca_carrega_o_corpo(
    servidor, monkeypatch, caplog, caches_de_cliente_limpos: None
) -> None:
    controlador, _ = servidor
    canal = _canal_apontando_para(controlador, monkeypatch)
    sentinela = "SENTINELA-CORPO o lead mora na Rua das Palmeiras"

    # Cala o `mail.log` do `aiosmtpd` (o SERVIDOR de teste, nao o adaptador) e
    # escuta a RAIZ em DEBUG. As duas partes importam: so calar o servidor e
    # continuar na raiz pega qualquer logger que vaze o corpo -- inclusive uma
    # biblioteca terceira em modo de depuracao, que e exatamente o que a D6
    # proibe. Escopar ao logger do adaptador (`mobia.domain.outbound.email`)
    # deixaria passar batido um vazamento por QUALQUER outro logger: medido,
    # inserindo `logging.getLogger("aiosmtplib.smtp").debug("DATA >> %s", corpo)`
    # dentro de `enviar()` -- o que a D6 proibe -- o teste escopado passava, e
    # so escutar a raiz pega esse caso.
    logging.getLogger("mail.log").setLevel(logging.WARNING)
    try:
        with caplog.at_level(logging.DEBUG):
            await canal.enviar(destino="p@x.com", assunto="a", corpo=sentinela)
    finally:
        logging.getLogger("mail.log").setLevel(logging.NOTSET)

    assert sentinela not in caplog.text


async def test_timeout_vira_falha_de_canal(monkeypatch, caches_de_cliente_limpos: None) -> None:
    """Estoura o tempo, e nao trava. Teste 7 do desenho.

    `SMTPTimeoutError` herda `SMTPException` E `TimeoutError` -- o `except`
    do adaptador pegaria por qualquer um dos dois nomes, mas so estourar o
    relogio de verdade prova que o caminho existe e nao trava o job do ARQ.
    Um socket que aceita a conexao e nunca fala nada forca a espera pela
    saudacao SMTP (`220 ...`) ate o timeout, sem depender de rede externa nem
    de endereco nao roteavel, que teria latencia imprevisivel.
    """
    servidor_mudo = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor_mudo.bind(("127.0.0.1", 0))
    servidor_mudo.listen(1)
    porta = servidor_mudo.getsockname()[1]
    # Curto para o teste nao pagar os 15s reais de SEGUNDOS_DE_TIMEOUT.
    monkeypatch.setattr("mobia.domain.outbound.email.SEGUNDOS_DE_TIMEOUT", 0.2)

    try:
        canal = _canal_em("127.0.0.1", porta, monkeypatch)
        with pytest.raises(FalhaDeCanal):
            await canal.enviar(destino="p@x.com", assunto="a", corpo="b")
    finally:
        servidor_mudo.close()
