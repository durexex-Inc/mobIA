# TEC-378 — O teste que reprovava conforme a hora do dia

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-378](https://eduardodurieuxlopes.atlassian.net/browse/TEC-378) — épico TEC-164
**Branch:** `fix/tec-378-teste-que-depende-da-hora`
**Origem:** achado ao validar a `main` depois dos merges dos PRs #182 e #183.

## O defeito, em uma frase

`test_dois_leads_no_mesmo_slot` quer dizer *"o horário que o outro lead levou não pode ser reoferecido"* e escreve *"a string `às 9h` não aparece no texto"*. As duas frases só coincidem enquanto nenhuma alternativa cair na mesma hora de outro dia — e `janelas_alocadas` dá **uma janela por dia**, sempre a primeira que cabe, que é o começo da jornada.

## D1 — Comparar o instante, e não a hora

`data_falada.py::data_e_hora_absolutas` já produz a forma que distingue: `"quinta-feira, 27 de agosto, às 15h"` — dia da semana, dia do mês e hora. É o que `linhas_das_janelas` usa para montar cada linha da oferta, então comparar contra ela é comparar contra **exatamente o que o lead leu**.

`assert data_e_hora_absolutas(tomado) not in texto` diz a frase certa, e é imune à hora em que a suíte roda.

## D2 — E afirmar sobre o banco, porque o texto é a ponta errada para esta garantia

A asserta de texto continua valendo — é um teste de feature, e o que o lead lê importa. Mas a garantia de fundo é sobre o que foi **oferecido**, e isso está em `janelas_propostas`: nenhuma proposta do segundo lead pode ter `inicio` igual ao `inicio` do agendamento do primeiro.

Essa forma não depende de formatação nenhuma. Se um dia o texto das janelas mudar — e ele já mudou duas vezes neste repo —, a asserta de texto se adapta ou some, e esta continua guardando a regra.

**As duas juntas, e não uma só:** a de banco prova a regra, a de texto prova que ela chegou ao lead.

## D3 — Uma das duas bordas dá para forçar; a outra não, e isso se declara

O critério de aceite pede exercitar "com janela livre hoje e sem". A segunda é forçável: basta ocupar a agenda de hoje, como `tests/features/test_lista_de_espera.py::_lotar_agenda` já faz. Um teste novo cobre esse caso — que é precisamente o que quebrava — de forma determinística **em qualquer hora**.

A primeira não é forçável sem controlar o relógio, e o turno carimba com `datetime.now`. Uma suíte que rode às 20h nunca terá janela hoje. **Não vale inventar injeção de relógio no `executar_turno` por causa de um teste**: o conserto da D1 já torna a asserta verdadeira nas duas bordas, e a borda forçável é a que historicamente falhou.

## D4 — O que a varredura do arquivo achou, e não achou

O critério pede conferir os demais. Os outros dois testes que olham horário **já são robustos**, e por razões diferentes:

- `test_o_lead_pede_horario_e_recebe_janelas_daquela_quinta` usa `_proxima_quinta()`, que nunca devolve hoje — e a docstring dela diz que é de propósito, "a antecedência mínima de 3 horas tornaria o cenário dependente da hora em que a suíte roda".
- `test_o_pedido_sem_data_oferece_a_grade_dos_proximos_dias` afirma que os dias são distintos, que é propriedade de `janelas_alocadas` e não depende de quais dias sejam.

Nada mais a mudar. O defeito era de um teste só.

## Critérios de aceite

| critério | onde |
| --- | --- |
| Passa em qualquer hora do dia | `test_dois_leads_no_mesmo_slot`, pela D1 |
| A borda "sem janela hoje" exercitada de propósito | teste novo, com a agenda de hoje ocupada |
| A intenção original preservada | a asserta de banco da D2 |

**Sem emenda ao SRS:** nada aqui muda regra de negócio. O código estava certo; o teste é que afirmava a coisa errada.
