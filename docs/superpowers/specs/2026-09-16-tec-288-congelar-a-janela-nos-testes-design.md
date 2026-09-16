# TEC-288 — A suíte não depende da hora em que roda

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-288](https://eduardodurieuxlopes.atlassian.net/browse/TEC-288) — Should (MoSCoW), épico TEC-133
**Branch:** `feat/tec-288-congelar-a-janela-nos-testes`
**Origem:** RF-04; dívida da TEC-143, descoberta durante a TEC-136.

## Objetivo

Dois testes de `tests/integration/test_pedido_de_humano.py` reprovam fora do horário comercial porque o arquivo não congela a janela de atendimento. A `main` fica vermelha em qualquer execução noturna, e o custo real não é o teste — é o sinal.

## Por que isto envenena o sinal, e não só incomoda

O `CLAUDE.md` deste repo tem uma regra de diagnóstico: *rode de novo antes de culpar sua mudança*. **Ela não separa este caso.** A falha não é flake — é determinística dentro da janela de tempo errada, e reproduz idêntica em duas execuções seguidas. Quem seguir a regra à risca conclui que a própria mudança quebrou alguma coisa.

É o mesmo mecanismo que o repo já registrou noutro lugar: falha conhecida treina quem lê a ignorar. Aqui é pior, porque a regra que existe para distinguir flake de regressão diz "regressão".

## A varredura, e o resultado dela é o conteúdo durável desta card

A card pedia varrer os outros arquivos de integração atrás da mesma dependência implícita do relógio. **Feito em 16/09/2026, e só existem os dois casos conhecidos.**

Todo outro teste guiado por relógio neste repo já está defendido, de uma de três formas:

| forma | onde |
| --- | --- |
| **Congela** — `monkeypatch`, `datetime` fixo, ou `agora=` explícito por parâmetro | `test_encaminhamento_por_intencao.py`, `test_deteccao_de_humano.py`, `test_horario_de_envio.py`, `test_followups_model.py`, `test_sweep_followups.py`, `test_handoff_sla.py` |
| **Ancora relativamente** — lê o relógio real só como referência entre um antes e um depois, de modo que nenhuma asserção depende da hora absoluta | `test_escalada_de_sla.py`, `test_recuperacao_sem_prazo.py` |
| **Lê e não afirma** — carimbos de `updated_at`, `clock_timestamp()` e afins, que ninguém asserta | toda a escrituração de timestamp em `src/` |

**O repo já resolveu este problema duas vezes, de jeitos diferentes**, e os dois merecem ser conhecidos:

1. A fixture `autouse` da TEC-137 (`test_encaminhamento_por_intencao.py`), que **congela** — é o molde desta card.
2. `_janela_fechada_para_agora()` em `test_notificacao_envio.py`, que **não pode** congelar e então escolhe, entre duas janelas fixas, a que estiver mais longe do relógio atual, com margem de pior caso de 150 minutos. O comentário de lá registra um bug anterior em que um cálculo ingênuo encolhia a margem para cerca de um minuto.

Quem encontrar um terceiro caso no futuro escolhe entre esses dois padrões conforme possa ou não congelar.

## Um critério da card já estava atendido

A card pede que *"a variante de fora do horário mereça teste próprio, com a janela congelada fechada"*. Ela já tem: `test_fora_do_horario_o_texto_muda_e_o_handoff_e_criado_do_mesmo_jeito` faz `monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: False)` e afirma as duas coisas que interessam. A card foi escrita sem esse conhecimento; fica registrado para não se criar um teste duplicado.

## Decisões

### D1 — Congelar a janela ABERTA por fixture `autouse`, no molde da TEC-137

```python
@pytest.fixture(autouse=True)
def janela_aberta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turno_mod, "dentro_da_janela_de_atendimento", lambda agora: True)
```

Congelar **aberta** e não fechada porque é o estado que a maioria dos testes do arquivo pressupõe — o texto de dentro do horário é o caminho principal do pedido de humano, e o de fora é a exceção que já tem teste próprio.

O `monkeypatch` alveja `turno_mod.dentro_da_janela_de_atendimento` — o nome **como importado em `turno.py`**, e não a definição em `deteccao.py`. É o que a fixture da TEC-137 faz, e é o que funciona: o turno resolve o nome no módulo dele.

**O teste de fora do horário continua valendo.** O `setattr` dele roda depois da fixture e vence. Isso vai ser confirmado por execução, não por dedução.

### D2 — A prova de RED fecha a janela por configuração, e não espera a madrugada

Esperar as 2h para ver o teste reprovar não é verificação, é superstição. A janela vem de `Settings.atendimento_horario_inicio/fim`, então fechá-la por variável de ambiente reproduz a falha em qualquer hora:

```bash
ATENDIMENTO_HORARIO_INICIO=0 ATENDIMENTO_HORARIO_FIM=1 ./.venv/Scripts/python.exe -m pytest tests/integration/test_pedido_de_humano.py
```

**Medido em 16/09/2026, 12:13 local:** com a janela assim, exatamente os dois testes reprovam e os outros catorze passam. Depois do conserto, o arquivo inteiro tem de passar **com e sem** essas variáveis — e as duas execuções são o critério de pronto, porque só a primeira prova que a fixture funciona e só a segunda prova que ela não quebrou o caminho normal.

## Lacunas declaradas

**A varredura é de hoje, não é um gate.** Nada impede que a próxima card escreva um teste com dependência implícita do relógio; o que esta card deixa é o registro dos dois padrões e a prosa que os nomeia. Um gate automático — algo que detecte `datetime.now` alcançável a partir de uma asserção — seria outra card, e provavelmente cara demais para o que evita.

**O texto do aviso continua prometendo "de segunda a sábado" enquanto o código não olha o dia da semana.** O comentário de `notificacao/envio.py` já declara essa divergência, e alinhar os dois é a TEC-285. Fora de escopo aqui.

## Testes

Não há teste novo. O critério é o arquivo existente passar nas duas execuções da D2 — com a janela de produção e com a janela fechada por configuração.

## Fora de escopo

- Mudar a janela de atendimento em si (TEC-285).
- Mudar qualquer texto entregue ao lead.
- O `SAWarning` pré-existente de `test_message_model.py` (TEC-260).
- Um gate automático contra dependência de relógio.
