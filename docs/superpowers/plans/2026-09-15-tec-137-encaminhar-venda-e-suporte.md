# TEC-137 — Encaminhar venda de imóvel e suporte de contrato direto ao handoff

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando a intenção é `VENDER_IMOVEL` ou `SUPORTE_CONTRATO`, o lead recebe um texto fixo de encaminhamento em vez da prosa do modelo — que hoje pode conter a pergunta de qualificação de comprador que a RN-03.4 proíbe.

**Architecture:** Duas constantes novas e uma substituição no mesmo sítio de `turno.py` que o teto de perguntas já usa, com precedência acima dele. O handoff, a etiqueta, o log e o resumo já existem desde a TEC-174 e **não são tocados** — esta card é só sobre o que o lead recebe.

**Tech Stack:** Python 3.13, pytest. Sem dependência nova, sem migração, sem configuração nova.

**Spec:** `docs/superpowers/specs/2026-09-15-tec-137-encaminhar-venda-e-suporte-design.md`

## Global Constraints

- **Comentários e docstrings em `src/` e `tests/`: português SEM acento.** Exceto valor citado.
- **Texto que o lead recebe: português COM acento** (TEC-267). Vale para as duas constantes novas.
- **Nenhum texto pode afirmar que alguém foi avisado.** `notificacao/envio.py:44-53` proíbe nominalmente e termina com *"Nao reintroduza a promessa"*; o comentário de `TEXTO_DO_LIMITE_DE_PERGUNTAS` repete. A TEC-143 reintroduziu a frase ontem e a revisão final a pegou.
- **Mensagem de commit:** `tipo(TEC-137): o que passou a ser verdade`, assunto em português sem acento, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Os três gates, com este escopo exato, antes de qualquer commit:**
  ```bash
  ./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
  ./.venv/Scripts/python.exe -m mypy
  ```
- **Testes:** `tests/unit/` sem Docker; `tests/integration/` com `docker compose` de pé. Rode o arquivo inteiro, sem `-k`.
- **NÃO mexa em `_GATILHO_DA_INTENCAO`, `ETIQUETA_DE`, `PRIORIDADE_DE` nem no bloco que registra o handoff da intenção.** Tudo isso já funciona.
- **NÃO acrescente instrução ao prompt de sistema.** A margem do orçamento está em 1,2 tokens (medido na TEC-143), e o teste `test_a_margem_do_orcamento_do_prompt_e_deliberada` reprova.

---

## File Structure

| arquivo | responsabilidade |
| --- | --- |
| `src/mobia/domain/agente/turno.py` (modifica) | as duas constantes e a substituição |
| `tests/integration/test_encaminhamento_por_intencao.py` (cria) | o comportamento no turno |
| `tests/unit/test_textos_do_encaminhamento.py` (cria) | os textos, puro |

Nada é criado em `src/`. As constantes moram em `turno.py` junto das irmãs (`TEXTO_DO_LIMITE_DE_PERGUNTAS`, `TEXTO_NEUTRO_DE_SAIDA`), e não num módulo novo: ao contrário do pedido de humano, aqui não há detecção nem assunto próprio — é só o texto que o orquestrador entrega.

---

### Task 1: As duas constantes

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (acrescenta depois de `TEXTO_DO_LIMITE_DE_PERGUNTAS`, perto da linha 174)
- Test: `tests/unit/test_textos_do_encaminhamento.py` (cria)

**Interfaces:**
- Consumes: nada
- Produces: `TEXTO_DO_ENCAMINHAMENTO_DE_VENDA: str`, `TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE: str`, `SUFIXO_FORA_DA_JANELA: str` (com `{inicio}` e `{fim}` para formatar)

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_textos_do_encaminhamento.py`:

```python
"""Os textos que o lead recebe ao ser encaminhado. TEC-137.

Puro: nao toca banco nem modelo. O que se testa aqui e o CONTEUDO -- em
especial que nenhum dos dois promete que alguem foi avisado, que e a frase que
este repo ja reescreveu duas vezes (TEC-174 e TEC-143).
"""

import pytest

from mobia.domain.agente.turno import (
    SUFIXO_FORA_DA_JANELA,
    TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
    TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
)


@pytest.mark.parametrize(
    "texto",
    [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA, TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE],
)
def test_nenhum_texto_promete_que_alguem_foi_avisado(texto: str) -> None:
    """A frase que o repo ja reescreveu duas vezes, barrada por teste.

    `notificacao/envio.py` proibe a promessa por escrito e nomeia o precedente:
    a TEC-174 escreveu "ja avisei um corretor" e teve de reescrever, porque
    nada notificava. A TEC-143 a reintroduziu e a revisao final a pegou. Criar
    handoff nao notifica ninguem -- TEC-280 e TEC-281 estao abertas.
    """
    minusculo = texto.lower()
    assert "avisei" not in minusculo
    assert "avisamos" not in minusculo
    assert "avisado" not in minusculo


