# TEC-225 — A estimativa de tokens enxerga densidade: plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIA: use `superpowers:subagent-driven-development` (recomendada) ou `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam caixa (`- [ ]`) para controle.

**Objetivo:** fazer a estimativa barata de `_contar_se_valer` parar de subcontar o português, o emoji e a URL — hoje ela é `len/4`, uma constante do inglês, e é ela que decide se o contexto cabe no teto quando fica abaixo do limiar.

**Arquitetura:** duas constantes novas em `montagem.py` substituem o divisor único; `_estimar` passa a somar `ascii/2,3 + não_ascii*3`; `_FATOR_PESSIMISTA` é rederivado do pior caso plausível medido em vez de dois números errados. Nada muda no fluxo — nem em `_contar_se_valer`, nem no backstop, nem no limiar, nem no `headroom`.

**Tecnologias:** Python 3.13. Nenhuma dependência nova.

**Desenho:** [`docs/superpowers/specs/2026-09-20-tec-225-estimativa-ciente-de-densidade-design.md`](../specs/2026-09-20-tec-225-estimativa-ciente-de-densidade-design.md)

## Restrições globais

- Comentários e docstrings em `src/` e `tests/`: português **sem** acento (exceto valor citado). Prosa em `docs/`: **com** acento.
- Os três gates, no escopo exato do CI, antes de cada commit: `ruff check src tests alembic evals scripts`, `ruff format --check src tests alembic evals scripts`, `mypy src`.
- Commit: `tipo(TEC-225): o que passou a ser verdade`, assunto em português sem acento, **linha em branco** antes do trailer.
- **Nenhum número deste plano é chute.** Todos saem da medição de 20/09/2026 registrada no desenho, feita com `ContadorAnthropic` contra `claude-sonnet-5`. Se você mudar algum, meça antes e registre a medição.
- **Não mexa** no `headroom`, na fração 0,6 do limiar, nem no contador real. Os três estão explicitamente fora de escopo.

## Os números medidos, que este plano usa

| conteúdo | chars/token real | `hoje/real` | `proposto/real` |
| --- | --- | --- | --- |
| português | 2,34 | 0,59 | 1,02 |
| português acentuado | 2,38 | 0,60 | 1,23 |
| inglês | 3,15 | 0,76 | 1,32 |
| emoji | 0,35 | 0,09 | 1,06 |
| URL | 1,85 | 0,46 | 0,80 |
| base64 | 0,99 | 0,25 | 0,43 |

Um conteúdo escapa da contagem real quando `estimativa/real` fica **abaixo de 0,60** (a fração do limiar). É por isso que a tabela acima é o critério de aceite inteiro desta card.

---

### Tarefa 1: A fórmula passa a enxergar densidade

**Arquivos:**
- Modificar: `src/mobia/domain/context/montagem.py` (`_estimar`, constantes novas)
- Testar: `tests/integration/test_montagem.py`

**Interfaces:**
- Consome: `SISTEMA`, `_texto_das`, `_texto_do_estado` (já existem, não mude nenhum).
- Produz: `_CHARS_POR_TOKEN_EM_PORTUGUES: float` e `_TOKENS_POR_CARACTERE_NAO_ASCII: int`, ambos usados pela Tarefa 2.

- [ ] **Passo 1: escrever os testes que falham**

Em `tests/integration/test_montagem.py`, junto dos testes de limiar que já existem (por volta da linha 1146-1268). São três, e os dois primeiros são critério de pronto da card:

```python
async def test_emoji_aciona_a_contagem_real(...) -> None:
    """Criterio de pronto da card. Medido: emoji roda a 0,35 chars/token.

    Para `len`, um emoji e uma vogal valem igual -- e por isso que a
    estimativa antiga via 600 caracteres de emoji como 150 tokens quando eles
    custam 1706.
    """
    # semeie mensagens com emoji suficiente e afirme que a contagem real foi paga


async def test_uma_duzia_de_urls_aciona_a_contagem_real(...) -> None:
    """Criterio de pronto da card. Um lead colando anuncios e trafego de terca.

    Medido: URL roda a 1,85 chars/token, e a estimativa nova a poe em 0,80 do
    real -- acima do corte de 0,60, entao ela deixa de escapar.
    """


async def test_portugues_moderado_continua_sem_pagar_a_contagem(...) -> None:
    """O criterio que protege a latencia, e o motivo de a estimativa existir.

    Medido sobre o corpus de eval: mesmo uma janela de 40 falas no p90 estima
    4134 tokens contra um limiar de 6564 -- 1,6x de folga.
    """
```

