# TEC-222 — `last_error` só com o nome da exceção

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-222](https://eduardodurieuxlopes.atlassian.net/browse/TEC-222) — épico TEC-123
**Branch:** `feat/tec-222-last-error-so-com-o-nome-da-excecao`
**Origem:** review final da branch `feat/tec-126-telemetria`.

## Objetivo

Fazer com que conteúdo de lead não possa ficar legível em `messages.last_error` — por construção, e não por disciplina de quem escreve a próxima exceção.

## O que a exploração mudou em relação ao texto da card

**O vazamento que a card descreve já está fechado, e o que sobrou é outro.** A card diz que `process_message.py` persiste `f"{type(exc).__name__}: {exc}"` em `last_error`. Isso deixou de ser verdade na TEC-134 (`d069f3e`, 26/08/2026): desde ela, `_detalhe_do_erro` grava o texto **apenas** para exceção cujo `__module__` seja `mobia` ou comece com `mobia.`; de qualquer outra, só o nome da classe.

Medido nesta máquina, contra o Postgres real, com o caso exato que a card reproduz — `insert()` de Core com `str` numa coluna `bytea`, que passa ao largo do `@validates` do ORM:

```
tipo                     : DBAPIError
modulo                   : sqlalchemy.exc
str(exc)[:200]           : "(sqlalchemy.dialects.postgresql.asyncpg.Error) <class
                            'asyncpg.exceptions.DataError'>: invalid input for query
                            argument $5: 'quero apto na zona sul, meu telefone 55...
                            (a bytes-like object is required, not 'str')"
_detalhe_do_erro(exc)    : 'DBAPIError'
sentinela em last_error? : False
```

Os dois lados da medição importam. O eco do driver **existe** — o asyncpg embute o valor ofensivo na mensagem, e o `[SQL parameters hidden due to hide_parameters=True]` aparece na mesma string, logo abaixo, sem alcançá-lo. E a exceção que chega é `DBAPIError` de `sqlalchemy.exc`, não de `mobia`, então o critério da TEC-134 a corta para o nome da classe.

**O eco é truncado em 38 caracteres**, e isso não é detalhe de rodapé — é o que decide como o teste T1 pode ser escrito. Medido: o asyncpg corta o valor em 38 e acrescenta `...`, então um sentinela mais longo que isso **nunca** aparece inteiro em `str(exc)`, e uma asserção `sentinela in str(exc)` sobre ele passaria a falsa impressão de que o driver não ecoa nada. Um sentinela de 37 caracteres aparece inteiro. O teste usa um curto, por isso.

**O defeito real é o critério, e não o caminho do asyncpg.** O critério da TEC-134 é, palavra por palavra, *"excecao definida em `mobia` teve a mensagem escrita aqui dentro e sabe-se o que ela carrega"*. Ele confunde **dono do tipo** com **dono da mensagem**. São coisas diferentes, e existe exatamente um sítio onde divergem.

## O único caminho de vazamento que existe hoje

`ModeracaoIndisponivel` é definida em `domain/moderacao/port.py:19` — portanto `mobia.*`, portanto a mensagem inteira vai para a coluna. Mas o texto dela não foi escrito aqui dentro:

```python
# infra/moderacao.py:176
raise ModeracaoIndisponivel(motivo_do_provedor(exc) or type(exc).__name__) from exc
```

`motivo_do_provedor` (`infra/anthropic.py:173`) devolve até 300 caracteres da `error.message` de um `APIStatusError` — prosa que o servidor da Anthropic escreveu em resposta a uma requisição cujo corpo é o texto moderado.

O caminho até a coluna é direto e está declarado por escrito no código. Na moderação de **saída** não há falha aberta, de propósito (`turno.py:2160-2164`: *"A excecao propaga: a linha vira FAILED com `attempts` e o sweeper retenta"*). Ela sobe de `turno.py:2176` ao `except Exception` de `process_message.py:291`, e de lá para `_marcar_falha`.

**De onde vem a aceitação do risco, e o quanto ela cobre este destino.** O docstring de `motivo_do_provedor` (`anthropic.py:200-210`) admite o risco por escrito e o limita com três coisas: o teto de caracteres, o mascaramento de dígitos de `app/logging.py`, e o formato da chamada do classificador.

**Uma das três, e só uma, é propriedade do log.** O teto é aplicado dentro da própria `motivo_do_provedor` (`mensagem[:MAX_CARACTERES_DO_MOTIVO]`), antes de qualquer destino; o formato da chamada é propriedade de como a requisição é montada, também anterior a qualquer destino. Os dois protegem a coluna exatamente como protegem o log. O que a coluna perde é o mascaramento — e ele alcança corrida de 10 a 15 dígitos contíguos e mais nada, de modo que sobre prosa em inglês de um SDK é quase um no-op.

> Esta é uma correção: a primeira versão deste desenho afirmava que **duas** das três eram propriedades do log e que "em `last_error` só o teto sobrevive". Era falso, e a revisão da Task 1 pegou. Fica registrado em vez de apagado porque a conta errada é o tipo de coisa que volta a ser feita quando some.

**A consequência é que a diferença entre os dois destinos é menor do que parece — e não é dela que sai a decisão.** A decisão sai de duas outras coisas, e elas bastam: a coluna é **durável** (o log rotaciona; a linha fica), e o **critério não se sustenta**, pelo argumento da seção anterior. O risco de `motivo_do_provedor` foi avaliado contra um destino e acabou valendo para outro sem que ninguém tomasse essa decisão — mas o que justifica mudar não é o tamanho desse delta, é o critério.

Levantamento exaustivo das 16 classes de exceção de `src/mobia/`: todas as outras 15 interpolam apenas literais, inteiros, enums, `type(...).__name__`, hashes de AAD ou nomes de coluna. O repositório é disciplinado nisso, com comentários explícitos recusando a interpolação em `whatsapp.py:92-93`, `classificador.py:1424-1425`, `moderacao.py:169-175` e `crypto.py:43-54`. `motivo_do_provedor` é a exceção deliberada (TEC-237) — e é justamente ela que atravessa.

## D1 — Separar os dois destinos, em vez de procurar um critério melhor

`_detalhe_do_erro` serve hoje a dois destinos com o mesmo valor: a coluna (`_marcar_falha`) e o log (`message.failed`, `message.cancelled`). As garantias dos dois são diferentes, e é essa confusão que produz o defeito. A correção é deixá-los divergir.

**A coluna passa a guardar `type(exc).__name__`, sempre.** Sem ramo e sem critério. A garantia deixa de depender de todo autor futuro de exceção ter sido cuidadoso e passa a valer por construção — que é exatamente o que o critério de pronto da card pede: *"uma falha de processamento cujo texto de exceção contenha conteúdo de lead não deixa esse conteúdo legível"*. Nenhuma formulação que preserve algum texto consegue prometer isso, porque a promessa teria de cobrir exceções que ainda não foram escritas.

**O log mantém o texto, pela regra atual da TEC-134.** Ali o mascarador alcança o valor — fracamente, mas alcança — e o raciocínio da TEC-237 se aplica como foi escrito, contra o destino para o qual foi escrito. Não mexer nele é não reabrir uma decisão que já foi tomada com os olhos abertos.

Em código, a função de hoje se parte em duas, com nomes que dizem o destino:

```python
def _detalhe_para_a_coluna(exc: BaseException) -> str:
    return type(exc).__name__


def _detalhe_para_o_log(exc: BaseException) -> str:
    modulo = type(exc).__module__
    if modulo == "mobia" or modulo.startswith("mobia."):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__
```

`_detalhe_para_o_log` é a função de hoje, intacta — o que muda é só que ela deixa de alimentar a coluna. Os dois chamadores (`except Exception` e `except asyncio.CancelledError`) passam a chamar as duas.

**O que se perde, dito sem rodeio.** `last_error` deixa de distinguir `RespostaInvalida: resposta veio vazia` de `RespostaInvalida: campo confianca fora do intervalo`. Quem olhar só a linha no banco vê `RespostaInvalida` e precisa do log para saber qual das duas. É aceito porque o log de `message.failed` carrega a diferença no mesmo instante, e porque a card afirma que o nome da exceção mais o `attempts` respondem à pergunta que a coluna existe para responder.

**Por que não a opção 2 da card (cifrar `last_error`).** Cifrar guarda o diagnóstico inteiro, mas troca uma coluna que se lê com um `SELECT` por uma que exige a chave e uma chamada a `decrypt` — e `last_error` existe justamente para o diagnóstico rápido. O custo recai inteiro sobre o uso legítimo da coluna, para preservar um texto cujo valor incremental sobre o nome da classe é pequeno e que o log já tem.

**Por que não corrigir só na origem.** Tirar `motivo_do_provedor` da mensagem de `ModeracaoIndisponivel` fecharia o único furo de hoje e manteria o critério da TEC-134 intacto. Foi considerado e recusado: ele deixa a invariante implícita — "nenhuma exceção de `mobia` interpola texto de terceiro" —, sem nada que a verifique, e a próxima exceção a violá-la reabre a coluna em silêncio.

E a invariante já falhou uma vez, rápido: a TEC-134 estabeleceu o critério em **26/08/2026** (`d069f3e`) e a TEC-237 o violou em **30/08/2026** (`d79e2d7`), **quatro dias depois**, sem que nenhuma revisão notasse. Não é o caso hipotético de um autor futuro desatento — é o caso medido de duas cards da mesma semana, as duas escritas com cuidado, cada uma correta sozinha.

## D2 — Os três testes

**T1 — exceção real do banco.** É o critério explícito da card: *"o teste força uma exceção real do banco, não um `raise ValueError(...)` sintético — o formato da mensagem do driver é justamente o que importa"*. A receita é a da medição acima: `insert()` de Core com `str` numa coluna `bytea`, que passa ao largo do `@validates` do ORM e faz o asyncpg montar a mensagem com o valor dentro.

O teste afirma as **duas** metades — que o sentinela **está** em `str(exc)`, e que **não** está no que vai para a coluna. Sem a primeira, o teste continuaria verde no dia em que o driver parasse de ecoar o valor, e aí não estaria provando coisa nenhuma: seria uma asserção de ausência sempre satisfeita, que é a classe de defeito que a TEC-289 acabou de tratar.

O sentinela tem no máximo 38 caracteres, pela truncagem medida acima. Escrever um mais longo e afirmar `sentinela in str(exc)` daria um teste vermelho por uma razão que não é a que ele investiga.

**T2 — o caminho da moderação.** O vazamento de verdade, ponta a ponta: `ModeracaoIndisponivel` com prosa de provedor no texto, propagando da moderação de saída até `last_error`. É o teste que teria ficado vermelho antes desta branch.

Ele afirma a divisão do D1 **nos dois sentidos**: o sentinela não está na coluna, **e está** no evento `message.failed` do log. Só a primeira metade deixaria passar uma implementação que emudecesse o log junto — que é regressão de diagnóstico, não segurança. A leitura do log usa `eventos_de_log` (`tests/conftest.py:1201`), o helper único da TEC-289, e não `caplog.text`.

**T3 — a inversão.** `test_erro_do_proprio_projeto_mantem_a_mensagem` (`tests/features/test_reprocessamento_apos_falha.py:255`) afirma hoje a premissa que esta card derruba, e o docstring dele a enuncia: *"excecao de `mobia` teve a mensagem escrita aqui dentro -- sabe-se o que ela carrega"*. Ele inverte, e o docstring novo registra por que a premissa caiu — não basta mudar a asserção e deixar a justificativa velha de pé, que é o defeito que a seção "Comentário não mente" do `CLAUDE.md` trata como erro.

`test_erro_de_terceiro_nao_leva_a_mensagem_para_last_error` (`:233`) continua valendo palavra por palavra e não muda.

## D3 — Os 25 pontos de log ficam fora desta card

A card sugere decidir junto com os pontos de log que fazem `detail=str(exc)`. O levantamento corrige o número: são **7 ocorrências do literal** `detail=str(exc)`, nos quatro arquivos que a card nomeia, mas **25 pontos do mesmo padrão** sob outros nomes de kwarg (`reason=`, `error=`, `motivo=`, `motivos=`, `provedor=`), com nove concentrados em `domain/agente/turno.py`.

Ficam fora, por duas razões:

1. **O log é o destino que a TEC-237 analisou e aceitou.** Mudá-lo é reverter aquela decisão, não completar esta.
2. **Dois dos 25 são risco de outra classe.** `api/routes/whatsapp.py:86` loga o texto de uma exceção do parser sobre o **payload cru da Meta** — um `KeyError` ali ecoa o envelope, telefone incluído. `domain/messages/recorder.py:136` loga o texto de um erro de SQLAlchemy sobre o INSERT da mensagem. Os dois merecem análise própria, não uma varredura no fim desta branch.

Vira card de seguimento, com os números acima.

**Sobre o mascarador, para a card de seguimento não precisar remedir:** `_mascarar_pii` (`app/logging.py:114-122`) é *key-based*. Redige por inteiro cinco chaves (`text_body`, `raw_payload`, `envelope_context`, `resumo`, `corpo`), mascara três de identificador, e a **todo o resto** aplica um único regex de corrida de 10 a 15 dígitos contíguos. Ele alcança `detail`, `error`, `reason`, dicts aninhados e o traceback de `exc_info` — a cobertura estrutural está correta. O que falta é a regra de conteúdo: telefone formatado (`+55 (11) 91234-5678`), CPF pontuado e texto livre passam intactos.

## Fora de escopo

- Os 25 pontos de log (D3).
- `EmailJaCadastrado(dados.email)` (`domain/corretores/repositorio.py:149` e `:204`) e `ArquivoInvalido(f"... {erro}")` (`domain/catalogo/parser.py:138`), que carregam PII no texto da exceção mas não alcançam `process_message` por caminho nenhum. Anotados porque quebrariam a invariante da TEC-134 se um refactor os trouxesse para o caminho do turno — e porque, depois desta card, deixam de importar para a coluna.
- Mudar o que `motivo_do_provedor` devolve, ou o que a moderação loga.