def test_os_dois_textos_sao_distintos() -> None:
    """Quem quer vender e quem tem duvida de contrato nao sao a mesma fila.

    O Gherkin da card pede etiquetas distintas (`venda-imovel` e
    `suporte-contrato`) porque sao trabalhos diferentes para o corretor. Um
    texto generico serviria mal a quem JA e cliente e so tem duvida de reajuste.
    """
    assert TEXTO_DO_ENCAMINHAMENTO_DE_VENDA != TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE


def test_o_sufixo_de_fora_da_janela_nomeia_o_horario() -> None:
    """O sufixo formata a partir da configuracao, e nao cita numero fixo.

    O Gherkin da card diz "das 9h as 19h" e a janela real da TEC-143 e 9h-18h.
    Citar o numero da card num literal faria o texto mentir sobre o que o
    sistema faz -- por isso ele vem de `Settings`. A divergencia esta declarada
    na D3 do desenho.
    """
    formatado = SUFIXO_FORA_DA_JANELA.format(inicio=9, fim=18)
    assert "9" in formatado
    assert "18" in formatado
    assert "{inicio}" not in formatado


@pytest.mark.parametrize(
    "texto",
    [TEXTO_DO_ENCAMINHAMENTO_DE_VENDA, TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE],
)
def test_nenhum_texto_faz_pergunta_de_qualificacao(texto: str) -> None:
    """A RN-03.4 tira estas intencoes do SDR, e o texto nao pode reintroduzi-la.

    Nao ha como provar ausencia de pergunta por analise de texto, entao o que
    esta guarda checa e o sinal mais grosseiro: o texto de encaminhamento nao
    termina em pergunta. Um "qual o bairro?" aqui seria a qualificacao de
    comprador entrando pela porta que a card fechou.
    """
    assert not texto.rstrip().endswith("?")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_textos_do_encaminhamento.py --tb=short`
Expected: FAIL com `ImportError: cannot import name 'TEXTO_DO_ENCAMINHAMENTO_DE_VENDA'`

- [ ] **Step 3: Write minimal implementation**

Em `turno.py`, logo depois de `TEXTO_DO_LIMITE_DE_PERGUNTAS` (que termina perto da linha 174):

```python
# RN-03.4 (TEC-137). Substituem a prosa do modelo quando a intencao e
# VENDER_IMOVEL ou SUPORTE_CONTRATO -- duas conversas que nao sao trabalho de
# SDR e que o `_GATILHO_DA_INTENCAO` ja manda para a fila humana desde a
# TEC-174. O que faltava era o lead saber disso: ate aqui ele recebia a prosa
# do modelo, que podia conter a pergunta de qualificacao de COMPRADOR que a
# regra proibe.
#
# **Dois textos e nao um.** Quem quer vender um imovel e quem tem duvida sobre
# contrato vigente vao para filas diferentes (`venda-imovel` e
# `suporte-contrato` em ETIQUETA_DE), e a segunda pessoa JA e cliente. "Vou
# passar para um corretor que te ajuda a encontrar" serviria mal a ela.
#
# **Nenhum dos dois promete que alguem foi avisado**, pela razao que o
# comentario de TEXTO_DO_LIMITE_DE_PERGUNTAS acima ja registra e que
# `notificacao/envio.py` proibe nominalmente: criar handoff nao notifica
# ninguem enquanto TEC-280 e TEC-281 estiverem abertas. A TEC-174 escreveu
# "ja avisei um corretor" e teve de reescrever; a TEC-143 reintroduziu a frase
# e a revisao final a pegou. `test_textos_do_encaminhamento.py` guarda isso.
#
# Sem kind proprio, como TEXTO_DO_LIMITE_DE_PERGUNTAS: isto e substituicao em
# lugar, nao mensagem adicional, entao nao ha segunda mensagem com que colidir
# na UNIQUE (message_id, kind).
TEXTO_DO_ENCAMINHAMENTO_DE_VENDA = (
    "Que bom que pensou na gente para vender seu imóvel! Isso quem cuida é um "
    "corretor da equipe, não eu — já coloquei sua conversa na fila deles."
)

TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE = (
    "Dúvida de contrato é com a equipe, não comigo — já coloquei sua conversa "
    "na fila deles para te responderem com segurança."
)

