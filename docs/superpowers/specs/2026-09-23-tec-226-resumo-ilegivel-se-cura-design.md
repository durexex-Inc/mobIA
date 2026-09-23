# TEC-226 — O resumo ilegível se cura em vez de repetir a chamada todo turno

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-226](https://eduardodurieuxlopes.atlassian.net/browse/TEC-226) — épico TEC-123
**Branch:** `feat/tec-226-resumo-ilegivel-se-cura`
**Origem:** review final da branch `feat/tec-127-janela-contexto`, achado no próprio diff da onda de correção.

## Objetivo

Tornar verdadeira a promessa que o README e o comentário do código já fazem — *"a próxima dobra sobrescreve a linha corrompida"* — numa janela em que ela era falsa, e tirar a invisibilidade que permitiu que ela fosse falsa sem ninguém notar.

## O defeito, confirmado no código antes de qualquer mudança

A cadeia fecha em quatro passos, todos verificáveis:

1. `ler_resumo` levanta `DecryptionError`; `montar_contexto` degrada com `resumo_atual = None`.
2. `marca_de(None)` devolve `None` — **a marca guardada junto com o texto corrompido é descartada**.
3. `literais_apos(..., None)` devolve a conversa inteira, e `_dobrar` calcula `nova_marca` a partir do último item dobrado — que pode ser **mais antigo** que a marca que ficou na linha.
4. `gravar_resumo` tem `where watermark_created_at <= excluded.watermark_created_at`. Marca mais antiga ⇒ a condição é falsa ⇒ **no-op silencioso**.

Reproduzido em teste, e o teste reprova sem a correção:

```
Failed: a linha ilegivel continuou ilegivel: a dobra virou no-op na guarda de
monotonia, e o proximo turno paga tudo de novo
```

### Por que os testes existentes não pegavam

`test_resumo_ilegivel_e_sobrescrito_pela_proxima_dobra` põe a marca em `criadas[0]` — a mensagem **mais antiga** da conversa. Qualquer dobra que comece do início a ultrapassa, a guarda deixa passar, e a cura acontece. O teste é honesto e continua valendo; ele só exercita o lado fácil.

O novo põe a marca em `criadas[-1]`, a mais **recente**. É o pior caso determinístico: nenhuma dobra que comece do início pode alcançá-la, então não depende de `contexto_literais_minimas` nem de quantas mensagens a conversa tem.

## D1 — A linha corrompida é apagada, não ignorada

É a correção que a card chama de mais barata, e continua sendo a certa depois de olhar o código: sem linha, não há marca velha, e a dobra seguinte grava normalmente.

A alternativa que a card levanta — carregar a marca guardada através do caminho degradado — foi descartada pela razão que a própria card antecipa: preservaria a cobertura registrada, mas deixaria um resumo **vazio** cobrindo aquele intervalo. As mensagens daquele trecho voltariam a não aparecer nem no resumo nem nos literais. Apagar é o que mantém a invariante que o comentário do degradado já promete: *sem marca, tudo volta literal — nada some, só cresce*.

O `apagar_resumo` não commita, pela mesma disciplina de `gravar_resumo`: a sessão é emprestada. Quem commita é `montar_contexto`, que é dono daquela sessão.

## D2 — O upsert deixa de ser mudo

`gravar_resumo` passa a devolver `bool` — `True` quando escreveu, `False` quando a guarda recusou —, lido do `rowcount` do `ON CONFLICT DO UPDATE ... WHERE`.

**Isto não é acessório da D1, é a outra metade da card.** A D1 conserta este defeito; a D2 é o motivo de ele ter durado. Três turnos seguidos pagaram uma chamada ao resumidor, e nem o código nem o log tinham como dizer que a escrita não aconteceu. `_dobrar` passa a logar `contexto.resumo_nao_gravado` quando recebe `False`.

**O log é `info`, não `warning`, e de propósito.** No caso para o qual a guarda existe — dois turnos concorrentes — recusar é o comportamento correto, e um `warning` treinaria quem lê a ignorá-lo. O que se quer é que a linha exista para ser encontrada quando alguém for investigar chamada repetida.

## D3 — O `contexto.resumo_ilegivel` ganha discriminador, e o comentário para de mentir

O comentário afirmava que *"só o tipo do erro vai para o log"*. A chamada passava **apenas** `channel`. É a classe de defeito que o CLAUDE.md trata como bug, não como sujeira — e aqui o comentário descrevia uma intenção que o código nunca teve.

Passam a ir `reason=type(exc).__name__` e `marca_do_aad=...`. Sem eles, um erro global de chave — incidente — é indistinguível de uma escrita parcial isolada — uma linha ruim. O critério é o mesmo que `_dobrar` já aplicava corretamente.

## D4 — `marca_do_aad` vira HMAC com subchave derivada

O segundo item menor da card, e o de maior consequência.

`_marca_do_aad` era `sha256(aad)[:12]`, **sem sal**. O AAD de resumo é montado a partir de `(channel, conversation_key)`, e `conversation_key` é o telefone do lead. Telefone brasileiro tem formato conhecido e espaço de busca pequeno: quem obtivesse o log reconstruiria o número por força bruta em tempo trivial. A função existe exatamente para impedir isso, então ela não estava cumprindo o que promete.

Passa a ser `HMAC-SHA256` com subchave derivada por **HKDF** da `content_encryption_key`, com `info=b"mobia/marca-do-aad/v1"`.

**Por que subchave derivada e não segredo novo:**

- Nenhuma entrada nova no `config.py` — nada a provisionar, nada a rotacionar por fora, nenhum caminho novo para o segredo vazar.
- O `info` próprio dá separação de domínio: a subchave não é a chave de cifragem, então ela não é reuso de chave entre algoritmos.

**Consequência aceita, e declarada:** trocada a `content_encryption_key`, as marcas mudam. Elas servem para correlacionar linhas de log dentro de uma janela de incidente, não para identificar uma conversa ao longo de meses — perder a correlação através de uma rotação não custa diagnóstico. Há teste fixando esse comportamento, para que seja decisão visível e não surpresa.

A função deixa de ser privada, porque `montagem.py` passa a usá-la. O nome curto (`marca_do_aad`) é o mesmo que a docstring de `montar_contexto` já citava.

## O que este desenho não entrega

**Rotação de chave.** Continua fora de escopo, como o comentário de `VERSAO_ATUAL` já registra. A D4 não a aproxima nem a afasta.

**A janela entre a corrupção e o turno seguinte.** O resumo daquele trecho está perdido — foi o `decrypt` que falhou, não este código. O que a card entrega é que a conversa volte ao normal no turno seguinte em vez de vinte mensagens depois; o conteúdo do resumo antigo não volta, e nada pode trazê-lo.

**Nenhuma varredura por outros upserts mudos.** A D2 conserta o de `gravar_resumo`, que é o que a card nomeia. Se há outro `on_conflict_do_update ... where` no repositório cujo no-op passa despercebido, não foi procurado.
