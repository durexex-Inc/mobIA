# TEC-337 — Configurar o agente com diff, confirmação e histórico de alterações

**Status:** desenhado em 2026-09-28.

**Card:** [TEC-337](https://eduardodurieuxlopes.atlassian.net/browse/TEC-337) — História, Should (MoSCoW), prioridade High. Origem: RF-FE-13, RN-FE-13.1 a 13.4 (SRS mobIA Frontend v1.0) · TEC-198.

**A história:** *"Como Rafael, administrador da imobiliária, quero ajustar tom, pesos do score e cadência de follow-up pela interface, para mudar o comportamento do agente sem esperar um deploy."*

**Full-stack, como a TEC-335.** O backend (TEC-198) está Feito e cobre a leitura, a escrita e o histórico — mas falta uma peça que a própria card exige por escrito (*"salvar usa `If-Match` com a versão"*) e que o terceiro cenário do Gherkin testa: **não existe controle de concorrência nenhum hoje**. `GET /agente` não expõe versão alguma, e `PATCH /agente` aplica a mudança direto sobre o que estiver vigente no instante da chamada, sem checar se é o mesmo que a tela leu. Decisão tomada com o Eduardo em 2026-09-28: construir essa peça nesta card, no mesmo padrão da TEC-335 (a card frontend que descobriu uma peça de backend faltando e a construiu).

## Decisão prévia (tomada com o Eduardo): domínios do widget ficam fora

A própria card tem um `[CONFIRMAR]` não resolvido: *"assumido que os domínios hospedeiros do widget (até 5 por tenant) também são cadastrados aqui; nenhum RF da spec cobre essa tela."* Confirmado com o Eduardo: **ficam fora**. Esta tela cobre só os sete campos que a seção de regras de negócio da própria card lista: nome do assistente, tom, teto de perguntas, os cinco pesos do score, a cadência e o orçamento mensal. `corPrimaria`, `posicaoDoBotao` (TEC-344) e `dominiosDoChat` (TEC-345) existem na mesma API e no mesmo formulário `PATCH`, mas pertencem à tela de aparência do widget — não a esta.

## D1 — A versão é o `id` da última linha de `versoes_da_configuracao`, exposta e conferida no backend

`VersaoDaConfiguracao.id` (UUID) já existe — é a chave de cada linha da tabela de histórico. Ele nunca saía da API. Duas mudanças em `api/routes/configuracao.py`/`domain/configuracao/repositorio.py`:

- **`GET /agente` ganha o campo `versao`**: o `id` da última versão gravada, como string, ou `null` quando ninguém nunca editou (a vigente é o `padrao()` hardcoded, sem linha na tabela). Uma função nova, `id_da_vigente(session) -> uuid.UUID | None`, ao lado de `configuracao_vigente` — não muda a assinatura desta (outros leitores, como o turno do agente, continuam recebendo só `ConfiguracaoDoAgente`).
- **`PATCH /agente` aceita `seVersao: str | None`, opcional** (ausente = sem checagem, mesmo padrão "ausente não muda" do resto do corpo). Quando presente, compara com `id_da_vigente(session)` **antes de validar ou aplicar qualquer mudança** — em desacordo, `409` com uma mensagem que nomeia o motivo, e nada é gravado (o terceiro cenário: "nada é sobrescrito"). `null` explícito compara contra "ninguém editou ainda" (também `None`), pelo mesmo motivo que `dominiosDoChat` distingue ausente de `null` neste arquivo.

**Sem lock, sem transação serializável.** A checagem lê a vigente, compara, e só then aplica — a mesma janela de corrida que a D7 do desenho da TEC-196 já aceitou para corretor duplicado: dois administradores salvando no mesmo instante exato ainda poderiam passar os dois pela checagem. Para uma tela de configuração com poucos administradores, cobrir essa fração de segundo com lock explícito seria complexidade que o Gherkin não pede — ele pede que uma edição SEGUIDA (não simultânea ao milissegundo) seja detectada, e é isso que a comparação de versão garante.

## D2 — As faixas de validação vêm de `GET /agente`, nunca hardcoded

A própria card manda: *"validação no cliente com as faixas do schema do backend."* `GET /agente` já devolve `limites` — min/máximo de cada campo, já pronto (`_LIMITES` em `configuracao.py`) — exatamente para a tela não guardar uma segunda cópia (o comentário do próprio arquivo já diz isso). **A tela usa esse objeto direto**, sem reescrever `PESO_MAXIMO`/`TETO_MAXIMO_DE_PERGUNTAS`/etc. em TypeScript. É a única das cards de imóveis/corretores em que os limites nunca precisaram de duplicação entre Python e TypeScript — o backend já foi desenhado para isso.

## D3 — A cadência é uma grade de campos fixos, não uma lista editável

`_LIMITES.cadencia.tentativasPorTemperatura` diz quantos intervalos cada temperatura tem (`QUENTE`/`MORNO`/`FRIO`) — e a quantidade é **fixa** (D5 do desenho da TEC-198: "está no CASE SQL do corte de candidatura"). A tela não permite adicionar/remover tentativa: para cada temperatura, exatamente `tentativasPorTemperatura[temperatura]` campos numéricos (horas), com a MESMA validação client-side "campo vazio" das outras telas — a faixa (`horaMinima`/`horaMaxima`) e a regra de "crescente" (cada intervalo maior que o anterior) são mostradas como dica, mas a validação de faixa/crescente em si só acontece no backend, cuja mensagem (uma string só, `ConfiguracaoInvalida`) é mostrada como veio — mesmo padrão D2 da TEC-333/TEC-334.

## D4 — O diff de confirmação compara só os campos desta tela, com o mesmo texto do valor

A card pede: *"antes de salvar, mostra o diff 'valor atual → novo valor' e pede confirmação."* A tela monta esse diff comparando o `Formulario` inicial com o atual, campo a campo — mesma função `pedidoDeEdicao`-like das outras telas (só o que mudou), mas aqui o resultado alimenta um DIÁLOGO de confirmação antes do `PATCH`, não o `PATCH` direto. Cada linha do diff mostra o texto tal como o campo aparece no formulário (`"5 → 3"`, `"Mia → Lia"`) — sem reformatar peso/hora/dinheiro de um jeito e o formulário de outro, para o que a confirmação mostra ser literalmente o que será salvo.

## D5 — 409 mostra "recarregar", e recarregar é buscar a configuração de novo

O terceiro cenário: *"a tela informa que a configuração mudou e oferece recarregar."* Um botão que refaz o `GET /agente` (nova `versao`, nova vigente) e substitui o formulário — descartando a edição em andamento, como o próprio Gherkin implica ("nada é sobrescrito", nem a mudança do outro admin nem a de Rafael). Não tenta mesclar as duas edições: a card não pede isso, e mesclar automaticamente é o tipo de mágica que esconde o que realmente aconteceu.

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Revisar a mudança antes de salvar | exercitado (D4) |
| Recusar valor fora da faixa | exercitado — client-side com `limites` (D2), backend sempre confere de novo |
| Configuração alterada por outra pessoa | exercitado — `seVersao`/`409` (D1), "recarregar" (D5) |
| Histórico de alterações | exercitado — `GET /agente/historico` já devolve autor/data/mudanças, mais recente primeiro |

## Fora de escopo

Domínios do widget, cor primária e posição do botão (decisão prévia — pertencem à tela de aparência, TEC-344/345). Lock/transação serializável para a corrida de milissegundo entre duas gravações simultâneas (D1 — aceito, mesmo argumento da D7 da TEC-196). Mesclar duas edições concorrentes (D5).
