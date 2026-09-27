# Painel de funil (TEC-190)

O dashboard da gerente comercial: as seis etapas do funil da RN-17.2 com
conversão entre elas, os indicadores da RN-17.1 e os cinco filtros da
RN-17.3. Consome `GET /api/v1/metricas/funil` do FastAPI.

## Rodar em desenvolvimento

O backend e o Redis precisam estar de pé:

```bash
cd ..
docker compose up -d
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m uvicorn mobia.app.main:app --port 8000
```

Noutro terminal:

```bash
MOBIA_API_BASE=http://localhost:8000 npm run dev
```

**Para entrar, é preciso um usuário, e desde a TEC-309 ele nasce por script** —
ainda não há tela de cadastro:

```bash
cd ..
./.venv/Scripts/python.exe scripts/criar_usuario.py --email ana@x.com --nome "Ana" --papel GERENTE
```

A senha é pedida pelo terminal. Para `ADMIN`, o script também imprime uma URI
`otpauth://` para cadastrar no aplicativo autenticador: administrador só entra
com o código de 6 dígitos (RNF-11). A URI leva a semente em claro.

## As variáveis, e por que nenhuma delas é `NEXT_PUBLIC_`

| variável | onde é lida | obrigatória |
| --- | --- | --- |
| `MOBIA_API_BASE` | servidor Next, ao montar a URL do FastAPI | não (`http://localhost:8000`) |
| `MOBIA_REDIS_URL` | servidor Next, onde a sessão do painel mora | não (`redis://localhost:6380`, o do `docker compose`) |
| `MOBIA_ORIGEM_DO_PAINEL` | proxy `/bff/*` e login, na checagem de `Origin` | só atrás de proxy — ver abaixo |

**Não há mais token de API no ambiente do Next.** Até a TEC-309 havia o
`MOBIA_ADMIN_TOKEN`, que ia em toda chamada como `X-Admin-Token` — um ADMIN sem
usuário. Agora cada chamada leva o JWT de quem está logado, que o FastAPI
emitiu no login e que fica guardado no Redis, e não no navegador. Um ambiente
que ainda tenha a variável antiga não faz diferença: nada mais a lê.

**`MOBIA_REDIS_URL` nunca chega ao navegador**: pode levar a senha do Redis, e
quem a tivesse leria todas as sessões. **Dois gates guardam isso, e eles pegam
enganos diferentes:**

| engano | quem reprova |
| --- | --- |
| importar `lib/servidor/` de um componente de cliente | `npm run build`, pelo `import 'server-only'` |
| renomear a variável para `NEXT_PUBLIC_MOBIA_REDIS_URL` | `npm run verificar:bundle` |

```bash
MOBIA_REDIS_URL=redis://:sentinela-com-16-ou-mais@localhost:6380 npm run build
MOBIA_REDIS_URL=redis://:sentinela-com-16-ou-mais@localhost:6380 npm run verificar:bundle
```

A varredura procura o valor de `MOBIA_REDIS_URL` em tudo que está sob
`.next/static` — o que o navegador de fato baixa. Ela **reprova** se a variável
não estiver setada, em vez de pular: verificação que pula em silêncio é
verificação que ninguém nota ter parado de rodar. No CI a sentinela é definida
uma vez, no nível do job, porque duas cópias divergentes fariam a varredura
passar sem ter procurado nada.

**O que nenhum dos dois pega:** um segredo passado como prop de um Server
Component para um Client Component. Ele iria no payload RSC do HTML, que não é
arquivo estático, e não dispara o `server-only` porque o módulo continua sendo
importado só do servidor.

## A sessão (TEC-309)

O login é senha mais, para `ADMIN`, um código TOTP — e não OIDC, que é o que a
card descrevia: o backend adotou credencial local (Emenda E-01 à RNF-11). O
desenho está em
`docs/superpowers/specs/2026-09-26-tec-309-login-do-painel-design.md`.

