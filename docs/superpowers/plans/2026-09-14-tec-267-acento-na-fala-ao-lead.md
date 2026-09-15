# TEC-267 — Acento no texto que o agente envia ao lead

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alinhar o texto que o lead lê com a voz que o modelo já usa — português acentuado — e escrever no `CLAUDE.md` onde essa fronteira fica.

**Architecture:** Substituição de literais em `src/`, mais os literais duplicados nos testes que os checam por string solta. Nenhuma mudança de lógica, de assinatura, de schema ou de banco. Comentários, docstrings e prompts de sistema **continuam sem acento**.

**Tech Stack:** Python 3.13. Nada novo.

**Spec:** `docs/superpowers/specs/2026-09-14-tec-267-acento-na-fala-ao-lead-design.md`

## Global Constraints

- **Os três gates, nesta ordem, antes de qualquer commit:**
  - `./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts`
  - `./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts`
  - `./.venv/Scripts/python.exe -m mypy`
- **A fronteira desta card, e ela é o ponto todo:** *texto que o lead lê* ganha acento; **comentário, docstring e prompt de sistema NÃO**. Ao editar um arquivo, mexa apenas na string de saída — se você acentuar um comentário vizinho, está fora do escopo e a revisão vai apontar.
- **Não troque literal duplicado em teste por import da constante.** Seria a mudança certa noutra card; aqui infla o diff e mistura duas coisas numa revisão só (`D4` do desenho).
- Commit: assunto em português **sem** acento, `tipo(TEC-267): o que passou a ser verdade`, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **`m2` fica como está.** Não há acento a pôr, e trocar por `m²` é outra mudança (superscrito, não diacrítico) — fora do escopo, registrada para o comentário da card.
- **`TEXTO_DA_CONFIRMACAO_DE_OPTOUT` já está acentuado.** Não toque nele.
- Cada task deve terminar com a suíte verde. Por isso a fonte e os testes que a duplicam viajam juntos.

---

### Task 1: As frases

**Files:**
- Modify: `src/mobia/domain/agente/identificacao.py`, `src/mobia/domain/agente/turno.py`, `src/mobia/domain/moderacao/port.py`, `src/mobia/domain/notificacao/envio.py`, `src/mobia/domain/followup/mensagem.py`, `src/mobia/workers/jobs/process_message.py`
- Test: `tests/unit/test_recomendacao_regras.py`, `tests/integration/test_apresentacao_no_turno.py`, `tests/unit/test_relaxamento_alargar.py`, `tests/unit/test_mensagem_do_followup.py`

**Interfaces:**
- Produces: os mesmos nomes de constante, com valores acentuados. Nada consome estrutura nova.

- [ ] **Step 1: Substituir, literal por literal**

`src/mobia/domain/agente/identificacao.py:95`
```python
TEXTO_DA_IDENTIFICACAO = (
    "Oi! Sou o assistente virtual da imobiliária. Posso te ajudar a encontrar "
    "um imóvel, e a qualquer momento te passo para um corretor."
)
```

`src/mobia/domain/agente/turno.py:115`
```python
TEXTO_DA_BUSCA_INCONCLUSIVA = (
    "Deixa eu confirmar algumas coisas com um corretor para não te passar "
    "informação errada. Já te retorno com as opções."
)
```

`turno.py:131`
```python
TEXTO_SEM_RESULTADO_APOS_AMPLIAR = (
    "Procurei também um pouco além do que você pediu e mesmo assim não achei "
    "nada que valha a pena te mostrar agora. Quer que um corretor olhe isso "
    "com você?"
)
```

`turno.py:158`
```python
TEXTO_DO_LIMITE_DE_PERGUNTAS = (
    "Já perguntei bastante e não quero virar interrogatório. "
    "Prefiro passar para um corretor, que vai conseguir te ajudar melhor daqui. "
    "Pode deixar que ele entra em contato."
)
```

`turno.py:176-187` — o prefixo e os três avisos de ampliação:
```python
_ABERTURA_DA_AMPLIACAO = "Não achei nada exatamente no que você pediu, então "

TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO = (
    f"{_ABERTURA_DA_AMPLIACAO}ampliei um pouco a busca: valor um pouco acima e "
    "bairros vizinhos. Veja se algum destes serve."
)
TEXTO_DO_CRITERIO_AMPLIADO_PRECO = (
    f"{_ABERTURA_DA_AMPLIACAO}ampliei um pouco o valor. Veja se algum destes serve."
)
TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO = (
    f"{_ABERTURA_DA_AMPLIACAO}incluí bairros vizinhos. Veja se algum destes serve."
)
```