# Acrescentado aos dois textos acima quando o pedido chega fora da janela de
# atendimento. As horas vem de `Settings`, e nao de um literal, porque o
# Gherkin da card diz "das 9h as 19h" enquanto a janela real (TEC-143) e
# 9h-18h: citar o numero da card faria o texto mentir sobre o que o sistema
# faz. Ver a D3 do desenho.
SUFIXO_FORA_DA_JANELA = " O atendimento é das {inicio}h às {fim}h, então a resposta vem no próximo horário."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/unit/test_textos_do_encaminhamento.py --tb=short`
Expected: 6 passed

- [ ] **Step 5: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py tests/unit/test_textos_do_encaminhamento.py
git commit -m "feat(TEC-137): os textos de encaminhamento existem e nao prometem aviso

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A substituição no turno

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` — o bloco perto da linha 1807 (`if teto_da_entrega and not desambiguando and not saida_bloqueada:`)
- Test: `tests/integration/test_encaminhamento_por_intencao.py` (cria)

**Interfaces:**
- Consumes: as três constantes da Task 1; `dentro_da_janela_de_atendimento` e `Settings.atendimento_horario_inicio/fim` (da TEC-143, já existem); `_GATILHO_DA_INTENCAO` (já existe, **não altere**)
- Produces: nada que tasks posteriores consumam

- [ ] **Step 1: Write the failing test**

Crie `tests/integration/test_encaminhamento_por_intencao.py`. A fixture `rodar_turno` está em `tests/conftest.py:556` com a assinatura `(session, classificador, outbound, resumidor, contador, moderador=None, agendador=None, *, texto=...)`, e o `ClassificadorFake` (linha 276) aceita `intencao=` e `resposta=` no construtor — é por `resposta=` que se distingue a prosa do modelo do texto novo.

O primeiro teste, completo, serve de molde para os outros seis:

```python
"""O encaminhamento de VENDER_IMOVEL e SUPORTE_CONTRATO. TEC-137."""

from datetime import UTC, datetime

from sqlalchemy import select

from mobia.domain.agente.schemas import Intencao
from mobia.domain.agente.turno import (
    TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
    TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
)
from mobia.domain.handoff.models import Handoff

PROSA_DO_MODELO = "Legal! Em que bairro voce procura e qual a sua faixa de preco?"


async def test_venda_de_imovel_entrega_o_texto_proprio_e_nao_a_prosa_do_modelo(
    session, outbound, resumidor, contador, rodar_turno
) -> None:
    """O caso da card: o proprietario nao pode ser qualificado como comprador.

    `PROSA_DO_MODELO` e uma pergunta de qualificacao de COMPRADOR -- exatamente
    o que a RN-03.4 tira destas duas intencoes. Ate a TEC-137 ela saia.
    """
    classificador = ClassificadorFake(intencao=Intencao.VENDER_IMOVEL, resposta=PROSA_DO_MODELO)

    await rodar_turno(
        session,
        classificador,
        outbound,
        resumidor,
        contador,
        texto="quero colocar meu apartamento a venda com voces",
    )

    entregue = outbound.entregues[-1]
    assert TEXTO_DO_ENCAMINHAMENTO_DE_VENDA in entregue
    assert PROSA_DO_MODELO not in entregue

    linha = await session.scalar(select(Handoff).where(Handoff.conversation_key.is_not(None)))
    assert linha is not None
    assert linha.etiqueta == "venda-imovel"
```

**Confira o nome e a forma de `outbound.entregues`** antes de escrever os outros — `test_pedido_de_humano.py` (TEC-143) usa o mesmo dublê e é o arquivo irmão a copiar. Se o dublê expuser o texto de outro jeito, use o que estiver lá.

Os outros seis, no mesmo molde:

