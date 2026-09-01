"""Deteccao do pedido de opt-out, e o texto que confirma ao lead.

RN-14.1 (SRS v1.0) lista "sair", "parar", "nao quero mais" e "descadastrar"
como palavras-chave. Aplicar isso como substring em qualquer posicao silencia
lead legitimo -- "podemos parar por aqui hoje?", "quero sair do aluguel e
comprar" -- e o erro e invisivel e permanente: o lead so ve o silencio.

Dai as duas faixas. A assimetria e o INVERSO da TEC-257: la marcar de mais era
o erro perigoso; aqui deixar de detectar um opt-out e violacao de LGPD e
detectar demais e prejuizo comercial. Por isso a faixa inequivoca e generosa e
so a ambigua e estrita.
"""

import re
import unicodedata

# Casam em qualquer posicao da mensagem. Cada termo carrega o objeto de
# mensageria, e e o objeto que fecha a colisao. "pare de me mandar mensagens"
# nao casa com "pare de mandar apartamento sem vaga". "nao quero mais receber
# mensagens" nao casa com "nao quero mais receber apartamento sem vaga". Por
# isso a posicao nao importa e o recall vale mais.
_TERMOS_INEQUIVOCOS: tuple[str, ...] = (
    "descadastrar",
    "descadastre",
    "remover meu contato",
    "nao quero mais receber mensagens",
    "nao quero mais receber mensagem",
    "nao quero mais receber nada",
    "pare de me mandar mensagens",
    "pare de me mandar mensagem",
    "pare de mandar mensagens",
    "pare de mandar mensagem",
    "nao me mande mais mensagens",
    "nao me mande mais mensagem",
    "nao me envie mais mensagens",
)

# Casam SO quando sao a mensagem inteira normalizada. Todos aparecem em fala
# normal de quem procura imovel, e a mensagem de uma palavra so e o padrao real
# de quem quer sair.
_TERMOS_AMBIGUOS: frozenset[str] = frozenset(
    {
        "sair",
        "parar",
        "pare",
        "stop",
        "cancelar",
        "cancela",
        "me tira da lista",
        "me tire da lista",
        "nao quero mais",
    }
)

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    Sem isso "PARAR!" e "Parar" escapariam da faixa estrita, que compara a
    mensagem inteira -- e sao exatamente a forma que um lead irritado escreve.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", sem_acento)).strip()


def pediu_optout(texto: str) -> bool:
    """O lead pediu para parar de receber mensagens.

    Deterministico e sem chamada paga: uma decisao de LGPD nao pode depender de
    um provedor estar de pe.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return False
    if normalizado in _TERMOS_AMBIGUOS:
        return True
    return any(termo in normalizado for termo in _TERMOS_INEQUIVOCOS)


# Mora aqui, e nao em `turno.py`, pelo mesmo motivo que
# `TEXTO_DA_RECUSA_DE_ENTRADA` mora no modulo de moderacao: o texto pertence ao
# assunto, nao ao orquestrador que o entrega.
TEXTO_DA_CONFIRMACAO_DE_OPTOUT = (
    "Pronto, não vou mais te enviar mensagens. Se mudar de ideia, é só falar "
    "com a nossa equipe. Obrigado pelo contato!"
)
