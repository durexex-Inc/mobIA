"""O canal de WhatsApp que entrega ao corretor. TEC-281, RN-16.2.

Substitui o `WhatsAppRegistrado`, que so escrevia `notificacao.nao_entregue`
desde a TEC-177. Aquele adaptador foi APAGADO junto com esta card, pela mesma
razao que a TEC-280 apagou o `EmailRegistrado`: manter disponivel o adaptador
que descarta em silencio preserva o caminho de volta para ele.

**Por que nao herda de `GuardedOutbound`, que e como todo envio de WhatsApp
deste projeto sai.** Aquela classe aplica tres guardas, e as tres sao sobre o
LEAD: opt-out por `message_id`, atendimento humano, e reserva em
`outbound_dispatches` contra resposta duplicada. O corretor nao e lead -- nao
tem linha em `messages`, nao tem opt-out, nao esta em conversa nenhuma.
Passar por ali exigiria inventar um `message_id`, isto e, uma linha falsa em
`messages`, que e a tabela de onde saem as metricas de origem e o historico
da conversa. **A ausencia das guardas aqui e decisao, nao esquecimento.**

Se um dia existir opt-out de CORRETOR, ele nao entra aqui de carona: o lugar
dele e a selecao do destinatario (`notificacao/destinatario.py`), que e quem
decide a quem avisar.
"""

from typing import Any

import httpx
import structlog

from mobia.app.config import get_settings
from mobia.domain.notificacao.canais import FalhaDeCanal
from mobia.domain.notificacao.mensagem import Aviso

log = structlog.get_logger(__name__)

# Teto por entrega, pelo mesmo motivo do `SEGUNDOS_DE_TIMEOUT` de `email.py`:
# sem ele um servidor pendurado segura o job do ARQ e a fila para atras dele.
SEGUNDOS_DE_TIMEOUT = 15.0

# A Meta exige o idioma do template no envio, e ele tem de bater com o do
# template aprovado. Fixo porque o produto inteiro fala portugues do Brasil --
# o dia em que houver template em outro idioma, isto vira configuracao junto
# com o nome, nao antes.
IDIOMA_DO_TEMPLATE = "pt_BR"


class WhatsAppTemplate:
    """Entrega o aviso ao corretor por template aprovado. Uma tentativa, sem retentativa."""

    nome = "whatsapp"

    def __init__(self, cliente: httpx.AsyncClient | None = None) -> None:
        self._cliente = cliente

    async def enviar(self, *, destino: str, aviso: Aviso) -> None:
        configuracao = get_settings()
        # O template vem do AVISO, e nao da configuracao lida aqui: o mesmo
        # vetor `canais_de_notificacao` serve `notificar` (lead pronto, ao
        # corretor) e `escalar_vencidos` (handoff vencido, ao gerente). Preso
        # ao canal, ele mandaria a mensagem de um ao destinatario do outro.
        # Ver o comentario do campo em `notificacao/mensagem.py`.
        template = aviso.template

        # Duas condicoes, um so desfecho: aviso sem template, ou com nome que
        # a operacao ainda nao marcou como aprovado. Em ambos os casos a
        # unica saida seria texto livre, e ela e recusa GARANTIDA -- o
        # destinatario esta sempre fora da janela de 24h porque nao conversa
        # com o numero da empresa, entao a Cloud API responderia 131047.
        # Tentar seria gastar chamada para receber o erro que ja se sabe.
        #
        # **Loga ANTES de levantar, e isso nao e redundancia.** `notificar` so
        # imprime `motivos` quando NENHUM canal aceita; com o e-mail
        # entregando, esta falha nao apareceria em lugar nenhum -- pior que o
        # `WhatsAppRegistrado` que esta card substitui, que ao menos
        # registrava. A card exige explicito e barulhento.
        if not template or template not in configuracao.templates_aprovados:
            motivo = (
                "aviso sem template aprovado"
                if not template
                else f"template {template} nao esta entre os aprovados"
            )
            log.warning(
                "notificacao.whatsapp_sem_template",
                destino=destino,
                assunto=aviso.assunto,
                motivo=motivo,
            )
            raise FalhaDeCanal(f"WhatsApp nao pode entregar: {motivo}")

        corpo = self._corpo_do_template(destino=destino, aviso=aviso, template=template)
        url = f"{configuracao.whatsapp_api_base}/{configuracao.whatsapp_phone_number_id}/messages"
        cliente = self._cliente or httpx.AsyncClient(timeout=SEGUNDOS_DE_TIMEOUT)

        try:
            resposta = await cliente.post(
                url,
                json=corpo,
                headers={"Authorization": f"Bearer {configuracao.whatsapp_access_token}"},
            )
            resposta.raise_for_status()
        # NAO e `except Exception`, pela razao que o docstring de
        # `FalhaDeCanal` registra: engolir TypeError e AttributeError faria o
        # handoff sair marcado como pendente de aviso manual por causa de um
        # defeito de programacao que ninguem veria.
        except (httpx.HTTPError, OSError) as erro:
            # **Nunca loga `aviso.corpo`**: ele carrega o resumo, pela mesma
            # razao que `handoffs.resumo` e cifrado em repouso.
            log.warning(
                "notificacao.whatsapp_recusado",
                destino=destino,
                assunto=aviso.assunto,
                reason=type(erro).__name__,
            )
            raise FalhaDeCanal(f"Cloud API recusou a mensagem: {type(erro).__name__}") from erro
        finally:
            if self._cliente is None:
                await cliente.aclose()

        log.info("notificacao.whatsapp_entregue", destino=destino, assunto=aviso.assunto)

    @staticmethod
    def _corpo_do_template(*, destino: str, aviso: Aviso, template: str) -> dict[str, Any]:
        """O payload da Cloud API, no mesmo formato que `outbound/whatsapp.py` monta.

        **`aviso.corpo` nao entra, e nao e descuido.** Ele carrega o resumo --
        ate 1.500 caracteres de prosa destilada do que o lead escreveu -- e um
        template da Meta recebe parametros posicionais revisados humano por
        humano. O WhatsApp leva o aviso; quem leva o resumo e o e-mail
        (TEC-280) ou o painel. Ver a D4 do desenho, e a emenda que ela abriu
        na RN-16.2.
        """
        return {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": IDIOMA_DO_TEMPLATE},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": aviso.etiqueta},
                            {"type": "text", "text": aviso.prioridade},
                            {"type": "text", "text": aviso.link},
                        ],
                    }
                ],
            },
        }
