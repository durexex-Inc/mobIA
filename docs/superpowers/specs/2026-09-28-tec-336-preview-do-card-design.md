# TEC-336 — Pré-visualizar o card do imóvel como aparece no chat web

**Status:** desenhado em 2026-09-28.

**Card:** [TEC-336](https://eduardodurieuxlopes.atlassian.net/browse/TEC-336) — História, Could (MoSCoW), prioridade Medium. Origem: RN-FE-12.6 (SRS mobIA Frontend v1.0).

**A história:** *"Como Rafael, administrador da imobiliária, quero ver o card do imóvel exatamente como o visitante vai ver no chat, para conferir o anúncio antes de publicar."*

**Só frontend, e menor do que as cards anteriores.** As duas dependências — TEC-333 (gestão de imóveis) e "os cards de imóvel do widget" — já estão prontas: `components/CardDeImovel.tsx` (TEC-349) já existe, e a própria docstring dele já anuncia esta card: *"a pré-visualização da administração (TEC-336) desenha o mesmo componente"*. TEC-336 é a metade que faltava: um botão na edição de imóvel que abre esse componente com os dados do formulário.

## Um achado, fora do escopo desta card: fotos da TEC-335 não aparecem no card real

Antes do desenho: `CardDeImovel` só aceita foto via `lib/imovel.ts::urlSegura`, que exige uma URL **absoluta** `http:`/`https:` (`new URL(valor)`, sem base). A TEC-335 grava em `imovel.fotos[i]` um caminho **relativo** (`/api/v1/imoveis/{id}/fotos/{fotoId}`). Nenhum lugar do backend converte esse caminho para absoluto antes de montar `Ficha`/`card_de` (`domain/agente/apresentacao.py`). Consequência: hoje, subir uma foto pela TEC-335 não muda nada no card que o visitante vê — `urlSegura` recusa a URL relativa e o card cai no placeholder, silenciosamente.

**Esta card não conserta isso.** Corrigir exigiria decidir a topologia pública da foto (D2 da TEC-335 já declarou essa decisão como de uma card futura) — não é desta história, que é sobre um botão de pré-visualização, não sobre entrega de foto. **E é exatamente o motivo de existir desta card**: reusando o componente sem cópia (D1 abaixo), o formulário vai mostrar ao administrador a MESMA foto que falta hoje — o placeholder, não uma foto que só existe na tela de edição. Fingir que a foto aparece seria a pré-visualização mentir sobre o que o visitante realmente vê, que é o problema que ela existe para evitar. Fica registrado aqui para abrir uma card de correção depois, sem tocar nela agora.

## D1 — `imovelDe` converte o formulário, sem atalho para a foto

O componente (`CardDeImovel`) e o parser que valida o payload (`lib/imovel.ts::imovelDe`) não mudam. A pré-visualização monta um objeto cru, no mesmo formato camelCase de `card_de` (`domain/agente/apresentacao.py`), a partir do `Formulario`/`fotos` em memória, e passa por `imovelDe` — a MESMA função que validaria um payload de rede de verdade. **Não existe um caminho separado "de confiança" para os dados do formulário**: se `imovelDe` descartaria o card por um campo ausente ou malformado, a pré-visualização deve mostrar exatamente essa falha, não inventar uma versão mais tolerante. É o que garante que "o mesmo layout exibido no chat web" da card seja verdade, e não só a mesma aparência visual.

Consequência direta, já prevista acima: `foto` é `imovel.fotos[0] ?? null`, e `urlSegura` vai recusá-la se for o caminho relativo da TEC-335 — o mesmo destino que o card real teria.

## D2 — O botão só existe na edição, e só fica ativo com o formulário válido

Não há "pré-visualizar" no cadastro de um imóvel novo: sem um imóvel salvo não há nada que o Gherkin peça pré-visualizar (os dois cenários partem de "um imóvel ativo"/"um imóvel sem foto", ambos já existentes). O botão "Pré-visualizar card" fica **desabilitado enquanto `formularioValido(atual)` for falso** (`lib/imoveis.ts`) — assim a pré-visualização nunca precisa decidir o que mostrar para um formulário incompleto (preço ausente, tipo não escolhido), e não introduz um terceiro estado ("não dá para pré-visualizar ainda") que a card não pede.

## D3 — O preço é `precoVenda` se houver, senão `precoAluguel`

`ImovelCard.precoCentavos` é um número só; o imóvel tem até dois (D1 do desenho da TEC-333). Quando a operação é `AMBOS`, não há "o preço da operação buscada" — não há busca nenhuma, é uma pré-visualização. **Decisão pragmática, sem Gherkin que a exercite**: prioriza `precoVenda`; cai para `precoAluguel` só quando não houver venda. Documentado aqui porque é uma escolha, não uma regra que exista em outro lugar do repo.

## D4 — "Diferencial" é as duas primeiras características, juntas por "e" — mesma regra de `diferencial_de`

O card mostra um `diferencial`, string única; o formulário guarda `caracteristicas`, uma lista (D1 da TEC-333: "diferencial" da card é o campo `caracteristicas`). A tradução de lista para essa string já existe e é pequena: `apresentacao.py::diferencial_de` pega as duas primeiras (`CARACTERISTICAS_NO_DESTAQUE = 2`) e junta com `" e "`. **Reescrita à mão em TypeScript**, pela mesma razão que a TEC-334 (D1/D5) e a TEC-335 (D3) já aceitaram pequenas duplicações de regra pura entre Python e TypeScript quando não há uma rota HTTP razoável para compartilhar: é uma função de duas linhas, sem I/O, e testável dos dois lados.

## D5 — `url` é sempre nulo, como no card real

`card_de` sempre manda `url: None` (L1 do desenho da TEC-364: "o catálogo não guarda a página do imóvel no site do tenant"). A pré-visualização copia isso sem condição — nunca haveria uma URL para mostrar, então clicar no título da pré-visualização sempre expande a ficha (o mesmo comportamento do card real hoje, RN-FE-18.3 do componente).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Pré-visualizar alteração não salva | exercitado — o diálogo lê `atual` (D1), não `inicial`/o que está salvo |
| Imóvel sem foto | exercitado de graça — é o próprio `CardDeImovel` que desenha o placeholder (RN-FE-18.2), sem nada específico desta card |

## Fora de escopo

Corrigir a foto da TEC-335 não aparecer no card real (achado acima — decisão de uma card futura). Pré-visualizar um imóvel ainda não salvo (D2). Reações "Gostei"/"Não é pra mim" na pré-visualização — `CardDeImovel` já as omite sem `aoReagir`, e a card não pede simular reação.
