"""A fronteira do acento, no sentido que a TEC-267 fixou.

Substitui as cinco assercoes `.isascii()` que guardavam a politica anterior.

**Esta guarda erra de menos, nunca de mais, e e isso que a torna aceitavel.**
A versao obvia -- "todo literal ao lead tem ao menos um caractere acentuado"
-- e FALSA: `m2`, `Destaque:` e `De {} por {}` nao tem vogal que receba
acento, e excetua-las viraria uma lista a mao que reprova texto certo. Esta
aqui tem a assimetria oposta: uma palavra faltando na lista so deixa de pegar
um caso, nunca reprova um caso correto.
"""

import pytest

from mobia.domain.agente.apresentacao import RESSALVA_DE_ESTIMATIVA
from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO
from mobia.domain.agente.turno import (
    TEXTO_DA_BUSCA_INCONCLUSIVA,
    TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
    TEXTO_DO_FILTRO_AJUSTADO,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
    TEXTO_SEM_RESULTADO_APOS_AMPLIAR,
)
from mobia.domain.followup.mensagem import CONVITE_PARA_AGENDAR
from mobia.domain.moderacao.port import (
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
)
from mobia.domain.notificacao.envio import TEXTO_DA_JANELA_HUMANA
from mobia.domain.optout.deteccao import TEXTO_DA_CONFIRMACAO_DE_OPTOUT
from mobia.workers.jobs.process_message import TEXTO_DO_AVISO_DE_ERRO

# As formas sem acento que o dominio usa de fato. Nao e o portugues inteiro:
# e a lista das palavras que apareciam nos literais desta card, mais as que
# um texto de imobiliaria escreve toda hora.
#
# " ja " e " mes " tem espaco nas duas pontas de proposito, e nao so ao
# final: "ja " (so com espaco a direita) casava dentro de "veja se" -- a
# palavra "veja" termina em "ja" e o espaco que vem depois do "se" fechava o
# padrao por acidente. "mes" sem espaco casava dentro de "mesmo"/"mesa". Os
# dois foram encontrados rodando esta guarda contra os 15 literais reais
# antes de commitar; sem o espaco nas duas pontas, cada um reprovava um
# literal certo.
FORMAS_SEM_ACENTO = (
    "voce",
    "nao",
    "imovel",
    "imoveis",
    "regiao",
    "preco",
    "condominio",
    "criterio",
    "ultima",
    "sabado",
    "horario",
    "tecnico",
    "informacao",
    "opcoes",
    "interrogatorio",
    "tambem",
    "alem",
    " ja ",
    "e so",
    " mes ",
    "area",
)

LITERAIS_AO_LEAD = (
    TEXTO_DA_IDENTIFICACAO,
    TEXTO_DA_BUSCA_INCONCLUSIVA,
    TEXTO_SEM_RESULTADO_APOS_AMPLIAR,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
    TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    TEXTO_DO_FILTRO_AJUSTADO,
    CONVITE_PARA_AGENDAR,
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
    TEXTO_DA_JANELA_HUMANA,
    TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
    TEXTO_DO_AVISO_DE_ERRO,
    RESSALVA_DE_ESTIMATIVA,
)


@pytest.mark.parametrize("texto", LITERAIS_AO_LEAD)
def test_nenhum_literal_ao_lead_tem_forma_sem_acento(texto: str) -> None:
    """A TEC-267 fixou que o texto que o lead le e portugues acentuado."""
    minusculo = texto.lower()
    achadas = [forma for forma in FORMAS_SEM_ACENTO if forma in minusculo]
    assert not achadas, f"{achadas} em {texto!r}"


def test_a_lista_de_literais_nao_encolheu_sem_querer() -> None:
    """Guarda da guarda: um literal removido da tupla acima faria o teste de
    cima passar sem checar nada, e ninguem notaria."""
    assert len(LITERAIS_AO_LEAD) == 15
