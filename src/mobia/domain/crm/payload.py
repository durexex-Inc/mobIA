"""O JSON versionado que o CRM recebe. TEC-180, RN-16.5.

Modulo sem I/O, como `dossie.py` e `contingencia.py`: monta um dicionario a
partir de fatos que ja vieram do banco. O corte existe para que o formato seja
testavel sem rede e sem banco -- e o formato e o que um consumidor externo
passa a depender, entao e o que mais precisa de teste.

**Reusa o `Dossie`, e nao le o banco por conta propria.** Ele ja e o retrato do
lead que `handoff/repositorio.py` monta para o resumo, com a qualificacao, o
score e os imoveis apresentados. Uma segunda coleta aqui seria uma segunda
fonte para os mesmos fatos -- o defeito que a TEC-146 gastou uma card inteira
consertando.

**Valor em CENTAVOS, e nao a prosa de `reais()`.** O leitor aqui e um programa:
`"R$ 600.000"` obrigaria o CRM a fazer parsing de moeda em portugues para
comparar dois numeros. `reais()` existe para o corretor ler, e continua sendo
so isso.
"""

import uuid
from typing import Any

from mobia.domain.handoff.dossie import Dossie, isoformat_ou_none

# A versao do FORMATO, nao do software. Sobe quando um consumidor que entende a
# versao anterior deixaria de entender esta -- campo removido ou com
# significado novo. Acrescentar campo opcional nao sobe: o consumidor que nao o
# conhece o ignora, que e a razao de a RN-16.5 pedir versao em primeiro lugar.
VERSAO_DO_PAYLOAD = 1


def montar(
    *,
    handoff_id: uuid.UUID,
    dossie: Dossie,
    resumo: str | None,
    resumo_fallback: bool,
) -> dict[str, Any]:
    """O payload da RN-16.5: dados do lead, qualificacao e resumo.

    `resumo` e `None` em dois casos que o consumidor nao consegue distinguir e
    nao precisa: o resumo ainda nao foi gerado, ou nao pode ser decifrado. Os
    dois significam "nao tenho o texto", e a exportacao acontece do mesmo jeito
    -- ver a D10 do desenho, que e o mesmo argumento da D2 da TEC-177 sobre a
    notificacao: o handoff sem resumo e o que mais precisa chegar a uma pessoa.

    `resumo_fallback` vai junto porque muda o que o texto E: com ele verdadeiro,
    o resumo nao foi redigido por modelo nenhum, foi montado do template de
    contingencia (RN-15.4). Quem for pontuar a qualidade do lead no CRM precisa
    saber disso, e o texto nao o diz de forma legivel por programa.

    **Sem nome do lead**: nenhuma tabela deste sistema guarda um -- ver a
    emenda E-02 da RN-15.1 e o comentario do campo (a) em `Dossie`.
    """
    return {
        "versao": VERSAO_DO_PAYLOAD,
        "handoff_id": str(handoff_id),
        "lead": {
            "canal": dossie.canal,
            "conversa": dossie.conversa,
            "primeira_mensagem_em": isoformat_ou_none(dossie.primeira_mensagem_em),
            "mensagens_do_lead": dossie.mensagens_do_lead,
        },
        "qualificacao": {
            "intencao": dossie.intencao,
            "faixa_min_centavos": dossie.faixa_min_centavos,
            "faixa_max_centavos": dossie.faixa_max_centavos,
            "regiao": dossie.regiao,
            "tipo_imovel": dossie.tipo_imovel,
            "quartos": dossie.quartos,
            "vagas": dossie.vagas,
            "urgencia": dossie.urgencia,
            "forma_pagamento": dossie.forma_pagamento,
            "tem_imovel_para_vender": dossie.tem_imovel_para_vender,
            "score_total": dossie.score_total,
            "temperatura": dossie.temperatura,
        },
        "imoveis_apresentados": [
            {
                "codigo": imovel.codigo,
                "preco_centavos": imovel.preco_centavos,
                # Qual preco e `preco_centavos`: "venda" ou "aluguel". Vai
                # junto pela mesma razao que `ImovelApresentado` o carrega --
                # um imovel pode ter os dois precos, e um numero sem rotulo
                # poria preco de venda no registro de um lead que quer alugar.
                "tipo_de_preco": imovel.tipo_de_preco,
                "reacao": imovel.reacao,
                "motivo_descarte": imovel.motivo_descarte,
            }
            for imovel in dossie.imoveis
        ],
        "handoff": {
            "gatilho": dossie.gatilho,
            "etiqueta": dossie.etiqueta,
            "prioridade": dossie.prioridade,
            "criado_em": isoformat_ou_none(dossie.criado_em),
        },
        "resumo": resumo,
        "resumo_fallback": resumo_fallback,
    }
