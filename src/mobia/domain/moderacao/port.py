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


# O vocabulario e derivado clausula a clausula do que cada prompt de sistema ja
# manda bloquear, e nao de uma taxonomia inventada aqui. Por isso as duas
# listas diferem: `OFENSA` (ofensa ao lead) so a saida bloqueia -- o corpus
# registra isso em `entrada-libera-ofensa-atendente` --, e `VIOLENCIA`
# (incitacao) so a entrada nomeia.
#
# `NEGOCIACAO` e da TEC-141. Sem ela, o modelo ficaria sem palavra legal para
# um bloqueio que aquela card acabou de instruir, e responderia fora do
# protocolo exatamente no caso novo.
CATEGORIAS_POR_DIRECAO: dict[Direcao, frozenset[str]] = {
    Direcao.ENTRADA: frozenset({"DISCRIMINACAO", "AMEACA", "ASSEDIO", "VIOLENCIA"}),
    Direcao.SAIDA: frozenset(
        {"DISCRIMINACAO", "AMEACA", "ASSEDIO", "OFENSA", "ACONSELHAMENTO", "NEGOCIACAO"}
    ),
}

# Fracasso do protocolo, nao categoria do dominio: o modelo bloqueou e o rotulo
# nao foi reconhecido. Fica FORA de `CATEGORIAS_POR_DIRECAO` de proposito --
# oferecer a palavra ao modelo seria oferecer a saida facil no lugar de decidir.
CATEGORIA_OUTRO = "OUTRO"


@dataclass(frozen=True)
class Veredito:
    """Frozen: o veredito atravessa o turno e nao e reescrito no caminho."""

    bloqueado: bool
    motivo: str
    # `None` **e** o veredito liberado: nao ha categoria de liberacao a
    # inventar, e um valor sentinela como "NENHUMA" criaria uma categoria que
    # nunca vai para a auditoria e que todo leitor teria que aprender a ignorar.
    categoria: str | None = None


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