> **`incluí` leva acento** — primeira pessoa do pretérito de *incluir*. É o único dos três em que o corpo muda; os outros dois só herdam o prefixo acentuado.

`turno.py:258`
```python
TEXTO_DO_FILTRO_AJUSTADO = "Tirei {bairros} da busca, que você já descartou."
```

`src/mobia/domain/moderacao/port.py:76`
```python
TEXTO_DA_RECUSA_DE_ENTRADA = (
    "Não consigo seguir com essa mensagem. A busca aqui é feita por critério "
    "do imóvel -- região, preço, quartos, vagas. Me diga o que você procura "
    "assim que eu ajudo."
)
```

`port.py:85`
```python
TEXTO_NEUTRO_DE_SAIDA = (
    "Tive um problema para montar a resposta agora. Pode repetir sua última "
    "mensagem que eu tento de novo?"
)
```

`src/mobia/domain/notificacao/envio.py:62`
```python
TEXTO_DA_JANELA_HUMANA = (
    "O atendimento humano funciona de segunda a sábado, das {inicio}h às {fim}h. "
    "Fora desse horário a resposta pode demorar mais."
)
```

> Note o **`às`** com crase: *das 9h às 18h*. É o único ponto desta card em que o acento não é só ortografia de palavra.

`src/mobia/domain/followup/mensagem.py:50`
```python
CONVITE_PARA_AGENDAR = "Quer agendar uma visita para conhecer algum dos imóveis que vimos?"
```

`src/mobia/workers/jobs/process_message.py:33`
```python
TEXTO_DO_AVISO_DE_ERRO = (
    "Tive um problema técnico aqui e não consegui seguir. "
    "Passei sua conversa para um corretor assumir."
)
```

- [ ] **Step 2: Rodar e ver o que quebra**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short`

Expected: FAIL em quatro arquivos, e os Steps 3 e 3b cobrem os quatro — `test_recomendacao_regras.py` (literais duplicados **e** asserções ASCII), `test_relaxamento_alargar.py` e `test_mensagem_do_followup.py` (asserções ASCII), mais `test_apresentacao_no_turno.py` na integração.

> **Se quebrar um quinto arquivo, pare e reporte.** O levantamento original desta card errou uma vez — previu dois arquivos onde eram quatro, porque procurou literal duplicado e não viu asserção sobre propriedade. Um quinto significaria que ele errou de novo, e eu preciso saber antes da Task 2.

- [ ] **Step 3: Corrigir os literais duplicados**

`tests/unit/test_recomendacao_regras.py`, linhas 209, 215, 222 e 231, e `tests/integration/test_apresentacao_no_turno.py`, linha 1001.

Eles trazem a frase como string solta. Acentue **o literal duplicado**, exatamente como ficou na fonte — `"Tirei ... da busca, que você já descartou."`. Não troque por `from ... import TEXTO_DO_FILTRO_AJUSTADO`.

> Abra cada linha e confira a forma exata antes de editar: alguns podem conter só um pedaço da frase (`"que voce ja descartou"`), e trocar a frase inteira onde havia um pedaço quebra a asserção de outro jeito.

- [ ] **Step 3b: Apagar as asserções `.isascii()` desta task**

**Correção ao levantamento** (`D5` do desenho): o repositório guarda a política antiga em asserções de propriedade, e o inventário original não as viu porque procurou literal duplicado. Três das cinco caem nesta task:

- `tests/unit/test_recomendacao_regras.py:63` e `:64` — asserções soltas dentro de outro teste. **Apague as duas linhas**, e nada mais do teste que as hospeda.
- `tests/unit/test_recomendacao_regras.py:244-247` — o teste `test_o_aviso_e_ascii` inteiro, docstring incluída. **Apague a função.**
- `tests/unit/test_relaxamento_alargar.py:169-176` — o teste `test_os_textos_do_aviso_sao_ascii` inteiro. **Apague a função**, e confira se o `import` de `TEXTO_SEM_RESULTADO_APOS_AMPLIAR` e dos três `CRITERIO_AMPLIADO` fica sem uso — se ficar, o `ruff` acusa `F401` e você remove o import também.
- `tests/integration/test_apresentacao_no_turno.py:1002` — asserção solta ao fim de um teste. **Apague a linha.**
- `tests/unit/test_mensagem_do_followup.py:107-113` — o teste `test_tudo_que_sai_para_o_lead_e_ascii` inteiro. **Apague a função.** Ele cai nesta task e não na 2: a primeira coisa que ele assevera é `CONVITE_PARA_AGENDAR`, que esta task acentua. (A linha 76 do mesmo arquivo, que duplica `"Condominio"`, é da Task 2 — não a toque aqui.)

São as **cinco** asserções, nos quatro arquivos. A guarda no sentido novo entra na Task 3; não a escreva aqui.

- [ ] **Step 3c: A asserção semântica escrita com a grafia antiga**

**Terceira classe de dependência**, e a última: `tests/unit/test_moderacao_port.py:48-49`, em `test_a_recusa_nomeia_o_criterio_legitimo`.

```python
    assert "imovel" in baixo
    for criterio in ("regiao", "preco", "quartos"):
        assert criterio in baixo
