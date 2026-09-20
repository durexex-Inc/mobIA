# TEC-289 — Asserção de ausência que pode reprovar

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-289](https://eduardodurieuxlopes.atlassian.net/browse/TEC-289) — épico TEC-208
**Branch:** `feat/tec-289-asserta-de-ausencia-que-pode-reprovar`
**Origem:** achado durante a TEC-138.

## Objetivo

Fazer com que uma asserção da forma *"este texto não vazou para o log"* possa de fato reprovar, e que continue podendo depois de qualquer acentuação futura de fixture.

## O que a exploração mudou em relação ao texto da card, e é muito

**O mecanismo não é o `json.dumps` escrito no teste — é o renderer da aplicação.** `configure_logging` usa `structlog.processors.JSONRenderer()` (`app/logging.py:125`), que serializa no padrão `ensure_ascii=True`. Então **`caplog.text` já chega escapado**, sem que nenhum teste chame `json.dumps`. A classe é muito maior que os dois sítios de `json.dumps` que a card mapeou: são ~70 asserções de ausência sobre log, e toda uma família (`not in caplog.text`, `not in registro.getMessage()`) está exposta pelo mesmo motivo.

Provado nesta máquina, com a configuração real do app: `assert "Acho que não falo de imóveis" not in caplog.text` **passa** enquanto o log traz o mesmo texto na forma escapada — os caracteres acentuados saem como `n\u00e3o` e `im\u00f3veis`, e a agulha acentuada nunca encontra o palheiro escapado.

**E mesmo assim não existe nenhuma asserção vazia hoje.** As 70 foram resolvidas até o literal. Todas as agulhas usadas contra log são ASCII puro; a única não-ASCII é `TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO` (a asserta da despedida em `test_conversa_encerrada.py`), e é exatamente a que a TEC-138 já protegeu com `ensure_ascii=False`. Os sentinelas de teste (`SENTINELA-RESUMO ...`, `"5511987654321"`) são ASCII por construção, e os nomes de evento (`"contexto.truncado"`) nunca terão acento.

**Consequência para o que esta card é.** Ela não conserta defeito: ela impede uma classe. O valor está inteiro no futuro — no dia em que alguém acentuar uma fixture de fala do lead, que é o que a convenção da TEC-267 pede, e a asserta de PII ao lado dela silenciar sem ficar vermelha.

**São seis cópias do helper, não três** (`test_apresentacao_no_turno.py`, `test_citacao_no_turno.py`, `test_conversa_encerrada.py`, `test_escalada_de_sla.py`, `test_notificacao_envio.py`, mais `eventos_de_log` sem underscore em `tests/features/test_dedup_por_message_id.py`), **e em duas assinaturas**: três devolvem `(nivel, corpo)` e três devolvem só o corpo.

**O `ruff` não pega, e a resposta é definitiva.** Nenhuma das 970 regras trata de `ensure_ascii`; as regras com "ascii" no nome são sobre nomes de identificador (`PLC2401`, `PLC2403`) e caracteres ambíguos (`RUF001-003`). A card pedia para responder isso em vez de deixar a pergunta aberta.

## D1 — Não se conserta no renderer, e a razão foi medida

A via mais curta seria uma linha em `app/logging.py`:

```python
_renderizar_json = structlog.processors.JSONRenderer(
    serializer=partial(json.dumps, ensure_ascii=False)
)
```

Ela mata a classe inteira e para sempre, inclusive para asserta futura que ninguém revisou. Foi sondada: os 1549 testes unitários seguem verdes, e a asserta antes vazia passa a reprovar. **Mesmo assim, não é o que esta card faz.**

Duas razões, nesta ordem:

1. **Custo medido, não hipotético.** O `stdout` desta máquina é `cp1252`, e escrever um emoji cru levanta `UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f642'`. Lead mandando emoji não é exótico — é o tráfego que a TEC-225 usou para justificar a contagem ciente de densidade. Desligar o escape exigiria reconfigurar o `stdout` junto, e aí a mudança deixa de ser de uma linha.
2. **Escopo.** A card diz, por escrito, que mudar o que o código loga está fora dela. Mudar os bytes que saem em produção para consertar uma armadilha de teste é decisão operacional — o que sai do log é lido por quem opera, não só por pytest.

Fica registrado como alternativa medida, não como caminho recusado por preguiça: se um dia o `stdout` já for UTF-8 por outra razão, esta é a forma mais barata de fechar o assunto.

## D2 — Um helper só, e ele devolve um `NamedTuple`

As seis cópias viram uma função em `tests/conftest.py`, visível a `unit`, `integration` e `features` sem import entre arquivos de teste.

O conflito de assinatura se resolve sem escolher um lado:

```python
class EventoDeLog(NamedTuple):
    nivel: str
    corpo: dict[str, Any]
```

`NamedTuple` **é** tupla, então os três sítios que hoje fazem `((nivel, corpo),) = _eventos_de_log(...)` continuam funcionando sem mudar uma letra. Os três que hoje recebem dicionários passam a escrever `.corpo`, que é uma edição mecânica e legível — e que torna explícito o que a forma antiga escondia: que o nível estava sendo jogado fora.

## D3 — `log_legivel(caplog)`, o substituto de `caplog.text` para agulha de produto

Também em `tests/conftest.py`. Decodifica cada registro JSON e re-serializa com `ensure_ascii=False`, deixando passar sem tocar o que não for JSON:

```python
def log_legivel(caplog: Any) -> str:
    """Todo o log capturado, com o escape de `\\uXXXX` desfeito."""
```

É o que uma asserta de ausência sobre texto de produto deve usar. **Não substitui `caplog.text` em toda parte:** as ~40 assertas que procuram nome de evento (`"contexto.truncado" not in caplog.text`) continuam como estão, porque nome de evento é ASCII por construção e trocá-las seria diff sem ganho.

## D4 — A guarda resolve a agulha, e é isso que a torna real

Teste novo em `tests/unit/`, no molde do que o repo já faz com `ast` em `scripts/comentarios_tocados.py`.

Ele varre `tests/` procurando asserção de ausência (`assert X not in Y`, e a forma `not any(X in ... )`) cujo **palheiro seja log escapado** — `caplog.text`, `registro.getMessage()`, ou `json.dumps(...)` sem `ensure_ascii=False` — e **resolve a agulha até o valor**:

* literal de string: o valor é ele mesmo;
* nome atribuído no topo do próprio arquivo de teste: resolvido por `ast`;
* nome importado de `mobia.*`: resolvido importando o módulo e lendo o atributo.

Se a agulha resolvida tiver caractere não-ASCII, a guarda reprova, nomeando arquivo, linha e o substituto (`log_legivel`).

**Uma agulha que não se resolver não reprova — é listada.** É a mesma assimetria que a guarda de acento declara, e que a TEC-286 repetiu: errar de menos nunca cria trabalho falso; errar de mais treina quem lê a ignorar. A varredura desta card mostrou que hoje as 70 agulhas se resolvem, então a lista de irresolvidos nasce vazia.

**Sem a resolução de agulha a guarda seria decorativa.** Barrar só `json.dumps` sem o flag — que foi a primeira versão desta seção — deixaria de fora justamente a família do `caplog.text`, que é onde estão todas as assertas a um refactor de distância de virar vazias.

## D5 — O sítio latente ganha a guarda que o irmão já tem

O teste do resumo ilegível em `test_notificacao_envio.py` serializa com `json.dumps(avisos[0])` no padrão. As agulhas são `"fulano"` e `"outro texto"`, ASCII, então a asserta é real hoje. Ela passa a usar `ensure_ascii=False`, com comentário — é o mesmo construto da asserta da despedida em `test_conversa_encerrada.py` sem a proteção, e basta alguém trocar `"fulano"` por um nome realista para nascer vazia.

## D6 — A armadilha vira teste executável

Um teste que afirma as duas metades do mecanismo, em vez de descrevê-las em comentário: com o logger configurado como o app o configura, uma agulha acentuada **não** é achada em `caplog.text` e **é** achada em `log_legivel(caplog)`.

É a documentação que não pode envelhecer: se um dia alguém desligar o escape no renderer (a D1), este teste reprova e obriga a rever esta card inteira, em vez de deixar dois fatos contraditórios convivendo no repo.

## D7 — O que não muda

* **As fixtures de fala do lead continuam sem acento.** Acentuá-las mudaria o que os testes exercitam, e é card de outra pessoa; com a guarda no lugar, acentuar uma delas passa a ser mudança que o repo denuncia em vez de engolir.
* **As ~40 assertas de nome de evento** ficam em `caplog.text`.
* **`test_extracao.py:248` usa `registro.message` em vez de `getMessage()`** — única ocorrência no repo, dependência de detalhe do pytest. Fica anotada, não consertada: não é escape, e trocá-la aqui seria carona.
* **O `SAWarning` de `test_message_model.py`** é a TEC-260, como a card já diz.

## Testes

* A guarda nova, sobre `tests/` inteiro: nenhuma asserta de ausência com agulha não-ASCII sobre palheiro escapado.
* **Verificação nos dois sentidos, que é a nota de método da card:** um caso plantado — agulha acentuada contra `caplog.text` — faz a guarda reprovar; sem ele, ela passa. Vale para a guarda e para o teste da D6.
* O helper único exercitado pelos seis arquivos que antes tinham cópia.
* A suíte inteira, uma vez, porque a mudança de assinatura toca arquivos de integração.

## O que este desenho não entrega

Acentuar as fixtures de fala do lead, que é o que tornaria as assertas de PII realistas em vez de apenas corretas. E o conserto no renderer (D1), que fecharia a classe também para quem escrever asserta fora destes padrões.
