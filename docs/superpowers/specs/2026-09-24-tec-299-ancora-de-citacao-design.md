# TEC-299 — Citação por âncora em vez de número de linha, com gate no CI

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-299](https://eduardodurieuxlopes.atlassian.net/browse/TEC-299)
**Branch:** `feat/tec-299-ancora-de-citacao`
**Origem:** achado colateral da TEC-190 (PR #154).

## Objetivo

Fazer a citação de código em documento versionado parar de envelhecer em silêncio. Hoje ela é `arquivo.py` seguido de dois-pontos e número de linha, e a única marca assertiva do `scripts/comentarios_tocados.py` (`FALSO`, linha além do fim do arquivo) nunca dispara: medido na card, **0 de 213** citações resolvidas. Citação errada aponta para *outra* linha, não para além do fim.

A decisão, tomada na card com medição (comentário de 24/09/2026) e confirmada no desenho: **âncora nominal**, `arquivo.py::Nome`, verificada por `ast`, com gate no CI para as duas classes que não pedem julgamento nenhum.

## O que esta card não resolve, dito antes

**Os ~19% de citações que caem dentro de `_executar_turno` continuam imprecisas.** A função vai da linha 1038 à 3874 de `turno.py` — **2837 linhas** —, e ancorar ali diz "em algum lugar de uma função de 2837 linhas". A âncora continua *verificável* (o nome existe ou não), mas não *localiza*. Só partir a função resolve, e isso não é esta card. A convenção recomenda, para esse caso, acompanhar a âncora de uma frase citada do comentário-alvo, que o leitor acha por busca de texto.

**Âncora para arquivo que não existe não reprova.** Alvo que não resolve para nenhum `.py` versionado é ignorado, como a citação por linha já é hoje. Isso cobre de propósito o caminho que não é deste repo, e cobre sem querer o arquivo apagado ou renomeado — a mesma cegueira da TEC-284, que continua aberta.

## D1 — A forma: `arquivo.py::Nome`

A sintaxe de node id do pytest, que o repo já usa: medido no desenho, **45 citações** `::` em `docs/`, `README.md`, `CLAUDE.md` e `evals/` (fora de `plans/`), das quais **41 resolvem** e **4 estão quebradas** — as quatro da tabela de testes do desenho da TEC-126, que citam nomes de teste renomeados depois. A varredura por fim de arquivo nunca as acharia.

- `Nome` é pontuado para aninhamento: `workers/main.py::WorkerSettings.job_timeout`.
- Resolve contra **definições**, por `ast`: `def`, `async def`, `class`, e alvo `Name` de atribuição (`=`, anotada, e os `Name` de uma tupla desempacotada) no módulo ou dentro de classe/função. Blocos que não abrem escopo (`if`, `try`, `with`, `for`, `while`, `match`) são percorridos com o mesmo prefixo — um `def` dentro de `if TYPE_CHECKING:` continua sendo `modulo::nome`.
- **Import não conta.** `from x import y` não define `y`; citar `mod.py::y` para um nome só importado é apontar para o lugar errado.
- O caminho resolve pelo `resolver()` existente, nos mesmos três degraus.

**Ambiguidade de arquivo se resolve a favor da certeza.** `models.py::Conversa` casa com 13 `models.py`. A âncora é válida se o nome existe em **algum** candidato, e quebrada se não existe em **nenhum** — nos dois casos a conclusão vale para qualquer leitura da citação, então a marca continua sendo certeza. É a diferença essencial para a citação por linha, em que ambiguidade força `PROSA`.

**Arquivo que não parseia** conta como "não verificável", não como quebrado: falha de leitura não autoriza afirmar nada — o mesmo raciocínio de `tamanho_de` devolver `maxsize`.

## D2 — Duas marcas novas, as únicas que reprovam

- **`ANCORA`** — âncora quebrada, em qualquer `.md` do escopo. **Repo inteiro, não só arquivos que a branch mexeu.** O invariante passa a ser "toda âncora resolve", e esta branch conserta as 4 quebradas para ele nascer verdadeiro. Custo por execução: um `ast.parse` por arquivo citado, memorizado.
- **`LINHA`** — citação por número de linha (o `_CITACAO` de hoje) numa linha **adicionada** de `.md` nesta branch. Isso implementa sozinho o "converter quando tocar" que a card pedia: quem reescreve uma frase que traz citação antiga precisa converter aquela, e só aquela. As 228 antigas intocadas continuam onde estão.

**Bloco cercado (` ``` ` ou `~~~`) é isento de `LINHA`.** É onde vive traceback e saída do pytest (`tests/x.py` seguido de `:123: AssertionError`), que é citação de *saída*, não afirmação sobre o código. A isenção vale para `LINHA` só: âncora dentro de bloco cercado continua sendo verificada, porque âncora quebrada é falsa em qualquer contexto.

**Planos continuam fora das duas**, por `PREFIXO_DOS_PLANOS`, pela razão já escrita lá.

`ALTERADO`, `VIZINHO`, `PROSA`, `FALSO` e `NOMEIA` não mudam. Todas continuam informativas.

**A doutrina do script muda de formulação, não de substância.** A docstring dizia que ele "não vira gate" porque decidir se um comentário está certo é julgamento de pessoa. Isso continua valendo para as cinco marcas antigas. As duas novas reprovam porque não pedem julgamento: um nome existe ou não no `ast`; uma linha adicionada tem o padrão ou não.

## D3 — `--checar` e o passo no CI

`--checar` roda só a verificação das duas marcas novas, imprime cada ocorrência com documento e linha, e sai com **1** se houver alguma, **0** se não. Sem `--checar`, a listagem de sempre continua saindo com 0 e passa a mostrar `ANCORA` e `LINHA` junto das outras marcas de prosa — **fora do teto** de `MAXIMO_DE_CITACOES_POR_DOCUMENTO`, pela mesma razão que `FALSO` e `NOMEIA` escapam dele.

No CI, um passo novo no job **Lint e tipos**, depois do `mypy`:

```yaml
- name: citacoes em prosa
  if: github.event_name == 'pull_request'
  run: python scripts/comentarios_tocados.py "origin/${{ github.base_ref }}" --checar
```

- Só em `pull_request`: `LINHA` compara contra a base do PR, e num push para a `main` não há base que faça sentido.
- O checkout desse job passa a usar `fetch-depth: 0`. O diff é `base...HEAD`, por merge-base, e o clone raso padrão não tem o histórico para calculá-lo.
- `ANCORA` não depende da base, mas roda no mesmo passo: separar em dois passos seria duplicar a leitura dos documentos por uma distinção que ninguém usa.

## D4 — As quatro citações da card, e as quatro da TEC-126

Alvos conferidos contra a `main` em `dcb5db5`:

| spec | citava | vira |
| --- | --- | --- |
| TEC-222, "A excecao propaga…" | linhas 2160-2164 de `turno.py` | `turno.py::_executar_turno`, mantendo a frase citada, que é o que localiza |
| TEC-222, a exceção sobe | linha 2176 de `turno.py`, e o `except Exception` de `process_message.py` | `turno.py::_executar_turno` e `process_message.py::process_message` |
| TEC-295, `texto_com_oferta(corpo, texto)` | linha 2761 de `turno.py` | `turno.py::_executar_turno`, com a chamada citada |
| TEC-130, chamador de `encerrar_conversa` | linha 3745 de `turno.py` | `turno.py::_executar_turno` (fecho da RN-03.5), mais emenda |

**A emenda da TEC-130 conta três chamadores, não dois.** A card diz dois; o desenho achou um terceiro. Hoje `encerrar_conversa` é chamada em produção por: `turno.py::_executar_turno` duas vezes — o fecho da RN-03.5 (`FORA_DE_ESCOPO`) e o opt-out (`OPTOUT`) — e por `conversa/repositorio.py::encerrar_inativas`, a varredura por `INATIVIDADE` que a própria TEC-130 criou. A frase "o único chamador" era verdadeira no dia do desenho e deixou de ser pela implementação da mesma card. Entra como item aninhado **Emenda E-01 (TEC-299, 24/09/2026)** abaixo da afirmação, sem reescrevê-la.

**TEC-126**: os quatro nomes de teste da tabela passam para os de hoje em `tests/features/test_telemetria_de_mensagens.py`, na mesma ordem dos cenários Gherkin (`test_registrar_mensagem_de_entrada_do_lead`, `test_registrar_resposta_do_agente_com_custo`, `test_conteudo_pessoal_nao_vaza_para_o_log`, `test_falha_de_telemetria_nao_derruba_o_atendimento`), com o caminho completo.

## D5 — Onde a regra fica escrita

- **`CLAUDE.md`, seção "Comentário não mente"**: a convenção (`arquivo.py::Nome`, por quê, e a frase citada para dentro de `_executar_turno`), as duas marcas novas, e que elas reprovam no CI. Na mesma passada, o tamanho de `executar_turno` nesse arquivo é corrigido de 2706 para 2837 linhas.
- **Desenho da TEC-282**, que criou `PROSA`: nota aninhada apontando para este desenho.
- **Docstring do script**: sete marcas em vez de cinco, e a reformulação da doutrina do D2.

## Testes

Unitários em `tests/unit/test_comentarios_tocados.py`, sobre funções puras que recebem texto — sem disco e sem git, como os de hoje:

- extração de âncoras de um texto, inclusive pontuadas e dentro de bloco cercado;
- nomes definidos de uma fonte: `def`, `class`, aninhados, atribuição simples, anotada e de tupla, dentro de `if`; import **não** entra;
- âncora válida, quebrada, arquivo ambíguo com o nome em um candidato só, arquivo ambíguo sem o nome em nenhum, arquivo que não resolve (ignorado), arquivo que não parseia (ignorado);
- linhas dentro de bloco cercado, com ` ``` ` e `~~~`, e bloco não fechado até o fim do documento;
- `LINHA` só em linha adicionada, e não em linha adicionada dentro de bloco cercado;
- `--checar`: código de saída 1 com ocorrência e 0 sem.

A verificação de ponta a ponta é a própria branch: `--checar` contra `origin/main` precisa sair com 0 depois das correções do D4 — e, antes delas, precisa apontar exatamente as 4 âncoras quebradas da TEC-126.