1. `test_venda_de_imovel_entrega_o_texto_proprio_e_nao_a_prosa_do_modelo` — classificador devolve `VENDER_IMOVEL`. Afirma: o texto entregue é `TEXTO_DO_ENCAMINHAMENTO_DE_VENDA`; a prosa do modelo **não** foi entregue; existe handoff com etiqueta `venda-imovel`.
2. `test_suporte_de_contrato_entrega_o_outro_texto` — mesmo com `SUPORTE_CONTRATO`, etiqueta `suporte-contrato`, e o texto é o de suporte (distinto do de venda).
3. `test_fora_da_janela_o_texto_nomeia_o_horario` — congele o relógio fora da janela. Afirma: o texto entregue começa com o de venda **e** contém as horas da configuração.
4. `test_dentro_da_janela_o_texto_nao_nomeia_horario` — a contraprova. Sem ela, um sufixo incondicional passaria.
5. `test_o_segundo_turno_com_a_mesma_intencao_entrega_de_novo` — dois turnos, mesma intenção. Afirma: o texto sai nos dois; existe **um** handoff só (a D2 aceita a repetição do texto, e `registrar_handoff` acumula sem duplicar).
6. `test_o_encaminhamento_vence_o_teto_de_perguntas` — estado com perguntas no teto **e** intenção de venda. Afirma: o texto entregue é o de encaminhamento, não `TEXTO_DO_LIMITE_DE_PERGUNTAS`.
7. `test_saida_bloqueada_vence_o_encaminhamento` — moderação de saída reprovando, com intenção de venda. Afirma: o texto é `TEXTO_NEUTRO_DE_SAIDA`. É a guarda que o comentário do sítio já exige.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_encaminhamento_por_intencao.py --tb=short`
Expected: FAIL — a prosa do modelo é entregue, não o texto novo

- [ ] **Step 3: Write minimal implementation**

O bloco novo entra **imediatamente antes** do `if teto_da_entrega and not desambiguando and not saida_bloqueada:` (linha 1807), para que a precedência funcione por ordem de atribuição — o teto sobrescreveria se viesse depois.

```python
    # RN-03.4 (TEC-137). Precedencia ACIMA do teto de perguntas, logo abaixo:
    # quem vai para a fila de venda nao precisa ouvir "ja perguntei bastante",
    # e o teto e sobre qualificacao, que estas duas intencoes nao recebem.
    #
    # As mesmas duas guardas do bloco de baixo, pelas mesmas razoes que o
    # comentario dele escreve por extenso: `not desambiguando` porque nesse
    # caminho quem sai e a pergunta do desambiguador, e `not saida_bloqueada`
    # porque `TEXTO_NEUTRO_DE_SAIDA` e a resposta declarada da politica de
    # moderacao e sobrepor a nossa a ela tornaria impossivel saber qual agiu.
    #
    # Le `gerada.intencao` e nao `gatilho_da_intencao`: aquela variavel vive no
    # bloco transacional la em cima e nao chega aqui, e o mapa e o mesmo.
    # Consequencia da D2 do desenho: isto roda em TODO turno com a intencao,
    # nao so no primeiro. O lead que insiste recebe a mesma frase de novo --
    # aceito, porque a alternativa devolveria ao modelo a palavra no segundo
    # turno, com ela a pergunta de qualificacao que a regra proibe.
    encaminhando = _TEXTO_DO_ENCAMINHAMENTO.get(gerada.intencao)
    if encaminhando is not None and not desambiguando and not saida_bloqueada:
        texto = encaminhando
        if not dentro_da_janela_de_atendimento(datetime.now(UTC)):
            settings_do_turno = get_settings()
            texto += SUFIXO_FORA_DA_JANELA.format(
                inicio=settings_do_turno.atendimento_horario_inicio,
                fim=settings_do_turno.atendimento_horario_fim,
            )
```

E o mapa, junto das constantes da Task 1:

```python
# Espelha `_GATILHO_DA_INTENCAO` deliberadamente: as duas intencoes que vao
# para a fila humana sao as mesmas que recebem texto proprio. Sao dois mapas e
# nao um porque respondem perguntas diferentes -- um diz "qual gatilho de
# handoff", o outro "qual texto para o lead" --, e um dicionario de tuplas
# obrigaria todo leitor de um dos lados a entender o outro.
_TEXTO_DO_ENCAMINHAMENTO = {
    Intencao.VENDER_IMOVEL: TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
    Intencao.SUPORTE_CONTRATO: TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
}
```

**Confira três coisas antes de commitar, porque o plano não as adivinha:**
1. `gerada` é o nome certo da variável com a resposta classificada naquele ponto? Se o nome for outro, use o que estiver lá.
2. `dentro_da_janela_de_atendimento` e `get_settings` já estão importados em `turno.py`? Se não, acrescente.
3. `datetime` e `UTC` estão no escopo? O bloco do pedido de humano (TEC-143) usa os dois.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/integration/test_encaminhamento_por_intencao.py --tb=short`
Expected: 7 passed

