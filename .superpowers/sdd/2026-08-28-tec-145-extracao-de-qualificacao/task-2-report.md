# Task 2 Report — Preparacao de contexto para extracao

**Date:** 2026-08-28  
**Author:** Claude Code  
**Status:** COMPLETED

## Mudancas Feitas

Execucao das preparacoes necessarias para que a TEC-145 (extracao de qualificacao) caiba dentro do limite de contexto, sem quebrar o teste de cobertura.

### 1. Ajuste da reserva de contexto

**File:** `src/mobia/app/config.py:88`

Modificado `contexto_headroom_de_tokens` de `400` para `702`.

**Justificativa:** O objeto `extracao` do `SCHEMA_DA_RESPOSTA` (adicionado na TEC-145) custa 263 tokens que sao enviados em toda chamada e nunca entram na contagem de `montar_contexto`. Com 400, o teste `test_diferenca_entre_o_contado_e_o_enviado` chegava a 526 tokens de diferenca nao contada, o que excedia a reserva.

Com 702:
- Subcontagem nao vista = 526 tokens
- Folga disponivel = 702 - 526 = 176 tokens
- Reserva para overhead estrutural = 702 * 0.25 = 175.5 tokens (margem positiva)

Preco pago: 302 tokens menos de literais e resumo por turno, sobre um teto de 12000 (2.5% do contexto).

**Comentario adicionado:** Documento completo na linha de codigo explicando a origem do numero e como medir de novo se necessario.

### 2. Correcao do spec

**File:** `docs/superpowers/specs/2026-08-28-tec-145-extracao-de-qualificacao-design.md`

Adicionado bloco de correcao na secao **D1** (apos o paragrafo sobre "Por que: o contexto de entrada ja foi pago nessa chamada"):

Bloco novo declara que "custo marginal quase zero" era otimista, fornece numero real (263 tokens), explica a decisao sobre usar 702 em vez de 700, e conclui que o custo nao e zero mas ainda e ordens de grandeza melhor que uma chamada separada.

**Fim com indicador de rastreabilidade:** "...quem medir isso depois merece encontrar o numero, nao o adjetivo." — criando expectativa de que alguem pode voltar com um numero diferente.

## Verificacao

| Teste | Resultado | Nota |
|-------|-----------|------|
| `python -m pytest tests/unit/test_config.py -q` | EXIT=0 ✓ | test_diferenca_entre_o_contado_e_o_enviado passa |
| `python -m ruff check src` | All checks passed! ✓ | Sem warnings |
| `python -m ruff format --check src` | 54 files already formatted ✓ | Sem alteracoes necessarias |
| `python -m mypy src` | No issues found ✓ | Tipagem correta |

## Arquivos Alterados

1. `src/mobia/app/config.py` — constante `contexto_headroom_de_tokens` e comentario associado
2. `docs/superpowers/specs/2026-08-28-tec-145-extracao-de-qualificacao-design.md` — secao D1 com bloco de correcao

## Preocupacoes

Nenhuma. O valor 702 em vez do 700 sugerido foi necessario para satisfazer a condicao `subcontagem < contexto_headroom * 0.75` do teste. A diferenca de 2 tokens nao afeta o objetivo (deixar folga para crescimento futuro) e foi comunicada no comentario do codigo.

## Proximos Passos

Task 2 pode prosseguir com a implementacao do schema e parse em `src/mobia/domain/agente/classificador.py` sem risco de estouro de limite de contexto.