- **O navegador recebe só um id opaco**, no cookie `mobia_sessao` (`HttpOnly`,
  `Secure`, `SameSite=Lax`, 7 dias). Os tokens do FastAPI ficam no Redis, sob o
  SHA-256 desse id.
- **Duas guardas:** `proxy.ts` manda ao login quem chega sem o cookie, e
  `exigirSessao` (em `lib/servidor/sessao.ts`) procura o valor no Redis. A
  primeira é só uma checagem rápida; a segunda é a de verdade, e toda página
  que mostre dado de lead precisa chamá-la.
- **Renovação transparente (TEC-310).** Faltando 5 minutos para o access
  vencer, a sessão troca o refresh por um par novo, com um lock no Redis —
  o refresh da TEC-201 detecta reuso, e duas renovações juntas derrubariam a
  sessão. A sessão dura 7 dias contados do login; renovar não estende.
- **"Sair" é um POST para `/sair`**: revoga o refresh no FastAPI, apaga a
  sessão e o cookie, e responde com `Clear-Site-Data: "cache"`.
- **Sessão ociosa (TEC-311).** Aos 30 minutos sem interação, um aviso conta
  60 segundos e depois chama `/sair`. Foi o **primeiro componente de cliente**
  do painel (`components/AvisoDeInatividade.tsx`); o segundo é a busca da lista
  de leads (TEC-321), o terceiro, a conversa do lead (TEC-324), e o quarto, o controle da
  conversa (TEC-327). Ele guarda no `localStorage`
  só o horário da última interação, para as abas se enxergarem. O servidor
  também encerra a sessão ociosa há mais de 32 minutos — para o celular
  esquecido, que não roda o aviso.
- **O Redis dos testes é um mapa** (`test/armazem-em-memoria.ts`), trocado por
  `vi.mock`: nenhum teste do frontend precisa de Redis de pé.

## Os dois caminhos até a API

Toda chamada autenticada sai do servidor, por um de dois caminhos, e os dois
passam pela mesma porta (`lib/servidor/api.ts`), que é o único lugar do projeto
que põe o JWT da sessão num cabeçalho:

| caminho | quem usa | cache | `X-Request-Id` |
| --- | --- | --- | --- |
| Server Component → `buscarFunil` | o painel de funil | `revalidate: 60` | **não** |
| Server Component → `buscarLeads` | a lista de leads | `no-store` | não |
| Route Handler `/bff/[...rota]` | a conversa do lead (falas anteriores, TEC-324; polling, TEC-327), assumir e devolver (TEC-327), revelar telefone (TEC-330), corrigir a qualificação (TEC-329), responder o lead (TEC-328) | `no-store` | sim |

**O painel não passa pelo `/bff/*`, e isso é deliberado.** Um Server Component
chamando o próprio Route Handler custaria um round-trip HTTP do processo para
ele mesmo e perderia o `revalidate: 60`, que é o que faz as abas de uma pessoa
com o painel aberto virarem **uma** chamada por minuto ao FastAPI. Desde a
TEC-309 é uma por pessoa, e não uma no total: o JWT vai no cabeçalho, e cabeçalho
entra na chave do cache — que é justamente o que impede o funil de um usuário
ser servido a outro. Migrar o painel,
na TEC-302, foi tirar dele o caminho privado até a API — não lhe dar um salto.

**O `X-Request-Id` não viaja no caminho cacheado, e o motivo não é óbvio.** O
Data Cache do Next casa uma requisição por URL, método, **headers** e corpo. Um
id novo a cada requisição daria uma entrada de cache por acesso, com taxa de
acerto zero — e nada ficaria vermelho: o painel continuaria correto, e a
enxurrada no FastAPI só apareceria quando muita gente abrisse a tela. O tipo de
`chamarApi` recusa cache e id de correlação juntos.