```

Não é literal duplicado nem asserção de propriedade: é uma pergunta **semântica** — *"a recusa nomeia o critério legítimo?"* — escrita com a grafia que o texto tinha. A pergunta continua válida; a grafia não. Troque para `"imóvel"`, `"região"`, `"preço"` (e `"quartos"`, que não muda).

> **Varri o resto da suíte procurando mais casos desta classe e não há.** As outras ~50 ocorrências de `"regiao"`/`"preco"` em asserções são **nome de campo** — chave de schema, entrada de `perguntados_sem_resposta`, coluna —, não prosa, e são imunes. `test_prosa_do_followup.py:153` assevera sobre `SISTEMA_DO_FOLLOWUP`, que é prompt de sistema e esta card não acentua.

- [ ] **Step 4: Rodar unitários e integração**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit -q --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration/test_apresentacao_no_turno.py -q --tb=short
```
Expected: PASS nos dois.

- [ ] **Step 5: Os três gates, e commitar**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/ tests/
git commit -F- <<'MSG'
feat(TEC-267): as frases que o lead recebe passam a ter acento

Doze literais em seis arquivos. O modelo ja escrevia acentuado e nada
normalizava a saida dele, entao a conversa ja era mista -- isto alinha o
codigo com a voz que o lead ja lia, em vez de manter metade dela com cara
de descuido.

Comentario, docstring e prompt de sistema continuam sem acento.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: Os rótulos de ficha

**Files:**
- Modify: `src/mobia/domain/agente/apresentacao.py`
- Test: `tests/unit/test_apresentacao.py`, `tests/integration/test_turno_investidor.py`, `tests/unit/test_mensagem_do_followup.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: rótulos acentuados. É a mensagem mais visível do produto — a ficha de imóvel.

- [ ] **Step 1: Substituir em `apresentacao.py`**

Quatro pontos, e **só quatro** — os demais rótulos do arquivo (`Aluguel estimado`, `yield bruto`, `Destaque:`, `m2`) não têm vogal que receba acento e ficam intactos.

`apresentacao.py:189`
```python
RESSALVA_DE_ESTIMATIVA = "Estimativa, não é garantia de retorno."
```

`apresentacao.py:197`
```python
_ALUGUEL_AUSENTE = "Aluguel estimado: não informado"
```

`apresentacao.py:231` — dentro do bloco do investidor:
```python
        linhas.append(f"Condomínio + IPTU {reais_de(rentabilidade.custos_centavos)}/mês")
```

`apresentacao.py:253` — na legenda da ficha:
```python
        linhas.append(f"Condomínio {reais_de(ficha.condominio_centavos)}")
```

> **`m2` fica.** Trocar por `m²` é superscrito, não acento — mudança de outra natureza, fora desta card.

- [ ] **Step 2: Rodar e ver quebrar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_apresentacao.py tests/unit/test_mensagem_do_followup.py -q --tb=short`
Expected: FAIL — `test_apresentacao.py` tem ~20 ocorrências duplicadas, `test_mensagem_do_followup.py` tem uma (`"Condominio"`, linha 76).

- [ ] **Step 3: Corrigir os três testes**

