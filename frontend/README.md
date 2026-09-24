# Painel de funil (TEC-190)

O dashboard da gerente comercial: as seis etapas do funil da RN-17.2 com
conversão entre elas, os indicadores da RN-17.1 e os cinco filtros da
RN-17.3. Consome `GET /api/v1/metricas/funil` do FastAPI.

## Rodar em desenvolvimento

O backend precisa estar de pé, com `CATALOGO_ADMIN_TOKEN` configurado:

```bash
cd ..
docker compose up -d
./.venv/Scripts/python.exe -m alembic upgrade head
CATALOGO_ADMIN_TOKEN=local ./.venv/Scripts/python.exe -m uvicorn mobia.app.main:app --port 8000
```

Noutro terminal:

```bash
MOBIA_API_BASE=http://localhost:8000 MOBIA_ADMIN_TOKEN=local npm run dev
```

## As variáveis, e por que nenhuma delas é `NEXT_PUBLIC_`

| variável | onde é lida | obrigatória |
| --- | --- | --- |
| `MOBIA_API_BASE` | servidor Next, ao montar a URL do FastAPI | não (`http://localhost:8000`) |
| `MOBIA_ADMIN_TOKEN` | servidor Next, no header `X-Admin-Token` | sim, na prática — sem ela o backend responde 403 |
| `MOBIA_ORIGEM_DO_PAINEL` | proxy `/bff/*`, na checagem de `Origin` | só atrás de proxy — ver abaixo |

**`MOBIA_ADMIN_TOKEN` nunca chega ao navegador, e desde a TEC-302 isso é
verificado em vez de combinado.** É o token de admin do backend inteiro — quem
o tem lê o catálogo, o cadastro de corretores e este painel. Prefixá-lo com
`NEXT_PUBLIC_` o embutiria no bundle de cliente, entregando-o a qualquer pessoa
que abrisse o painel.

**Dois gates guardam isso, e eles pegam enganos diferentes:**

| engano | quem reprova |
| --- | --- |
| importar `lib/servidor/api.ts` de um componente de cliente | `npm run build`, pelo `import 'server-only'` |
| renomear a variável para `NEXT_PUBLIC_MOBIA_ADMIN_TOKEN` | `npm run verificar:bundle` |

```bash
MOBIA_ADMIN_TOKEN=sentinela-com-16-ou-mais npm run build
MOBIA_ADMIN_TOKEN=sentinela-com-16-ou-mais npm run verificar:bundle
```

A varredura procura o valor de `MOBIA_ADMIN_TOKEN` em tudo que está sob
`.next/static` — o que o navegador de fato baixa. Ela **reprova** se a variável
não estiver setada, em vez de pular: verificação que pula em silêncio é
verificação que ninguém nota ter parado de rodar. No CI a sentinela é definida
uma vez, no nível do job, porque duas cópias divergentes fariam a varredura
passar sem ter procurado nada.

**O que nenhum dos dois pega:** o token passado como prop de um Server
Component para um Client Component. Ele iria no payload RSC do HTML, que não é
arquivo estático, e não dispara o `server-only` porque o módulo continua sendo
importado só do servidor.

## Os dois caminhos até a API

Toda chamada autenticada sai do servidor, por um de dois caminhos, e os dois
passam pela mesma porta (`lib/servidor/api.ts`), que é o único lugar do projeto
que lê o token:

| caminho | quem usa | cache | `X-Request-Id` |
| --- | --- | --- | --- |
| Server Component → `buscarFunil` | o painel de funil | `revalidate: 60` | **não** |
| Route Handler `/bff/[...rota]` | fundação para TEC-309 e TEC-312 | `no-store` | sim |

**O painel não passa pelo `/bff/*`, e isso é deliberado.** Um Server Component
chamando o próprio Route Handler custaria um round-trip HTTP do processo para
ele mesmo e perderia o `revalidate: 60`, que é o que faz N navegadores com o
painel aberto virarem **uma** chamada por minuto ao FastAPI. Migrar o painel,
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

## O proxy `/bff/*` não autentica ninguém

A checagem de `Origin` é defesa de **CSRF**: ela vale porque quem escreve aquele
header é o navegador. `curl` não manda `Origin` nenhum, e um `GET` sem `Origin` é
aceito — senão navegação e prefetch legítimos quebrariam, porque o navegador
também não o manda em requisição de mesma origem com método seguro.

Então **quem alcança o servidor Next lê o funil**. Não é regressão: esse mesmo
alguém já lia o funil pedindo o HTML do painel, que também não autentica. O que
muda é a conveniência. O que contém o estrago é a allowlist de uma entrada só
(`GET /api/v1/metricas/funil`), uma leitura agregada sem dado pessoal de lead.

**Enquanto a TEC-309 não existir, este servidor não pode ficar exposto na
internet.**

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
