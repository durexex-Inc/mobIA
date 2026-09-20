"""Os canais da RN-16.2.

TEC-177, D4.

**Os dois adaptadores ja nao tem o mesmo desfecho.** Desde a TEC-280 o
e-mail entrega, por SMTP -- o adaptador `EmailSmtp` vive em
`domain/outbound/email.py`. O WhatsApp continua so registrando, e isso nao e
provisorio por desleixo: e provisorio por dependencia externa.

O WhatsApp esbarra na Meta: a Cloud API recusa mensagem livre passadas 24h da
ultima fala do destinatario (codigo 131047, que `outbound/whatsapp.py` ja
trata), e o corretor esta SEMPRE fora dessa janela porque nao conversa com o
numero da empresa. Entregar exige um template aprovado, que e cadastro
externo com prazo proprio.

**Uma forma so para os dois** continua valendo: a porta ainda e uma so, e e
por isso que o orquestrador trata os dois igual.
"""

from typing import Protocol

import structlog

log = structlog.get_logger(__name__)


class FalhaDeCanal(RuntimeError):
    """O canal nao aceitou a mensagem.

    Existe para o orquestrador distinguir "este canal falhou" de um defeito de
    programacao, que deve subir. Sem ela, um `except Exception` no
    orquestrador engoliria TypeError e AttributeError como se fossem falha de
    entrega, e o handoff sairia marcado como pendente de aviso manual por um
    bug que ninguem veria.
    """


class CanalDeNotificacaoPort(Protocol):
    nome: str

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None: ...


class _CanalQueRegistra:
    """Base do adaptador de WhatsApp, unico que ainda so registra. Nunca levanta, nunca entrega."""

    nome = ""
    motivo = ""

    async def enviar(self, *, destino: str, assunto: str, corpo: str) -> None:
        # **Nunca loga `corpo`**: ele carrega o resumo, que e prosa destilada
        # do que o lead escreveu -- a mesma razao pela qual `handoffs.resumo`
        # e cifrado em repouso. `destino` e `assunto` entram porque sao o que
        # permite saber se o roteamento esta certo.
        log.info(
            "notificacao.nao_entregue",
            canal=self.nome,
            destino=destino,
            assunto=assunto,
            motivo=self.motivo,
        )


class WhatsAppRegistrado(_CanalQueRegistra):
    nome = "whatsapp"
    motivo = "sem template aprovado pela Meta para mensagem fora da janela de 24h"
