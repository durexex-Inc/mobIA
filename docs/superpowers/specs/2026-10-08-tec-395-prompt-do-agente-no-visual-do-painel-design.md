# TEC-395 — a página de prompt do agente no visual do painel

Card: TEC-395. Épico: TEC-308. Continua a TEC-393 e a TEC-394, de quem herda tokens, `Cartao`, `Botao` e `CampoDeSelecao`. Referência: imagem de `/admin/prompts/investidor` enviada por Eduardo em 08/10/2026.

## O que muda

Só a aparência de `/admin/prompts/[agente]`. Publicar, comparar por `?de=&para=` e reverter com confirmação pelo número da versão continuam iguais (TEC-338, TEC-339).

## Decisões

**D1 — O Monaco acompanha o tema por `useTemaAtual`.** O editor pinta por JS e não lê variável CSS, então o hook observa `data-tema` no `<html>` (o botão da TEC-393) e o `prefers-color-scheme`, e o editor troca de tema sem recarregar. Os dois temas (`mobia-claro`, `mobia-escuro`) repetem em hex os tokens `--superficie` e `--primaria` — o único lugar do painel onde cor de token é duplicada, dito no comentário de `TEMA_DO_MONACO`.

**D2 — "Variáveis detectadas" e "Dentro do limite" são derivados do texto, no cliente.** `marcadoresNoTexto` usa a mesma forma de `{marcador}` do realce e do backend. O selo compara o tamanho com `maximoDeCaracteres`; continua sendo indicador, não trava — quem recusa é o 422 do backend (D5 da TEC-338).

**D3 — A versão ativa entra na lista, marcada "Em produção" e sem "Reverter".** A referência a mostra; reverter para a vigente não mudaria nada. A versão 0 é o texto do código e entra sempre, por último quando não é a ativa.

**D4 — O botão continua "Reverter para esta versão", e não "Restaurar".** É o verbo do diálogo de confirmação ("Confirmar reversão") e da TEC-339; trocar só o botão criaria dois nomes para a mesma ação.

**D5 — O diff continua sendo o `DiffEditor` do Monaco.** A referência desenha dois painéis de texto; o Monaco já faz o lado a lado com realce de diferença, e trocar por texto estático perderia exatamente o que a tela existe para mostrar. Os cabeçalhos "Origem"/"Destino" ficam por cima dele.

**D6 — Peças novas genéricas em `components/ui/`:** `Selo` (o "Badge") e `Trilha` (o "Breadcrumb"). `ListaDeVersoes` sai da página para `components/prompts/`, por ter regra de ordenação própria.

## Lacunas

- **L1** — A referência mostra, por versão, a contagem de caracteres e uma descrição ("Prompt base inicializado…"). Nenhuma das duas existe na API: `VersaoResumida` não traz texto nem descrição. Ficaram de fora.
- **L2** — A barra do editor mostra `agente · versão N`, e não um nome de arquivo como na referência: não há arquivo.
- **L3** — A trilha diz "Prompts", o título real da listagem, e não "Agentes".
