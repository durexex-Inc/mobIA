"""O vocabulario de `messages.channel`. TEC-124.

Ate esta card o unico valor da coluna era a string `"whatsapp"`, escrita a mao
no default de `IngestionService.ingest`. O canal web precisa de um segundo
valor, e um segundo literal solto seria o primeiro passo para tres grafias do
mesmo canal.

**Minusculo, e nao `WEB` como a card escreve.** A coluna ja esta povoada com
`whatsapp` desde a TEC-122; um valor maiusculo ao lado faria toda consulta por
canal depender de caixa, e o primeiro `WHERE channel = 'web'` escrito de
memoria sairia vazio sem erro nenhum. A divergencia esta no comentario da
card.

**Sem CHECK no banco, ao contrario de `role` e `direction` (TEC-223).** La o
vocabulario esta fechado e um literal errado burla filtro em SQL cru. Aqui ele
ainda cresce -- TEC-131 e TEC-132 podem trazer mais -- e o custo de errar e
outro: canal sem adaptador nao passa despercebido, o roteador levanta.
"""

CANAL_WHATSAPP = "whatsapp"
CANAL_WEB = "web"

# O "de" do canal web. Nao ha numero de origem, e a coluna precisa de valor:
# `indicador_de_digitacao` desiste cedo quando `recipient_external_id` e nulo,
# e `_avisar_lead_da_janela_humana` le esse campo como o remetente do canal.
REMETENTE_DO_WIDGET = "widget"

# Quem recebe reengajamento (RF-13). **Allowlist, e nao `!= CANAL_WEB`**:
# canal novo nasce de fora e entra quando alguem decidir que ele tem para onde
# empurrar mensagem. O web nao tem: um follow-up de 24h numa sessao de
# navegador vira linha em `followups` marcada como enviada e texto que a
# visitante so veria se voltasse por conta propria -- caso em que ela nao
# precisava do follow-up.
CANAIS_COM_REENGAJAMENTO: tuple[str, ...] = (CANAL_WHATSAPP,)
