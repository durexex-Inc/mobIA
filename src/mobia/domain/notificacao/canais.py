"""Os canais da RN-16.2.

TEC-177, D4.

**Os dois adaptadores entregam.** O e-mail por SMTP desde a TEC-280
(`domain/outbound/email.py`); o WhatsApp por template aprovado desde a
TEC-281 (`domain/outbound/whatsapp_notificacao.py`). Ate aquela card o
WhatsApp so registrava, e o registrador foi APAGADO junto com ela -- mesma
decisao que a TEC-280 tomou com o `EmailRegistrado`, e pela mesma razao:
manter o adaptador que descarta em silencio preserva o caminho de volta
para ele.

O WhatsApp esbarra na Meta e continua esbarrando: a Cloud API recusa mensagem
livre passadas 24h da ultima fala do destinatario (codigo 131047, que
`outbound/whatsapp.py` ja trata), e o corretor esta SEMPRE fora dessa janela
porque nao conversa com o numero da empresa. Entregar exige template
aprovado, que e cadastro externo com prazo proprio -- por isso o nome do
template e configuracao, e sem ele o canal falha alto em vez de tentar texto
livre que seria recusado de qualquer forma.

**Uma forma so para os dois** continua valendo: a porta ainda e uma so, e e
por isso que o orquestrador trata os dois igual. Desde a TEC-281 ela passa um
`Aviso` em vez de `(assunto, corpo)` -- o e-mail le a prosa, o WhatsApp le os
campos estruturados, e nenhum dos dois precisa saber do outro.
"""

from typing import Protocol

from mobia.domain.notificacao.mensagem import Aviso


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

    async def enviar(self, *, destino: str, aviso: Aviso) -> None: ...
