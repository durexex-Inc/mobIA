"""A guarda da lista que as outras duas guardas leem. TEC-286.

`literais_ao_lead.py` nao pode conter este teste: o pytest so coleta arquivos
`test_*.py`, entao um teste escrito la dentro nao rodaria e a lista ficaria
sem guarda nenhuma -- que e exatamente a falha silenciosa contra a qual ele
existe.
"""

from tests.unit.literais_ao_lead import LITERAIS_AO_LEAD


def test_a_lista_de_literais_nao_encolheu_sem_querer() -> None:
    """Um literal removido da lista faz as duas guardas passarem sem checa-lo.

    Nem a de acento nem a de promessa reprovam por ausencia -- elas iteram o
    que a lista tem. Sem este numero escrito a mao, tirar um texto da lista e
    uma mudanca que nada denuncia.

    Foi 17 ate a TEC-286, que acrescentou `TEXTO_DO_PEDIDO_DE_HUMANO` (o de
    dentro do horario; so a variante fora do horario estava) e os dois textos
    de encaminhamento -- tres constantes ao lead que nunca estiveram sob a
    guarda de acento. Foi 20 ate a TEC-167, que acrescentou as oito perguntas
    da data falada (`data_falada.py`).
    """
    assert len(LITERAIS_AO_LEAD) == 28
