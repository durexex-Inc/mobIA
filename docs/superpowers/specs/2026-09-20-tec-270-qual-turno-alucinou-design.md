# TEC-270 — O relatório diz qual turno alucinou

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-270](https://eduardodurieuxlopes.atlassian.net/browse/TEC-270) — épico TEC-208
**Branch:** `feat/tec-270-qual-turno-alucinou`
**Origem:** RNF-26 (SRS v1.0); RT-01. Continua a TEC-269.

## Objetivo

Fazer o relatório do gate dizer **quais** turnos citaram cifra ou código sem base, em vez de só quantos. O dado já é coletado e descartado: `InvencaoObservada.divergencias` chega em `_metricas_de` e para ali.

## O que a exploração mudou em relação ao texto da card

**O terceiro critério de aceite já está satisfeito na origem, e isso muda o que ele vira.** A card manda formatar o valor citado com `reais_de` em vez de centavos. Mas `Divergencia.citado` (`domain/agente/citacao.py`) **já chega formatado** — o comentário de lá registra a mesma razão que a card cita, a D10 da TEC-161: `_mascarar_digitos` come corridas de 10 a 15 dígitos, e R$ 10 milhões em centavos são exatamente dez. O relatório só imprime o campo. O critério continua valendo, mas como **guarda contra regressão**, não como transformação a escrever.

**A seção vizinha faz o oposto do que esta card exige, de propósito.** `_secao_de_formato` imprime `violacao.texto` — a prosa do agente — e o comentário de lá justifica: corpus fictício, fala do agente, e sem o texto não dá para separar duas perguntas de verdade de erro do proxy de `?`. Aqui a prosa é proibida, pela regra da TEC-161: registrá-la recria no artefato aquilo que a guarda impediu de sair.

As duas coisas são certas ao mesmo tempo, e a diferença **tem de estar escrita no código**. Sem isso, a próxima pessoa que ler as duas seções lado a lado uniformiza a mais nova pela mais velha e reintroduz a prosa.

## D1 — `ResumoDaInvencao`, no molde das outras cinco seções

Dataclass nova em `metricas.py`, mais `resumo_da_invencao(invencoes, respostas)`, espelhando `ResumoDoFormato`/`resumo_do_formato` sem inventar forma nova:

```python
@dataclass(frozen=True)
class ResumoDaInvencao:
    respostas: int
    turnos: list[InvencaoObservada]
```

**O `respostas` é o que faz a seção poder dizer zero.** Uma seção montada só a partir da lista de invenções desaparece quando a execução está limpa — e seção que some quando está tudo bem treina o leitor a não procurá-la, que é exatamente a regra da card. Com o total dentro do resumo, o parâmetro de `render` é `None` só quando não houve medição nenhuma, e não quando a medição deu zero.

A alternativa — passar `invencoes` e o total soltos para `render` — foi recusada: as cinco seções de diagnóstico existentes recebem um `Resumo*`, e a sexta com assinatura própria obrigaria todo leitor a descobrir por que aquela é diferente.

## D2 — A seção, e o que ela não imprime

`_secao_de_invencao` em `relatorio.py`, no molde de `_secao_de_formato`:

```
## Ancoragem: turnos que citaram sem base (diagnostico)

- 147 turnos medidos
- turnos com cifra ou codigo sem base: 1

Onde:

  - conversa-12 turno 3: preco -- R$ 1.250.000
```

Três decisões dentro dela:

**A prosa do turno não entra, e o docstring diz por que a vizinha imprime a dela.** É a única defesa contra a uniformização futura — e o repo já tem o precedente inverso: a TEC-146 mostrou que comentário errado sobrevive a duas revisões porque quem lê acredita nele.

**O valor sai como `citado` chega**, sem reformatar. Reformatar aqui criaria uma segunda conta de formatação de dinheiro no repo, e a primeira já mora em `citacao.py` com a razão escrita.

**Um turno com duas divergências aparece uma vez por divergência**, sob o mesmo endereço. É o que `_secao_de_formato` faz com violações, e é o que permite ver que o turno inventou preço *e* código — informação que uma linha por turno esconderia.

## D3 — A linha que faltava no runner

`evals/test_acuracia_de_intencao.py` já acumula `invencoes` e já as passa para `_metricas_de`. Passa a passá-las também para `render`, via `resumo_da_invencao`. É uma linha, e é toda a mudança no runner — o que confirma o diagnóstico da card: o dado estava pronto e ninguém o entregava.

## Testes

* A execução com dois turnos inventando: a seção existe e lista os dois, com conversa, índice, tipo e valor.
* A execução limpa: a seção existe e declara zero.
* **A prosa não aparece:** um turno cuja prosa é um sentinela reconhecível, e a asserta é que o sentinela não está no relatório. Guarda de verdade, e não observação — `InvencaoObservada` nem carrega a prosa, então o teste prende a impossibilidade estrutural de hoje contra alguém que amanhã acrescente o campo.
* **O valor sai legível:** um `citado` de `R$ 10.000.000` aparece com os pontos de milhar, e a corrida de dez dígitos não aparece em lugar nenhum.
* Um turno com duas divergências produz duas linhas sob o mesmo endereço.

## O que este desenho não entrega

Trocar o piso-andaime de 50% por piso medido (card própria, precisa de histórico). Qualquer mudança na guarda da TEC-161 ou no que conta como alucinação — aqui só se mostra o que já é contado. E o relatório continua sem dizer **por que** o turno inventou: para isso seria preciso a prosa, que é justamente o que não pode entrar.
