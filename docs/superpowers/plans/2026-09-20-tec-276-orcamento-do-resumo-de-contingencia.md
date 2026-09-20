# TEC-276 — O orçamento do resumo de contingência: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O resumo de contingência mostra tantos imóveis quantos couberem nos 1.500 caracteres, em vez de dois fixos dimensionados para o pior caso do banco.

**Architecture:** `montar` monta o texto com `n` imóveis e mede; sobe `n` enquanto couber. O teto fixo some; a garantia de caber passa a ser propriedade do algoritmo, não de uma tabela em comentário.

**Tech Stack:** Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-276-orcamento-do-resumo-de-contingencia-design.md`

## Global Constraints

- **Os três gates estáticos, no escopo do CI**, antes de cada commit:
  `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`,
  `./.venv/Scripts/python.exe -m mypy`.
- **Comentários e docstrings em `src/` e `tests/`: português SEM acento**, exceto valor citado.
- **Não mude o limite de 1.500 nem o conteúdo dos seis blocos** — a card escopa os dois para fora. Se `resumo.py` ou os `MARCADORES` precisarem mudar, pare.
- **`renderizar` (modo redigido) não é tocado.** Ele chama `imoveis()` sem teto de propósito: o modelo recebe o dossiê inteiro.
- **Mensagem de commit:** `tipo(TEC-276): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Loop:** `./.venv/Scripts/python.exe -m pytest tests/unit/test_handoff_contingencia.py -q` (instantâneo, sem Docker).
- **Números medidos nesta card, para conferir contra a implementação:** pior caso do banco cabe com 2 imóveis (1425) e estoura com 3 (1503); lead típico cabe com 15 (1418) e estoura com 20; uma montagem custa 0,011 ms (10 imóveis) a 0,084 ms (200).

---

### Task 1: Os dois testes que descrevem o comportamento novo

**Files:**
- Modify: `tests/unit/test_handoff_contingencia.py`

- [ ] **Step 1: O construtor do pior caso, derivado dos tetos do módulo**

Um helper que monta o dossiê extremo **a partir de `contingencia.TETO_*`**, e não de literais: `"R" * TETO_REGIAO`, `"C" * TETO_CODIGO`, o maior membro de cada enum, 40 imóveis, 50 itens de 32 caracteres por lista de atenção.

É esta derivação que torna a medição reproduzível — quem alargar `LeadQualification.regiao` para `String(200)` muda o teste junto sem editá-lo. Um literal `"R" * 120` aqui reintroduziria a tabela de prosa em outra forma.

- [ ] **Step 2: Os testes**

1. **o pior caso do banco cabe** — `montar` não levanta, e o texto fica ≤ 1.500;
2. **o lead típico vê mais de dois imóveis** — a asserta é `> 2`, **não** `== 15`. Prender o 15 faria o teste reprovar na primeira palavra acrescentada a um bloco, que é o acoplamento que esta card remove;
3. **200 imóveis não estouram** — e a busca não percorre o dossiê inteiro;
4. **dossiê sem imóvel** continua montando;
5. **os mais recentes continuam sendo os escolhidos** — o orçamento muda quantos, não quais (Important 3 da TEC-176).

Rode e veja reprovar: hoje o teto fixo de 2 faz o teste 2 falhar.

- [ ] **Step 3: Commit dos testes junto com a implementação** (Task 2) — não commite a suíte vermelha.

---

### Task 2: O orçamento

**Files:**
- Modify: `src/mobia/domain/handoff/contingencia.py`

- [ ] **Step 1: Extrair a montagem para uma função que aceita `n`**

O corpo de `montar` hoje é um `"\n".join(...)` com `teto=TETO_DE_IMOVEIS` no meio. Vira `_texto_com(dossie, quantos_imoveis)`, e `montar` passa a escolher o `quantos`.

**Não mude nada dentro do `join` além do parâmetro** — qualquer edição de texto aqui muda todos os números medidos e o diff deixa de ser revisável.

- [ ] **Step 2: A busca ascendente**

Sobe de 0 até `len(dossie.imoveis)`, guarda o último que coube, para no primeiro que estoura. O comentário registra as duas razões: a monotonicidade (cada imóvel só acrescenta caracteres) é o que autoriza parar; e subir em vez de descer é o que faz o custo acompanhar o orçamento (~40 candidatos no máximo) em vez do dossiê (200+), medido em 0,084 ms por montagem.

Compare contra `LIMITE_DE_CARACTERES` (`handoff/resumo.py`) sobre o texto **já com `.strip()`**, que é o que `validar` mede — comparar contra outro comprimento faria a busca aceitar um texto que `validar` recusa.

- [ ] **Step 3: Quando nem zero cabe**

`validar` levanta `ResumoAcimaDoLimite`, como hoje. A rede de segurança de `geracao.gerar_resumo` depende disso — não engula.

- [ ] **Step 4: `TETO_DE_IMOVEIS` sai, e o comentário de 40 linhas com ele**

A tabela de prosa é substituída por um parágrafo curto que diz onde a medição mora agora (os testes da Task 1) e por que não há número aqui. `TETO_POR_LISTA_DE_ATENCAO` **fica**, com a lacuna da D2 declarada.

- [ ] **Step 5: Gates, testes, commit**

`feat(TEC-276): o resumo de contingencia mostra quantos imoveis couberem`

---

### Task 3: Fechamento

- [ ] **Step 1: Conferir os números contra a implementação**

Rode a medição de novo pelo caminho novo: o pior caso tem de sair com 2 imóveis, e o lead típico com 15. Se divergir, o desenho está errado, não o teste.

- [ ] **Step 2: A suíte inteira, uma vez** (`-n 8 --dist loadfile`) e `scripts/comentarios_tocados.py`.

Esta branch apaga um comentário de 40 linhas e mexe num módulo denso — é caso de `VIZINHO`.

- [ ] **Step 3: Push, PR, e a card em Em análise, com comentário registrando:**

- **A contradição interna da card:** "reajustar os tetos pela medição" dá 2, o mesmo de hoje, e torna o terceiro critério de aceite impossível. A medição decidiu o desenho — orçamento em vez de teto.
- **Uma terceira medição discordante:** a tabela no código dizia 1452/48; medi 1425/75, e `2/2`, que ela diz estourar, cabe. Nenhum dos três números sobrevive; por isso nenhum deles ficou escrito.
- **Ganho medido:** lead típico passa de 2 para 15 imóveis; sobravam 577 caracteres de 1.500.
- **Lacuna declarada, decisão de produto:** a folga restante não alimenta as listas de atenção, porque escolher entre imóvel e ponto de atenção não é decisão de código.
