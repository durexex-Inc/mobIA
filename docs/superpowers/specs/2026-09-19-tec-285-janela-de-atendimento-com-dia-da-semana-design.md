# TEC-285 — A janela de atendimento ganha dia da semana

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-285](https://eduardodurieuxlopes.atlassian.net/browse/TEC-285) — épico TEC-133
**Branch:** `feat/tec-285-janela-de-atendimento-com-dia-da-semana`
**Decisão de produto:** comentário do Eduardo na card, 19/09/2026 — *"Janela de atendimento humano segunda-a-sábado 9h–19h"*.
**Origem:** dívida declarada da TEC-137 (D3 do desenho, Emenda E-01 à RN-03.4); a TEC-288 passou o bastão nominalmente.

## Objetivo

Fazer a janela de atendimento humano ser **segunda a sábado, 9h–19h**, e fazer o texto que o lead recebe dizer isso.

Hoje ela é 9h–18h e trata domingo como dia útil. O `SUFIXO_FORA_DA_JANELA` já carrega um comentário que existe **só** para registrar essa divergência; ele sai com esta card.

## O que a exploração mudou em relação ao texto da card

Três coisas, e vale registrá-las porque a card foi escrita antes de alguém ler o código com esta pergunta na mão.

**A maior decisão técnica já estava tomada, por escrito.** O docstring de `dentro_da_janela_de_atendimento` (`domain/humano/deteccao.py`) antecipa este caso: *"Se as duas um dia divergirem, é esta função que para de delegar e ganha aritmética própria; `horario_permite_envio` não ganha um parâmetro para as duas."* Não houve o que decidir — só o que executar, com uma ressalva (D1).

**A contagem de textos da card está errada, e para menos.** Ela diz três sítios — pedido de humano, encaminhamento de venda, encaminhamento de suporte. No código, venda e suporte compartilham o **mesmo** `SUFIXO_FORA_DA_JANELA` e o **mesmo** `if`: são um sítio, não dois. E existe um terceiro literal com horário que a card não lista, `TEXTO_DA_JANELA_HUMANA`, que é o único que **já** promete "de segunda a sábado".

**Há um quarto sítio de dia-da-semana que ninguém listou.** `limite_de_aceite` (`domain/handoff/sla.py`) é a única função do repo que atravessa dias, e rola por dia corrido sem olhar `weekday()`: um prazo de aceite aberto sábado à noite conta domingo como jornada. Fica fora do escopo (D6), mas passa a ser incoerência visível a partir daqui.

## D1 — A guarda de domingo entra depois da delegação; a hora continua delegada

`dentro_da_janela_de_atendimento` hoje tem quatro linhas de corpo: lê `Settings` e repassa tudo para `horario_permite_envio` (`domain/outbound/horario.py`).

O docstring dela manda "parar de delegar e ganhar aritmética própria". **Esta card segue a intenção e não a letra**, e a razão é o defeito que a instrução existe para evitar:

A aritmética que `horario_permite_envio` possui é a **borda de minuto** — `inicio * 60 <= minuto_do_dia <= fim * 60`, com `fim` sendo o último minuto em que a janela vale. O próprio docstring de `deteccao.py` registra que a TEC-146 gastou uma card inteira consertando duas fontes dessa mesma conta. Reescrever a comparação aqui para acrescentar um `weekday()` reabriria exatamente aquilo.

A guarda de domingo **não é** aritmética de borda. Ela entra depois da delegação, não antes:

```python
if not horario_permite_envio(momento=agora, inicio=..., fim=..., fuso=fuso):
    return False
return agora.astimezone(fuso).weekday() != _DOMINGO
```

**Esta ordem inverteu a que esta seção previa quando foi escrita, e a execução é quem achou o motivo.** `horario_permite_envio` é quem levanta `ValueError` para um `datetime` ingênuo (sem `tzinfo`), incondicionalmente. Converter o fuso primeiro para olhar o dia — a ordem que este parágrafo chegou a prescrever — faria um naive ser lido como hora do SISTEMA em vez de levantar, e a exceção passaria a depender do dia da semana em vez de ser incondicional. `test_o_momento_ingenuo_continua_levantando` usa um naive de domingo (2026-09-20) exatamente para prender isso: sob a ordem que esta seção descrevia, aquele naive devolveria `False` em silêncio em vez de levantar `ValueError`. A guarda de domingo teve de ir depois de `horario_permite_envio`, não antes.

`_DOMINGO` é `6`, porque `datetime.weekday()` conta a partir de segunda como `0` — e é constante nomeada justamente porque `6` sozinho não diz qual das duas convenções (`weekday` ou `isoweekday`) está em uso.

`horario_permite_envio` mantém assinatura e semântica intactas, e os outros dois chamadores dela — o sweep de follow-up e a jornada do corretor — não sentem nada. É o que a instrução queria comprar; a letra dela só não previu que o eixo novo fosse separável do antigo.

A conversão de fuso acontece duas vezes **no caminho aceito** (uma dentro de `horario_permite_envio` para a hora, outra aqui para o dia) — no caminho recusado por hora, a segunda nunca roda, porque a função já retornou. No caminho aceito é redundância sem consequência: `astimezone` sobre um aware já convertido é idempotente, e nenhuma semântica de borda é duplicada. Pagar uma conversão para não duplicar a conta de borda é a troca certa.

**A assinatura continua `(agora: datetime) -> bool`.** Não é detalhe: duas fixtures `janela_aberta` monkeypatcham `lambda agora: True`, e mudar a aridade quebra as duas.

## D2 — `atendimento_horario_fim` vai de 18 para 19

Uma linha em `app/config.py`. O validator já aceita: `0 <= 9 < 19 <= 23`.

**Efeito colateral que a card não menciona:** sábado às 18h30 passa de **fora** para **dentro** da janela. A mudança de horas alcança os seis dias, não só o domingo, e um teste afirma isso para que não seja descoberto por acidente.

## D3 — Dois literais ganham "de segunda a sábado"

`TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO` (`domain/humano/deteccao.py`) e `SUFIXO_FORA_DA_JANELA` (`domain/agente/turno.py`).

As **horas continuam vindo de `Settings`** via `.format()`, como já vêm, e isso não pode regredir — é regra da card e do repo. Os **dias entram como literal**, pela D4 abaixo.

`TEXTO_DA_JANELA_HUMANA` (`domain/notificacao/envio.py`) **não muda**: já tem a frase.

Os dois literais tocados passam a estar na lista de `tests/unit/test_acento_no_texto_ao_lead.py`, que reprova se um literal sumir dela. Eles nao estavam antes desta card: a lacuna foi achada durante a execucao, e o contador daquele arquivo foi de 15 para 17.

## D4 — Os dias são regra em código, não configuração

Nenhum campo novo em `Settings`. Foi escolhido contra duas alternativas:

- **Um booleano `atendimento_aos_domingos`** nomearia a decisão, mas nada o amarraria aos literais: ligá-lo faria três textos mentirem em silêncio, que é o defeito que esta card existe para fechar.
- **Um `atendimento_ultimo_dia_da_semana` com um teste que amarra** impede a mentira, ao custo de generalidade que ninguém pediu — e o teste que amarra é mais código que a regra inteira.

Este é o agente de **uma** imobiliária, não um produto multi-tenant, e "segunda a sábado" foi decidido por uma pessoa em 19/09/2026, não por uma variável de deploy. YAGNI.

**A assimetria é declarada:** horas vêm da configuração, dias vêm do código. O comentário de `_DOMINGO` registra que mudar os dias é mudança de código **e** de texto, juntos, e que essa é a razão de não haver campo.

## D5 — A prosa que passa a mentir

Seis sítios, e o primeiro é o menos óbvio:

1. **O docstring do validator** `_recusar_janela_de_atendimento_impossivel` (`app/config.py`) afirma que a imobiliária só aparenta nunca ter ninguém disponível quando a janela está invertida. **Deixa de ser verdade**: com domingo fechado, há um dia inteiro em que todo lead recebe o texto de fora do horário, e o validator não tem nada a dizer sobre isso. A guarda continua certa; o que muda é a afirmação de exclusividade.
2. **O comentário de `atendimento_horario_inicio/fim`** (`app/config.py`), que descreve a janela sem dia da semana.
3. **O docstring de `dentro_da_janela_de_atendimento`**, que prescreve "parar de delegar" — passa a registrar o que foi feito e por quê (D1).
4. **O comentário de `SUFIXO_FORA_DA_JANELA`** (`domain/agente/turno.py`), que existe **só** para registrar que o Gherkin dizia 9h–19h e a janela real era 9h–18h. A divergência fecha; o comentário sai ou vira registro histórico.
5. **O comentário de `TEXTO_DA_JANELA_HUMANA`** (`domain/notificacao/envio.py`), que declara a divergência inteira. Ela **encolhe pela metade** — ver D6.
6. **O SRS:** `Emenda E-02 (TEC-285, 19/09/2026)` sob a **RN-03.4**, fechando a divergência que a E-01 (TEC-137) declarou. A E-01 não cai: o texto continua formatando as horas a partir da configuração, que era o argumento dela.

`scripts/comentarios_tocados.py` roda antes do PR, com atenção aos `VIZINHO` dentro de `dentro_da_janela_de_atendimento` e dos dois blocos de texto.

## D6 — O que não muda, e a lacuna que fica declarada

**Não muda:** `horario_permite_envio` (assinatura, semântica e três chamadores), `followup_horario_*`, a jornada do corretor (`corretores.horario_inicio/fim`), e `limite_de_aceite`.

**Duas lacunas ficam declaradas, e as duas são sobre o corretor:**

**`TEXTO_DA_JANELA_HUMANA` continua meio mentindo.** Ele promete "de segunda a sábado", mas é guardado por `horario_permite_envio` com as horas do **corretor**, cuja jornada não tem dia da semana. Depois desta card o lado da imobiliária fecha e o lado do corretor não — a divergência que `envio.py` declara encolhe pela metade e sobrevive. Consertar exige dia na jornada do corretor, que é a TEC-170.

**`limite_de_aceite` conta domingo como jornada.** Um prazo de aceite aberto sábado às 19h vence domingo, num dia em que a imobiliária passa a declarar que não atende. Não é contradição de código — são janelas diferentes, uma da imobiliária e outra do corretor —, mas é a primeira vez que as duas discordam sobre um dia inteiro.

## Testes

| # | afirma | onde |
| --- | --- | --- |
| T1 | domingo às 15h (dentro do intervalo de horas) recusa | `tests/unit/test_deteccao_de_humano.py` |
| T2 | sábado às 18h30 **aceita** — a mudança de horas alcança os seis dias | idem |
| T3 | sábado às 19h01 recusa — a borda de minuto continua valendo no último dia | idem |
| T4 | segunda às 9h em ponto aceita — a borda de abertura não regrediu | idem (já existe, muda o número) |
| T5 | os dois literais tocados nomeiam os dias **e** formatam as horas de `Settings` | `tests/unit/test_textos_do_encaminhamento.py`, `test_deteccao_de_humano.py` |
| T6 | nenhum dos dois literais escreve a hora à mão | idem — hoje dois testes têm `.format(inicio=9, fim=18)` escrito à mão e passam a usar `Settings` |
| T7 | a assinatura `(agora)` sobrevive: as duas fixtures `janela_aberta` continuam valendo | `tests/integration/test_pedido_de_humano.py`, `test_encaminhamento_por_intencao.py` |

T2 é o que pega o efeito colateral da D2, e T7 é o que impede a D1 de quebrar duas fixtures que ninguém lembraria de conferir.

**A receita de RED por configuração da TEC-288 continua valendo** (`ATENDIMENTO_HORARIO_INICIO=0 ATENDIMENTO_HORARIO_FIM=1` no arquivo, nunca na suíte inteira), e agora tem uma irmã: para exercitar domingo não há variável — é o `datetime` congelado do teste que escolhe o dia.

## O que este desenho não entrega

**Nada mede se "segunda a sábado" é o expediente real da imobiliária.** É a decisão de uma pessoa registrada numa card, e o código passa a afirmá-la ao lead. Se estiver errada, o lead ouve a mentira num tom de certeza que antes ele não ouvia — porque antes o texto só dizia horas.

**A assimetria entre horas e dias vai incomodar um dia.** Quando alguém quiser sábado meio período, ou feriado, a resposta desta card é "mude o código e o texto juntos". É a resposta certa para hoje e a errada para o dia em que a agenda de verdade (TEC-170) chegar — e aí os dois eixos voltam para a configuração de uma vez.
