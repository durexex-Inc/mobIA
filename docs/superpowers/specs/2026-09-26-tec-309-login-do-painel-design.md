# TEC-309 — Entrar no painel com senha, TOTP para administradores, e sessão só no servidor

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-309](https://eduardodurieuxlopes.atlassian.net/browse/TEC-309) — épico TEC-301
**Branch:** `feat/tec-309-login-do-painel`
**Depende de:** TEC-201 (rotas `/api/v1/auth/*`), TEC-302 (BFF), TEC-202 (papéis)

## O que a card pede e o que existe para atendê-la

A card foi escrita para OIDC com Authorization Code + PKCE, executado pelo Auth.js no BFF. **Esse provedor não existe.** Na TEC-201, o Eduardo escolheu senha local + TOTP em 24/09/2026 — é a Emenda E-01 à RNF-11, que esta card levou ao SRS —, e o que o backend oferece são cinco rotas: `login`, `mfa`, `refresh`, `logout` e `me`, em `src/mobia/api/routes/auth.py`. Elas devolvem os tokens **no corpo da resposta**.

Então esta card é o outro lado dessas rotas: um formulário de login no Next, uma etapa de código TOTP para quem é ADMIN, e uma sessão guardada no servidor. As regras de negócio da card que não dependem de OIDC continuam valendo sem mudança:

- toda rota, exceto `/login` e `/embed/*`, manda ao login quem não tem sessão;
- o navegador nunca recebe access token nem refresh token;
- o cookie leva só o id da sessão, `HttpOnly`, `Secure`, `SameSite=Lax`, e a sessão fica no Redis;
- ADMIN sem MFA é barrado com uma mensagem que explica a exigência;
- o `returnTo` só aceita rota interna.

## D1 — Sem Auth.js

O Auth.js serviria se houvesse OIDC. Para senha, ele oferece o provedor `Credentials`, que **só funciona com sessão em JWT**: a documentação dele recusa o adaptador de banco com esse provedor. Um JWT de sessão no cookie contraria duas regras da card de uma vez — o cookie deixaria de levar só o id, e a sessão deixaria de morar no Redis.

Sobra usar o Auth.js como casca e reescrever por baixo a sessão, o armazenamento e o fluxo de MFA, que ele não tem. Isso é uma dependência grande para não usar nada dela. O que a card precisa cabe em três módulos pequenos, e cada um se testa sem o runtime do Next — o mesmo molde que a TEC-302 usou em `lib/servidor/bff.ts`.

## D2 — A sessão é um id opaco no cookie e um registro no Redis

- **O id** tem 32 bytes aleatórios de `crypto.getRandomValues`, em base64url. O cookie `mobia_sessao` leva só isso.
- **A chave no Redis é o SHA-256 do id**, e não o id: um dump do Redis não entrega sessão a ninguém. É o mesmo raciocínio de `SessaoDeRefresh.digest` no backend. O hash é simples porque a entrada já tem 256 bits de entropia.
- **O registro** guarda `access` e `refresh` — os dois tokens que o FastAPI emitiu — e o instante da criação. Mais nada: papel e permissões saem de `GET /auth/me` quando alguém precisar, como a RN-FE-03.2 manda (TEC-312).
- **A validade é de 7 dias**, no Redis e no `Max-Age` do cookie, que é a vida do refresh (RNF-11). O access dura 60 minutos, e renová-lo com o refresh é a TEC-310. Ver a L3.

O cliente Redis é o pacote `redis` (node-redis), atrás de uma interface de três operações (`obter`, `gravar` com expiração, `apagar`). Os testes trocam essa interface por um mapa em memória, e nenhum deles precisa de Redis de pé.

## D3 — O desafio de MFA também não vai ao navegador

Quando a senha de um ADMIN confere, o FastAPI devolve `{"mfa_requerido": true, "desafio": "<JWT de 5 minutos>"}`. O desafio é uma credencial de meio caminho: prova a senha e ainda não prova o segundo fator.

Ele fica no Redis como a sessão fica, com o cookie `mobia_mfa` (`HttpOnly`, `Path=/login`, 5 minutos) levando o id. Não seria incorreto mandá-lo ao navegador, mas a regra da card — nenhum token chega lá — fica mais simples de afirmar sem exceção.

**Código errado não consome o desafio.** Quem errou um dígito tenta de novo sem redigitar a senha, enquanto os 5 minutos do desafio valerem. O registro só é apagado quando o código confere.

## D4 — Os formulários são POST para Route Handlers, e não Server Actions

`/login/entrar` recebe e-mail e senha, e `/login/mfa` recebe o código. Os dois respondem com `303` para a próxima tela.

- **Funcionam sem JavaScript.** É um `<form method="post">` puro, e a CSP da TEC-356 já tem `form-action 'self'`.
- **Testam-se como a TEC-302 testa o `/bff/*`**: chamando `POST(requisicao)` com uma `NextRequest` montada à mão, sem subir o Next.
- **O `Origin` é conferido com a mesma `origemAceita`** de `lib/servidor/bff.ts`. Um POST de login vindo de outra origem é CSRF de login — quem ataca faz a vítima entrar na conta dele —, e a regra que já existe para mutação o recusa.

Server Actions fariam o mesmo com menos arquivos, mas trazem o protocolo delas junto (ids de ação, a checagem de `Origin` que é própria delas) e não se testam como função pura.

## D5 — Duas guardas: uma rápida no `proxy.ts`, e a de verdade no servidor

1. **`proxy.ts`**, que já roda em toda rota de documento por causa da CSP, passa a mandar para `/login?returnTo=<rota pedida>` quem chega sem o cookie `mobia_sessao`. Ele não consulta o Redis: é a "checagem otimista" que o guia de autenticação do Next 16 descreve, e o motivo de existir é não renderizar a página só para descobrir que não há ninguém.
2. **A verificação real** fica em `exigirSessao()`, chamada pela página e pelo `/bff/*`. Ela lê o cookie, busca o registro no Redis e devolve o access token. Sem registro, a página redireciona ao login e o BFF responde `401`.

A primeira guarda sozinha seria furável — qualquer valor no cookie passa. A segunda sozinha funcionaria, e a primeira existe só por custo.

**Com cookie forjado ou expirado no Redis, a resposta é `200`, e isso não é a guarda falhando.** Observado na verificação de ponta a ponta: como existe `app/loading.tsx`, o Next começa o streaming — status `200`, `<title>` e o esqueleto de carregamento — antes de a página rodar. O `redirect()` de `exigirSessao` chega depois, como `NEXT_REDIRECT` no payload do React e um `<meta http-equiv="refresh">` para `/login`. Nenhum dado do funil sai: a página redireciona antes de chamar o FastAPI, e o HTML entregue não tem etapa nem token. Quem medir a guarda pelo status HTTP vai concluir errado; o que se mede é o corpo. O mesmo vale para o `401` do access expirado (D7). Mover a consulta ao Redis para o `proxy.ts` daria um `307` de verdade nesses casos, ao custo de uma ida ao Redis em toda navegação — não compensa enquanto o resultado para quem usa é o mesmo.

**Rotas públicas:** `/login` e o que vem abaixo dele, e `/embed/*`, que ainda não existe (TEC-344) mas a card já exclui. O `/bff/*` segue fora do `matcher`, como na TEC-356, e responde `401` em JSON: um redirecionamento seria a resposta errada para um `fetch`.

## D6 — O `returnTo` só aceita caminho interno

`destinoSeguro(bruto)` devolve um caminho que começa com `/`, ou devolve `/`. Recusa:

- tudo que não começa com uma barra só: `https://…`, `//site-externo.com`, `/\site-externo.com` (alguns navegadores normalizam `\` para `/`);
- caractere de controle, que é como se contrabandeia quebra de cabeçalho;
- qualquer valor cuja resolução contra uma origem de referência saia dessa origem — a checagem final, que pega o que as outras não previram;
- `/login…` e `/bff…`, que levariam a um laço ou a um JSON.

**"A página inicial do seu papel" é `/` para todos os papéis, por enquanto.** Só existe uma tela, e escolher a tela de cada papel é a navegação por papel (TEC-312).

## D7 — O painel passa a chamar o FastAPI com o JWT de quem está logado

`chamarApi` perde o `X-Admin-Token` e ganha a opção `acesso`, que vira `Authorization: Bearer`. A variável `MOBIA_ADMIN_TOKEN` desaparece do frontend inteiro. As rotas de `/auth/*` chamam sem `acesso`, porque são elas que o produzem.

**O cache de 60 segundos do funil continua e não vaza entre usuários.** O Data Cache do Next casa por URL, método, **cabeçalhos** e corpo (referência de `fetch`, Next 16), então cada token tem a sua entrada. O custo é uma entrada por pessoa por hora, e o argumento da D9 da TEC-190 continua de pé: N abas da mesma pessoa viram uma chamada por minuto.

**O `403` do painel muda de significado.** Antes, `403` queria dizer "o token do ambiente está errado". Agora quer dizer que o papel não tem `VER_FUNIL` — o `CORRETOR`, pela matriz da TEC-202. O aviso é reescrito para dizer isso. A tela "Sem permissão" é a TEC-312.

- **Nota (TEC-312, 26/09/2026):** o `403` do funil deixou de ser aviso e virou a tela "Sem permissão", e quem não tem `VER_FUNIL` nem chega a buscar o funil. Ver `docs/superpowers/specs/2026-09-26-tec-312-menu-por-papel-design.md`.

**`401` da API quer dizer que o access expirou**, 60 minutos depois do login, porque sem a TEC-310 ninguém o renova. A página manda ao login com o `returnTo` preservado.

## D8 — O primeiro usuário nasce por um script

Decisão do Eduardo em 26/09/2026: `scripts/criar_usuario.py`, sem tela.

- Recebe `--email`, `--nome`, `--papel` e, para `CORRETOR`, `--corretor-id`. A senha é pedida duas vezes pelo `getpass`, nunca por argumento: argumento fica no histórico do shell e na lista de processos.
- **Para ADMIN, gera a semente TOTP**, grava cifrada (`totp.cifrar_semente`), marca `mfa_habilitado` e imprime a URI `otpauth://` que o aplicativo autenticador lê. Sem isso o ADMIN nasceria barrado, pela D5 da TEC-201.
- `--mfa` liga o mesmo para os outros papéis, que a regra não obriga.
- A lógica fica numa função que recebe a sessão do banco; o `main` só junta os argumentos. O teste chama a função.

Fecha a lacuna L2 da TEC-201 na parte "não há como o primeiro usuário existir". Cadastro por tela, convite e habilitar TOTP depois de criado continuam sem existir.

## D9 — A varredura do bundle muda de sentinela

`npm run verificar:bundle` procurava o valor de `MOBIA_ADMIN_TOKEN` em `.next/static`. Essa variável deixa de existir. O único segredo que o servidor Next passa a ler de ambiente é `MOBIA_REDIS_URL`, que pode levar senha. A sentinela passa a ser o valor dela, e o job `Frontend` do CI recebe uma URL com uma senha-sentinela.

O access token e o refresh token não entram nessa varredura porque não existem na hora do build: eles nascem em tempo de execução, no Redis. O que prova que eles não chegam ao navegador é a D2 — o cookie só tem o id — e os testes que afirmam o `Set-Cookie` inteiro das respostas de login.

## Lacunas declaradas

- **L1 — o FastAPI ainda aceita o `X-Admin-Token`.** O frontend para de mandá-lo, mas quem tiver o token continua entrando direto na API, sem usuário, sem papel e sem MFA. A remoção mexe em 33 arquivos de teste e virou a TEC-382, por decisão do Eduardo em 26/09/2026. A Emenda E-02 da TEC-201 atribuía a remoção a esta card; o comentário em `api/autorizacao.py` que diz isso passa a apontar para a TEC-382.
- **L2 — todo login chega ao FastAPI com o IP do servidor Next.** O limitador por IP da TEC-205 deixa de separar quem tenta: todas as tentativas de todo mundo caem no mesmo balde de 100 por minuto. Um atacante insistindo em senha trava o login de todos por um minuto, e o limite não o isola. Resolver pede que o Next repasse o IP do cliente em `X-Forwarded-For` e que o FastAPI confie nele (`confiar_em_forwarded_for`), o que depende de como o deploy vai ficar (TEC-219).
- **L3 — sem renovação e sem logout.** São a TEC-310. Até lá, 60 minutos depois do login o painel manda de volta ao login, e não há botão de sair. O registro da sessão antiga fica no Redis até completar 7 dias, com um refresh válido dentro — e é por isso que a TEC-310 precisa revogá-lo no logout.
  - **Nota (TEC-310, 26/09/2026):** fechada. A sessão renova o access 5 minutos antes de ele vencer, e "Sair" revoga o refresh e apaga a sessão. A D7 acima tinha um laço: o `401` mandava ao login, e o login, vendo a sessão no Redis, devolvia à página. A TEC-310 passou a apagar a sessão num `401`. Ver `docs/superpowers/specs/2026-09-26-tec-310-renovar-e-sair-design.md`.
- **L4 — o cenário 2 pede inspecionar o "armazenamento local e os cookies legíveis por script".** Não há teste de navegador neste projeto. O que se mecaniza: nenhuma resposta de login põe token em `Set-Cookie`, e o único cookie tem `HttpOnly`; o código de cliente não escreve em `localStorage` porque não há código de cliente no fluxo; e a varredura do bundle cobre os segredos de ambiente (D9). A verificação no navegador de verdade é manual, e fica registrada no PR.
  - **Nota (TEC-311, 26/09/2026):** o painel passou a ter um componente de cliente, o aviso de inatividade, e ele escreve no `localStorage` — só o horário da última interação (`mobia:ultima-interacao`), nenhum token. O teste dele afirma que essa é a única chave gravada.

## Critérios de aceite

| cenário | onde |
| --- | --- |
| voltar à página pretendida após autenticar | `proxy.ts` (D5) + `destinoSeguro` (D6) + teste do `/login/entrar` que segue o `303` |
| nenhum token de API chega ao navegador | D2, D3, D7, D9; testes do `Set-Cookie`; L4 |
| recusar destino externo após o login | `destinoSeguro` (D6), com um teste por forma de ataque |
| bloquear administrador sem segundo fator | o `403` de `/auth/login` vira a mensagem da tela; teste do `/login/entrar` |

**Emenda E-03 à RNF-11, e duas que faltavam.** O contrato desta card é o SRS do frontend, que não está versionado no repo (a TEC-302 já registrou isso). Do SRS do agente, ela toca a RNF-11: a Emenda E-02 da TEC-201 dizia que esta card fecharia a convivência com o `X-Admin-Token`, e ela fecha só a metade do navegador (L1) — é a E-03. **As Emendas E-01 e E-02 à RNF-11, da TEC-201, não estavam no SRS.** Foram decididas e escritas no desenho da TEC-201, e o comentário de merge daquela card as dá por feitas, mas o documento nunca as recebeu — achado ao procurar onde pôr a E-03. Entram agora, com o texto e a data de lá, e a E-03 registra isso.
