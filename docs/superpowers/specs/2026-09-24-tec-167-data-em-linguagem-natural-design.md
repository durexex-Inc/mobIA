# TEC-167 — Data em linguagem natural, com confirmação absoluta

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-167](https://eduardodurieuxlopes.atlassian.net/browse/TEC-167) — épico TEC-164
**Branch:** `feat/tec-167-data-em-linguagem-natural`
**Origem:** RF-11, RN-11.3 (SRS v1.0); RT-10.

## Objetivo

Transformar o que o lead escreve — "pode ser quinta de manhã", "amanhã de tarde", "quinta às 15h" — numa data, período ou instante no fuso `America/Sao_Paulo`, relativo ao momento atual; transformar isso em janelas concretas pelo motor da TEC-165; e escrever a data e a hora **absolutas** que a confirmação exige ("quinta-feira, 27 de agosto, às 15h"). O que for ambíguo vira pergunta, nunca chute.

## O que esta card não entrega, dito antes

**Nada muda na conversa.** Como na TEC-165: o agente não reconhece pedido de horário nem oferece janela, porque escolher uma não grava nada (TEC-168). Oferecer antes seria prometer uma marcação que o sistema não faz.

**O cenário "Nada é gravado sem confirmação explícita" não é exercitável.** Não existe gravação de agendamento — ela é a TEC-168. Um teste que afirmasse "nenhum agendamento criado" contra uma tabela que não existe seria o teste que inventa a entidade que falta para se auto-satisfazer, que a Emenda E-01 da TEC-190 proíbe. O critério volta com a TEC-168; esta card entrega a peça que ele vai exigir, a data absoluta da confirmação.

## D1 — Regras determinísticas, não o modelo

Decidido no desenho. O RT-10 é justamente "interpretação errada gera visita no dia errado"; um modelo pode errar o dia com confiança, e cada chamada custa orçamento de prompt e dinheiro. Um parser por regras erra **por falta**, e a falta vira pergunta. É o molde de `domain/agente/dinheiro.py` (TEC-146): gramática fixa, testada com valor exato, estendê-la é decisão de card.

**`resolver` nunca levanta** para texto do lead, pelo mesmo argumento da docstring de `dinheiro.py`: qualquer sequência de caracteres é entrada válida, e uma exceção aqui derrubaria o turno inteiro. Só `agora` sem fuso levanta — é erro de programação, não de fala.

## D2 — O módulo e o que ele devolve

`src/mobia/domain/agendamento/data_falada.py`, puro. A entrada passa por `domain/texto.py::dobrar` (sem acento, caixa dobrada), então "amanhã" e "AMANHA" seguem o mesmo caminho.

`resolver(texto, *, agora) -> Resolucao`, com seis formas:

| forma | exemplo (terça, 25/08, 14h) | conteúdo |
| --- | --- | --- |
| `Instante` | "quinta às 15h" | `momento` = 27/08 15:00 |
| `Periodo` | "amanhã de tarde" | `dia` = 26/08, `periodo` = TARDE |
| `Dia` | "quinta", "dia 3", "3/9" | `dia` |
| `Semana` | "semana que vem" | `segunda` = 31/08 |
| `Ambigua` | "no fim de semana" | `pergunta` (texto ao lead) |
| `NaoReconhecida` | "tanto faz" | — |

## D3 — A gramática

Dias:
- "hoje", "amanhã", "depois de amanhã". "Amanhã" numa sexta é o sábado.
- Dia da semana ("segunda" … "sábado", com ou sem "-feira"): a **próxima** ocorrência a partir de amanhã. "Sexta que vem" e "próxima sexta" valem o mesmo que "sexta" — o uso é regional, e é a confirmação absoluta que pega a divergência.
- "dia 3": o próximo dia 3 no futuro (este mês se ainda não passou, senão o próximo).
- "3/9" ou "03/09": dia/mês, no ano corrente.
- "semana que vem", "próxima semana": a semana que começa na próxima segunda.

Períodos: "de manhã"/"pela manhã" = 9h às 12h; "de tarde"/"à tarde" = 12h às 19h. A tarde termina onde o atendimento termina.

Horas: "15h", "15h30", "15:30", "às 15", "3 da tarde" (= 15h), "10 da manhã".

## D4 — O que é ambíguo, e portanto pergunta

| entrada | por quê | pergunta |
| --- | --- | --- |
| "fim de semana" | domingo não tem atendimento | se é o sábado (com a data) |
| "domingo" | idem | outro dia, e diz que domingo não há atendimento |
| o dia da semana de hoje ("quinta" numa quinta) | hoje ou a próxima? | qual dos dois (com as datas) |
| hora de 1 a 7 sem período ("às 3") | 3h ou 15h? | qual das duas |
| qualquer resolução no passado ("hoje às 10h" às 14h, "3/8" em 25/08) | não dá para marcar no passado | outro horário |
| dois dias na mesma frase ("quinta ou sexta") | qual? | qual dos dois |
| "de noite", "à noite" | o atendimento termina às 19h | se o fim da tarde serve |
| "dia 31" num mês sem dia 31, "31/02" | data que não existe | outro dia |

As perguntas são texto ao lead: português **com acento** (TEC-267), constantes de módulo `TEXTO_...` (algumas com lacuna para a data, formatada por D6), registradas em `tests/unit/literais_ao_lead.py` para caírem nas guardas de acento e de promessa (TEC-286).

## D5 — A ponte com o motor da TEC-165

O motor ganha um parâmetro opcional, **`de`**: o início da busca. Hoje a busca começa em `agora + 3h`; com `de`, começa em `max(de, agora + 3h)`. Sem `de`, nada muda — os 23 testes da TEC-165 seguem valendo.

`janelas_para(resolucao, *, agora, jornada_inicio, jornada_fim, ocupados, tipo) -> list[Intervalo] | Resolucao`:

- `Periodo` → busca de `dia período-início` a `dia período-fim`.
- `Dia` → busca do início ao fim daquele dia.
- `Semana` → busca de segunda 00:00 a domingo 23:59.
- `Instante` → se a janela que começa ali couber (motor com `de` = instante e `ate` = instante + duração), devolve só ela; senão, as janelas daquele dia.
- `Ambigua` e `NaoReconhecida` → devolvidas como estão, sem chamar o motor: quem chama faz a pergunta.

"Quinta de manhã" (card, primeiro cenário) → até 3 janelas da manhã de quinta, 27/08. O motor espalha por dia; num dia só, completa cronologicamente.

## D6 — A data e a hora absolutas

`data_e_hora_absolutas(momento) -> str`: "quinta-feira, 27 de agosto, às 15h"; com minutos, "às 15h30". Dia da semana por extenso, dia do mês e mês por extenso, horário — as três coisas que a RN-11.3 e a card exigem. Sempre no fuso `America/Sao_Paulo`, qualquer que seja o fuso do `momento`. `data_absoluta(dia) -> str` ("sábado, 29 de agosto") serve as perguntas do D4.

## Testes

Pelo menos 25 expressões resolvidas com valor exato, a partir de terça, 25/08/2026, 14h (o `agora` da card):

- as três da tabela da card ("amanhã de tarde" → 26/08 tarde; "quinta às 15h" → 27/08 15h; "semana que vem" → semana de 31/08);
- o primeiro cenário: "pode ser quinta de manhã" → janelas só da manhã de 27/08;
- cada linha do D4 vira `Ambigua`, e "fim de semana" pergunta pelo sábado 29/08;
- "amanhã" numa sexta → sábado;
- formatos de hora (15h, 15h30, 15:30, "às 15", "3 da tarde", "10 da manhã"), com e sem acento;
- "dia 3" → 03/09; "3/9" → 03/09; "dia 25" (hoje) e "dia 20" (passou) → setembro;
- texto sem data → `NaoReconhecida`; texto enorme ou lixo → sem exceção;
- `data_e_hora_absolutas` com e sem minutos e com `momento` em UTC;
- o `de` novo do motor: começa a busca no `de`, respeita `agora + 3h` quando `de` é anterior, e sem `de` o resultado é o de antes.
