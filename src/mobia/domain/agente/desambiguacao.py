"""As decisoes do TEC-135, isoladas de banco, modelo e entrega.

Duas funcoes puras. O turno faz I/O; o que ele decide, decide aqui.
"""

from datetime import datetime
from decimal import Decimal

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao


def deve_desambiguar(confianca: Decimal, desambiguado_em: datetime | None) -> bool:
    """Se este turno deve perguntar em vez de responder.

    Duas condicoes, e as duas importam. A confianca abaixo do limiar diz que o
    palpite nao e confiavel; o marcador vazio diz que este episodio de
    ambiguidade ainda nao gastou a sua pergunta. Com o marcador preenchido o
    agente segue com `INDEFINIDA` -- o ticket e explicito em que ambiguidade
    persistente nao vira insistencia.
    """
    return confianca < LIMIAR_DE_DESAMBIGUACAO and desambiguado_em is None


def intencao_efetiva(intencao: Intencao, confianca: Decimal) -> Intencao:
    """A intencao que se pode usar para rotear, dado o quanto ela e confiavel.

    `conversation_intent` guarda o que o classificador devolveu, sem edicao --
    e desse par (palpite, confianca) que a TEC-210 precisa para medir o limiar.
    Quem consome nao quer o palpite cru: abaixo do limiar, "COMPRA com 0,45" e
    operacionalmente `INDEFINIDA`, e e por aqui que o TEC-136 e o TEC-137 leem.
    """
    if confianca < LIMIAR_DE_DESAMBIGUACAO:
        return Intencao.INDEFINIDA
    return intencao