**Propagar o `X-Request-Id` ainda não correlaciona nada.** O FastAPI não lê esse
header em lugar nenhum — `correlation_id`, em `app/logging.py`, é preenchido com
um UUID próprio pelo webhook e pelo widget, e a rota de métricas nem isso faz. O
header sai do BFF e é descartado na entrada.

## A lista de leads (TEC-321)

`/leads` lista os leads por score, com busca por telefone ou bairro, e é a tela
de entrada do CORRETOR: o login manda todo mundo para `/`, e o funil redireciona
para `/leads` quem não tem `VER_FUNIL` e tem `VER_LEADS`. O desenho está em
`docs/superpowers/specs/2026-09-26-tec-321-lista-de-leads-design.md`.

- **A ordem é do backend.** "Score" e "Última interação" são links
  (`?ordenar=`), e a tabela nunca reordena o que recebeu: ordenar no cliente
  reordenaria só os 25 da página.
- **A busca troca a URL, e não chama a API.** `components/BuscaDeLeads.tsx`
  espera 300 ms e só navega com 2 caracteres ou mais (ou com zero, para voltar
  à lista inteira). A página aplica a mesma regra a uma `?busca=` digitada à
  mão.
- **Não há nome.** Nenhuma tabela o guarda; a primeira coluna é o telefone
  mascarado que a API devolve.
- **Sem cache**, ao contrário do funil: o score muda a cada turno do agente.
- **Só a primeira página.** Paginação, filtros e cartões no celular são a
  TEC-322.

## O detalhe do lead (TEC-323)

`/leads/[leadId]` mostra o resumo em seis blocos, o contato mascarado, a
qualificação, os agendamentos e os follow-ups. Guardado por
`VER_DETALHE_DO_LEAD`: LEITURA vê a lista e não o detalhe, e para ela a linha
da lista não é link. O desenho está em
`docs/superpowers/specs/2026-09-27-tec-323-detalhe-do-lead-design.md`.

- **Abrir o detalhe grava um acesso na trilha de auditoria** (TEC-193), a cada
  abertura, recarregar inclusive. Por isso a lista linka para ele com `<a>`, e
  não com `next/link`. O prefetch padrão para no `loading.tsx` do detalhe e não
  grava nada, mas `prefetch={true}`, ou apagar aquele `loading.tsx`, passaria a
  gravar um acesso por linha visível.
- **O resumo é cortado nos marcadores literais da TEC-175** (`## Quem e o
  lead` …). Se um marcador mudar lá, a tela mostra o texto inteiro, sem os
  títulos, e nada some.
- **Histórico de score e imóveis recomendados** entraram na TEC-325, entre
  Qualificação e Agendamentos. O gráfico é SVG desenhado à mão, sem biblioteca,
  e a lista embaixo dele é a leitura completa. A reação ao imóvel usa os
  rótulos do chat web ("Gostei", "Não é pra mim").

## A conversa do lead (TEC-324)

A última seção do detalhe. A primeira página, com as 100 falas mais recentes,
vem do servidor, pedida **em paralelo** com o detalhe. As anteriores vêm do
navegador, pelo `/bff/*`. A conversa é o **primeiro consumidor de cliente
do proxy**: a allowlist ganhou `GET api/v1/leads/*/mensagens`, e só essa rota
de lead. O desenho está em
`docs/superpowers/specs/2026-09-27-tec-324-transcricao-design.md`.

- **Abrir o detalhe grava dois acessos na trilha** (`detalhe` e `transcricao`),
  e cada "Carregar anteriores" grava mais um. Por isso as anteriores só vêm por
  clique, e nunca ao rolar.
- **`components/Transcricao.tsx` é o terceiro componente de cliente**: manter
  a posição de leitura ao inserir falas acima exige medir a altura antes e
  depois.
- **A moderação é do backend.** A fala retida só chega para ADMIN, e a tela a
  mostra como "Mensagem retida pela moderação" mesmo que um conteúdo viesse.