Use o estilo dos testes vizinhos para semear mensagens e para contar chamadas do contador (`contador.chamadas`); **leia-os antes**, não invente forma nova.

- [ ] **Passo 2: rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py -k "emoji_aciona or urls_aciona or portugues_moderado" --tb=short
```

Esperado: os dois primeiros FALHAM (a estimativa de hoje não aciona a contagem); o terceiro passa desde já, e é assim mesmo — ele é a rede que impede a Tarefa 1 de consertar o escape matando a latência.

- [ ] **Passo 3: as constantes**

Em `src/mobia/domain/context/montagem.py`, substituindo o comentário e a constante `_CHARS_POR_TOKEN_NO_PIOR_CASO` que existem hoje:

```python
# Caracteres por token do portugues, MEDIDO -- nao suposto.
#
# Medicao de 20/09/2026 com `ContadorAnthropic` contra claude-sonnet-5, pela
# inclinacao entre um texto e o mesmo texto oito vezes (o que cancela a
# sobrecarga fixa da chamada): portugues sem acento 2,34, com acento 2,38.
#
# O valor anterior era 4, que e o INGLES (3,15 medido). A consequencia estava
# documentada ao contrario: `Settings.limiar_de_contagem_efetivo` afirmava que
# o portugues ficava "coberto com folga" pela razao de seguranca de 2,4, e a
# folga real era de 2,6%. Ver o desenho da TEC-225.
_CHARS_POR_TOKEN_EM_PORTUGUES = 2.3

# Tokens por caractere NAO-ASCII.
#
# Um emoji e UM caractere Python e custa cerca de 2,9 tokens (0,35 chars/token
# medido). Para `len` ele vale o mesmo que uma vogal, e e exatamente essa
# cegueira que fazia 600 caracteres de emoji serem estimados em 150 tokens
# quando custam 1706.
#
# O acento do portugues paga este mesmo preco, o que superestima um pouco
# (1,23 do real, contra 1,02 do texto sem acento). Superestimar e a direcao
# segura, e a folga de latencia aguenta -- ver a D3 do desenho.
_TOKENS_POR_CARACTERE_NAO_ASCII = 3
```

- [ ] **Passo 4: a fórmula**

Substituir o corpo de `_estimar`, mantendo a assinatura:

```python
def _estimar(resumo: str | None, literais: list[Message], estado: LeadQualification | None) -> int:
    """Estimativa barata de tokens, ciente de densidade (TEC-225).

    Separa ASCII de nao-ASCII porque os dois custam ordens diferentes: o
    portugues roda a 2,3 caracteres por token e o emoji a 0,35 -- e `len`
    nao distingue os dois. A formula anterior (`len // 4`) supunha o ingles e
    subcontava tudo que este produto processa.
    """
    texto = (
        SISTEMA + (resumo or "") + _texto_das(literais) + _texto_do_estado(estado)
    )
    nao_ascii = sum(1 for caractere in texto if ord(caractere) > 127)
    ascii_ = len(texto) - nao_ascii
    return int(
        ascii_ / _CHARS_POR_TOKEN_EM_PORTUGUES
        + nao_ascii * _TOKENS_POR_CARACTERE_NAO_ASCII
    )
```

**Atenção a uma mudança de forma que importa:** a versão antiga somava `len()` de cada parte separadamente; esta concatena antes de contar. O resultado é o mesmo para `len`, mas a concatenação é necessária para varrer os caracteres uma vez só. Se o perfil mostrar isso caro, meça antes de otimizar — o texto tem ordem de 10 mil caracteres.

- [ ] **Passo 5: rodar e ver passar**

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py --tb=short
```

