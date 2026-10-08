# TEC-399 — a trilha de auditoria no visual do painel

Card: TEC-399. Épico: TEC-308. Continua a TEC-398, de quem herda `Trilha`, `Selo`, `Cartao`, `.campo`, `.campo-selecao` e `.painel__descricao`. Referência: imagem de `/admin/auditoria` enviada por Eduardo em 08/10/2026.

## O que muda

Só a aparência de `/admin/auditoria`, mais o link "Limpar filtros". Filtros, cursor, "Carregar mais" e a ausência de qualquer ação por linha (cenário 2 da TEC-343) continuam iguais.

## Decisões

**D1 — Fica de fora tudo o que a referência mostra e a API não sustenta.** `GET /api/v1/auditoria` é uma lista por cursor, sem total e sem agregado. Não entram: os quatro cartões de estatística ("Total de registros", "Acessos negados (24h)", "Mutação de dados", "Integridade do ledger"), "Exibindo 4 de 256", a paginação numerada, "Exportar relatório", "Criptografia SHA-256 ativa", "Sync com ledger" e "Stream em tempo real". Nenhum desses existe no backend; mostrar número ou selo fixo seria afirmar o que ninguém mede.

**D2 — O selo "Imutável" entra, porque é verdade.** O trigger `eventos_auditoria_imutavel` (migration 0053) recusa `UPDATE` e `DELETE` na tabela.

**D3 — O tipo de evento vira selo, com cor por categoria** (`categoriaDaAcao`, em `lib/auditoria.ts`): recusa e risco (`ACESSO_NEGADO`, `INJECAO_DETECTADA`, `TITULAR_RECUSADO`) em vermelho; alteração (`QUALIFICACAO_ALTERADA`, `CONFIGURACAO_ALTERADA`, `PROMPT_PUBLICADO`, `PROMPT_REVERTIDO`) em azul; o resto neutro. A cor reforça, o texto continua dizendo o tipo.

**D4 — "Quem" ganha a inicial do tipo de ator** (U, A, S), decorativa, e o identificador vai numa segunda linha, cortado com reticências por CSS — o texto inteiro continua no DOM e no `title`.

**D5 — A contagem diz o que está na tela**: "N eventos carregados", não "N de total".

**D6 — "Limpar filtros" é um link para `/admin/auditoria`**, e só aparece com algum filtro ativo.

## Lacunas

- **L1** — A trilha da referência é "Administração / Segurança / Trilha de auditoria". Não existe página "Segurança"; a trilha é "Administração / Trilha de auditoria".
