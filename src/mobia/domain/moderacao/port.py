from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Direcao(StrEnum):
    """De que lado o texto veio, porque o criterio nao e o mesmo.

    Na ENTRADA julga-se a fala de um estranho, e a pergunta e o que nao pode
    entrar no contexto do agente. Na SAIDA julga-se o que a imobiliaria vai
    dizer em nome proprio, e o criterio e mais estrito: o mesmo texto pode ser
    toleravel vindo do lead e inaceitavel vindo da empresa.
    """

    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"


class ModeracaoIndisponivel(RuntimeError):
    """Nao deu para moderar. **Nao** e o mesmo que "moderou e liberou".

    Quem trata esta excecao decide de forma assimetrica: na entrada o turno
    segue (a fala do lead ja esta cifrada no banco, e negar atendimento por um
    servico caido pune o inocente); na saida a entrega e impedida, porque
    entregar texto nao moderado e o risco que este subsistema existe para
    fechar.
    """


@dataclass(frozen=True)
class Veredito:
    """Frozen: o veredito atravessa o turno e nao e reescrito no caminho."""

    bloqueado: bool
    motivo: str


class ModeradorPort(Protocol):
    async def moderar(self, texto: str, *, direcao: Direcao) -> Veredito: ...


# Curto, neutro, e nao explica o criterio -- explicar ensina a contornar. Nao
# acusa o lead: falso positivo em moderacao e comum, e o legitimo que caiu nele
# nao pode ser tratado como infrator.
TEXTO_DA_RECUSA_DE_ENTRADA = (
    "Nao consigo seguir com essa mensagem. Se quiser, me diga de outro jeito o "
    "que voce procura em imovel que eu ajudo."
)

# Nao finge ser resposta. O lead precisa perceber que algo nao saiu, senao
# espera por uma resposta que nao vem -- e o evento no log leva um humano ate
# ali.
TEXTO_NEUTRO_DE_SAIDA = (
    "Tive um problema para montar a resposta agora. Pode repetir sua ultima "
    "mensagem que eu tento de novo?"
)