Esperado: os três novos passam. **`test_conteudo_curto_em_caracteres_nunca_aciona_a_contagem_real` agora FALHA — isso é o desfecho esperado**, e a própria nota dele diz isso. Ele é tratado na Tarefa 3; não o conserte aqui e não o delete.

- [ ] **Passo 6: os três gates**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
```

- [ ] **Passo 7: commit**

```bash
git add src/mobia/domain/context/montagem.py tests/integration/test_montagem.py
git commit -m "feat(TEC-225): a estimativa de tokens separa ASCII de nao-ASCII"
```

---

### Tarefa 2: O modo sem modelo volta a errar para cima

**Arquivos:**
- Modificar: `src/mobia/domain/context/montagem.py` (`_FATOR_PESSIMISTA`, `_estimar_pessimista`)
- Testar: `tests/unit/test_classificador.py`

**Interfaces:**
- Consome: `_estimar` e as duas constantes da Tarefa 1.
- Produz: nada que tarefa seguinte consuma.

- [ ] **Passo 1: entender o defeito antes de mexer**

`_estimar_pessimista` serve o modo sem modelo — o caminho de estouro de deadline, onde **não existe limiar** e a estimativa é a palavra final. A docstring dele promete errar para cima.

Ele é `(estimativa + 1) * _FATOR_PESSIMISTA`, com `_FATOR_PESSIMISTA = 4 / 3.2 = 1,25`. Os dois números são errados: o `4` é o divisor do inglês, o `3,2` é um "pior caso do português" que a medição derrubou (real: 2,34).

Medido: o modo **pessimista** subcontava o português em 27% (razão 0,73). O caminho que existe para errar para cima errava para baixo.

- [ ] **Passo 2: escrever o teste que falha**

O teste que existe, `test_a_estimativa_sem_modelo_supoe_o_piso_de_caracteres_por_token` (`tests/unit/test_classificador.py`, por volta da linha 635), prende a razão contra o piso de 3,2. Ele passa a prender contra o que foi medido:

```python
def test_a_estimativa_sem_modelo_erra_para_cima_e_nao_para_baixo() -> None:
    """O modo sem modelo nao tem limiar atras dele -- a estimativa E a decisao.

    Ate a TEC-225 este caminho prometia errar para cima e errava para baixo:
    `_FATOR_PESSIMISTA` saia de `4 / 3.2`, e os dois numeros estavam errados.
    Medido, ele subcontava o portugues em 27%.
    """
```

Ele deve afirmar que, para um texto em português de tamanho realista, a estimativa pessimista fica **acima** da contagem real — usando a razão medida de 2,34 chars/token como referência de "real", sem chamar a API.

**Substitua o teste antigo, não o delete:** o que ele prendia (a propriedade de errar para cima) continua valendo; o que muda é o número contra o qual ele prende.

- [ ] **Passo 3: rederivar o fator**

```python
# A razao entre a estimativa nova e a contagem real no pior caso PLAUSIVEL
# medido: a URL, em 0,80 (600 caracteres de URL estimam 688 contra 859 reais).
#
# Base64 fica de fora de proposito -- 0,43 -- porque cobri-lo exigiria um
# detector de "sequencia longa sem espaco", que tem falso-positivo proprio
# (uma URL longa tambem e uma). Ver a D4 do desenho.
_PIOR_RAZAO_PLAUSIVEL = 0.80

# Derivado, e nao escrito como 1.25: o fator existe para devolver ao pior caso
# plausivel a folga que a estimativa nao lhe da. O valor calhar de ser o mesmo
# que o de antes e coincidencia -- aquele saia de `4 / 3.2`, dois numeros que a
# medicao da TEC-225 derrubou.
_FATOR_PESSIMISTA = 1 / _PIOR_RAZAO_PLAUSIVEL
```

A constante `_CHARS_POR_TOKEN_NO_PIOR_CASO` e o comentário de 12 linhas dela saem — a Tarefa 1 já os substituiu pelas duas constantes novas.

O corpo de `_estimar_pessimista` não muda. **A docstring dele muda**: a explicação do `+ 1` cita a divisão inteira de `_estimar`, que agora é um `int()` sobre soma de floats — confira se a frase ainda descreve o que o código faz e ajuste se não descrever.

- [ ] **Passo 4: rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_classificador.py -k "sem_modelo" --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py --tb=short
```

