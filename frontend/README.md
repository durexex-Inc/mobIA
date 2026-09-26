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
- **Sem renovação e sem logout ainda** — é a TEC-310. Uma hora depois do login
  o access expira e o painel manda de volta ao login, preservando o recorte.
- **O Redis dos testes é um mapa** (`test/armazem-em-memoria.ts`), trocado por
  `vi.mock`: nenhum teste do frontend precisa de Redis de pé.

## Os dois caminhos até a API

Toda chamada autenticada sai do servidor, por um de dois caminhos, e os dois
passam pela mesma porta (`lib/servidor/api.ts`), que é o único lugar do projeto
que põe o JWT da sessão num cabeçalho:

| caminho | quem usa | cache | `X-Request-Id` |
| --- | --- | --- | --- |
| Server Component → `buscarFunil` | o painel de funil | `revalidate: 60` | **não** |
| Route Handler `/bff/[...rota]` | fundação para a TEC-312 | `no-store` | sim |

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
