# TEC-352 — Exibir o aviso de privacidade e registrar o consentimento de marketing no chat

**Status:** implementado (28/09/2026)
**Card:** [TEC-352](https://eduardodurieuxlopes.atlassian.net/browse/TEC-352) — épico TEC-307
**Branch:** `feat/tec-352-privacidade-no-chat`
**Depende de:** TEC-363 (o frame `consentimento` e a tabela), TEC-346 (a conversa), TEC-344 (a aparência)

## O que existe quando a card começa

- **O servidor já registra o consentimento.**
  - O frame `{"tipo": "consentimento", "marketing": bool, "textoExibido": "...", "exibidoEm": "<ISO>"}` grava uma linha em `consentimentos`, inclusive a recusa (`marketing: false`, D3 da TEC-363), e responde `consentimento_registrado`.
  - Os erros de consentimento vêm como `erro` sem `messageId`: `consentimento_invalido`, `aviso_ausente`, `aviso_longo_demais` (frame mal formado) e `consentimento_nao_registrado` (banco).
  - Nada no cliente manda o frame (L1 da TEC-363).
- **O sistema não guarda o endereço do aviso de privacidade nem o contato do encarregado.** A RNF-24 diz só que "a POC define o papel e o e-mail". O endereço e o contato só existiriam como texto fixo no código.

As regras RN-FE-20.2 e RB-FE-04 vêm do texto da card: o SRS do frontend não está no repo.

## D1 — Aviso e encarregado são configuração do backend, servida pela aparência

Decisão do Eduardo, 28/09/2026.

- **Duas variáveis no `Settings`:** `AVISO_DE_PRIVACIDADE_URL` (endereço `http`/`https`) e `ENCARREGADO_EMAIL`. Vazias viram nulo. Fora do formato, o backend não sobe, no molde de `_tenant_slug_no_formato_do_next`: um valor errado sumiria com o chat sem uma linha de log.
- **`GET /widget/aparencia` passa a devolver `avisoDePrivacidadeUrl` e `encarregadoEmail`.** São públicos por natureza: estão na faixa que toda visitante lê. O loader do site não os recebe — `/embed/aparencia` continua mandando só os três campos do botão.
- **Configuração de implantação, e não da imobiliária no painel**, como o `TENANT_SLUG`. Tenant único na POC (PR-03). Levar para a configuração do agente é card própria, com migration e formulário.

## D2 — Sem aviso e encarregado configurados, o chat não abre a conversa

Decisão do Eduardo, 28/09/2026.

- **A página `/embed/chat` desenha o cabeçalho e "O chat está indisponível no momento."**, sem campo e sem socket. Nenhum dado é coletado sem o aviso: é o que a LGPD pede e o que a card chama de Must.
- O botão do site continua aparecendo, e o painel abre com esse aviso. O botão depende só da aparência, e tirá-lo seria esconder uma configuração errada em vez de mostrá-la.
- Basta faltar um dos dois para o chat ficar indisponível. A card pede os dois links.

## D3 — A faixa

**Enquanto a visitante não mandou mensagem nenhuma**, uma faixa acima do campo mostra:

- a finalidade: "Usamos os dados que você informar nesta conversa para responder ao seu interesse em imóveis e, se quiser, colocar você em contato com um corretor. Ao enviar sua primeira mensagem, você declara estar ciente do aviso de privacidade.";
- os links "Aviso de privacidade" (nova aba) e "Contato do encarregado" (`mailto:`);
- o checkbox "Aceito receber ofertas de imóveis por esta conversa e pelos meus contatos.", **desmarcado**.

Detalhes:

- **"Primeira abertura" é "nenhuma mensagem da visitante nesta sessão".** Isso cobre tanto a mensagem enviada daqui quanto a que o `historico` da retomada traz (TEC-347). Quem retoma uma conversa em que já escreveu já deu ciência, e não vê a faixa de novo. "Encerrar conversa" abre uma sessão nova, e a faixa volta, com o checkbox desmarcado: o consentimento é por sessão (D4 da TEC-363).
- **Depois da primeira mensagem, a faixa se reduz aos dois links**, numa linha acima do campo. O aviso continua a um toque, e a finalidade e o checkbox saem.
- É texto que a visitante lê: com acento.

## D4 — A primeira mensagem manda o consentimento antes dela, sempre

- **O envio da primeira mensagem vale como ciência** (regra da card). Nesse momento o cliente manda o frame `consentimento`, com o `marketing` do checkbox, **antes** do frame da mensagem, no mesmo socket. O servidor lê os frames em ordem, então o consentimento é gravado antes de a mensagem virar turno.
- **O frame vai também com `marketing: false`.** O servidor grava a recusa (D3 da TEC-363): é a prova de que o aviso foi exibido e de que a resposta foi não. O quarto cenário da card ("nenhum consentimento de marketing é registrado") é o que `tem_consentimento_de_marketing` responde: `False`.
- **`textoExibido`** é o que a faixa mostrou: a finalidade, o texto do checkbox e os dois destinos (o endereço do aviso e o e-mail do encarregado). Sem os destinos, o registro diria a que a pessoa foi apresentada sem dizer onde estava o aviso.
- **`exibidoEm`** é o instante em que a faixa apareceu, no relógio do aparelho. O servidor guarda o dele como a data que vale (D2 da TEC-363).
- **Sem socket aberto**, o consentimento espera como a mensagem (TEC-348, D4). No `open`, a ordem é `ola`, consentimento pendente, mensagens `enviando`.
  - `consentimento_registrado` o encerra.
  - `consentimento_nao_registrado` o deixa pendente para o próximo socket.
  - Os três erros de frame mal formado o encerram sem retentar, porque mandar de novo o mesmo frame daria o mesmo erro.
- **O estado vive no redutor** (`consentimento` na `Conversa`, evento `deuCiencia`), e `encerrou` o zera.

## Verificação no navegador (28/09/2026)

Edge headless dirigido por CDP, `/embed/chat` servido pelo `next dev`, API local com as chaves externas inválidas.

| passo | resultado |
| --- | --- |
| API sem `AVISO_DE_PRIVACIDADE_URL` nem `ENCARREGADO_EMAIL` | cabeçalho e "O chat está indisponível no momento."; nenhuma conexão ao `WS /widget/chat` no log da API |
| API com os dois, `localStorage` limpo | a faixa acima do campo com a finalidade, os dois links e o checkbox desmarcado |
| checkbox marcado com clique de mouse, primeira mensagem | mensagem "Recebida"; a faixa ficou só com os links; linha em `consentimentos` com `channel = web`, `marketing = t`, `exibido_em` do aparelho, `created_at` do servidor e o texto com o endereço do aviso |

O cache de 60 s da aparência no Next (D4 da TEC-344) fez a página continuar "indisponível" por até um minuto depois de a API subir com as variáveis. É o comportamento documentado, e não defeito.

## Testes

- Backend:
  - Os dois campos novos na aparência, nulos por padrão e com o valor quando configurados.
  - Os validadores do `Settings`: vazio vira nulo; URL sem esquema `http(s)` e e-mail sem `@` não sobem.
- `lib`: a leitura dos dois campos, e o `null` quando falta um.
- Redutor:
  - `deuCiencia` só uma vez.
  - `consentimento_registrado`; os erros de consentimento que encerram e o que deixa pendente.
  - `encerrou` zera.
- Componente (socket falso):
  - A faixa antes do campo, com os dois links.
  - O checkbox desmarcado.
  - A primeira mensagem manda `consentimento` antes de `mensagem`, com `marketing` verdadeiro ou falso.
  - A faixa se reduz aos links depois da primeira mensagem.
  - A retomada com fala da visitante no `historico` não mostra a faixa.
  - O consentimento pendente sai no `open` seguinte.
  - O encerramento volta a faixa.
- Página: sem privacidade configurada, "indisponível" e nenhum socket.
- Navegador: a faixa, o checkbox marcado, e a linha em `consentimentos` com `marketing = true` e o texto exibido.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| Aviso na primeira abertura | componente: a faixa antes do campo, com os links; navegador |
| Marketing começa desmarcado | componente |
| Registro do consentimento de marketing | componente: o frame com o texto e o instante; navegador: a linha em `consentimentos` (o servidor põe o canal `web` e o `created_at`) |
| Conversar sem aceitar marketing | componente: o frame com `marketing: false` e a conversa seguindo; a recusa gravada não é consentimento (D4, D3 da TEC-363) |

## Lacunas declaradas

- **L1 — O SRS do frontend não está no repo.** As regras vêm do texto da card.
- **L2 — O texto do aviso de privacidade não é deste repo.** A card linka um aviso que a imobiliária publica. Sem `AVISO_DE_PRIVACIDADE_URL` configurado, o chat fica indisponível (D2).
- **L3 — Uma queda entre o envio do consentimento e o `consentimento_registrado` pode gravar duas linhas iguais.** O socket seguinte manda o consentimento de novo, e a tabela é append-only, sem chave de deduplicação. As duas dizem a mesma coisa, e a última vale.
- **L4 — Mudar de ideia sobre o marketing depois da primeira mensagem não tem controle na tela.** O checkbox sai com a ciência. Revogar é pedido ao titular (TEC-207) ou card própria.
- **L5 — A retomada mostra a faixa por um instante antes de o `historico` chegar**, porque até lá a tela não sabe que a visitante já escreveu.