- [ ] **Passo 5: os três gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/context/montagem.py tests/unit/test_classificador.py
git commit -m "fix(TEC-225): o modo sem modelo volta a errar para cima"
```

---

### Tarefa 2b: O headroom passa a cobrir o que foi medido

> **Esta tarefa não estava no plano original.** Ela entrou depois que a revisão da Tarefa 1 achou que a contabilidade do orçamento afirmava usar "o mesmo proxy `len/4` do módulo de montagem", e a medição que se seguiu mostrou que a reserva está curta. A decisão de fazê-la aqui, em vez de em card própria, é do dono do produto. Ver a **D5** do desenho, que substitui uma versão anterior e explica o erro.

**Arquivos:**
- Modificar: `src/mobia/app/config.py` (`contexto_headroom_de_tokens` e o comentário dele)
- Testar: `tests/unit/test_config.py`

**Interfaces:**
- Consome: nada das tarefas anteriores.
- Produz: um teto efetivo menor (10.400), que a Tarefa 3 cita na prosa.

- [ ] **Passo 1: entender o que está errado antes de mexer**

`contexto_headroom_de_tokens` é a reserva subtraída do teto de 12.000 antes de toda comparação. Ela existe para cobrir a diferença entre o que o contador mede (uma mensagem de usuário achatada) e o que a requisição real manda (`system=` separado, schema, `tools=`, rótulos).

Dois testes supostamente a validam. **Os dois medem as parcelas com `len/4`** — o mesmo proxy que a Tarefa 1 derrubou. Eles passam porque a régua é a mesma dos dois lados.

Medido em 20/09/2026, parcela a parcela, contra `ContadorAnthropic`:

| parcela | `len/4` | contador real |
| --- | --- | --- |
| − `montagem.SISTEMA` | −42,0 | −77,0 |
| + `SISTEMA_DO_AGENTE` | 305,5 | 541,0 |
| + schema compilado | 372,8 | 798,0 |
| + rótulos de `montar_prompt` | 19,2 | 41,0 |
| + ferramenta de busca | 131,2 | 242,0 |
| **= subcontagem** | **786,8** | **1.545,0** |

A reserva de 1.060 é **485 tokens menor** que a lacuna real.

- [ ] **Passo 2: escrever o teste que falha**

Em `tests/unit/test_config.py`, um teste novo que trava a razão de ser do número — **não** um que repita `headroom == 1600`, que seria tautologia:

```python
def test_o_headroom_cobre_a_subcontagem_medida() -> None:
    """A reserva tem de cobrir a diferenca MEDIDA, nao a do proxy.

    Ate a TEC-225 dois testes validavam o headroom com `len/4` dos dois lados
    da conta, entao passavam sem dizer nada sobre a reserva. Medido com
    `ContadorAnthropic` em 20/09/2026, parcela a parcela, a subcontagem real e
    de 1545 tokens -- contra uma reserva de 1060.

    O numero abaixo e a medicao, transcrita aqui porque medi-la no teste
    exigiria chamar a API a cada execucao. Se alguem mexer no prompt do
    agente, no schema ou na ferramenta de busca, ele envelhece -- e o teste
    vizinho de margem do orcamento e quem avisa, porque conta crescimento do
    prompt em unidades do proxy.
    """
    SUBCONTAGEM_REAL_MEDIDA = 1545
    assert get_settings().contexto_headroom_de_tokens >= SUBCONTAGEM_REAL_MEDIDA
```

- [ ] **Passo 3: rodar e ver falhar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_config.py -k "headroom_cobre" --tb=short
```

Esperado: FAIL — 1060 não cobre 1545.

- [ ] **Passo 4: subir o valor**

`contexto_headroom_de_tokens` passa de `1060` para `1600`.

O comentário desse campo tem 96 linhas e registra cada subida anterior (400→800 na TEC-145, →850 na TEC-250, →880 na TEC-257, →1060 na TEC-265). **Acrescente esta subida no mesmo formato das outras**, e diga o que nenhuma das anteriores podia dizer: que este é o primeiro valor derivado de medição com o contador real, e não de aritmética sobre o proxy `len/4`.

