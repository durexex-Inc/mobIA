# TEC-374 — Marcar o desfecho da visita: realizada ou não comparecida

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-374](https://eduardodurieuxlopes.atlassian.net/browse/TEC-374) — épico TEC-304
**Branch:** `feat/tec-374-desfecho-da-visita-pelo-dashboard`
**Origem:** SRS v1.0 — RF-12, RN-12.4, RN-12.5 · TEC-172, TEC-202, TEC-376

## Objetivo

`ciclo.py::marcar_realizado` e `marcar_nao_comparecimento` existem desde a TEC-172, têm teste, e **não têm um único chamador**. O próprio módulo declara: *"sao acao do corretor, e a interface dele e a E8, que nao existe."*

A consequência apareceu ontem na TEC-376: `agendamentosRealizados` sai **0** e `taxaNoShow` sai **nula** em produção, porque nenhum caminho escreve o desfecho. Esta card é o que enche aquela metade.

## D1 — Esta card é uma tela, e só a metade de trás dela é construível

A TEC-374 está no épico **`[FE]` Atendimento do lead pelo corretor**, e a card diz *"depende do detalhe do lead (TEC-323) para saber onde as ações moram"*. A TEC-323 não existe, nem o resto da casca do dashboard — TEC-309 (login), TEC-312 (menu por papel) e TEC-321 (lista) também não.

**Então esta branch entrega a API e as regras, e não a tela.** É o mesmo molde que `handoffs.py` já assumiu por escrito: *"O Gherkin diz 'pelo dashboard', e o dashboard (E8) está fora do escopo das duas cards. Estas rotas são o mecanismo que ele vai chamar; até lá, é por elas que os critérios de aceite correspondentes são exercitados."*

Vai no comentário da card como entrega parcial declarada.

## D2 — A guarda do horário mora no DOMÍNIO, e isso corrige a TEC-172

A card: *"as duas ações só aparecem para agendamento `CONFIRMADO`, e só **depois** do horário de início: marcar no-show antes da hora é afirmar o que ainda não aconteceu."*

A justificativa é **semântica**, não visual — "afirmar o que ainda não aconteceu" é sobre o ato de marcar, não sobre o botão. Duas consequências:

1. **A guarda entra em `marcar_realizado` e `marcar_nao_comparecimento`**, e não na rota. Deixá-la na rota manteria `ciclo.py` permitindo uma transição que nunca está certa, e o próximo chamador — uma varredura que marcasse no-show automático depois de N horas é plausível — teria de reimplementá-la.
2. **Ela NÃO entra em `cancelar` nem em `remarcar`**: desistir ou remarcar antes da hora é exatamente o caso comum dos dois.

**Isto reprova testes da TEC-172, e reprová-los é o achado.** `test_ciclo_do_agendamento.py` define `INICIO = 26/09 15h` e `AGORA = 25/09 12h` — o relógio dos testes está **um dia antes** do agendamento, e oito chamadas marcam realizado ou no-show a partir dali. Ou seja: a suíte afirma hoje que se pode marcar como realizada uma visita que ainda não começou. Não é intenção, é conveniência de fixture — mas é uma asserta errada, e corrigi-la faz parte da card.

A correção é acrescentar `DEPOIS = FIM + 1h` e trocar o `agora` só nas chamadas de `marcar_*`. As de `cancelar` e `remarcar` continuam em `AGORA`, porque para elas o relógio anterior é o certo.

Motivo novo: **`MOTIVO_ANTES_DA_HORA`**.

## D3 — `Recusado` passa a carregar o status atual

A card exige que a recusa seja dita como tal: *"este agendamento já foi cancelado — e não como erro genérico"*. `Recusado(MOTIVO_ORIGEM_ILEGAL)` não diz de qual origem ilegal se trata, então a rota não teria como montar a frase.

**O dado já está sendo lido e jogado fora.** `_transicionar`, no caminho de recusa, faz `session.get(Agendamento, agendamento_id)` justamente para separar "origem ilegal" de "inexistente" — e descarta a linha depois de olhar se ela é `None`.

`Recusado` ganha `status_atual: str | None = None`, preenchido nesse ponto. Campo opcional, então os chamadores existentes (`agendamento/conversa.py`) não mudam.

**A frase é montada na BORDA, e não no domínio.** Texto que uma pessoa lê é produto: mora junto da rota, com acento (a fronteira do CLAUDE.md), e não num módulo de domínio que hoje não tem literal nenhum voltado ao usuário.

## D4 — Duas rotas, e não uma com `{"desfecho": ...}`

```
POST /api/v1/agendamentos/{agendamento_id}/realizado
POST /api/v1/agendamentos/{agendamento_id}/nao-comparecimento
```

Molde de `/handoffs/{id}/aceitar`, que já é uma ação nomeada no caminho. E as duas **não são o mesmo ato com um parâmetro**: uma não custa nada ao lead e a outra tira 15 pontos de forma irreversível. Um corpo com enum faria a diferença entre elas caber num caractere de diferença numa string — e é o tipo de coisa que um cliente erra.

Cada uma ganha a própria linha em `PERMISSAO_ESPERADA` (`tests/unit/test_autorizacao_em_toda_rota.py`), que é onde uma rota nova custa uma decisão explícita.

## D5 — Autorização: `ATENDER_LEAD` mais dono

`Exige(Permissao.ATENDER_LEAD)` — que ADMIN, GERENTE e CORRETOR têm e LEITURA não — mais `exigir_dono(...)` sobre `agendamentos.corretor_id`. É exatamente *"só o corretor dono do agendamento — ou um gerente"*.

**Mais simples que o caso do handoff:** `agendamentos.corretor_id` é `NOT NULL`, então a sutileza que `_exigir_dono_do` precisou tratar — *"'não existe' NÃO é a mesma coisa que 'sem destinatário'"* — não se aplica. Continua valendo a outra metade: agendamento inexistente passa pela guarda sem erro, e quem responde 404 é o corpo da rota. Levantar 403 sobre um id que não existe transformaria a guarda num oráculo ao contrário.

## D6 — Os três códigos, e por que não um só

| caso | código | por quê |
|---|---|---|
| id não existe | **404** | `MOTIVO_INEXISTENTE` |
| corretor de outro | **403** | `exigir_dono`, que já registra a negativa na trilha |
| origem ilegal, ou antes da hora | **409** | o pedido está bem formado; o conflito é com o estado do recurso |

409 e não 422: 422 diria que o corpo está errado, e ele não está — quem mudou foi o mundo. É a mesma distinção que `reservar` faz ao traduzir a recusa do banco em `Conflito`.

## D7 — O aviso dos 15 pontos é da tela; a resposta carrega o custo

A card pede que *"o não comparecimento avisa que custa 15 pontos ao lead **antes** de confirmar"*. Um aviso prévio é, por construção, coisa de interface: a API não avisa, ela faz.

**O que a API pode fazer é não deixar a tela inventar o número.** A resposta do no-show devolve `penalidade` (o valor de `PONTOS_POR_NAO_COMPARECIMENTO`), `penalidadeTotal` (o acumulado do lead) e `scoreNovo`. Com isso a tela mostra o aviso com o número que o domínio de fato aplica, em vez de repetir um 15 escrito à mão em TypeScript que envelhece no dia em que a RN-12.4 mudar.

**Não há flag de confirmação no corpo.** Um `{"confirmado": true}` seria uma segunda trava para o mesmo mau clique que o botão de confirmação já cobre, e ela não protege de nada que um cliente automatizado não possa mandar junto.

Declarado: o cenário 3 do Gherkin (*"as ações não estão disponíveis"*) é sobre a tela. O que esta branch exercita é o correspondente de API — o 409 antes da hora.

## D8 — Quem marcou não fica registrado, e isso NÃO é construído aqui

`registrar_recalculo` grava a causa (`CAUSA_NAO_COMPARECIMENTO`) e **não grava o autor** — a assinatura não tem por onde recebê-lo. Então, depois desta card, o sistema terá uma ação humana, irreversível, que tira 15 pontos de um lead, e **nenhum registro de quem a fez**. A trilha de `lead_score_audit` diz que o score moveu e por quê; não diz por quem.

**Não construo isso aqui, e a razão é escopo.** A card não pede auditoria, e acrescentá-la custa um `Acao` novo, uma `Entidade` nova e uma migration recriando o CHECK da `0053` — foi exatamente o que a TEC-195 fez ontem, então o caminho é conhecido e barato, mas é decisão de quem define a política de trilha.

Vai no comentário da card como lacuna, com a recomendação concreta. A RN-18.4 (*"toda edição manual é registrada com autor e timestamp"*) é o argumento a favor; que ela esteja escrita sobre a edição de qualificação, e não sobre esta ação, é o argumento de que a decisão não é minha.

## D9 — A tensão da RN-12.4 continua de pé, e esta card a torna alcançável

A [TEC-375](https://eduardodurieuxlopes.atlassian.net/browse/TEC-375) registra que punir o no-show com score **faz o sistema desistir mais cedo de quem faltou**: a cadência da RN-13.1 é por temperatura, e 15 pontos podem rebaixar a faixa.

Até hoje isso era teórico, porque nada marcava no-show. **A partir desta card é alcançável em produção.** Implemento a RN-12.4 como escrita — é o que a TEC-172 já fez e o que o Gherkin desta card afirma — e a decisão continua sendo a TEC-375.

## Emendas ao SRS

- **RN-12.5, Emenda** — a transição para `REALIZADO` e `NO_SHOW` passa a exigir que o horário de início já tenha passado, e a recusa nomeia o status atual.
- **RF-12 / seção 6.4** — as duas rotas novas, com os três códigos.

## Fora do escopo

- **A tela** — depende da TEC-323 e da casca do dashboard.
- **Auditoria do autor** — D8, declarada.
- **Cancelar e remarcar pelo painel** — a card já os põe fora; hoje só o lead faz pela conversa.
- **A decisão da RN-12.4** — TEC-375.