- [ ] **Step 5: Gates, suíte inteira e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
./.venv/Scripts/python.exe -m pytest -n 8 --dist loadfile --tb=short
```

Uma execução verde basta. Se falhar, rode de novo sobre a mesma árvore antes de culpar a mudança — há falhas conhecidas de `ConnectionResetError [WinError 64]` neste repo. Se persistir idêntica em duas execuções, **pare e relate**.

**Atenção especial nesta suíte:** existem testes da TEC-174 e da TEC-153 que exercitam `VENDER_IMOVEL`/`SUPORTE_CONTRATO` e podem afirmar que a prosa do modelo sai. Se algum reprovar, **não o relaxe sem entender**: ele pode estar fixando o comportamento que esta card muda de propósito — nesse caso, atualize-o e diga no relatório qual era e por que mudou — ou pode ter pegado uma regressão de verdade.

```bash
git add src/mobia/domain/agente/turno.py tests/integration/test_encaminhamento_por_intencao.py
git commit -m "feat(TEC-137): a venda e o suporte recebem texto proprio em vez da prosa do modelo

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A prosa que a mudança tornou desatualizada

**Files:**
- Modify: `src/mobia/domain/agente/turno.py` (o comentário de `_GATILHO_DA_INTENCAO`, perto da linha 214)
- Modify: `docs/srs/srs-agente-sdr-imobiliario-v1.0.md` (emenda à RN-03.4)

- [ ] **Step 1: Rodar a listagem de comentários tocados**

```bash
./.venv/Scripts/python.exe scripts/comentarios_tocados.py main
```

Releia o que ela apontar. Ela aponta prosa em `.md` desde a TEC-282, e **é cega a docstring de módulo** (TEC-283, aberta) — então confira à mão a docstring de topo de cada arquivo tocado.

- [ ] **Step 2: Corrigir o comentário de `_GATILHO_DA_INTENCAO`**

Ele diz hoje:

> **O lead segue recebendo a resposta deste turno**: silenciar e a RN-16.4, que e a TEC-179.

Isso deixou de ser verdade — o lead passa a receber o texto de encaminhamento. Reescreva essa frase para o que vale agora, mantendo o resto do comentário. A distinção que ele fazia (receber resposta ≠ ser silenciado) continua útil e deve sobreviver: o agente **não** silencia nesta card, só troca o texto.

- [ ] **Step 3: Emendar o SRS**

A RN-03.4 é a regra que manda estas intenções para handoff. Acrescente **`Emenda E-nn (TEC-137, 15/09/2026)`** como item aninhado abaixo dela, usando o próximo `nn` livre naquela regra, **sem reescrever** o texto de 22/08/2026.

A emenda declara: o lead recebe texto fixo de encaminhamento em vez da prosa do modelo, com dois textos distintos por intenção; a substituição vale em todo turno com aquela intenção, não só no primeiro; o aviso de horário usa a janela da imobiliária da TEC-143; e **o Gherkin da card diz "segunda a sábado, das 9h às 19h" enquanto a janela real é 9h–18h sem dia da semana** — o texto formata a partir da configuração, e alinhar os dois é decisão de produto.

Prosa em `docs/` vai **COM** acento.

- [ ] **Step 4: Gates e commit**

```bash
./.venv/Scripts/python.exe -m ruff check src tests alembic evals scripts
./.venv/Scripts/python.exe -m ruff format --check src tests alembic evals scripts
./.venv/Scripts/python.exe -m mypy
git add src/mobia/domain/agente/turno.py docs/srs/
git commit -m "docs(TEC-137): a RN-03.4 ganha a emenda do texto ao lead, e o comentario para de dizer que o modelo responde

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Cobertura dos critérios de aceite da card

| cenário Gherkin | onde é exercitado |
| --- | --- |
| Proprietário que quer vender vai direto ao handoff | T2 teste 1 — handoff com etiqueta `venda-imovel`, texto próprio, prosa do modelo não entregue |
| Dúvida sobre contrato também é encaminhada | T2 teste 2 — etiqueta `suporte-contrato`, texto distinto |
| Pedido fora do horário de atendimento | T2 testes 3 e 4 — com a contraprova de dentro da janela |
| "o agente não faz perguntas de qualificação" | T2 teste 1 (prosa substituída) e T1 (o texto não termina em pergunta) |
| "o lead recebe confirmação do encaminhamento" | T2 testes 1 e 2 |

**Divergência declarada (D3):** o Gherkin diz *"de segunda a sábado, das 9h às 19h"*; a janela real é 9h–18h sem dia da semana. O texto diz o que a configuração diz. Vai no comentário da card.

**O que já existia e esta card não refaz:** o handoff, a etiqueta, o log `handoff.criado` e o `_agendar_resumo` vêm da TEC-174. Os testes 1 e 2 os afirmam para garantir que a mudança não os quebrou, não porque esta card os construa.