## Assumir e devolver a conversa (TEC-327)

Quem tem `ATENDER_LEAD` e vínculo de corretor vê "Assumir conversa" ou
"Devolver ao agente" logo abaixo do título do lead. As duas ações pedem
confirmação e vão como `POST` pelo `/bff/*`, as primeiras mutações do
navegador pelo proxy. Depois de cada uma, a tela recarrega do servidor
(`router.refresh()`) em vez de mudar a faixa por conta própria. O desenho está
em `docs/superpowers/specs/2026-09-27-tec-327-assumir-e-devolver-design.md`.

- **Com a conversa assumida por quem vê a tela, a conversa faz polling a cada
  5 s**, só com a aba visível, pedindo `?depois=` o cursor que o servidor
  devolveu. **O backend só grava esse poll na trilha quando ele traz fala**
  (decisão de 27/09/2026): um poll vazio não entrega dado pessoal.
- **A faixa sobrevive a recarregar**, porque o detalhe diz quem tem a conversa
  (`atendimento`). O 409 de "já assumida" traz o nome de quem a tem.

## Responder o lead (TEC-328)

Quem vê "Assumir conversa" vê também, embaixo da conversa, o campo para
responder o lead. Ele só fica habilitado com a conversa assumida por quem vê a
tela. Enviar faz `POST /leads/{leadId}/mensagens` pelo `/bff/*`, e a fala
entra no fim da conversa com o rótulo "Corretor". O desenho está em
`docs/superpowers/specs/2026-09-27-tec-328-responder-pelo-painel-design.md`.

- **Até 1.000 caracteres**, com contador. A API aceita até 4096; o limite
  menor é da tela.
- **Cada mensagem leva um `messageId`**, gerado no cliente e reusado enquanto
  o texto não mudar. Reenviar depois de uma falha não manda a mensagem duas
  vezes ao lead.
- **Janela de 24 h do WhatsApp:** o detalhe diz quando ela fecha
  (`janelaDeServicoFechaEm`), e a tela bloqueia o texto livre a partir daí e
  explica que só template aprovado pode ser enviado. Uma fala nova do lead
  reabre a janela. O painel ainda não envia templates.

## Corrigir a qualificação (TEC-329)

Quem tem `ATENDER_LEAD` vê "Editar qualificação" na seção Qualificação do
detalhe. Isso inclui CORRETOR, GERENTE e ADMIN, e a GERENTE sem cadastro de
corretor também. Salvar faz `PATCH /leads/{leadId}/qualificacao` pelo
`/bff/*`, mostra "Score 47 → 62" e recarrega a tela do servidor. O desenho está
em `docs/superpowers/specs/2026-09-27-tec-329-corrigir-qualificacao-design.md`.

- **Só o que mudou vai no `PATCH`**, comparado com o formulário de partida, e
  não com a ficha. Campo esvaziado vai como `null`, que limpa.
- **Tipo de imóvel, urgência e forma de pagamento são listas**, e as opções
  são os mapas de rótulo de `lib/detalhe.ts`. `tests/unit/test_vocabulario_da_tela.py`,
  do lado Python, reprova se eles divergirem dos enums do backend.
- **A região é texto**: o backend a trata como conjunto aberto e a grava na
  forma canônica. "Perto do Campeche" vira `campeche`.
- **A faixa de preço é digitada em reais inteiros.**
- **Formulário sujo** avisa o aviso de inatividade (TEC-311).
- **Conversa encerrada** não mostra o botão.

## Revelar telefone e e-mail (TEC-330)

O telefone chega mascarado para todo papel (`+55 48 9****-**21`), na lista e
no detalhe: o número cheio nunca vem na página. Quem tem `VER_DADOS_COMPLETOS`
(GERENTE e ADMIN) vê um botão "Revelar" ao lado da máscara. O clique faz
`POST /leads/{leadId}/revelar` pelo `/bff/*`, e o backend grava a trilha antes
de responder. O desenho está em
`docs/superpowers/specs/2026-09-27-tec-330-revelar-dado-pessoal-design.md`.

