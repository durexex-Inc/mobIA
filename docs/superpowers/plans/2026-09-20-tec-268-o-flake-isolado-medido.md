# TEC-268 — O flake isolado, medido: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A instrução "rode o arquivo sozinho" volta a ser verdadeira — datada, atribuída à máquina, e re-verificável por um comando.

**Architecture:** O parágrafo do CLAUDE.md vira tabela de duas medições; `scripts/taxa_de_flake.py` refaz a conta em ~13 minutos.

**Tech Stack:** Python 3.13, pytest, `subprocess`.

**Spec:** `docs/superpowers/specs/2026-09-20-tec-268-o-flake-isolado-medido-design.md`

## Global Constraints

- **Os três gates estáticos, no escopo do CI** — `scripts/` está dentro dele, e foi justamente um script que reprovou o formatador da primeira vez que a pasta entrou no escopo (12/09/2026). Rode o formatador.
- **Comentários e docstrings em `src/`, `tests/` e `scripts/`: português SEM acento.** O CLAUDE.md é prosa em `docs`-like: **com** acento.
- **Nada de tocar em `src/`.** A D3 recusa mexer no Redis às cegas; se a implementação levar a `infra/queue.py`, pare.
- **Não apague a medição de setembro.** Ela é a metade da tabela que impede a próxima pessoa de achar que é a primeira a ver o flake.
- **Mensagem de commit:** `tipo(TEC-268): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: O script que refaz a medição

**Files:**
- Create: `scripts/taxa_de_flake.py`

- [ ] **Step 1: Escrever**

Roda cada arquivo sozinho, `--vezes` vezes, em processo pytest próprio (`-p no:cacheprovider`, para uma execução não herdar ordem da anterior). Imprime quantas passaram, a média de duração, e nomeia os testes que reprovaram em cada execução.

A lista de arquivos é a do CLAUDE.md, e o comentário diz por que ela não cresce sozinha: o script mede a afirmação que está escrita lá.

- [ ] **Step 2: Rodar com `--vezes 2` para ver funcionar**, e com `--arquivo` para conferir o recorte.

- [ ] **Step 3: Gates.** `scripts/` está no escopo dos três.

---

### Task 2: O parágrafo do CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (seção "Testes", o parágrafo "Testes de integração flakeiam sob carga")

- [ ] **Step 1: Trocar a propriedade por uma tabela**

Duas linhas: 09/09/2026 na máquina anterior (3 de 5 reprovando, erro de Redis em `localhost:6380`), 20/09/2026 nesta (75 execuções, 0 falhas). Com a conclusão dita com a força certa: evidência forte, não prova, nas duas direções.

- [ ] **Step 2: Apontar o script**, para quem quiser saber se vale na máquina dele.

- [ ] **Step 3: Conferir que o script não passou a mentir.** O docstring dele cita o que o CLAUDE.md afirma — e o CLAUDE.md acabou de mudar. É o caso clássico de prosa que envelhece dentro da própria branch.

---

### Task 3: Fechamento

- [ ] **Step 1: A suíte inteira, uma vez** (`-n 8 --dist loadfile`).

Esta branch não toca `src/` nem `tests/`, mas a suíte é o que prova isso.

- [ ] **Step 2: `scripts/comentarios_tocados.py`** — e note que ele avisa sobre arquivo `.py` não commitado, então commite antes de confiar na listagem.

- [ ] **Step 3: Push, PR, e a card em Em análise, com comentário registrando:**

- **A premissa da card não se sustenta nesta máquina:** 75 execuções isoladas, 0 falhas. A medição de setembro continua válida — o que estava errado é a afirmação do CLAUDE.md ser incondicional, não ela estar desatualizada.
- **O que a card pedia e não foi feito:** investigar o caminho do Redis. Sem reprodução, seria mudança de produção às cegas; o script dá a taxa antes/depois quando o sintoma reaparecer.
- **Achado lateral:** o desenho da TEC-162 (`docs/superpowers/specs/2026-09-09-...`) cita a frase antiga do CLAUDE.md no presente. É spec de outra card, registrando o que era verdade então — não foi tocada.
