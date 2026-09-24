"""A porta de saida para o CRM. TEC-180, RN-16.5.

A forma e a de `domain/notificacao/canais.py`: um `Protocol` no dominio, o
adaptador ao lado, e o `startup` do worker decidindo qual instancia entra no
`ctx`. E o que faz o quarto cenario do Gherkin -- "trocar de destino nao exige
mudanca de codigo" -- sair por construcao: a URL e configuracao, e um conector
nativo futuro e uma classe nova no mesmo `ctx`.

**Nao existe adaptador que registra e nao entrega.** Sem `CRM_WEBHOOK_URL`,
`ctx["crm"]` e `None`, e tanto o job quanto a varredura saem cedo. O repo ja
tomou essa decisao duas vezes e nas duas APAGOU o dubles -- o `EmailRegistrado`
na TEC-280 e o registrador de WhatsApp na TEC-281 --, com a razao escrita em
`canais.py`: manter o adaptador que descarta em silencio preserva o caminho de
volta para ele. Ver a D1 do desenho.
"""

import uuid
from typing import Any, Protocol

# As tres tentativas da RN-16.5.
#
# **Constante, e nao configuracao.** A regra fixa tres; um `.env` que mudasse
# este numero seria um jeito de viola-la sem tocar em codigo revisavel. O que e
# configuravel e a BASE do backoff (`crm_backoff_base_segundos`), e so porque o
# teste precisa injetar centesimos de segundo -- mesmo argumento que
# `indicador_de_digitacao_apos_segundos` registra em `app/config.py`.
MAX_TENTATIVAS = 3


class FalhaDeExportacao(RuntimeError):
    """O CRM nao aceitou o payload.

    Existe pelo mesmo motivo que `FalhaDeCanal` em `notificacao/canais.py`:
    o job precisa distinguir "o destino falhou, retente" de defeito de
    programacao, que deve subir. Sem ela, um `except Exception` no job
    engoliria TypeError e AttributeError como se fossem indisponibilidade do
    CRM -- e o handoff sairia marcado como "falhou tres vezes" por um bug que
    ninguem veria, com o alerta apontando para o lado errado.

    **Cobre tudo o que nao e 2xx**, inclusive timeout e erro de rede: do nosso
    lado sao o mesmo desfecho, e a rodada seguinte da varredura tenta de novo.

    **`motivo` existe porque o nome da classe nao diria nada aqui.** A regra da
    TEC-222 manda gravar em coluna duravel so o nome da excecao, e ela existe
    para barrar prosa de terceiro -- a mensagem que o SDK do provedor escreveu,
    que pode carregar URL, corpo ou PII. Se `crm_ultimo_erro` guardasse o nome
    da classe, guardaria `FalhaDeExportacao` em 100% das falhas, porque TODAS
    passam por aqui: uma coluna com um valor so nao distingue "o CRM esta fora"
    de "o CRM recusou o que mandamos", que e a unica pergunta que ela responde.

    O que a preenche e este campo, e a garantia que o torna seguro e dos
    SITIOS QUE LEVANTAM, nao desta classe: cada um monta um token curto e
    proprio -- o nome da classe da excecao do httpx, ou `HTTP <status>`. Nunca
    `str(excecao_de_terceiro)`. Quem acrescentar um sitio novo de `raise`
    mantem essa garantia ou quebra a regra da TEC-222 sem nenhum gate notar.
    """

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class CrmPort(Protocol):
    nome: str

    async def exportar(self, *, handoff_id: uuid.UUID, payload: dict[str, Any]) -> None:
        """Entrega o lead. Levanta `FalhaDeExportacao` se o destino nao aceitar.

        `handoff_id` vem separado apesar de tambem estar dentro de `payload`:
        e a chave de idempotencia que o adaptador poe no cabecalho, e obrigar
        cada adaptador a saber qual campo do dicionario carrega essa chave
        acopla o transporte ao formato. Ver a D6 do desenho.
        """
        ...
