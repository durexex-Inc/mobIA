# TEC-378 — O teste que dependia da hora do dia

**Desenho:** `docs/superpowers/specs/2026-09-25-tec-378-teste-que-depende-da-hora-design.md`
**Branch:** `fix/tec-378-teste-que-depende-da-hora`

Card pequena: um arquivo de teste, nenhum código de produção. O desenho carrega as decisões; aqui ficam os passos e a verificação.

---

### Task 1: A asserta que compara o instante

**Files:** `tests/features/test_agendamento_pela_conversa.py`

- [x] **Step 1:** trocar `f"às {hora}" not in texto` por `data_e_hora_absolutas(tomado) not in texto` (D1). A mesma função que `linhas_das_janelas` usa, então compara com o que o lead leu.
- [x] **Step 2:** acrescentar a asserta de banco — nenhuma `JanelaProposta` do segundo lead tem o `inicio` do agendamento do primeiro (D2). As duas juntas: a de banco prova a regra, a de texto prova que ela chegou ao lead.
- [x] **Step 3:** o comentário diz o que mudou e por quê, incluindo o mecanismo — uma janela por dia, todas no começo da jornada.

---

### Task 2: A borda forçada

**Files:** `tests/features/test_agendamento_pela_conversa.py`

- [x] **Step 1:** `_ocupar_hoje`, que toma a jornada inteira do dia para que o primeiro slot livre seja de amanhã — determinístico em qualquer hora.
- [x] **Step 2:** o teste novo, com a **premissa asserida**: alguma alternativa cai na mesma hora do slot tomado. Sem ela o teste passaria por acaso.
- [x] **Step 3:** não exigir que TODAS caiam nessa hora — o dia do slot tomado sai às 10h porque as 9h estão ocupadas, e esse deslocamento é o motor funcionando, não o que está em questão.

---

### Verificação final

- [ ] Os três gates com o escopo do CI.
- [ ] `pytest -n 8 --dist loadfile`, uma vez. **Esperado zero falhas** — esta é a card que tira a única que restava.
- [ ] `scripts/comentarios_tocados.py` e `--checar`.
