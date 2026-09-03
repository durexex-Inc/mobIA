"""Os gatilhos que forcam QUENTE, detectados na fala do lead.

TEC-151, RN-06.3: "pedido explicito de visita, pedido de falar com corretor,
mencao a proposta ou contrato". Pura de proposito: sem I/O, sem banco, sem
chamada paga.

**Deterministico, e nao campo novo no schema do classificador.** O campo
pegaria parafrase que regex nenhum pega, e teria sido a escolha melhor num
orcamento folgado. O orcamento nao e folgado:
`test_a_margem_do_orcamento_do_prompt_e_deliberada` fixa o teto em 655, o
liquido e 648,8 e a margem e **6,2**. O campo `recusou` da TEC-148 custou
17,6 -- tres vezes a margem inteira --, e o ritual manda perguntar "o que sai
do prompt para o novo texto entrar?" antes de subir o numero. Esta card nao
tem resposta para essa pergunta. O detector custa zero de orcamento.

**A assimetria de erro e o INVERSO do opt-out, e por isso a faixa e estrita.**
Em `optout/deteccao.py`, deixar de detectar e violacao de LGPD e detectar
demais e prejuizo comercial, entao a faixa inequivoca e generosa. Aqui:

  - Falso negativo: um lead pronto para agir nao chega ao topo da fila.
    Ruim, e recuperavel -- ele continua na conversa, o score continua
    subindo, e o proximo turno pode disparar.
  - Falso positivo: forca QUENTE PERMANENTEMENTE (a RN-06.3 diz "ate
    intervencao humana") e toca o telefone do corretor. **Nao existe tela
    para desfazer** -- a TEC-192 e a dona da intervencao humana e nao existe.
    O erro e invisivel, permanente, e custa a confianca do corretor na fila,
    que e o unico produto que a RF-06 entrega.

Permanente e sem desfazer vence recuperavel.

**O custo aceito e de recall, e esta declarado:** quem escrever "posso ver o
apartamento amanha?" nao dispara. O detector tambem nao ve o historico --
recebe o texto de um turno so --, entao "e a visita?" referindo-se a um
pedido de dois turnos atras tambem nao dispara.
"""

import re
import unicodedata

MOTIVO_VISITA = "VISITA"
MOTIVO_CORRETOR = "CORRETOR"
MOTIVO_PROPOSTA = "PROPOSTA"

# **O criterio e o VERBO DE ACAO junto do objeto, e nunca o objeto sozinho.**
# E o que faz "quero agendar visita" casar e "voces tem plantao de visita no
# fim de semana?" nao -- o segundo e fala real do corpus
# (`evals/corpus/compra.yaml:318`), e pergunta sobre horario de funcionamento.
# Mesma forma que fecha a colisao no opt-out, onde e o objeto de mensageria
# que faz "pare de me mandar mensagens" nao casar com "pare de mandar
# apartamento sem vaga".
#
# Casam em qualquer posicao da mensagem: com o verbo exigido, a posicao nao
# acrescenta risco, e exigir inicio de frase perderia "bom dia, queria
# agendar visita".
#
# A ordem desta tupla e a ordem da saida de `gatilhos_de`: duas execucoes com
# o mesmo texto devolvem a mesma tupla, e o teste pode comparar por igualdade
# em vez de por conjunto. Mesma escolha de `_CAUSA_POR_FATOR` em
# `auditoria.py`.
_TERMOS_POR_MOTIVO: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        MOTIVO_VISITA,
        (
            "agendar visita",
            "agendar uma visita",
            "agendar a visita",
            "marcar visita",
            "marcar uma visita",
            "marcar a visita",
            "remarcar visita",
            "remarcar uma visita",
            "remarcar a visita",
        ),
    ),
    (
        MOTIVO_CORRETOR,
        (
            "falar com corretor",
            "falar com um corretor",
            "falar com o corretor",
            "falar com um humano",
            "falar com uma pessoa",
            "falar com atendente",
            "falar com um atendente",
        ),
    ),
    (
        MOTIVO_PROPOSTA,
        (
            "fazer proposta",
            "fazer uma proposta",
            "enviar proposta",
            "enviar uma proposta",
            "assinar contrato",
            "assinar o contrato",
            "fechar negocio",
            "fechar o negocio",
        ),
    ),
)

_SO_LETRAS_E_ESPACO = re.compile(r"[^a-z ]+")
_ESPACOS = re.compile(r"\s+")


def _normalizar(texto: str) -> str:
    """Minusculas, sem acento, sem pontuacao, espacos colapsados.

    **E o mesmo transform de `_normalizar` em `optout/deteccao.py`, e as duas
    copias sao deliberadas.** Compartilhar acoplaria um detector comercial a
    um detector de decisao de LGPD: toda mudanca aqui -- um termo novo pedindo
    tolerancia a digito, digamos -- viraria mudanca no caminho regulado, que
    e o ultimo lugar onde se quer efeito colateral. A casa ja tem
    normalizadores por proposito e nao um compartilhado: `_normalizar_regiao`
    em `schemas.py` e `_RUIDO` em `dinheiro.py` sao outros dois.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", _SO_LETRAS_E_ESPACO.sub(" ", sem_acento)).strip()


def gatilhos_de(texto: str) -> tuple[str, ...]:
    """Os motivos da RN-06.3 que esta fala dispara. Vazio quando nenhum.

    **Tupla e nao motivo unico.** "quero fazer uma proposta e agendar visita"
    casa dois, e motivo unico exigiria regra de precedencia -- que aqui
    descarta informacao real, pelo mesmo argumento da D4 da TEC-152 contra
    uma coluna unica de causa.

    Nunca levanta. Texto sem letra nenhuma normaliza para vazio e devolve
    tupla vazia.
    """
    normalizado = _normalizar(texto)
    if not normalizado:
        return ()
    return tuple(
        motivo
        for motivo, termos in _TERMOS_POR_MOTIVO
        if any(termo in normalizado for termo in termos)
    )
