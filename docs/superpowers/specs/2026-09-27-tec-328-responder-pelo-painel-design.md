# TEC-328 — Responder o lead pelo painel, respeitando a janela de 24 h do WhatsApp

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-328](https://eduardodurieuxlopes.atlassian.net/browse/TEC-328) — épico TEC-304
**Branch:** `feat/tec-328-responder-pelo-painel`
**Depende de:** TEC-194 (`POST /leads/{leadId}/mensagens`), TEC-327 (assumir e o polling), TEC-324 (a conversa), TEC-302 (o `/bff/*`)

## O que existe quando a card começa

`POST /api/v1/leads/{leadId}/mensagens` com `{"texto"}` existe desde a TEC-194. Ele é **síncrono**: assume a conversa, envia pelo canal e só então grava a fala, com `role=CORRETOR`. A resposta é `201 {id, em}` ou uma recusa com `detail` estável:
- 409 `conversa_de_outro`, `janela_fechada`, `lead_em_optout` e `sem_fala_do_lead`;
- 502 `canal_falhou`.

O teto de texto é 4096, o da Meta. A conversa (TEC-324) faz polling a cada 5 s quando é de quem vê a tela (TEC-327).

**Três coisas que a card pressupõe e que não existem:**

1. **o `messageId` gerado no cliente.** O corpo é `extra="forbid"` e o id da fala nasce no servidor. Um clique duplo, ou um reenvio depois de a rede cair com a mensagem já entregue, manda a fala duas vezes ao lead;
2. **saber da janela antes de enviar.** Hoje a janela fechada só aparece quando a Meta recusa (código 131047). A tela não tem como bloquear o texto livre antes do clique, que é o que o quarto cenário pede;
3. **o limite de 1.000 caracteres.** É regra de tela (RN-FE-09.3). O backend aceita até 4096 e continua aceitando.

## D1 — O `messageId` do cliente é o id da fala, e reenviar não manda de novo

`PedidoDeFala` ganha `messageId` (UUID, opcional para não quebrar quem já chama). Ele passa a ser o id da fala e, com ele, o `kind` da reserva em `outbound_dispatches`.

- **Fala com esse id já gravada**, para o mesmo lead e com `role=CORRETOR`: responde `201` com o mesmo `{id, em}` e **não envia**. É o reenvio de quem não viu a primeira resposta.
- **Id de uma fala de outro lead, ou de outro autor**: 409 `message_id_em_uso`. Não envia.
- **Reserva desse `kind` já existe e a fala não está gravada**: 409 `fala_em_envio`. Não envia. Ou a primeira chamada ainda está esperando a Meta, ou entregou e caiu antes de gravar. Nos dois casos, enviar de novo seria a duplicata que o id existe para impedir.

**A reserva é conferida pelo `kind`, e não pelo par `(message_id, kind)` da UNIQUE.** O `message_id` da reserva é a âncora, a última fala do lead. Se o lead falar entre as duas tentativas, a âncora muda e a UNIQUE deixaria passar.

**O que continua podendo duplicar:** duas chamadas **simultâneas** com o mesmo id, em que as duas passam pelas conferências antes de qualquer uma reservar. A UNIQUE pega esse caso quando a âncora é a mesma, e a segunda recebe `False` da guarda. Esse `False` deixa de ser lido como opt-out: a rota confere a reserva de novo e responde `fala_em_envio`.

Vira a **Emenda E-03 à RN-18.3**.

## D2 — A janela de 24 h é conferida antes do envio, e o detalhe diz quando fecha

**No envio:** com canal WhatsApp, `falar_com_o_lead` confere `outbound/janela.py::dentro_da_janela` contra a âncora **antes** de chamar a Meta. Fora dela, a resposta é `janela_fechada` sem requisição nenhuma. A regra é a mesma que follow-up, lembrete e remarcação já usam, e a recusa da Meta fica como segunda linha.

**No detalhe:** `GET /leads/{leadId}` ganha **`janelaDeServicoFechaEm`**. No WhatsApp, é a âncora mais `JANELA_DE_SERVICO`. No site, ou num lead que nunca falou, é `null`, porque não há janela. A tela compara com o relógio, e a regra do `<` estrito continua escrita num lugar só: aos 24 h exatos a janela já fechou.

**A tela não calcula a janela a partir das falas.** A primeira página da conversa tem as 100 falas mais recentes, e um lead cuja última fala está além delas pareceria fora da janela sem estar. Mas **uma fala nova do lead que chega pelo polling reabre a janela** na tela, a partir do `em` dela, porque é o mesmo fato que a Meta usa. Para isso a tela precisa da duração, e `lib/resposta.ts` a escreve de novo como `JANELA_DE_SERVICO_MS`. Reler o detalhe a cada fala nova gravaria um acesso na trilha. `tests/unit/test_vocabulario_da_tela.py` reprova se as duas durações divergirem.

Vira a **Emenda E-03 à seção 6.2 / `GET /api/v1/leads/{leadId}`**.

## D3 — O campo de envio mora na conversa

A caixa de texto fica **embaixo da conversa**, dentro de `Transcricao`, que já sabe se a conversa é de quem vê a tela (`acompanhar`, D5 da TEC-327). A página a mostra para quem tem `ATENDER_LEAD` e vínculo de corretor, os mesmos que veem "Assumir conversa".

| estado | a tela |
| --- | --- |
| a conversa não é de quem vê | campo desabilitado: "Assuma a conversa para responder." |
| WhatsApp com a janela fechada | campo desabilitado e a explicação: "Já se passaram 24 horas desde a última mensagem do lead. Pelo WhatsApp, fora dessa janela só um modelo de mensagem aprovado pode ser enviado, e o painel ainda não envia modelos." |
| mais de 1.000 caracteres | o contador diz quantos passaram, e **Enviar** fica desabilitado |
| em branco | **Enviar** desabilitado |

O contador fica sempre à vista: "N/1000".

**Enviou (201):** a fala entra no fim da conversa na hora, com o rótulo "Corretor", o `id` e o `em` da resposta. O campo esvazia. O polling traz a mesma fala depois e ela não se duplica, porque a lista já deduplica por `id` e o `id` é o `messageId` (D1).

**O `messageId` é gerado por texto, e não por clique.** Ele nasce no primeiro envio e é reusado se o envio falhar e a pessoa tentar de novo com o mesmo texto: é isso que torna o reenvio seguro. Mudar o texto ou enviar com sucesso gera outro.

**O relógio da janela anda com a tela aberta.** Ele é conferido a cada minuto, então a janela que fecha durante a leitura desabilita o campo sem recarregar.

## D4 — Recusas

| resposta | a tela diz | o campo |
| --- | --- | --- |
| 409 `janela_fechada` | a explicação da janela (D3) | desabilita |
| 409 `lead_em_optout` | O lead pediu para não receber mensagens. | desabilita |
| 409 `conversa_de_outro` | Outro corretor assumiu esta conversa. Recarregue a página. | desabilita |
| 409 `fala_em_envio` | Esta mensagem já está sendo enviada. Aguarde um instante. | fica, com o mesmo texto |
| 502 `canal_falhou` / rede | Não foi possível entregar a mensagem. Tente de novo. | fica, com o mesmo texto e o mesmo `messageId` |
| 401 | Sua sessão terminou. Recarregue a página para entrar de novo. | fica |
| outro | Não foi possível enviar. Tente de novo. | fica |

## D5 — O proxy libera o envio

`ROTAS_PERMITIDAS` ganha `POST api/v1/leads/*/mensagens`. O `GET` da mesma rota já estava lá.

## Fora do escopo

- **Enviar template fora da janela.** A tela explica e não oferece. Os templates da Meta ainda nem estão aprovados (TEC-373).
- **Mídia e anexos.** Só texto.
- **Baixar o teto do backend para 1.000.** A API continua aceitando 4096; o limite menor é de tela.
