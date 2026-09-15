"""A informacao nova que o follow-up entrega, montada sem tocar banco.

TEC-184, RN-13.2. Modulo sem I/O de proposito -- mesmo molde de
`handoff/vocabulario.py`, `corretores/vocabulario.py` e `apresentacao.py`: e o
que permite testar a regra em `tests/unit/`, sem Postgres de pe.
`repositorio.py` (com I/O) importa daqui, nunca o contrario. Quem consulta o
banco e decide gravar e o job (Task 6); aqui so se escolhe a novidade e se
monta o texto.

**A ordem de precedencia mora aqui, e nao no job**: queda de preco vence
imovel novo, que vence o convite. E regra da card, nao orquestracao, e no job
ela ficaria misturada com guardas, laco e entrega.

Todo texto daqui sai para o lead e e ASCII sem acento, como em
`apresentacao.py`.
"""

import uuid
from dataclasses import dataclass

from mobia.domain.agente.apresentacao import (
    SEPARADOR_DA_PROSA,
    Ficha,
    legenda_de,
    prosa_que_cabe,
    reais_de,
)


@dataclass(frozen=True, slots=True)
class QuedaDePreco:
    """Um imovel que o lead VIU e que hoje custa menos. TEC-184, D2.

    `preco_antes_centavos` sai de `recomendacoes.preco_centavos`, que e o
    numero que saiu na ficha -- fato historico, nao copia do preco do imovel
    (ver o comentario daquela coluna, TEC-275 D3). E e por isso que esta card
    nao precisa de tabela de historico de preco.
    """

    imovel_id: uuid.UUID
    preco_antes_centavos: int
    preco_agora_centavos: int


# O fallback da card quando nao ha novidade nenhuma. **Nao e saudacao**: a
# RN-13.2 proibe "oi, tudo bem?" solto, e o que separa um do outro e pedir
# algo concreto. A regra de negocio oferece "ou tarefa para o corretor" como
# alternativa, mas quem notifica corretor e a TEC-280/281, ainda abertas --
# entao este e o unico caminho vivo (L2 do desenho).
CONVITE_PARA_AGENDAR = "Quer agendar uma visita para conhecer algum dos imóveis que vimos?"


def linha_da_queda(queda: QuedaDePreco) -> str:
    """`De R$ 620.000 por R$ 590.000`.

    Os dois lados por `reais_de`, que trunca para BAIXO -- a mesma razao que
    ela ja documenta, e que aqui vale duas vezes: arredondar o preco NOVO para
    cima cota ao lead acima do real, e arredondar o ANTIGO para baixo encolhe
    a queda que a mensagem existe para anunciar.
    """
    return f"De {reais_de(queda.preco_antes_centavos)} por {reais_de(queda.preco_agora_centavos)}"


def _com_prefixo(corpo: str, prefixo: str | None) -> str:
    """O corpo com a prosa do modelo na frente, dentro do teto de 600.

    Delega a `prosa_que_cabe` de `apresentacao.py`: mesma aritmetica (separador,
    corte na ultima fronteira de palavra, reticencia), mesma prioridade da D14
    da TEC-162 -- estourado o teto, o que cede e a prosa, nunca o corpo. Duas
    copias da mesma regra dos 600 e o defeito que a TEC-146 gastou uma card
    inteira consertando.
    """
    if not prefixo:
        return corpo
    prosa = prosa_que_cabe(prefixo, len(corpo))
    if not prosa:
        return corpo
    return f"{prosa}{SEPARADOR_DA_PROSA}{corpo}"


def texto_do_followup(
    *, ficha: Ficha | None, queda: QuedaDePreco | None, prefixo: str | None = None
) -> str:
    """A mensagem inteira: a novidade de maior precedencia, com a prosa na frente.

    **Nunca devolve string vazia.** Sem ficha e sem queda sobra o convite, e e
    isso que torna a "mensagem vazia" da card IMPOSSIVEL em vez de bloqueada
    (D6). Nao ha envio a barrar porque nao ha como produzir mensagem sem
    conteudo.

    **Com `queda`, a `ficha` tem de ser a do imovel que caiu.** Mostrar o
    preco de um imovel com a ficha de outro e um erro que o lead nao tem como
    perceber, entao ele levanta aqui em vez de sair pelo WhatsApp.
    """
    if queda is not None:
        if ficha is None or ficha.id != queda.imovel_id:
            raise ValueError("a ficha da queda tem de ser a do imovel que caiu")
        corpo = f"{legenda_de(ficha)}\n{linha_da_queda(queda)}"
        return _com_prefixo(corpo, prefixo)
    if ficha is not None:
        return _com_prefixo(legenda_de(ficha), prefixo)
    return _com_prefixo(CONVITE_PARA_AGENDAR, prefixo)