O comentário precisa registrar também o custo, porque ele é real: o teto efetivo cai de 10.940 para 10.400, cerca de 1.240 caracteres de conversa a menos por chamada.

- [ ] **Passo 5: as duas afirmações que passam a mentir**

`config.py` diz em dois lugares que a conta do orçamento usa "o mesmo proxy `len/4` do módulo de montagem", e `tests/unit/test_config.py` repete a frase num terceiro. **Deixou de ser o mesmo.**

Corrija as três para dizer o que é verdade: que o orçamento mede em unidades de um proxy `len/4` **próprio**, que não é mais o da montagem, e que por isso os dois testes de orçamento são alarme contra **crescimento do prompt** — não validação da reserva, que agora é o teste do passo 2.

**Não mude o proxy nem os tetos daqueles dois testes.** Trocá-lo é a correção na raiz e está declarada fora de escopo no desenho.

- [ ] **Passo 6: rodar tudo que depende do teto**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_config.py --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration/test_montagem.py --tb=short
./.venv/Scripts/python.exe -m pytest tests/features/test_janela_de_contexto.py --tb=short
```

O limiar cai junto com o teto (6.564 → 6.240). Conferido antes de escrever este brief: os três testes da Tarefa 1 continuam com o mesmo desfecho (emoji 7.283 e URLs 7.350 acionam; português 3.633 não). Se algum reprovar mesmo assim, **não ajuste o teste** — meça e reporte, porque significa que a conta acima está errada.

- [ ] **Passo 7: os três gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/app/config.py tests/unit/test_config.py
git commit -m "fix(TEC-225): o headroom passa a cobrir a subcontagem medida"
```

---

### Tarefa 3: O teste da lacuna é invertido, e a prosa para de mentir

**Arquivos:**
- Modificar: `tests/integration/test_montagem.py` (o teste da lacuna e a referência cruzada morta)
- Modificar: `src/mobia/app/config.py` (`limiar_de_contagem_efetivo`)
- Modificar: `src/mobia/domain/context/montagem.py` (docstring de `_contar_se_valer`)

**Interfaces:** nenhuma. Esta tarefa é de prosa e de um teste que inverte; **não mude nenhuma linha de lógica.**

- [ ] **Passo 1: inverter o teste da lacuna**

`test_conteudo_curto_em_caracteres_nunca_aciona_a_contagem_real` (por volta da linha 1235) afirma hoje `contador.chamadas == 0` para 200 emojis, e a nota dele diz:

> NOTA PARA QUEM VIER DEPOIS: este teste ficar vermelho e o desfecho esperado, nao uma regressao. [...] no dia em que existir um estimador que leve densidade de caracteres nao-ASCII em conta (ticket proprio, fora do TEC-127), este conteudo passara a acionar a contagem real e a asserção abaixo tem de ser invertida junto com a mudanca, nao "consertada".

**Esse dia é hoje.** Inverta: renomeie para algo como `test_conteudo_denso_em_emoji_aciona_a_contagem_real`, troque a asserção, e **troque a nota** por uma que registre o que aconteceu — que a lacuna existiu, foi declarada por este teste, e foi fechada pela TEC-225 com medição. A card exige que ele seja substituído e não deletado.

> **Inverter a asserção não basta, e isto é correção de um erro deste plano.** O teste semeia 200 emojis × 3 mensagens = 600 caracteres, que sob a fórmula nova estimam 1.873 — longe do limiar. Ele continuaria verde. **Re-semeie com o cenário que a própria card descreve, ~3.600 caracteres de emoji**, que estimam 10.873 e acionam a contagem. Medido antes de escrever esta correção: 1.800 caracteres ainda não acionam; 3.600 acionam. Os 600 de hoje nunca exercitaram a lacuna — eram um sexto do que seria preciso.

- [ ] **Passo 2: a referência cruzada morta**

A docstring de `test_limiar_de_contagem_cede_a_vez_para_a_contagem_real` (por volta da linha 1204) cita um `test_limiar_nao_protege_conteudo_denso_em_emoji` "logo abaixo". **Esse teste não existe com esse nome.** Aponte para o nome real depois da renomeação do passo 1.

