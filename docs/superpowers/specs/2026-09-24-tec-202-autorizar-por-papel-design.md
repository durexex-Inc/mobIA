# TEC-202 — Autorizar por papel em todas as rotas

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-202](https://eduardodurieuxlopes.atlassian.net/browse/TEC-202) — épico TEC-200
**Branch:** `feat/tec-202-autorizar-por-papel`
**Origem:** RNF-12 (SRS v1.0); papéis do modelo `Usuario` da seção 5.1, entregues pela TEC-201

## O problema

A TEC-201 trouxe usuário, papel e JWT — e a lacuna L1 daquele desenho diz o que ficou de fora:

> **não há checagem de papel por rota.** É a TEC-202, e a card a declara fora de escopo. O JWT **carrega** o papel; ninguém ainda o exige, além do `ADMIN` que `exigir_admin` passa a conferir.

Hoje toda rota não pública do sistema — importação de catálogo, CRUD de corretores, aceite de handoff, assumir conversa, funil — está atrás da mesma dependência `exigir_admin`. São **onze rotas com uma guarda só**, e essa guarda pergunta uma coisa só: "é ADMIN, ou tem o token compartilhado?". Um `GERENTE` não entra em lugar nenhum; um `CORRETOR` tampouco; e quem entra, entra em tudo.

A consequência prática está escrita em três emendas do SRS, cada uma declarando a mesma exposição por um caminho diferente — a Emenda E-01 da RN-19.5 (cadastro de corretores), a Emenda E-01 da RN-16.4 (assumir e devolver) e o parágrafo de autenticação da seção 6.6 (funil). Todas apontam para esta card.

## D1 — A rota exige PERMISSÃO, não papel, e a matriz mora num lugar só

Uma rota podia declarar `papeis={"ADMIN", "GERENTE"}`. Recusado. A rota passa a declarar **o que ela faz** — `Permissao.VER_FUNIL` — e quem sabe quais papéis a têm é uma matriz única em `domain/usuarios/permissoes.py`.

Três razões, em ordem de peso:

1. **A card já obriga a isso.** `VER_DADOS_COMPLETOS` é descrita como "concedida por papel", e ela não é rota nenhuma: é uma capacidade que a TEC-195 vai consultar dentro de um handler. Um modelo que só sabe falar de papéis por rota não teria onde guardá-la.
2. **Mudar quem pode o quê vira uma linha na matriz**, e não uma varredura por onze arquivos de rota atrás de conjuntos de strings que precisam concordar entre si.
3. **A matriz é testável sem HTTP.** `tests/unit/` responde "o `LEITURA` tem alguma permissão de escrita?" sem subir app, sem banco e sem token — que é a pergunta do terceiro cenário do Gherkin, feita de uma vez para todas as rotas em vez de uma vez por rota.

A matriz das rotas que existem hoje:

| permissão | ADMIN | GERENTE | CORRETOR | LEITURA | rotas |
| --- | :-: | :-: | :-: | :-: | --- |
| `GERIR_CATALOGO` | ✓ | | | | `POST /imoveis/importar`, `GET /imoveis/importacoes/{id}` |
| `GERIR_CORRETORES` | ✓ | | | | `POST`/`GET`/`PATCH /corretores` |
| `BUSCAR_IMOVEIS` | ✓ | ✓ | ✓ | ✓ | `POST /imoveis/busca` |
| `VER_FUNIL` | ✓ | ✓ | | ✓ | `GET /metricas/funil` |
| `ATENDER_LEAD` | ✓ | ✓ | ✓ | | `POST /handoffs/{id}/aceitar`, `/resumo`, `POST /conversas/assumir`, `/devolver` |
| `VER_DADOS_COMPLETOS` | ✓ | ✓ | | | nenhuma ainda — ver a D7 |

Três escolhas dessa tabela não são óbvias e ficam ditas:

- **`LEITURA` tem `VER_FUNIL` e `CORRETOR` não.** É a matriz de navegação da RN-FE-03.1, transcrita da card de tela TEC-312: o funil aparece para ADMIN, GERENTE e LEITURA, e não para CORRETOR. Faz sentido de negócio — o funil é da operação inteira, e o corretor trabalha a própria carteira.
- **`GERENTE` tem `ATENDER_LEAD`**, embora a seção 6.2 do SRS escreva "Papel: `CORRETOR`" para assumir. A escalada de SLA da RN-16.3 vai justamente **para o gerente** quando ninguém aceita; deixá-la chegar a quem não pode agir seria desenhar um beco sem saída. Entra na emenda E-01 abaixo.
- **`LEITURA` não tem nada além de ler.** É o terceiro cenário do Gherkin, e é a única linha da matriz que o teste unitário afirma por negação: nenhuma permissão de escrita, em nenhuma rota, agora ou depois.

## D2 — `ADMIN` é superconjunto, e o token compartilhado é um `ADMIN` sintético

**`ADMIN` tem todas as permissões**, e isso é afirmado por um teste e não por repetição na tabela. A alternativa — privilégio mínimo estrito, com `ADMIN` recusado em `ATENDER_LEAD` por "não é corretor" — foi considerada e recusada: a operação de emergência (a conversa travada, o handoff que ninguém pega) precisa de alguém que possa agir, e inventar um quinto papel para isso é pior que aceitar o superconjunto.

**O `X-Admin-Token` continua valendo, e resolve para uma identidade `ADMIN` sem usuário.** Não é concessão preguiçosa: é o que a Emenda E-01 da RN-19.5 já escreveu em 12/09/2026 — *"enquanto a TEC-201 não existir, o papel `ADMIN` é o header `X-Admin-Token`"*. A TEC-201 chegou e não o apagou, por sequenciamento (D2 daquele desenho): quem o apaga é a TEC-309, que faz o BFF mandar sessão de verdade.

Se esta card negasse o token compartilhado, o painel pararia hoje e a TEC-309 não teria o que migrar.

**A consequência fica dita, e é a mesma da TEC-201, agora com mais alcance:** quem tem o token compartilhado passa em **toda** permissão desta matriz, inclusive nas que nenhum papel além de `ADMIN` tem. A autorização por papel só vale de verdade para quem entra por JWT — e é por isso que o `warning` por uso do token, que a TEC-201 instalou para medir quando ele parou de ser usado, importa mais depois desta card, não menos.

## D3 — A checagem é dependência por rota, e quem garante o "toda rota" é uma varredura em teste

A regra da card é *"a checagem acontece em **toda** rota"*. Há duas formas de garantir isso, e o repo tem precedente para a que eu **não** escolhi.

O precedente é o `RateLimitPorIP` (TEC-205), e o comentário dele diz por que é middleware:

> Aplica-se por omissao e nao por opt-in: uma lista de rotas incluidas erraria para o lado de esquecer uma rota nova, que e o erro caro.

O argumento é bom e vale aqui — mas **middleware não consegue fazer esta checagem**, e a razão é mecânica: o Starlette resolve qual rota atende a requisição **dentro** do router, depois de toda a pilha de middleware. Um `BaseHTTPMiddleware` que quisesse saber "qual permissão esta rota exige" teria de reimplementar a correspondência de caminho — inclusive `/{corretor_id}` e `/{handoff_id}` — em paralelo ao FastAPI, e duas implementações de roteamento divergem em silêncio por definição.

Então a checagem é `Depends(Exige(Permissao.X))` na assinatura de cada rota, e o "esqueci uma rota nova" é pego por **`test_toda_rota_declara_autorizacao`**: uma varredura de `app.routes` que exige de cada rota registrada ou uma dependência `Exige`, ou presença numa lista `ROTAS_PUBLICAS` com a razão de cada uma escrita ao lado. Rota nova sem nenhum dos dois reprova a suíte.

É proteção de CI e não de runtime, e a diferença está dita. O que ela garante é o que importa: nenhuma rota chega à `main` sem alguém ter decidido, por escrito, quem pode chamá-la.

## D4 — O dono vem do JWT, e não de uma consulta por requisição

A regra *"o corretor vê apenas os próprios leads"* exige saber **qual corretor** é o usuário. O `Usuario` já tem `corretor_id` desde a TEC-201 — e o JWT não o carrega.

Duas formas de obtê-lo, e a escolha é a que a TEC-201 já fez:

- **Nova claim `corretor_id` no JWT.** Custo zero por requisição.
- **Consultar `usuarios` a cada requisição autorizada.** Daria de graça o que a lacuna L5 da TEC-201 não tem (desativar um usuário valeria na hora, em vez de valer só no refresh).

Fica a claim. A L5 registrou que *"uma lista de revogação daria isso ao custo de uma consulta por requisição; a janela de uma hora foi aceita"* — e reabrir essa decisão de lado, dentro de uma card que é sobre outra coisa, seria desfazer sem discutir. **A consequência herdada:** mudar o vínculo de corretor de um usuário só passa a valer no próximo `refresh`, em até 60 minutos. É a mesma janela que já vale para o papel.

**A claim entra em todos os JWTs deste sistema, inclusive no desafio de MFA**, para que exista uma forma só de corpo. `validar` a exige como as outras; `None` é valor legítimo e quer dizer "não é corretor" — o `ADMIN` e a `GERENTE` não são.

**E `None` num usuário de papel `CORRETOR` nega tudo o que é por dono**, em vez de liberar. Um `CORRETOR` sem vínculo é cadastro incompleto (ver a L7), e a diferença entre "não tem dono" e "é dono de tudo" é exatamente o erro que esta card existe para não cometer.

## D5 — Onde a regra do dono se aplica hoje, já que `/leads/{id}` não existe

O segundo cenário do Gherkin diz *"requisita diretamente o identificador de um lead de outro corretor"*. A rota que o SRS descreve para isso é `GET /api/v1/leads/{leadId}` (seção 6.2), e **ela não existe neste sistema** — nem ela, nem `GET /api/v1/leads`, nem `PATCH /api/v1/leads/{leadId}/qualificacao`.

Escrever o teste do cenário exigiria criar a rota, e criar a rota de lead dentro de uma card de autorização seria **inventar a entidade que falta para o teste se auto-satisfazer**. Não é o que esta card faz.

O que existe e carrega dono é o **handoff**: `handoffs.corretor_id` aponta para quem recebeu o lead, e há duas rotas que o endereçam por identificador — `POST /handoffs/{id}/aceitar` e `POST /handoffs/{id}/resumo`. A regra do dono vale ali, com a mesma forma que valerá em `/leads/{id}` quando ela existir: papel `CORRETOR` agindo sobre handoff de outro corretor recebe **403 e a tentativa é registrada**.

E vale também em `POST /conversas/assumir` e `/devolver`, onde a mudança é de outra natureza e é a mais valiosa desta card: hoje o `corretor_id` vem **no corpo** e é, nas palavras da Emenda E-01 da RN-16.4, *"afirmação de quem chama, não identidade provada"*. Para quem entra com JWT de papel `CORRETOR`, ele passa a ser conferido contra a identidade — assumir em nome de outro vira 403. Para `ADMIN` e `GERENTE` (e para o token compartilhado, que é um `ADMIN`), continua sendo afirmação, porque para esses papéis agir em nome de terceiro é a função.

## D6 — A tentativa negada vai para o LOG, e não para uma tabela

A card pede *"tentativa de acesso negada é registrada"*. O repo tem os dois precedentes, e eles discordam: `moderation_events` e `rate_limit_events` são tabelas; `auth.login_recusado` e `auth.jwt_recusado` são log.

Decide o docstring de `RateLimitEvent`:

> Escrever uma linha por requisicao transformaria o registro de abuso no proprio vetor de abuso: no widget, o atacante escreveria uma linha de banco por requisicao e a defesa custaria mais que o ataque.

Vale igual aqui, e com menos defesa: negação de autorização é o que um varredor de endpoints produz **em rajada**, e ele não precisa de credencial nenhuma para produzi-la. Uma tabela escrita a cada 403 é um amplificador — uma requisição barata do atacante vira uma escrita no Postgres do defensor.

Então o registro é um evento estruturado, `autorizacao.negada`, com `usuario_id`, `papel`, a permissão exigida, o método e a rota — e **nunca** o token nem o corpo. O `structlog` do projeto já mascara as chaves sensíveis (`app/logging.py`).

**A trilha imutável de conformidade é a TEC-206**, que não depende desta e traz a tabela com retenção de 12 meses. Quando ela chegar, este evento ganha um destino persistente sem mudar de forma. Fica declarado como a L5.

## D7 — `VER_DADOS_COMPLETOS` existe, não mascara nada ainda, e `GET /auth/me` é o que a torna observável

A card afirma que esta autorização *"é também a base do mascaramento de dado pessoal **já entregue em TEC-195**"*. **A TEC-195 não está entregue** — está em "A fazer", é bloqueada por esta e pela TEC-192, e nada no código mascara telefone ou e-mail de lead hoje. A card está errada sobre o próprio estado, e a divergência vai no comentário dela.

Isso deixa `VER_DADOS_COMPLETOS` numa posição incômoda: a card manda concedê-la por papel, e não há um único sítio que a consulte. Permissão que ninguém checa é código morto — e código morto numa matriz de segurança é pior que ausente, porque parece proteção.

A saída não é inventar um mascaramento aqui (é a TEC-195, e ela tem quatro cenários próprios). É dar à permissão **um consumidor real e pequeno**: `GET /api/v1/auth/me`, que devolve `{usuarioId, papel, corretorId, permissoes[]}` para quem apresenta JWT válido.

Não é enfeite, e quem pediu foi outra card: a RN-FE-03.2, na TEC-312, diz *"papéis e permissões vêm de `GET /bff/me`; o cliente não decodifica JWT"*. O BFF da TEC-302 precisa de uma origem para esses dados, e é esta. Com ela, `VER_DADOS_COMPLETOS` deixa de ser declaração e passa a ser resposta HTTP observável e testada.

## D8 — 403 e não 404 para o recurso de outro corretor

Responder 404 esconderia a existência do handoff; responder 403 revela que ele existe e nega o acesso. O SRS decide, na seção 6.2: *"Erros: 403 (lead de outro corretor), 404"* — os dois códigos, com sentidos distintos.

Fica o 403, e a razão é mais forte que a obediência ao texto: **o 404 e o "não é seu" seriam indistinguíveis**, e aí a própria tentativa negada — que a card manda registrar — se perderia dentro do ruído de identificadores inexistentes. Quem investiga precisa saber a diferença entre "sondou um id aleatório" e "tentou o lead do colega".

A informação que isso vaza é a existência de um UUIDv4 que o atacante teria de adivinhar. Aceito, e escrito para não ser redescoberto.

## Arquivos

```
src/mobia/domain/usuarios/permissoes.py     # Permissao, MATRIZ e permissoes_de (D1)
src/mobia/api/autorizacao.py                # Identidade da requisicao, Exige, ROTAS_PUBLICAS (D3)
src/mobia/api/deps.py                       # exigir_admin sai; o ramo do token compartilhado migra
src/mobia/api/routes/auth.py                # GET /auth/me (D7)
src/mobia/api/routes/imoveis.py             # GERIR_CATALOGO e BUSCAR_IMOVEIS
src/mobia/api/routes/corretores.py          # GERIR_CORRETORES
src/mobia/api/routes/metricas.py            # VER_FUNIL
src/mobia/api/routes/handoffs.py            # ATENDER_LEAD + dono (D5)
src/mobia/api/routes/conversas.py           # ATENDER_LEAD + dono (D5)
src/mobia/domain/usuarios/tokens.py         # claim corretor_id (D4)
```

Sem migration: a coluna `usuarios.corretor_id` já existe desde a `0044`.

## Testes

- **Unitários da matriz** — `ADMIN` tem tudo; `LEITURA` não tem nenhuma escrita; cada permissão nomeia pelo menos um papel; a matriz cobre os quatro papéis da `PAPEIS`.
- **A varredura (D3)** — toda rota de `create_app()` ou exige permissão, ou está em `ROTAS_PUBLICAS`.
- **O esquema do primeiro cenário, contra banco** — os quatro papéis contra uma rota `ADMIN`, com a tabela do Gherkin virando `parametrize`.
- **O dono (D5)** — `CORRETOR` aceita o próprio handoff (200) e o de outro (403); `assumir` em nome de outro (403) e em nome de si (200).
- **`LEITURA` não altera nada** — contra as escritas que existem, não contra uma rota inventada.
- **A tentativa negada é registrada (D6)** — o evento `autorizacao.negada` sai com papel e rota, capturado pelo mesmo molde dos testes de log que já existem.
- **A coexistência (D2)** — o token compartilhado continua passando em rota de qualquer permissão. É o teste que garante que esta card não quebrou o painel, como o equivalente da TEC-201.
- **`GET /auth/me`** — devolve as permissões do papel, e recusa sem JWT (o token compartilhado não serve: ele não tem usuário).

## Emendas ao SRS

**Emenda E-01 à RNF-12 (TEC-202, 24/09/2026)** — a regra nomeia os quatro papéis e uma regra de visibilidade; a matriz concreta de **permissões por papel** fica fixada no desenho desta card e em `domain/usuarios/permissoes.py`, com três desvios do que as seções 6.x escrevem por rota, cada um com razão: (a) **`ADMIN` é superconjunto** e passa em toda permissão, inclusive nas rotas que a seção 6.2 marca como `CORRETOR`, porque a operação de emergência precisa de alguém que possa agir; (b) **`GERENTE` recebe `ATENDER_LEAD`**, que a seção 6.2 não prevê, porque a escalada de SLA da RN-16.3 chega a ela e um destinatário que não pode agir é um beco sem saída; (c) **`LEITURA` recebe `VER_FUNIL`** e **`CORRETOR` não**, conforme a matriz de navegação da RN-FE-03.1 (TEC-312). **Consequência declarada:** o `X-Admin-Token` compartilhado resolve para uma identidade `ADMIN` sintética e portanto **passa em todas as permissões desta matriz** — a autorização por papel só vale para quem entra por JWT, e quem fecha isso é a TEC-309. Ver as D1 e D2 do desenho.

**Emenda E-05 à RN-16.4 (TEC-202, 24/09/2026)** — a Emenda E-01 desta mesma regra (TEC-179, 13/09/2026) registrou que o `corretor_id` de assumir e devolver é *"afirmação de quem chama, não identidade provada"* e que *"fechar é a TEC-201"*. Fecha aqui, e **só para o papel `CORRETOR`**: quem apresenta JWT de `CORRETOR` só assume ou devolve em nome do próprio `corretor_id`, conferido contra a claim do token; divergir é `403` com registro. Para `ADMIN` e `GERENTE` — e para o token compartilhado, que resolve para `ADMIN` — o campo **continua sendo afirmação**, porque agir em nome de terceiro é a função desses papéis. **Consequência declarada:** a exposição que aquela emenda descreveu permanece inteira para quem tem o token compartilhado. Ver a D5 do desenho.

## Lacunas declaradas

- **L1 — o primeiro cenário do Gherkin não é exercitado sobre "a configuração do agente", porque ela não existe.** `GET · PUT /api/v1/configuracoes/{chave}` (RN-19.3, seção 6.6) não tem rota neste sistema. O esquema de cenário (ADMIN permitido, os outros três negados) é exercitado sobre as rotas `ADMIN` que existem — CRUD de corretores e importação de catálogo. Quando o módulo de configuração chegar, ele entra na matriz com `GERIR_CONFIGURACAO` e o teste ganha mais uma linha.
- **L2 — o terceiro cenário também troca de sujeito, pela mesma razão.** *"Tenta editar a qualificação de um lead"* aponta para `PATCH /api/v1/leads/{leadId}/qualificacao`, que não existe. O `LEITURA` é exercitado contra as escritas que existem, e a matriz garante o resto por construção: ele não tem permissão de escrita nenhuma.
- **L3 — nada mascara dado pessoal ainda.** `VER_DADOS_COMPLETOS` é concedida por papel e consultável em `GET /auth/me`, e nenhum handler a usa para esconder telefone ou e-mail. É a TEC-195 — que a card afirma entregue e **não está**.
- **L4 — o token compartilhado continua abrindo tudo**, sem usuário, sem papel real e sem MFA (D2). Esta card não o fecha; a TEC-309 fecha.
- **L5 — não há trilha imutável.** A tentativa negada vai para o log estruturado (D6), que não é imutável nem retido por 12 meses como a RNF-18 exige. A tabela é a TEC-206.
- **L6 — `/docs`, `/redoc` e `/openapi.json` continuam públicos.** São rotas que o FastAPI registra sozinho e que descrevem a API inteira a quem pedir. Entram na `ROTAS_PUBLICAS` com essa razão escrita — não porque alguém decidiu que devem ser públicas, mas porque desligá-las é decisão de outra card, e escondê-las dentro desta as tiraria da vista de quem for decidir.
- **L7 — continua sem rota de cadastro de usuário** (é a L2 da TEC-201, intacta). Na prática, o papel e o vínculo de corretor de cada pessoa são gravados à mão no banco — inclusive o `corretor_id` de que a D4 depende. Um `CORRETOR` cadastrado sem vínculo não consegue agir sobre handoff nenhum, e não há tela que mostre isso a quem cadastrou.