- `tests/unit/test_apresentacao.py` — linhas 63-159, 184, 186, 208: `RESSALVA_DE_ESTIMATIVA`, `_ALUGUEL_AUSENTE`, `"Condominio"`, `"Aluguel estimado"`, `"yield bruto"`. **Só as duas primeiras e `Condominio` mudam**; `Aluguel estimado` e `yield bruto` continuam sem acento, então as asserções sobre eles não se tocam.
- `tests/integration/test_turno_investidor.py` — linhas 512, 513, 514, 576, 577.
- `tests/unit/test_mensagem_do_followup.py` — linha 76, `"Condominio"` → `"Condomínio"`.

- [ ] **Step 4: Rodar**

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_apresentacao.py tests/unit/test_mensagem_do_followup.py -q --tb=short
./.venv/Scripts/python.exe -m pytest tests/integration/test_turno_investidor.py -q --tb=short
```
Expected: PASS.

- [ ] **Step 5: Os três gates, e commitar**

```bash
git add src/ tests/
git commit -F- <<'MSG'
feat(TEC-267): os rotulos da ficha de imovel passam a ter acento

Condominio, e a ressalva de estimativa do bloco do investidor. E a mensagem
mais visivel que o lead recebe, e a que o produto existe para entregar.

m2 fica como esta: nao ha acento a por, e trocar por m2 sobrescrito e
mudanca de outra natureza.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: A guarda, no sentido novo

**Files:**
- Create: `tests/unit/test_acento_no_texto_ao_lead.py`

**Interfaces:**
- Consumes: as constantes acentuadas das Tasks 1 e 2.
- Produces: nada que outra task use.

**Por que esta task existe:** as Tasks 1 e 2 apagaram cinco asserções `.isascii()` que guardavam a política revogada (`D5` do desenho). Sem isto, a card sai deixando a fronteira **menos** protegida do que a encontrou.

- [ ] **Step 1: Escrever a guarda**

```python
"""A fronteira do acento, no sentido que a TEC-267 fixou.

Substitui as cinco assercoes `.isascii()` que guardavam a politica anterior.

**Esta guarda erra de menos, nunca de mais, e e isso que a torna aceitavel.**
A versao obvia -- "todo literal ao lead tem ao menos um caractere acentuado"
-- e FALSA: `m2`, `Destaque:` e `De {} por {}` nao tem vogal que receba
acento, e excetua-las viraria uma lista a mao que reprova texto certo. Esta
aqui tem a assimetria oposta: uma palavra faltando na lista so deixa de pegar
um caso, nunca reprova um caso correto.
"""

import pytest

from mobia.domain.agente.apresentacao import RESSALVA_DE_ESTIMATIVA
from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO
from mobia.domain.agente.turno import (
    TEXTO_DA_BUSCA_INCONCLUSIVA,
    TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
    TEXTO_DO_FILTRO_AJUSTADO,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
    TEXTO_SEM_RESULTADO_APOS_AMPLIAR,
)
from mobia.domain.followup.mensagem import CONVITE_PARA_AGENDAR
from mobia.domain.moderacao.port import (
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
)
from mobia.domain.notificacao.envio import TEXTO_DA_JANELA_HUMANA
from mobia.domain.optout.deteccao import TEXTO_DA_CONFIRMACAO_DE_OPTOUT
from mobia.workers.jobs.process_message import TEXTO_DO_AVISO_DE_ERRO

# As formas sem acento que o dominio usa de fato. Nao e o portugues inteiro:
# e a lista das palavras que apareciam nos literais desta card, mais as que
# um texto de imobiliaria escreve toda hora.
FORMAS_SEM_ACENTO = (
    "voce",
    "nao",
    "imovel",
    "imoveis",
    "regiao",
    "preco",
    "condominio",
    "criterio",
    "ultima",
    "sabado",
    "horario",
    "tecnico",
    "informacao",
    "opcoes",
    "interrogatorio",
    "tambem",
    "alem",
    "ja ",
    "e so",
    "mes",
    "area",
)

LITERAIS_AO_LEAD = (
    TEXTO_DA_IDENTIFICACAO,
    TEXTO_DA_BUSCA_INCONCLUSIVA,
    TEXTO_SEM_RESULTADO_APOS_AMPLIAR,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
    TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    TEXTO_DO_FILTRO_AJUSTADO,
    CONVITE_PARA_AGENDAR,
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
    TEXTO_DA_JANELA_HUMANA,
    TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
    TEXTO_DO_AVISO_DE_ERRO,
    RESSALVA_DE_ESTIMATIVA,
)


@pytest.mark.parametrize("texto", LITERAIS_AO_LEAD)
def test_nenhum_literal_ao_lead_tem_forma_sem_acento(texto: str) -> None:
    """A TEC-267 fixou que o texto que o lead le e portugues acentuado."""
    minusculo = texto.lower()
    achadas = [forma for forma in FORMAS_SEM_ACENTO if forma in minusculo]
    assert not achadas, f"{achadas} em {texto!r}"


def test_a_lista_de_literais_nao_encolheu_sem_querer() -> None:
    """Guarda da guarda: um literal removido da tupla acima faria o teste de
    cima passar sem checar nada, e ninguem notaria."""
    assert len(LITERAIS_AO_LEAD) == 15
```

