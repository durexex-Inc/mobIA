# TEC-262 — Alinhar o vocabulário de tipo de imóvel entre a fala do lead e o catálogo

**Status:** desenhado em 2026-09-08 na branch `feat/tec-262-vocabulario-de-tipo`.

**Card:** [TEC-262](https://eduardodurieuxlopes.atlassian.net/browse/TEC-262) — Should (MoSCoW), prioridade High. Origem: RN-09.1 (o filtro estruturado por tipo), lacuna 2 do desenho da TEC-158, e a D1 da TEC-242 com a emenda da TEC-246. Épico [TEC-155](https://eduardodurieuxlopes.atlassian.net/browse/TEC-155).

**Bloqueia [TEC-160](https://eduardodurieuxlopes.atlassian.net/browse/TEC-160)** — não por dependência de código, mas porque a TEC-160 existe para relaxar zero-resultados e o relaxamento que a RN-09.3 descreve é de faixa de preço e bairros adjacentes. Um zero causado por tipo sem par no catálogo é invisível para ela: relaxaria preço e bairro de uma busca que nunca teve chance.

## Objetivo

A TEC-158 entregou um filtro de tipo por igualdade em SQL. Existem **dois** `TipoImovel` no repositório e eles divergem em dois membros, então o filtro erra nos dois sentidos — e nenhum dos dois erros dá sintoma.

**O que esta card entrega:** `RURAL` no enum do catálogo, coberturas alcançáveis por quem pede apartamento, e imóveis rurais na base simulada para que a correção seja observável.

**O que ela não entrega:** nenhuma mudança no agente. Nem no enum dele, nem no prompt, nem no schema da chamada, nem no corpus de eval — e a seção seguinte é sobre por que isso não é economia, é requisito.

## O defeito, em duas metades com causas diferentes

Ler os dois enums lado a lado sugere que a correção é uni-los. **Não é**, e a razão está numa card já decidida.

### `RURAL` está certo no agente e falta no catálogo

`agente/schemas.py::TipoImovel` tem `RURAL`; `catalogo/enums.py::TipoImovel` não. O modelo devolve `RURAL` sozinho, e o corpus anota `chacara`/`sitio` como `RURAL` desde a emenda da TEC-246 — `compra-13` é a conversa que exercita, e `compra.yaml:270` tem a anotação.

Então o caminho inteiro funciona até a última cláusula: o lead diz *"queria comprar uma chácara pra passar os fins de semana com a família, perto de são roque"*, a extração grava `tipo_imovel = RURAL`, e a busca filtra `tipo = 'RURAL'` contra uma coluna que **nunca pode conter esse valor**. Zero resultados, sem erro, sem log.

**A correção é de um lado só:** o membro entra no catálogo.

### `COBERTURA` está certo no catálogo e não pode entrar no agente

A leitura simétrica — "então `COBERTURA` entra no agente" — quebraria a **D1 da TEC-242**, que decidiu o oposto e por um motivo que continua valendo.

Aquela card mapeou `cobertura duplex → APARTAMENTO`, e pôs o mapa **nas regras de anotação do corpus** (`TurnoAnotado`, em `evals/corpus.py`), com a decisão escrita em voz alta: *"Nenhuma mudança em `src/mobia/domain/`. Nada em `extrair`, nada no schema, nada no prompt."* O motivo é que o schema da chamada é estrito e o modelo já devolve `APARTAMENTO` para quem diz cobertura; a tradução existe para a **medição** não contar `extra`.

Os três turnos de `compra-06` que dizem "cobertura", "na cobertura" e "dessa cobertura" estão anotados `APARTAMENTO`. Acrescentar o membro ao enum do agente mudaria o schema estrito, o modelo passaria a devolver `COBERTURA`, e as três anotações viravam discrepância — uma regressão de eval causada por "consertar" uma assimetria que era decisão.

**A correção é no filtro, não no vocabulário:** um pedido de `APARTAMENTO` passa a casar `COBERTURA` também.

## Decisões

### D1 — `RURAL` entra no enum do catálogo, e só isso

`catalogo/enums.py::TipoImovel` passa a seis membros: `APARTAMENTO`, `CASA`, `COBERTURA`, `TERRENO`, `COMERCIAL`, `RURAL`.

Três consequências que **não** precisam de trabalho, e vale escrever por quê:

- **O contrato do arquivo se corrige sozinho.** O parser faz `tipo = enumerado("tipo", TipoImovel)` (`parser.py:325`), lendo o enum do catálogo. Acrescentar o membro é o que faz uma linha com `RURAL` deixar de ser rejeitada — não há código de parser a mexer.
- **Sem migration.** `imoveis.tipo` é `String(16)` e `lead_qualification.tipo_imovel` é `String(32)`; não existe um único tipo `ENUM` do Postgres neste schema (a D10 da TEC-156 registra o porquê), então não há `ALTER TYPE`. `RURAL` tem 5 caracteres e cabe.
- **Sem efeito no eval.** Os dois guardas de `tests/unit/test_evals_corpus_real.py` — `_SINONIMOS_DE_TIPO_IMOVEL` e `_LITERAIS_DE_TIPO_IMOVEL` — são **regex literais escritos à mão**, e não derivados de enum nenhum. A emenda da TEC-246 já registra que `rural` não aparece em fala nenhuma do corpus, e por isso o segundo guarda não o varre.

### D2 — A inclusão é uma tabela de exceção, e a seta aponta num sentido só

A condição de tipo da busca deixa de ser igualdade e passa a `in_`, alimentada por:

```python
_INCLUSOES = {TipoImovel.APARTAMENTO: (TipoImovel.APARTAMENTO, TipoImovel.COBERTURA)}
```

com `_INCLUSOES.get(tipo, (tipo,))` produzindo os valores do `WHERE`.

**Uma entrada, e um `.get` com default de identidade — não um mapa completo.** A forma é a mensagem: quem lê vê que existe **uma** regra assimétrica e que todo o resto é ele mesmo. Um dicionário com as seis chaves preenchidas convidaria o próximo leitor a completar a simetria — `CASA: (CASA,)`, `TERRENO: (TERRENO,)` — e, tendo completado, a "consertar" a linha que não é simétrica. A assimetria é o ponto, não um esquecimento.

**Por que a seta não aponta de volta.** Não existe pedido de `COBERTURA` vindo do lead: o enum do agente não tem o membro, e a D1 da TEC-242 garante que não terá. Um chamador HTTP *pode* pedir `COBERTURA` — o contrato da seção 6.3 aceita o enum do catálogo — e nesse caso a igualdade pura é a resposta certa: quem pede cobertura explicitamente quer cobertura. E quem pede `CASA` não deve ver apartamento, que seria a generalização errada da mesma ideia.

**Onde mora.** Em `domain/catalogo/busca.py`, ao lado da consulta. Não em `enums.py`, que é vocabulário e não regra de casamento; e não em `schemas.py`, onde `COLUNA_DE_PRECO` foi parar porque a guarda de `FiltroDeBusca.__post_init__` precisava dele — aqui nenhuma guarda precisa.

### D3 — O `RURAL` entra no gerador, e o CSV é regerado

A base simulada (`data/seed/imoveis.csv`, 520 linhas) tem hoje `APARTAMENTO` 275, `CASA` 136, `TERRENO` 42, `COBERTURA` 42, `COMERCIAL` 25 e **`RURAL` zero**. Sem imóvel rural, a D1 fica correta e **inobservável**: o critério de aceite passa nos testes, que inserem as próprias linhas, e quem subir o ambiente e digitar "quero uma chácara" vê o mesmo zero de hoje.

A RN-08.1 promete base *"gerada com distribuição realista de bairros, preços e tipologias"*. Uma tipologia que o agente sabe pedir e o catálogo nunca tem não é distribuição realista.

**O membro entra em `TIPOS`, no `scripts/gerar_base_simulada.py`, e o arquivo é regerado.** A alternativa — apensar ~20 linhas à mão — foi recusada, e o motivo está na docstring do próprio gerador: ele é determinístico (`Random(20260906)`) *"para que regerar produza o mesmo arquivo"*. Linhas apensadas à mão sobrevivem até a próxima regeração e **desaparecem em silêncio** nela, que é a mesma classe de armadilha que a D1 da TEC-157 recusou ao manter a definição do documento num lugar só.

**O custo, declarado:** acrescentar um tipo muda a sequência do `rng`, então **as 520 linhas mudam** — códigos, preços e bairros novos em todas. Nenhum teste quebra, porque as asserções de `tests/unit/test_base_simulada.py` são de limiar e não de conteúdo (`>= 500` linhas, `>= 8` bairros, `>= 4` tipos, códigos únicos, faixa de preço com `max >= 3 * min`). Quem tiver banco local semeado precisa reimportar.

`quantidade` fica em **520**. Subir o total junto tornaria o diff ainda maior sem ganho, e 520 é o número que os comentários de `parser.py`, `test_catalogo_upsert.py` e `test_migracao_vetorial.py` citam.

**A entrada nova em `TIPOS`**, no molde das cinco existentes `(nome, prefixo, peso, (área mín, área máx), (quartos mín, quartos máx))`:

```python
("RURAL", "RU", 0.05, (400, 5000), (1, 4)),
```

O peso de `APARTAMENTO` cai de `0.55` para `0.50` para que a soma continue em `1.00` — os pesos são passados a `rng.choices`, que não exige soma 1, mas a lista atual soma e manter isso deixa o peso legível como percentual. `0.05` dá ~26 linhas, entre `COMERCIAL` (25) e `TERRENO` (42), que é onde uma tipologia de nicho pertence.

A faixa de área é a mais larga do arquivo, e de propósito: chácara e sítio vão de terreno pequeno a propriedade grande, e a faixa larga é o que faz a asserção de dispersão de preço (`max >= 3 * min`) continuar folgada com um tipo a mais.

O prefixo de código do tipo novo é **`RU`**, seguindo o molde dos cinco existentes (`AP`, `CA`, `CO`, `TE`, `CM`).

### D4 — A base ganha a guarda que impede o zero de voltar

`tests/unit/test_base_simulada.py` passa a afirmar que **os seis tipos aparecem** na base, e não só que há `>= 4` tipos distintos.

É a guarda da própria card: um peso zerado numa regeração futura, ou uma edição manual do CSV, devolveria o catálogo ao estado que esta card existe para sair — e o teste de limiar `>= 4` continuaria verde com cinco tipos. A asserção nova é o que torna a ausência de rural um teste vermelho em vez de um zero-resultado silencioso meses depois.

## Fluxo

Uma busca de lead que pediu chácara, depois desta card:

1. O lead diz "quero uma chácara pra passar os fins de semana". A extração grava `tipo_imovel = RURAL` — **inalterado**, já funcionava.
2. Quem chama a busca traduz o tipo do agente para o do catálogo. `RURAL` agora tem par, então a tradução é a identidade. (A tradução em si é lacuna declarada da TEC-158 e continua sendo — TEC-161/162.)
3. A busca monta `tipo IN ('RURAL')` — `_INCLUSOES.get` não tem entrada para `RURAL`, logo identidade.
4. O `WHERE` casa as linhas rurais que a base simulada agora tem.

E de um lead que pediu apartamento:

3'. A busca monta `tipo IN ('APARTAMENTO', 'COBERTURA')`, e as 42 coberturas da base — 8% do catálogo, hoje invisíveis para o pedido mais comum — passam a concorrer com os apartamentos, ordenadas pelo mesmo score da RN-09.6.

## Testes

TDD. Nenhum arquivo de teste novo: as asserções entram nos arquivos que já cobrem cada superfície, e os basenames não colidem porque não há basename novo.

**`tests/integration/test_busca_hibrida.py`:**

- imóvel `RURAL` disponível é encontrado por um filtro de `tipo=RURAL` — o cenário 1 do Gherkin da card, e o que hoje devolveria zero;
- pedido de `APARTAMENTO` devolve o apartamento **e** a cobertura, os dois;
- **a inclusão aponta num sentido só** — pedido de `CASA` não devolve apartamento, e pedido de `COBERTURA` não devolve apartamento. As duas metades, porque a primeira sozinha passaria com um mapa simétrico errado;
- o `score` da cobertura sai da mesma fórmula da RN-09.6, sem tratamento especial.

**`tests/integration/test_catalogo_upsert.py`:** uma linha com `tipo = RURAL` é inserida, e não contada como rejeitada — o cenário 2 do Gherkin, e o que prova que o parser se corrigiu pelo enum.

**`tests/unit/test_base_simulada.py`:** os seis tipos estão presentes (D4).

**O que NÃO é testado, de propósito:** que `COBERTURA` está fora do schema da chamada ao modelo. O cenário 5 do Gherkin da card pede isso, e ele já é coberto por `test_a_margem_do_orcamento_do_prompt_e_deliberada` mais os guardas do corpus — o schema é medido a cada execução, e uma mudança nele move a margem. Escrever uma asserção nova que enumere os membros do enum do agente seria uma segunda definição do vocabulário, exatamente o que a D2 da TEC-242 evitou.

## Emendas ao SRS

**RN-08.1 — Emenda E-02 (TEC-262, 08/09/2026).** A E-01 (TEC-156) fixou o contrato do arquivo, incluindo *"enums em maiúscula exata, sem normalização"*. A emenda registra que o domínio de `tipo` passa a ter seis valores, com `RURAL` entre eles, e que a base simulada da própria regra passa a conter exemplares dele — uma tipologia que o agente sabe pedir e o catálogo nunca tem não satisfaz a *"distribuição realista de tipologias"* que a regra promete.

**RN-09.1 — Emenda E-02 (TEC-262, 08/09/2026).** A E-01 (TEC-158) estabeleceu que o filtro de região é a união de bairro e zona. Esta emenda registra a segunda exceção à igualdade pura: um pedido de `APARTAMENTO` casa `tipo IN ('APARTAMENTO', 'COBERTURA')`, e **só nesse sentido**. O motivo é que a D1 da TEC-242 já decidiu que, para a fala do lead, cobertura é uma espécie de apartamento — e mantê-la fora do resultado faria o filtro contradizer a anotação do corpus. **Consequência declarada:** o filtro de tipo deixa de ser igualdade em um caso, e quem ler a cláusula sem esta emenda vai achar a assimetria um bug.

## Lacunas declaradas

1. **A tradução do `TipoImovel` do agente para o do catálogo continua no chamador**, e o chamador continua não existindo (TEC-161/162). Esta card faz os dois vocabulários terem os mesmos valores *úteis*, mas eles seguem sendo dois tipos Python distintos: `catalogo` não importa `agente`, pela D2 da TEC-158. Quem ligar a busca ao turno converte por nome.
2. **Nenhuma outra hierarquia de tipo entra.** `sobrado` dentro de `CASA`, `flat`/`kitnet`/`studio` dentro de `APARTAMENTO` — todos resolvidos na anotação do corpus pela TEC-242, sem regra em SQL, porque o modelo já devolve o membro certo. `COBERTURA` é a única exceção porque é a única em que o **catálogo** tem um membro que a fala do lead não produz.
3. **A base regerada invalida bancos locais semeados** (D3). Reimportar é `python -m mobia.admin.seed_catalogo`.
4. **`república` continua fora do vocabulário**, e a D2 da TEC-242 explica por quê — a fala do corpus não a sustenta. Esta card não reabre.
5. **O filtro de cidade continua ausente** (lacuna 8 do desenho da TEC-158), e agora com uma aresta nova: chácara é o tipo mais provável de estar fora da cidade que o lead nomeou. Num catálogo de uma cidade só, inócuo.
6. **O gerador escolhe bairro independente do tipo, então a base terá chácara no Centro.** O laço de `gerar_base_simulada.py` sorteia tipo e bairro em passos separados, e os 12 bairros são urbanos — uma linha `RURAL` em "Centro" ou "Trindade" é implausível para um olho humano. Fica assim de propósito: nenhuma regra, teste ou eval depende da coerência entre tipo e bairro, e condicionar o sorteio exigiria dar a cada tipo o seu conjunto de bairros, que é um refactor do gerador maior que esta card. Quem for usar a base para demonstração a cliente, e não para teste, provavelmente quer fechar isso primeiro.

## Fora de escopo

- **Qualquer mudança em `domain/agente/`** — enum, prompt, schema da chamada.
- **O mapa de sinônimos do corpus** (TEC-242, emendado pela TEC-246).
- **O relaxamento de critério** (TEC-160), que esta card destrava e não implementa.
- **A tradução agente→catálogo no turno** (TEC-161/162).
