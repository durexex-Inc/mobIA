# TEC-316 — Manter os filtros do funil na URL, com o filtro por corretor desabilitado

**Status:** implementado (28/09/2026)
**Card:** [TEC-316](https://eduardodurieuxlopes.atlassian.net/browse/TEC-316) — épico TEC-303
**Branch:** `feat/tec-316-filtros-do-funil-na-url`
**Relaciona-se a:** TEC-166 (não desbloqueia o filtro — ver a descoberta abaixo)

## O que já existe quando a card começa

A maior parte da regra de negócio desta card **já foi entregue pela TEC-190**, que implementou o funil inteiro de uma vez:

- **Os cinco filtros já vivem na URL.** `app/(painel)/page.tsx::filtrosDaUrl` lê `de`, `ate`, `canal`, `intencao`, `temperatura`, `corretorId` de `searchParams`; `Filtros.tsx` é um `<form method="get">` sem JavaScript; `urlDoRecorte` remonta a URL do recorte atual para o "tentar de novo" e, por construção, é a mesma URL que reproduz a visão — o cenário 1 do Gherkin ("outra gerente abre o link copiado") já vale hoje, sem nada novo.
- **Período padrão de 30 dias já existe** (`lib/periodo.ts::periodoPadrao`), com teste próprio.
- **O filtro por corretor já é recusado pelo backend com 422** (`domain/metricas/filtros.py::montar_recorte`), e o texto do erro já é estruturado para ir ao lado do campo (`CAMPOS_COM_MENSAGEM` já inclui `corretorId`).

O que falta, e é o que esta card entrega:

## Descoberta: a TEC-166 não desbloqueia nada aqui

A dependência da card diz "relaciona-se à TEC-166 (habilita o filtro por corretor)" — mas a TEC-166, **já implementada**, aloca corretor ao **agendamento** (RF-11: especialidade, região, capacidade diária), não ao **handoff**. `domain/metricas/filtros.py:78-90` já documenta isso por extenso: `handoffs.corretor_id` continua nula em toda linha, porque é outra tabela que a TEC-166 nunca tocou. O filtro do funil continua recusado com 422, exatamente como antes — a TEC-166 não muda o estado desta card. Fica dito para quem ler a dependência e presumir o contrário.

## D1 — Período padrão corrigido de 29 para 30 dias de volta a partir de hoje

`periodoPadrao` (TEC-190) calculava `ate - 29 dias` como `de`, dando 30 dias corridos incluindo hoje — mas o cenário 2 do Gherkin **desta** card é explícito: "hoje é 24/09/2026 ⟹ o período exibido vai de **25/08/2026** a 24/09/2026", que são 31 dias corridos (`ate - 30 dias`). É uma diferença de um dia entre a prosa "últimos 30 dias" e o exemplo escrito por extenso na mesma card — a mesma classe de imprecisão que este repo já viu entre RN e Gherkin outras vezes. O Gherkin é o critério de aceite verificável; a implementação passa a bater com ele.

**Isto muda o comportamento de uma função já testada e em produção desde a TEC-190.** Fica registrado aqui e no comentário da card: quem abrir o funil sem filtro verá o período começar um dia mais cedo do que via ontem.

## D2 — O filtro por corretor vira o padrão "indisponível" da TEC-322, e não um campo de texto recusado

Hoje `Filtros.tsx` desenha `<input type="text" name="corretorId">`: a gerente pode digitar um id, mandar, e levar um 422. A card pede outra coisa: o campo **desabilitado**, com o motivo escrito, antes de qualquer envio. `FiltrosDeLeads.tsx` (TEC-322, D5) já tem exatamente este padrão para "filtro indisponível para o papel":

```tsx
<label className="leads-filtro">
  Corretor
  <select disabled aria-describedby="filtro-corretor-motivo">
    <option>Todos</option>
  </select>
  <span id="filtro-corretor-motivo" className="leads-filtro-motivo">
    Filtro por corretor indisponível para o seu papel.
  </span>
</label>
```

`Filtros.tsx` reaproveita a mesma forma, com o texto exato da card: "Disponível após a alocação de corretor."

## D3 — `corretorId` para de ser lido da URL, e por isso nunca é enviado

A letra da card: "o parâmetro não é enviado enquanto o backend responder 422." Com o campo desabilitado (D2) ninguém digita mais um valor novo, mas uma URL antiga (de antes desta card) ou montada à mão ainda poderia trazer `?corretorId=...`. `filtrosDaUrl` (`page.tsx`) para de ler esse parâmetro — `filtros.corretorId` fica sempre `undefined`, e `buscarFunil` (que só envia chaves com valor truthy) nunca manda o parâmetro. Não é uma checagem nova em `buscarFunil`: é a fonte the dado nunca mais produzindo o valor.

O tipo `Filtros` (`lib/metricas.ts`) mantém o campo `corretorId?`: é o mesmo contrato do backend, e apagá-lo agora só para recriá-lo quando a alocação existir de verdade trocaria uma linha por uma migração de tipo depois — o mesmo argumento que a TEC-190 já usou para `Agendado` (D1 daquele desenho).

## D4 — Intervalo máximo de 12 meses é regra de domínio, no mesmo lugar que já recusa `de > ate`

`montar_recorte` (`domain/metricas/filtros.py`) já é o único lugar que decide se um recorte de período é válido — recusar em duplicidade no frontend seria uma segunda cópia da regra, o defeito que este repo evita sistematicamente (D4 da TEC-190, sobre a regra de qualificação). Ganha uma checagem nova:

```python
def _mais_um_ano(dia: date) -> date:
    try:
        return dia.replace(year=dia.year + 1)
    except ValueError:
        return dia.replace(year=dia.year + 1, day=28)  # 29/02 sem ano bissexto seguinte
```

`ate > _mais_um_ano(de)` é `FiltroInvalido("ate", ...)`, com a mensagem citando o limite de 12 meses.

**Correção sobre onde a mensagem aparece.** `FiltroInvalido` vira `HTTPException(detail=str(erro))` — uma STRING, não a lista estruturada com `loc` que o FastAPI produz sozinho para erro de tipo (`metricas.py:76`). `detalheDe` (`lib/metricas.ts`) só extrai `campos` da forma em lista; um `detail` string sempre cai em `campos: []`. Por isso este erro, como o de "de > ate" que já existia antes desta card, aparece **acima do formulário** (`erroSolto`), e não ao lado de "Até" — confirmado no navegador. `ate` continuar em `CAMPOS_COM_MENSAGEM` não muda isso: aquele conjunto só importa para os 422 que o próprio FastAPI gera com `loc` (data malformada, UUID inválido), não para os que `montar_recorte` levanta. Isto ainda satisfaz o Gherkin ("o período é recusado com a indicação do limite de 12 meses"), que não pede um lugar específico.

## Testes

- **Backend** (`tests/unit/test_filtros_do_funil.py`): 12 meses exatos passa; 12 meses e 1 dia recusa; o exemplo do Gherkin (01/01/2025 a 24/09/2026) recusa; 29/02 num ano bissexto some ainda dentro do limite (`de=2024-02-29` → limite `2025-02-28`).
- **Frontend** (`lib/periodo.test.ts`): os dois casos existentes, com a data esperada um dia mais cedo.
- **Frontend** (`Filtros.test.tsx`): o campo Corretor está desabilitado com o texto certo; não há mais `<input name="corretorId">` editável; os testes do "422 ao lado do campo" que citavam `corretorId` são removidos (não há mais como esse campo levar 422 — ninguém o envia).
- **Frontend** (`page.test.tsx` do funil): uma URL com `?corretorId=x` não faz `buscarFunil` enviar o parâmetro.

## Verificação no navegador (28/09/2026)

Edge headless por CDP, `next dev` e API locais, sessão ADMIN por MFA.

| passo | resultado |
| --- | --- |
| `/` sem filtro, hoje 28/09/2026 | `de=2026-08-29`, `ate=2026-09-28` — 30 dias corridos incluindo hoje, batendo com a fórmula corrigida |
| campo Corretor | `<select disabled>` com "Todos", e "Disponível após a alocação de corretor." visível |
| `?de=2025-01-01&ate=2026-09-24` (o exemplo do Gherkin) | recusado, com a mensagem citando o limite (`o limite e 2026-01-01`) acima do formulário |
| `?de=...&ate=...&canal=web&temperatura=QUENTE` | os quatro campos vêm preenchidos com os mesmos valores — o link reproduz a visão |
| `?corretorId=abc-123` | a página carrega normalmente, ignorando o parâmetro; nenhuma chamada ao backend leva `corretorId` |

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Link compartilhado reproduz a visão | já valia desde a TEC-190 (`filtrosDaUrl`/`Filtros`/`urlDoRecorte`); sem mudança nesta card |
| Abrir o funil sem filtros | `periodo.test.ts`, corrigido (D1) |
| Recusar intervalo maior que 12 meses | `test_filtros_do_funil.py` (D4) |
| Filtro por corretor ainda indisponível | `Filtros.test.tsx` (D2) |

## Lacunas declaradas

- **L1 — A TEC-166 não desbloqueia o filtro por corretor.** Nenhuma card visível hoje escreve `handoffs.corretor_id`. Quando alguma escrever, o desbloqueio é: apagar a recusa em `montar_recorte`, trocar o campo desabilitado por um de verdade, e voltar a ler `corretorId` da URL em `filtrosDaUrl`.
- **L2 — O SRS do frontend não está no repo.** RN-FE-05.3 e RN-FE-05.5 vêm do texto da card.