> **Confira os nomes de import antes de rodar.** Escrevi esta lista a partir do inventário; se algum módulo ou constante tiver outro nome, use o real e diga no relatório. `_ALUGUEL_AUSENTE` fica de fora de propósito: é privado, e importar um `_nome` de outro módulo num teste é pior que não cobri-lo.

- [ ] **Step 2: Rodar**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_acento_no_texto_ao_lead.py -q --tb=short`
Expected: PASS.

> **Se alguma forma da lista der falso positivo, não relaxe a asserção — conserte a lista.** `"ja "` tem espaço ao fim de propósito, para não casar dentro de outra palavra; `"mes"` casaria em "mesmo", então **confira**: se casar, ou tire da lista ou torne-a mais específica (`"/mes"`). Registre no relatório o que ajustou e por quê.

- [ ] **Step 3: Os três gates, e commitar**

```bash
git add tests/unit/test_acento_no_texto_ao_lead.py
git commit -F- <<'MSG'
test(TEC-267): a fronteira do acento ganha guarda no sentido novo

Substitui as cinco assercoes .isascii() que guardavam a politica revogada e
que as duas tasks anteriores apagaram. Sem isto a card sairia deixando a
fronteira menos protegida do que a encontrou.

Guarda por LISTA DE FORMAS SEM ACENTO, e nao por "tem ao menos um acentuado":
a segunda e falsa para m2, Destaque: e De {} por {}. Esta erra de menos --
uma palavra faltando so deixa de pegar um caso, nunca reprova um certo.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: A fronteira escrita, no `CLAUDE.md` e na docstring que ficou ambígua

**Files:**
- Modify: `CLAUDE.md`, `src/mobia/domain/agente/turno.py` (docstring de `aviso_de_ajuste`)

- [ ] **Step 1: O `CLAUDE.md`**

A seção "Acentos: onde sim, onde não" hoje tem três marcadores. O primeiro diz:

> - **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Convenção do repo, não checada por linter nenhum — é responsabilidade de quem escreve.

Acrescente um marcador **antes** dele, porque é a regra mais visível para o produto:

```markdown
- **Texto que o lead recebe: português COM acento** (TEC-267). Vale para todo literal que chega ao lead — a ficha de imóvel, os avisos, os fallbacks. A razão é que o modelo já escreve acentuado e nada normaliza a saída dele: manter os literais sem acento não produzia uniformidade, produzia metade da conversa com cara de descuido. **Prompt de sistema não conta** — é instrução para o modelo, não texto de produto, e continua sem acento.
```

E ao primeiro marcador existente, acrescente ao fim: `Nenhum linter checa esta fronteira nem a de cima.`

- [ ] **Step 2: A docstring de `aviso_de_ajuste`**

Em `src/mobia/domain/agente/turno.py`, a docstring afirma:

> `bairros` chega na forma dobrada (`recomendacao.bairros_a_excluir`, minuscula e sem acento -- ver `texto.dobrar`); `.title()` basta para virar nome legivel, e o dobrado ja garante ASCII -- nao ha acento para perder na volta.

Continua verdadeira **sobre o nome**, mas agora convive com uma moldura acentuada, e sem uma palavra a mais o próximo leitor a entende como se valesse para a frase inteira. Acrescente ao parágrafo, **em português sem acento** (é docstring):

