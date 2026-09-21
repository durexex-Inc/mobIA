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
#
# Nomear o criterio LEGITIMO (TEC-142) e o que satisfaz a card sem quebrar
# nenhuma das duas regras acima: diz o que e aceito em vez do que foi
# recusado. Por isso continua sendo UM texto para todas as categorias -- um
# texto por categoria contaria ao lead qual filtro disparou.
TEXTO_DA_RECUSA_DE_ENTRADA = (
    "Não consigo seguir com essa mensagem. A busca aqui é feita por critério "
    "do imóvel -- região, preço, quartos, vagas. Me diga o que você procura "
    "assim que eu ajudo."
)

# TEC-295, D4. Kind proprio, e nao o default `KIND_DA_RESPOSTA` ("reply") de
# `_entregar_texto_fixo` -- mesmo padrao de `KIND_DA_CONFIRMACAO_DE_OPTOUT`
# (`domain/optout/deteccao.py`) e `KIND_DA_JANELA_HUMANA`, que o docstring de
# `domain/outbound/kinds.py` (linhas 3-10) registra: "o kind vive no modulo
# que possui o comportamento, e quem precisa dele importa de la". A recusa
# usando o "reply" generico ERA a anomalia, so que benigna ate a TEC-295: as
# duas nunca saiam na mesma mensagem, entao a UNIQUE (message_id, kind) de
# `outbound_dispatches` nunca via as duas juntas. Com a continuacao da D4, a
# recusa e a resposta podem sair na MESMA mensagem, e reusar "reply" faria a
# segunda ser suprimida como reentrega da primeira -- silenciosamente.
KIND_DA_RECUSA_DE_ENTRADA = "recusa_de_entrada"

# Nao finge ser resposta. O lead precisa perceber que algo nao saiu, senao
# espera por uma resposta que nao vem -- e o evento no log leva um humano ate
# ali.
TEXTO_NEUTRO_DE_SAIDA = (
    "Tive um problema para montar a resposta agora. Pode repetir sua última "
    "mensagem que eu tento de novo?"
)