- [ ] **Passo 3: a docstring do limiar**

`Settings.limiar_de_contagem_efetivo`, em `src/mobia/app/config.py` (por volta da linha 601). O trecho que precisa mudar, e ele é o mais importante desta tarefa:

- A afirmação `português acentuado (~3.2-3.7 chars/token) fica coberto com folga` — **medido: 2,38, e a folga era de 2,6%**.
- O parágrafo em negrito que declara emoji e base64 como risco aceito "até existir um estimador que leve densidade de caracteres não-ASCII em conta" — **esse estimador passou a existir.** O texto novo declara o que sobrou: só base64, em 0,43, e a razão de ele ter ficado de fora (a D4 do desenho).
- A frase `a estimativa é len//4` deixou de ser verdade.

Mantenha a estrutura e o tom do comentário — ele é longo de propósito, e é a derivação que quem vier depois vai ler.

- [ ] **Passo 4: a docstring de `_contar_se_valer`**

Ela repete `len/4 supoe 4 caracteres por token` e o intervalo 3,2–3,7. Atualize para a fórmula e os números novos, e mantenha o apontamento para `Settings.limiar_de_contagem_efetivo`, que continua sendo onde mora a derivação completa.

- [ ] **Passo 5: rodar a listagem de comentários**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py
```

Leia cada achado. Esta card mexe numa área com comentário denso — `config.py` sozinho tem 96 linhas sobre o `headroom` — e é provável que apareça prosa que este plano não previu. Conserte o que estiver errado e registre no relatório.

**O que NÃO é para mexer**, e o relatório deve dizer que foi conferido e deixado: os testes de margem do orçamento (`test_a_margem_do_orcamento_do_prompt_e_deliberada` e `test_diferenca_entre_o_contado_e_o_enviado`) e o proxy `len/4` de `_decomposicao`, que o desenho declara fora de escopo.

**O comentário do `headroom` já foi tratado pela Tarefa 2b**, que subiu o valor para 1.600 e acrescentou a subida ao histórico. Não o reescreva; confira que ele bate com o código e siga.

- [ ] **Passo 6: os três gates e a suíte unitária**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest tests/unit --tb=short -q
```

- [ ] **Passo 7: commit**

```bash
git add src/mobia/app/config.py src/mobia/domain/context/montagem.py tests/integration/test_montagem.py
git commit -m "docs(TEC-225): a prosa do limiar para de citar o numero do ingles"
```

---

### Tarefa 4: A suíte inteira, uma vez, e o PR

**Arquivos:** nenhum.

- [ ] **Passo 1: a suíte inteira**

```bash
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Se voltar com centenas de `ERROR` de setup, **não repita o mesmo comando**: rode por blocos (`tests/unit`, `tests/integration`, `tests/features`).

Se falhar num teste, repita **uma** vez sobre a mesma árvore antes de culpar esta branch.

**Atenção especial a `tests/features/test_janela_de_contexto.py`**, que é o critério de aceite Gherkin da TEC-127 e depende de conteúdo cruzar o limiar. A estimativa mudou de escala — se ele falhar, leia antes de consertar: pode ser que o teste dependesse do número velho.

- [ ] **Passo 2: push e PR**

```bash
git push -u origin feat/tec-225-estimativa-ciente-de-densidade
```

Se o push voltar 403, refaça com `git -c credential.helper= -c credential.helper='!gh auth git-credential' push ...`.

- [ ] **Passo 3: a card**

Comentar na TEC-225 e mover para "Em análise". O comentário registra:

- **A divergência principal:** a card classifica o português como "não escapa, coberto pela margem". Medido, ele escapa — a folga era de 2,6%, e a docstring que a card herdou citava o número do inglês.
- **O segundo item da card está obsoleto:** o `headroom` não é mais 400 nem é chute; são 1.060, com quatro subidas registradas e dois testes medindo a diferença entre o contado e o enviado. A TEC-134, de quem ele dependia, existe.
- **Um defeito que a card não menciona:** o modo sem modelo subcontava o português em 27%, num caminho onde não há limiar para corrigir.
- **O que não entrega:** base64 continua escapando (0,43), e a razão está no desenho.
