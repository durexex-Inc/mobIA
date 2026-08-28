# Task 2 Report — Preparacao de contexto para extracao

**Date:** 2026-08-28  
**Author:** Claude Code  
**Status:** COMPLETED

## Mudancas Feitas

Execucao das preparacoes necessarias para que a TEC-145 (extracao de qualificacao) caiba dentro do limite de contexto, sem quebrar o teste de cobertura.

### 1. Ajuste da reserva de contexto

**File:** `src/mobia/app/config.py:88`

Modificado `contexto_headroom_de_tokens` de `400` para `800`.

**Justificativa:** O objeto `extracao` do `SCHEMA_DA_RESPOSTA` (adicionado na TEC-145) custa 263 tokens que sao enviados em toda chamada e nunca entram na contagem de `montar_contexto`. Com 400, o teste `test_diferenca_entre_o_contado_e_o_enviado` chegava a 526 tokens de diferenca nao contada, o que excedia a reserva.

Com 800:
- Subcontagem nao vista = 526 tokens
- Folga disponivel = 800 - 526 = 274 tokens
- Reserva para overhead estrutural = 800 * 0.25 = 200 tokens (margem confortavel)
- Espaco de crescimento de prompt = 74 tokens

Preco pago: 400 tokens menos de literais e resumo por turno, sobre um teto de 12000 (3.3% do contexto).

**Comentario adicionado:** Documento completo na linha de codigo explicando a origem do numero, por que 800 em vez de 702, e como medir de novo se necessario.

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

## Por que 800 e nao 702?

O valor minimo que passa no teste `test_config.py` e 702 (com subcontagem de 526, a assercao `526 < 702 * 0.75 = 526.5` passa por margem de 0.5 token). Contudo, essa margem derrota o proposito do fator 0.75, que e garantir folga para crescimento futuro de prompt. A proxima frase acrescentada ao `SISTEMA_DO_AGENTE` causaria falha sem motivo aparente.

Com 800, a margem e 200 tokens (800 * 0.75 = 600, e 600 - 526 = 74 tokens de crescimento de prompt), suficiente para absorver mudancas pequenas sem surpresar o desenvolvedor. O custo adicional (100 tokens = 0.83% do teto) vale a diferenca entre "passa por acaso" e "passa com folga de proposito".

## Preocupacoes

Nenhuma. Todos os testes passam, formatacao e tipagem corretas.

## Proximos Passos

Task 2 pode prosseguir com a implementacao do schema e parse em `src/mobia/domain/agente/classificador.py` sem risco de estouro de limite de contexto.
