# TEC-396 — a configuração do agente no visual do painel

Card: TEC-396. Épico: TEC-308. Continua a TEC-395, de quem herda `Trilha`, `Selo`, `Cartao`, `Botao`, `CampoDeSelecao` e as classes `.campo`/`.secao`. Referência: imagem de `/admin/configuracao` enviada por Eduardo em 08/10/2026.

## O que muda

Só a aparência de `/admin/configuracao`. Validação pelos `limites` (D2 da TEC-337), confirmação por diff antes do `PATCH` (D4) e "Recarregar" no 409 (D5) continuam iguais.

## Decisões

**D1 — Três módulos em cartões, mais o rodapé do orçamento.** "Identidade e limites" (nome, tom, teto), "Pesos de qualificação" e "Cadência de follow-up", cada um com o sobretítulo "Módulo 0n" da referência. Orçamento e os botões ficam num cartão próprio no fim do formulário, como na referência.

**D2 — A soma dos pesos é calculada ao vivo e é só indicador.** Mostra `soma / limites.pesos.somaMaxima` e "Configuração válida" quando a soma está entre 1 e o máximo, "Fora da faixa" quando não. Não trava o "Salvar": quem recusa a soma continua sendo o backend, como hoje — mesma regra do selo de limite da TEC-395 (D2 de lá). Campo vazio ou não numérico conta como 0.

**D3 — Os pesos não levam "%".** A referência põe "%" em cada peso, mas a soma pode ficar abaixo de 100; o número não é percentagem. Fica sem unidade.

**D4 — "Redefinir" volta ao que foi carregado**, sem rede: devolve o formulário à linha de base local e limpa recusa e diff. Fica desabilitado quando nada mudou. O botão de envio passa a se chamar "Salvar configurações", como na referência.

**D5 — Cada disparo da cadência é rotulado "Nº disparo"**, e o nome acessível passa de "Quente, intervalo 1" para "Quente, 1º disparo" — o nome que se ouve tem de conter o que se vê.

**D6 — O nome acessível dos pesos continua "Peso de urgência"** etc.; o rótulo visível é "Urgência", e o "Peso de" fica num `span` só para leitor de tela. Os mesmos nomes aparecem no diff de confirmação e no histórico (`ROTULOS_DE_CAMPO`).

**D7 — Os textos de ajuda dizem o que o campo faz no código, não o que a referência diz.** O orçamento, em especial: a referência fala em "limite máximo de consumo para evitar estouro", mas `orcamento_mensal_usd` só alimenta o alerta do painel de custo (`api/routes/metricas.py`) — nada interrompe o agente. O texto diz isso.

**D8 — A confirmação continua inline (`role="alertdialog"`), agora num cartão.** Trocar por `<dialog>` modal mudaria comportamento, não aparência.

## Lacunas

- **L1** — "v2.4-prod", "Status do Pipeline: operando normalmente" e "Agente Autônomo Ativo" não têm fonte: a API de configuração não traz rótulo de versão legível (a `versao` é um token de concorrência) nem estado de pipeline ou do agente. Ficaram de fora.
- **L2** — O histórico continua mostrando o autor como `uuid` (TEC-337): não há consulta de nome.
