# TEC-201 — Autenticação do dashboard

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-201](https://eduardodurieuxlopes.atlassian.net/browse/TEC-201) — épico TEC-200
**Branch:** `feat/tec-201-autenticacao-do-dashboard`
**Origem:** RNF-11 (SRS v1.0); modelo `Usuario` da seção 5.1

## O problema

Toda rota administrativa é guardada hoje por `exigir_admin` (`api/deps.py`), que compara um **token compartilhado** vindo no header `X-Admin-Token`. Um token só, para todo mundo: não há usuário, não há papel, não há como saber quem fez o quê, e revogar o acesso de uma pessoa significa trocar o token de todas.

O próprio docstring daquela função antecipa esta card:

> Quando a TEC-201 chegar, o corpo desta funcao vira validacao de JWT mais papel ADMIN e nenhum handler muda -- e esse o ponto de ter uma funcao aqui em vez de um `if` dentro da rota.

Esta card destrava a TEC-309 (login no BFF) e, por ela, o épico TEC-301 inteiro — hoje bloqueado em quatro cards —, mais a TEC-202 (autorização por papel).

## D1 — Credencial local, e não delegação a um IdP — e o que isso custa

**A decisão é do Eduardo, tomada em 24/09/2026 com a alternativa na mesa.** A regra 1 da card diz "OAuth2/OIDC" e a TEC-309 descreve *Authorization Code + PKCE* contra "o provedor de identidade", o que descreveria o mobIA como **cliente** de um IdP externo. O Gherkin, porém, diz *"um usuário com papel ADMIN e senha correta"*, o que descreve o mobIA guardando a credencial. Os dois caminhos foram apresentados; o escolhido foi **senha local mais TOTP**.

Registro o que isso significa, porque é o tipo de coisa que ninguém quer redescobrir num incidente:

- **Passamos a guardar segredo de autenticação** — hash de senha e semente de TOTP — numa base que já contém dado pessoal de todos os leads. Antes desta card não havia nenhum dos dois.
- **Passamos a responder por reset de senha, bloqueio por tentativa e rotação.** Nada disso está nesta card; ver as lacunas L2 e L3.
- **O MFA passa a ser nosso.** Um IdP externo traria isso pronto e auditado.

Em troca, não dependemos de cadastro externo nenhum para o sistema funcionar — que é exatamente o que travou a notificação por e-mail até a TEC-280 e o WhatsApp ao corretor até a TEC-281.

**A porta fica aberta para o outro caminho**: o `Usuario` não guarda só credencial, e um adaptador de IdP futuro popularia o mesmo registro sem tocar em papel, sessão ou rota.

## D2 — O `X-Admin-Token` NÃO morre nesta card, e isso é sequenciamento, não indecisão

Trocar o corpo de `exigir_admin` por validação de JWT **quebraria o painel hoje**: o BFF do frontend manda `X-Admin-Token` (`lib/servidor/api.ts`), e quem faz o BFF passar a mandar sessão de verdade é a TEC-309 — que esta card destrava e que portanto ainda não existe.

A evidência de que os dois devem coexistir está na própria TEC-309, cujo segundo cenário exige que não cheguem ao navegador "nenhum token de acesso, de renovação **ou o token administrativo provisório**". Se o token provisório já não existisse ali, o cenário não teria o que verificar.

Então: **`exigir_admin` aceita JWT válido OU o token compartilhado**, com o segundo marcado como transitório e logado quando usado. Um `warning` por uso, não por requisição, para que se possa medir quando ele parou de ser usado e apagá-lo com evidência em vez de com fé.

**O risco declarado:** enquanto os dois convivem, a segurança do conjunto é a do elo mais fraco — quem tiver o token compartilhado continua entrando sem usuário, sem papel e sem MFA. Esta card **não fecha** o acesso; ela constrói o caminho que permite fechá-lo. Quem apaga o token é a TEC-309.

## D3 — Os três segredos, e por que cada um é guardado de um jeito

| segredo | como | por quê |
| --- | --- | --- |
| senha | **Argon2id** (`argon2-cffi`) | função de hash de senha, com custo ajustável; é a primeira escolha do OWASP. Nunca reversível |
| semente TOTP | **AES-GCM**, com o `crypto.py` que já existe | precisa ser **lida de volta** para conferir o código, então hash não serve. Cifrada em repouso com AAD amarrado ao id do usuário, como `handoffs.resumo` |
| refresh token | **SHA-256 do valor**, não o valor | o que vai para o cliente é aleatório e opaco; o banco guarda só o digest. Vazamento da tabela não dá sessão a ninguém |

**A senha não é cifrada com a chave do `crypto.py`, e isso é deliberado:** cifra é reversível, e senha não deve ser. Quem tiver a chave de conteúdo não deve poder ler senha nenhuma.

**A semente do TOTP é o oposto** — precisa ser reversível, e por isso é o único segredo desta card que fica ao alcance da chave de conteúdo. Está dito porque é uma exposição real: comprometida a chave, o segundo fator de todos cai junto.

## D4 — O refresh é rotativo, e o logout revoga a família inteira

A cada `refresh`, o token usado é marcado como usado e um novo é emitido. Isso dá duas coisas que um refresh fixo de 7 dias não dá:

1. **Logout que significa alguma coisa** (quinto cenário do Gherkin): revogar a linha basta.
2. **Detecção de roubo.** Um refresh **já usado** apresentado de novo significa que duas partes têm o mesmo token — o legítimo e quem o copiou. A resposta é revogar a **família inteira** daquela sessão, derrubando os dois. É a recomendação da OAuth 2.0 Security BCP para clientes públicos, e é barata: uma coluna de família e um UPDATE.

Derrubar o usuário legítimo é o comportamento certo aqui: a alternativa é deixar o ladrão dentro.

## D5 — O MFA é exigido no LOGIN, e o JWT carrega a prova

O quarto cenário pede que o ADMIN sem segundo fator seja negado. Duas formas de fazer isso, e a escolha importa:

- **Negar o JWT até o TOTP ser conferido** — o login de um ADMIN devolve, em vez do par de tokens, um **desafio** de curta duração; só o `POST /auth/mfa` com o código correto emite os tokens.
- Emitir o JWT e deixar cada rota checar uma flag. Recusado: espalha a regra por toda rota e erra para o lado de esquecer.

O JWT carrega `mfa: true` quando a sessão passou pelo segundo fator. Rota nenhuma precisa saber disso hoje — **a checagem vale no login** —, mas a claim fica porque a TEC-202 vai querer exigir MFA para ações específicas, e reconstruí-la depois exigiria relogar todo mundo.

**ADMIN sem `mfa_habilitado` não consegue entrar.** Não é lacuna: é a regra. Quem cadastra o primeiro ADMIN tem de habilitar o TOTP dele no mesmo ato — ver a lacuna L2, que é justamente a ausência desse ato.

## D6 — `email` em claro, como o `corretores` já faz

O modelo da seção 5.1 marca `nome` e `email` do `Usuario` como **DP**. Ficam em claro, pelo precedente que a TEC-196 já escreveu para `corretores` e que o comentário de lá guarda:

> este repo cifra CONTEUDO e nao IDENTIFICADOR (...) e cifrar aqui destruiria o UNIQUE do e-mail

Vale igual e com mais força: o e-mail é **a chave de login**, e um índice único sobre valor cifrado com nonce aleatório não existe.

## D7 — Três dependências novas, e por que nenhuma foi escrita à mão

`argon2-cffi`, `pyjwt` e `pyotp`. Nenhuma das três é grande, e as três cobrem terreno em que código próprio erra em silêncio: formato de hash, verificação de assinatura e janela de tempo de OTP. Assinar um JWT "na mão" com `hmac` é o exemplo clássico de economia que custa caro — a família de ataques de confusão de algoritmo existe por causa disso.

`cryptography` já está no projeto e oferece `Scrypt`; foi considerado para a senha e recusado porque obrigaria a inventar o formato de armazenamento (sal, parâmetros, versão) no ponto de maior consequência da card.

## Arquivos

```
src/mobia/domain/usuarios/__init__.py
src/mobia/domain/usuarios/models.py        # Usuario e SessaoDeRefresh
src/mobia/domain/usuarios/senha.py         # Argon2id (D3)
src/mobia/domain/usuarios/totp.py          # semente cifrada e conferencia (D3, D5)
src/mobia/domain/usuarios/tokens.py        # emissao e validacao de JWT (D3)
src/mobia/domain/usuarios/sessoes.py       # rotacao, revogacao e familia (D4)
src/mobia/domain/usuarios/repositorio.py
src/mobia/api/routes/auth.py               # login, mfa, refresh, logout
src/mobia/api/deps.py                      # exigir_admin aceita os dois (D2)
src/mobia/app/config.py                    # segredo do JWT e tempos
src/mobia/app/main.py                      # registro do router
alembic/versions/0044_usuarios_e_sessoes.py
pyproject.toml                             # as tres dependencias (D7)
```

## Testes

- **Unitários** — senha que confere e que não confere; hash diferente para a mesma senha (sal); TOTP dentro e fora da janela; JWT expirado recusado; JWT com assinatura trocada recusado; JWT com `alg: none` recusado (é o ataque que justifica a biblioteca).
- **Integração** — os cinco cenários do Gherkin, contra banco de verdade.
- **A rotação e o reuso (D4)** — refresh usado duas vezes derruba a família; é o teste que mais importa depois do de expiração.
- **A coexistência (D2)** — rota administrativa responde com JWT válido **e** com o token compartilhado, e recusa sem nenhum dos dois. É o que garante que esta card não quebrou o painel.
- **`alg: none` e chave trocada** entram como teste de segurança explícito, não como confiança na biblioteca.

## Emendas ao SRS

**Emenda E-01 à RNF-11 (TEC-201, 24/09/2026)** — a autenticação é por **credencial local (senha + TOTP)**, e não por delegação a um provedor OIDC externo. A regra diz "OAuth2/OIDC", e o texto da card diverge dela no próprio critério de aceite, que fala em "senha correta"; a decisão de 24/09/2026 foi pela credencial local, para não depender de cadastro externo — o mesmo tipo de dependência que manteve a notificação por e-mail sem entregar até a TEC-280 e o WhatsApp ao corretor até a TEC-281. **Consequência declarada:** o sistema passa a guardar hash de senha e semente de TOTP numa base que contém dado pessoal de leads, e passa a responder por reset, bloqueio e rotação — nada disso entregue aqui (lacunas L2 e L3). O JWT de 60 minutos, o refresh de 7 dias e o MFA obrigatório para `ADMIN` continuam valendo como escritos. Ver a D1 do desenho.

**Emenda E-02 à RNF-11 (TEC-201, 24/09/2026)** — *"nenhuma rota do dashboard responde sem token válido"* **ainda não vale**, e por sequenciamento: o `X-Admin-Token` compartilhado continua sendo aceito ao lado do JWT, porque o BFF do frontend só passa a mandar sessão de verdade na TEC-309, que esta card destrava. A própria TEC-309 pressupõe essa convivência ao exigir que "o token administrativo provisório" não chegue ao navegador. **Consequência declarada:** enquanto os dois convivem, quem tiver o token compartilhado entra sem usuário, sem papel e sem MFA — a segurança do conjunto é a do elo mais fraco, e quem fecha isso é a TEC-309. Ver a D2 do desenho.

## Lacunas declaradas

- **L1 — não há checagem de papel por rota.** É a TEC-202, e a card a declara fora de escopo. O JWT **carrega** o papel; ninguém ainda o exige, além do `ADMIN` que `exigir_admin` passa a conferir.
- **L2 — não há como cadastrar usuário.** Não há rota de criação, nem de convite, nem de habilitar TOTP. Na prática: **o primeiro usuário precisa ser inserido no banco à mão**, e um `ADMIN` sem `mfa_habilitado` não consegue entrar (D5). Sem isso, esta card não é utilizável por ninguém — é fundação, não funcionalidade. Merece card própria.
- **L3 — não há reset de senha, bloqueio por tentativa nem rotação.** Tentativa infinita de senha é o buraco mais gritante: nada impede força bruta contra `/auth/login`. O limitador por IP da TEC-205 existe e cobre parcialmente, mas ele não é por conta.
- **L4 — logout é por sessão, não global.** Revoga a família daquela sessão; outros navegadores da mesma pessoa seguem válidos. É o comportamento que o Gherkin descreve, e a alternativa (derrubar tudo) seria surpresa.
- **L5 — o JWT não é revogável antes de expirar.** Desativar um usuário impede o *refresh*, mas o JWT dele continua valendo por até 60 minutos. Uma lista de revogação daria isso ao custo de uma consulta por requisição; a janela de uma hora foi aceita, e está aqui para não ser descoberta num incidente.