- **O número vive só no estado de `components/DadoRevelavel.tsx`.** Some em 5
  minutos, no "Ocultar" ou ao sair da tela. Nada vai para a URL, o
  armazenamento do navegador ou o `console`. Revelar de novo grava outra
  linha na trilha.
- **O e-mail não tem botão**, porque nenhuma tabela guarda e-mail de lead
  (D7 da TEC-195) e o detalhe o recebe sempre nulo. Quando a fonte existir e o
  backend mandar a máscara, o botão aparece sem mudar a tela.
- **Na lista, o botão fica fora do link** que abre o detalhe.
- **Toda resposta do `/bff/*` é `Cache-Control: no-store`**, recusa
  inclusive.

## O proxy `/bff/*` exige sessão

Desde a TEC-309, uma requisição sem sessão válida no Redis leva `401` e não
chega ao FastAPI. Com sessão, ela leva o JWT de quem está logado, e é o FastAPI
que decide pelo papel (TEC-202).

A checagem de `Origin` continua sendo o que era: defesa de **CSRF**, e não
autenticação. Ela vale porque quem escreve aquele header é o navegador; um `GET`
sem `Origin` é aceito, senão navegação e prefetch legítimos quebrariam. As
rotas de POST do login usam a mesma regra — lá ela barra o CSRF de login, em que
quem ataca faz a vítima entrar na conta dele.

`MOBIA_ORIGEM_DO_PAINEL` só é necessária atrás de proxy, onde o `Host` que o
Next vê pode ser `localhost:3000` enquanto o navegador manda o domínio público —
e aí a comparação recusaria toda mutação legítima. Sem proxy, a origem da própria
requisição é o valor certo e não há o que configurar.

## O cache do painel pode mentir por um minuto

Observado na verificação de ponta a ponta da TEC-190: com o backend
fora do ar, um recorte que o cache já viu continua sendo servido, com dado
de até 60 segundos atrás, em vez de mostrar o aviso de falha. É o
`stale-while-revalidate` fazendo o que promete, e é o comportamento
desejado — mas quem for diagnosticar uma queda precisa saber que a tela
pode estar mentindo por um minuto. Um recorte novo, que o cache não tem,
mostra o aviso na hora.

## O que o painel ainda não sabe

A etapa **Agendado** e os quatro indicadores de visita (criados, confirmados,
realizados e taxa de no-show) saem `null`, com o texto "sem fonte de dados" —
**nunca zero**. Não existe tabela de agendamento no backend: marcar visita é
RF-11 e RF-12, épicos ainda não construídos. Zero seria uma afirmação falsa,
e é a decisão D1 do desenho.

A tela distingue três ausências, e a distinção é deliberada:

| texto | significa |
| --- | --- |
| `sem fonte de dados` | não existe de onde tirar o número (defeito do sistema, RF-12 conserta) |
| `sem dados no período` | a coorte estava vazia (fato do negócio) |
| `—` | não há conversão calculável entre estas duas etapas |

## Comandos

```bash
npm run dev                # desenvolvimento
npm test                   # vitest
npm run lint               # eslint
npm run build              # build de produção
npm run verificar:bundle   # o token não está no bundle de cliente
```

Os quatro últimos rodam no CI, no job `Frontend`. Os gates de Python (`ruff`,
`mypy`) não olham para este diretório — nenhum deles lê TypeScript.

**O Node precisa ser o do `.nvmrc` (24).** Com Node 20 o `vitest` não roda um
teste sequer: morre em `TypeError: webidl.util.markAsUncloneable is not a
function`, que é o `jsdom` novo exigindo Node ≥ 22. Não é defeito da suíte, e
reexecutar não muda nada.
