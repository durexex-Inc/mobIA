# TEC-385 — Cadência de reengajamento lê a temperatura sem a penalidade de não comparecimento

**Status:** implementado nesta branch
**Card:** [TEC-385](https://eduardodurieuxlopes.atlassian.net/browse/TEC-385)
**Origem:** decisão da TEC-375 — Emenda E-02 à RN-12.4 e Emenda E-02 à RN-13.1.

## O que o repo tem, medido sobre `ac83824`

- **A varredura não recalcula a temperatura.** As duas consultas de `followup/repositorio.py` — os candidatos e os dormentes — leem a coluna `lead_qualification.temperatura`, e é dela que saem a régua, o teto de tentativas, o adormecimento e o valor gravado em `followups`.
- **Só `registrar_recalculo` grava essa coluna.** Ele é chamado pelo turno, pelo não comparecimento (`agendamento/ciclo.py`) e pela edição manual (`leads/edicao.py`).
- **O SLA** (`notificacao/envio.py`) **e o handoff automático** (`turno.py`) leem a mesma temperatura, e ela continua valendo para eles.

## D1 — Uma coluna, `temperatura_da_cadencia`

Ela é gravada no mesmo `UPDATE` de `registrar_recalculo`, a partir da mesma conta:

```python
temperatura_da_cadencia_de(score, qualificado=..., forcada=...)
# == temperatura_de(replace(score, penalidade=0), ...)
```

**Só a penalidade sai da conta.** O teto de `qualificado` e o forçamento continuam valendo, porque os dois descrevem o que o lead sinalizou. A falta é o juízo que a Emenda E-02 à RN-12.4 tirou da cadência; o resto dos sinais do lead continua contando.

**Alternativa descartada: calcular na consulta.** O score não é persistido em `lead_qualification`. Calcular na consulta exigiria reescrever `calcular_score` em SQL, e isso criaria uma segunda fonte da regra.

## D2 — As consultas leem `COALESCE(temperatura_da_cadencia, temperatura)`

O `COALESCE` cobre as linhas que o preenchimento deixou nulas (D3). Para elas, a régua é a de antes desta card.

## D3 — Preenchimento

- **A migration 0068 copia `temperatura` onde não há penalidade.** Nesse caso as duas temperaturas são iguais por construção, então a cópia é exata.
- **Onde há penalidade, a coluna fica nula.** A temperatura sem penalidade depende de `qualificado` e do score recalculado, e isso é regra de domínio.
- **`scripts/preencher_temperatura_da_cadencia.py` recalcula essas linhas** pelo caminho do domínio (`preencher_temperaturas_da_cadencia`), um lead por transação.

Sem o script, esses leads só são corrigidos no próximo recálculo, e um lead que faltou e ficou em silêncio pode não ter nenhum.

## Correção de comentário

A docstring de `cadencia.py::esta_dormente` afirmava que esfriar sem fala do lead era inalcançável, porque `registrar_recalculo` só seria chamado pelo turno. Isso deixou de valer com a TEC-172 e a TEC-194, e a docstring foi corrigida.

## Emenda ao SRS

**RN-13.1 E-03 (TEC-385, 27/09/2026):** registra que a Emenda E-02 foi implementada, e como.

## O que esta card não entrega

- **O script não roda sozinho.** É preciso executá-lo uma vez depois do deploy da 0068.
- **Não há teste da migration.** O que se testa é o domínio: o recálculo grava as duas colunas, e o preenchimento cobre as linhas nulas.
- **O SLA é afirmado sobre `prazo_em_minutos`** e a coluna que `notificacao/envio.py` lê. O teste não abre um handoff de ponta a ponta.
