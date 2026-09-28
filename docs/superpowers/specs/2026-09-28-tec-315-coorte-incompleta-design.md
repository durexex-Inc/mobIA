# TEC-315 — Sinalizar coorte incompleta e "Ainda não medido" no funil

**Status:** implementado (28/09/2026)
**Card:** [TEC-315](https://eduardodurieuxlopes.atlassian.net/browse/TEC-315) — épico TEC-303
**Branch:** `feat/tec-315-coorte-incompleta`
**Depende de:** TEC-313 (estados padrão de tela, já implementada)

## O que existe quando a card começa

- **A TEC-313 já entrega o vocabulário e o texto.** `lib/estados.ts` (`TEXTO_SEM_FONTE = 'Ainda não medido'`), `components/estado/AindaNaoMedido.tsx` (o padrão de motivo por dois canais: `title` para o mouse e `aria-describedby` para um `span.visually-hidden`), e `lib/formato.ts::quantidadeLegivel` já troca o texto de qualquer etapa `disponivel: false` por "Ainda não medido" — a D1 do desenho da TEC-313 já registrou essa fronteira: "a TEC-315 continua dona do **comportamento** da etapa (conversão não calculada, coorte incompleta)".
- **`Funil.tsx` só formata o que o backend manda.** Não há cálculo nenhum ali: `percentual(etapa.conversaoDaAnterior)` (linha 27) imprime o número cru. Nenhuma lógica de "acima de 100%" existe em lugar nenhum do repo — confirmado por grep, "Coorte incompleta" não aparece em nenhum arquivo.
- **`lib/formato.ts:36-37` já cita esta card por nome**: "O comportamento da etapa (não calcular conversão para quem não tem fonte) continua sendo da TEC-315."

## Descoberta: as duas premissas da card não acontecem mais com dado real

Isto muda o que a card significa, e precisa ser dito antes de qualquer decisão de design.

- **A etapa `Agendado` não fica mais sem fonte.** `domain/metricas/calculo.py::montar_funil` (linha 53) tem `disponivel=True` **constante** para as seis etapas, desde a TEC-376 — a RF-11/RF-12 que a TEC-190 dizia não existir foram construídas depois, e o comentário da própria função registra: "constante desde a TEC-376, e o campo FICA... tira-lo é mudança de contrato de verdade... ele volta a valer no dia em que uma etapa nova nascer sem fonte." Ou seja: hoje nenhuma etapa vem `disponivel: false` na prática, mas o contrato (o tipo `Etapa` do frontend, e o campo em si no backend) continua permitindo, de propósito, para quando isso voltar a acontecer.
- **A conversão não pode mais passar de 100%, por construção.** A TEC-367 (`tests/integration/test_funil_monotono.py`) resolveu o defeito raiz que a TEC-190 (D10) descrevia como "coorte incompleta" — mudando a contagem para **acumulada**: alcançar uma etapa implica ter passado pelas anteriores, então a contagem nunca cresce descendo o funil, e `atual / anterior` nunca passa de 1.0. Isso vale para QUALQUER filtro, porque é propriedade da definição de "alcançar uma etapa", não um caso específico corrigido.

**Consequência prática, no molde da CA-17.1 da TEC-190** (um critério que a própria origem da card já sabia que talvez não desse para exercitar com dado real): os dois cenários do Gherkin desta card — "conversão acima de 100%" e "etapa sem fonte" — **não são reproduzíveis hoje contra o backend de verdade**. Não há como semear um banco e ver isso acontecer no navegador. A verificação possível é só de componente, com um `Etapa[]` escrito à mão.

**Isto não esvazia a card.** O tipo `Etapa` do contrato (`lib/metricas.ts`) continua sendo `number | null` para quantidade e conversão — nada no TypeScript impede um backend futuro (ou um bug de regressão na TEC-367/TEC-376) de mandar `disponivel: false` ou uma fração maior que 1. A resposta de `GET /api/v1/metricas/funil` é fronteira de sistema (API externa ao processo do Next), e validar nela é o caso exatamente previsto por "só validar em fronteira de sistema" — não é gold-plating. O que muda é que a implementação é defesa em profundidade contra uma condição hoje inatingível, não a correção de um defeito visível — e isso vai no comentário da card.

## D1 — `Funil.tsx` decide a confiabilidade da conversão sozinho, sem confiar cegamente em `conversaoDaAnterior`

Em vez de só formatar o que veio, o componente agora sabe, olhando a etapa **e a etapa anterior no array**, se a conversão é confiável:

```ts
function conversaoConfiavel(etapa: Etapa, anterior: Etapa | undefined): number | null {
  if (!etapa.disponivel || (anterior && !anterior.disponivel)) {
    return null
  }
  return etapa.conversaoDaAnterior
}
```

Isso é a mesma garantia que o backend já aplica (`_conversao` em `calculo.py`), repetida do lado de cá — de propósito. Não é confiar duas vezes na mesma regra por acidente: é o funil recusando, ele mesmo, "dividir Handoff aceito por Recomendado" se algum dia `Agendado` (ou qualquer etapa) voltar a ficar sem fonte e o backend, por bug, não zerar a conversão adjacente. A frase que já existe no desenho da TEC-190 ("um número plausível e errado") é exatamente o que isto impede, agora dos dois lados.

## D2 — "Coorte incompleta" é uma função pura nova, não uma mudança em `percentual()`

`percentual()` (`lib/formato.ts`) também formata `taxaQualificacao` e `slaHandoffCumpridoPct` em `Indicadores.tsx` — frações de um todo, sem semântica de coorte. Acoplar o aviso a `percentual()` o faria aparecer (ou exigir um parâmetro extra) em lugares que não são conversão entre etapas do funil. Por isso:

```ts
export function coorteIncompleta(valor: number | null): boolean {
  return valor !== null && valor > 1
}
```

mora ao lado de `percentual`, mas só é chamada por `Funil.tsx`.

## D3 — O aviso segue o molde de dois canais da TEC-313, não o de `FilaDoTitular`

`FilaDoTitular` (⚠ decorativo + texto sempre visível) resolve um aviso curto e autoexplicativo ("Prazo curto"). Este aviso precisa de **explicação** (a letra da card: "com explicação... backfill de `qualificado_em`, qualificação numa única mensagem"), que é frase longa demais para ficar sempre visível ao lado de cada percentual. Por isso reaproveita o padrão exato de `AindaNaoMedido` (D4 da TEC-313): `title` para o mouse e o mesmo texto por `aria-describedby` a um `span.visually-hidden`, com `useId()`. O texto curto "Coorte incompleta" fica sempre visível (é o que o Gherkin pede textualmente); a explicação mais longa é o motivo, nos dois canais.

## Testes

- `lib/formato.test.ts`: `coorteIncompleta` — `null` é falso, `1.0` é falso (100% exato não é "incompleta"), `1.0001` é verdadeiro, `40.0` é verdadeiro.
- `Funil.test.tsx`: conversão > 100% mostra o valor real + "Coorte incompleta"; conversão normal não mostra o aviso; etapa com `disponivel: false` não propaga conversão nem para ela nem a partir dela, **mesmo que o backend (por hipótese do teste) mande um número ali** — prova que `Funil.tsx` não confia cegamente.

## Verificação

**Só de componente para os dois cenários centrais** — não são reproduzíveis contra o backend real (ver a descoberta acima).

No navegador (28/09/2026, Edge headless por CDP, sessão ADMIN real): `/` mostra o funil de verdade, com `Agendado` disponível (`0`, não "Ainda não medido" — confirma que a etapa realmente ganhou fonte desde a TEC-376) e nenhuma conversão acima de 100% nos dados de dev atuais. `document.body.innerText` não contém "Coorte incompleta" em lugar nenhum — a tela real continua idêntica, como o desenho previu.

## Lacunas declaradas

- **L1 — Os dois cenários centrais do Gherkin não são exercitáveis contra dado real hoje.** A TEC-367 (contagem acumulada) e a TEC-376 (`Agendado` com fonte) resolveram, na raiz, os dois defeitos que esta card foi escrita para sinalizar na tela. A implementação é defesa em profundidade numa fronteira de API, não correção de algo visível. Mesma classe de lacuna que a CA-17.1 da TEC-190.
- **L2 — O SRS do frontend não está no repo.** RN-FE-05.1, RN-FE-05.2 e RT-FE-02 vêm do texto da card.
