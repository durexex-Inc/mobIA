# TEC-364 — Os eventos `ack` e `erro` e o formato dos imóveis no WebSocket do chat web

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-364](https://eduardodurieuxlopes.atlassian.net/browse/TEC-364) — épico TEC-123
**Branch:** `feat/tec-364-ack-e-erro-no-websocket`
**Origem:** RN-FE-17.4, RN-FE-17.5, RN-FE-18.1, §6.3, P-09 (SRS mobIA Frontend v1.0) · TEC-124, TEC-125, TEC-162 · destrava TEC-346, TEC-348, TEC-349

## O que já existe

A TEC-124 já confirma e já recusa, com outros nomes: `{"tipo": "recebido", "id"}` para cada mensagem aceita (inclusive a que a UNIQUE deduplicou) e `{"tipo": "erro", "motivo"}` para as recusas que não derrubam o socket. Os imóveis saem como um frame `imagem` por ficha, com uma legenda de texto pronta no formato do WhatsApp — o navegador não tem os campos para desenhar o card da TEC-349.

**Nenhum cliente consome este WebSocket**: as telas do chat (TEC-344 a TEC-353) estão todas por fazer. Trocar nomes agora não quebra ninguém.

## D1 — `ack` e `erro` com os nomes da card

Decisão do Eduardo, 26/09/2026: o contrato da card substitui o da TEC-124, sem período de convivência.

```json
{ "tipo": "ack", "messageId": "<o id que o cliente mandou>" }
{ "tipo": "erro", "codigo": "texto_longo_demais", "mensagem": "Sua mensagem passou do limite de 4096 caracteres.", "messageId": "<id>" }
```

- **`ack` confirma o id, e não o conteúdo**, como o `recebido` confirmava: o reenvio com o mesmo `messageId` é descartado pela UNIQUE e confirmado de novo — o segundo cenário da card.
- **`erro.codigo` é vocabulário fechado**, o mesmo conjunto de `motivo` de hoje: `texto_vazio`, `texto_longo_demais`, `consentimento_invalido`, `aviso_ausente`, `aviso_longo_demais`, `consentimento_nao_registrado`. `mensagem` é texto em português, com acento, que a tela pode mostrar como está; o limite citado é o do servidor (`tamanho_maximo_do_texto_do_widget`, 4096), e não os 1.000 que a TEC-346 impõe na tela — o servidor é a rede de baixo.
- **`erro.messageId` vem quando o erro é sobre uma mensagem** (as duas recusas de texto). Não está no texto da card, e existe porque sem ele o cliente não sabe qual balão marcar como `falhou` — RN-FE-17.5. As recusas de consentimento não têm mensagem e saem sem ele.
- Para isso o `id` passa a ser lido **antes** das recusas de texto. Id inválido continua fechando com 1002.

O que continua sem frame de erro, por ser cliente quebrado e não engano de uso: frame que não é JSON, tipo desconhecido, id fora do formato — 1002. Banco fora — 1011, e o `ack` nunca chega, que é o sinal para reenviar.

## D2 — Um frame por imóvel, com o card estruturado

Decisão do Eduardo, 26/09/2026. A ficha continua sendo a unidade de entrega — é por ela que a reserva em `outbound_dispatches` deduplica e que a entrega parcial é retomada (TEC-275) —, e o canal web passa a receber:

```json
{
  "tipo": "imovel",
  "kind": "ficha_1",
  "texto": "<a prosa do agente, só no primeiro; null nos outros>",
  "imovel": {
    "id": "…", "titulo": "…", "bairro": "…",
    "precoCentavos": 51646430, "condominioCentavos": 85000,
    "quartos": 3, "vagas": 2, "areaUtilM2": 98,
    "diferencial": "piscina", "foto": "https://…", "url": null
  }
}
```

**Até 3 por turno** vem da TEC-162, que já limita a apresentação. O cliente agrupa os frames `imovel` consecutivos numa fileira de cards; a §6.3 do SRS de frontend, que fala em `imoveis` dentro de `resposta`, ganha emenda.

**`foto` nulo continua saindo como `imovel`**, e não como `mensagem`: a TEC-349 pede placeholder com o bairro e os dados textuais, e só o card estruturado permite isso. **`url` é sempre nulo**: o catálogo não tem a página do imóvel no site (L1).

O WhatsApp não muda: o adaptador ignora a chave `imovel` e continua mandando a imagem com a legenda.

## Arquivos

```
src/mobia/api/routes/widget.py          # ack, erro com codigo e mensagem, id lido antes
src/mobia/domain/outbound/web.py        # o frame `imovel`
src/mobia/domain/agente/apresentacao.py # card_de(ficha)
src/mobia/domain/agente/turno.py        # payload da ficha leva `imovel` e `prosa`
docs/superpowers/specs/2026-09-23-tec-124-widget-web-via-websocket-design.md  # os três contratos
```

## Testes

- **Os dois cenários** — a mensagem aceita recebe `ack` com o mesmo `messageId`; o reenvio com o mesmo id recebe `ack` de novo e a conversa tem uma linha só.
- **Os erros** — texto vazio e longo demais saem com `codigo`, `mensagem` e `messageId`; consentimento inválido sai sem `messageId`.
- **Os imóveis** — o frame `imovel` traz o card inteiro; o primeiro leva a prosa, o segundo não; ficha sem foto sai como `imovel` com `foto: null`; o WhatsApp recebe o mesmo payload de antes.

## Lacunas declaradas

- **L1 — não há URL do imóvel.** A TEC-349 pede abrir a página do imóvel no site do tenant "quando houver URL"; o catálogo não tem a coluna, então `url` é sempre nulo e o card sempre expande no chat. Acrescentar a coluna é da importação (RN-08), não deste contrato.
- **L2 — o histórico da reconexão traz a ficha como texto.** O frame `historico` repassa o que está em `messages`, que guarda a legenda; o card estruturado só existe ao vivo. Uma visitante que recarrega a página vê as fichas antigas como balões de texto.
- **L3 — o SRS do frontend não está no repo**, como a TEC-362 e a TEC-302 declararam. O contrato veio do texto das cards TEC-364, TEC-346 e TEC-349.