```
    **A moldura tem acento e o nome nao** (TEC-267, L2): o lead le "Tirei
    Aclimacao da busca, que voce ja descartou". Restaurar a forma de exibicao
    exigiria carrega-la ao lado da chave dobrada por toda a cadeia de
    recomendacao, ou consultar o catalogo aqui dentro -- as duas
    desproporcionais, e a segunda errada. Lacuna declarada, nao esquecimento.
```

- [ ] **Step 3: Commitar**

Sem gates de código a rodar (`CLAUDE.md` não é `.py`), mas rode os três mesmo assim porque `turno.py` foi tocado.

```bash
git add CLAUDE.md src/mobia/domain/agente/turno.py
git commit -F- <<'MSG'
docs(TEC-267): o CLAUDE.md passa a dizer onde a fronteira do acento fica

Ele documentava a regra so para comentario e docstring, e o repo a aplicava
ao texto de produto tambem -- divergencia entre o documentado e o praticado
que e metade do que criou esta card, e a razao pela qual um literal ja tinha
ganhado acento sem ninguem reclamar nem corrigir.

A docstring de aviso_de_ajuste muda junto: ela diz que nao ha acento a perder
na volta, o que continua certo sobre o NOME do bairro e passaria a soar como
se valesse para a frase inteira.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 5: Fechamento

- [ ] **Step 1: Procurar o que ficou para trás**

O desenho lista 24 literais, mas foi um levantamento e levantamentos erram. Varra de novo:

```bash
git diff main --stat
```

E procure literal de saída ainda sem acento nos arquivos que esta branch não tocou:

```bash
grep -rn 'recorder_texto=\|_entregar_texto_fixo(' src/ | head -30
```

Para cada resultado, confirme que o texto entregue já é constante acentuada desta branch, ou que é prosa do modelo. **Se achar um literal de saída que a lista não previa, acrescente-o e diga no relatório** — é exatamente o que aconteceu com `TEXTO_DA_JANELA_HUMANA`, que ninguém esperava encontrar em `notificacao/envio.py`.

- [ ] **Step 2: A listagem de comentários**

Run: `./.venv/Scripts/python.exe scripts/comentarios_tocados.py`

Esta card mexe em oito arquivos de `src/` e altera **texto**, não lógica — a categoria `VIZINHO` tende a ser pequena. O que importa é `ALTERADO`: confira se algum comentário vizinho afirma algo sobre o texto sem acento.

- [ ] **Step 3: A suíte inteira, UMA vez**

Run: `./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short -q`
Expected: verde. Guarde o hash.

- [ ] **Step 4: Os três gates**

- [ ] **Step 5: PR e card**

Mover para **Em análise** e comentar. O comentário precisa registrar:

- **Que a primeira das três saídas da card não existe**, com a evidência: o modelo já escreve acentuado (vinte respostas reais em `evals/relatorios/2026-08-31-tom-com-o-texto.md`), nada normaliza a saída, e portanto a linha de base nunca foi uniforme. **A justificativa da D12 da TEC-162 é falsa.**
- Que eram **24 literais em 8 arquivos**, não os 3 que a card supunha, e que um deles já tinha acento — "manter a convenção" exigiria removê-lo.
- **A lacuna `L2`**: o lead lê *"Tirei Aclimacao da busca, que você já descartou."* Nome de bairro continua ASCII porque é chave de busca. Decisão de produto: aceitável ou vira card?
- **A lacuna `L1`**: nenhum linter checa a fronteira nova, como nenhum checava a antiga.
- **`m2` continua `m2`.** Trocar por `m²` é mudança de outra natureza e ninguém decidiu — é pergunta de produto adjacente, e vale levantá-la.
- **A lacuna `L3`**: o gate do orçamento do prompt mede `len/4` sobre code points e é **cego a acento**. Não importou aqui, porque prompt não é texto ao lead; importa para quem um dia propuser acentuá-los, com 6,2 tokens de margem.

## Cobertura

A card não tem Gherkin — é card de decisão. O que ela pede:

| O que a card pede | Onde | Situação |
| --- | --- | --- |
| Levantar quantos literais existem | Desenho, seção da medição | Feito: 24 em 8 arquivos, contra os 3 supostos |
| Decidir entre as três saídas | `D1` | Decidido: acentuar o que o lead lê |
| Se a política mudar, o `CLAUDE.md` muda junto | Task 3 | Feito |
