"""O canal de e-mail que entrega de verdade. TEC-280, RN-16.2.

SMTP direto e nao API de provedor: a escolha de 19/09/2026 foi deliberada, e a
razao esta na TEC-219, que ainda nao decidiu a nuvem. Falando SMTP, trocar
para SES, Resend ou Postmark e mexer em variavel de ambiente e nao em codigo.

Substitui o `EmailRegistrado`, que so escrevia `notificacao.nao_entregue`
desde a TEC-177. Aquele adaptador foi APAGADO junto com esta card, e nao
mantido como alternativa: deixa-lo disponivel preservaria o caminho de volta
para o descarte em silencio.
"""

from email.message import EmailMessage

import aiosmtplib
import structlog

from mobia.app.config import get_settings
from mobia.domain.notificacao.canais import FalhaDeCanal

log = structlog.get_logger(__name__)

# Teto por entrega. Sem ele um servidor pendurado segura o job do ARQ pelo
# tempo que quiser, e a fila para atras dele.
SEGUNDOS_DE_TIMEOUT = 15.0


class EmailSmtp:
    """Entrega a notificacao por SMTP. Uma tentativa, sem retentativa."""

    nome = "email"

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        configuracao = get_settings()

        # `EmailMessage` e nao concatenacao de cabecalho: o corpo vem do
        # modelo e vem acentuado, e e' aqui que se escolhe entre UTF-8 bem
        # declarado e mojibake na caixa do corretor.
        mensagem = EmailMessage()
        mensagem["From"] = configuracao.smtp_remetente
        mensagem["To"] = destino
        mensagem["Subject"] = assunto
        mensagem.set_content(corpo, charset="utf-8")

        try:
            await aiosmtplib.send(
                mensagem,
                hostname=configuracao.smtp_host,
                port=configuracao.smtp_porta,
                username=configuracao.smtp_usuario or None,
                password=configuracao.smtp_senha or None,
                start_tls=configuracao.smtp_starttls,
                timeout=SEGUNDOS_DE_TIMEOUT,
            )
        # NAO e `except Exception`. A docstring de `FalhaDeCanal` diz por que:
        # engolir TypeError e AttributeError faria o handoff sair marcado como
        # pendente de aviso manual por causa de um defeito de programacao, que
        # ninguem veria. Aqui a lista e explicita -- recusa do servidor, erro
        # de rede e estouro de tempo --, e o resto sobe.
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as erro:
            # **Nunca loga `corpo`**: ele carrega o resumo, pela mesma razao
            # que `handoffs.resumo` e cifrado em repouso.
            log.warning("notificacao.email_recusado", destino=destino, assunto=assunto)
            raise FalhaDeCanal(f"SMTP recusou a mensagem: {type(erro).__name__}") from erro

        log.info("notificacao.email_entregue", destino=destino, assunto=assunto)
