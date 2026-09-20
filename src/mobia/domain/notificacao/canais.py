"""Os canais da RN-16.2 -- e a razao de nenhum deles entregar ainda.

TEC-177, D4.

**Os dois adaptadores registram e nao entregam, e isso nao e provisorio por
desleixo: e provisorio por dependencia externa.**

O e-mail nao tem infraestrutura neste projeto -- nenhuma dependencia no
`pyproject.toml`, nenhum SMTP, nenhum provedor -- e escolher um foi
deliberadamente adiado em 12/09/2026.

O WhatsApp esbarra na Meta: a Cloud API recusa mensagem livre passadas 24h da
ultima fala do destinatario (codigo 131047, que `outbound/whatsapp.py` ja
trata), e o corretor esta SEMPRE fora dessa janela porque nao conversa com o
numero da empresa. Entregar exige um template aprovado, que e cadastro
externo com prazo proprio.

**Uma forma so para os dois** porque a regra os trata igual: "falha em um dos
canais nao cancela o outro" so e escrevivel uma vez se os dois tiverem a
mesma assinatura.
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
    """Base dos dois adaptadores de hoje. Nunca levanta, nunca entrega."""

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
