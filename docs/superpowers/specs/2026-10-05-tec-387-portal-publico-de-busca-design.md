# TEC-387 — Buscar e filtrar imóveis no portal do cliente

**Status:** em desenho (05/10/2026)
**Card:** [TEC-387](https://eduardodurieuxlopes.atlassian.net/browse/TEC-387)
**Branch:** `feat/tec-387-portal-publico-de-busca`

## Perguntas bloqueantes da card, resolvidas antes do desenho

- **O portal substitui o widget de chat ou é canal adicional?** Canal adicional, página própria. O widget de chat (`/embed/chat`) continua existindo sem mudança nenhuma; o portal é uma tela nova, fora do grupo `(painel)` e fora do `embed/`.
- **O cliente precisa se identificar para buscar?** Não. Busca anônima, sem login — igual a qualquer portal imobiliário público.

## O que existe quando a card começa

- **A busca por filtro já existe, mas é interna.** `POST /api/v1/imoveis/busca` (`src/mobia/api/routes/imoveis.py:271`) resolve exatamente os filtros da RF-09 (operação, preço min/máx, tipo, quartos mín., vagas mín., bairro/zona) contra `buscar_com_relaxamento` (`domain/catalogo/relaxamento.py` → `domain/catalogo/busca.py`), mas exige `Permissao.BUSCAR_IMOVEIS` — concedida aos quatro papéis internos, nunca a um visitante anônimo.
- **`GET /api/v1/imoveis` não é a vitrine.** É a listagem de administração (`GERIR_CATALOGO`), com inativos e todos os campos — o próprio comentário do arquivo já registra essa distinção (D1 da TEC-197).
- **A exclusão do que não está `DISPONIVEL` é hardcoded no domínio** (`busca.py:224`, RN-08.4) e o schema de filtro não aceita `status` como parâmetro — ninguém, nem o endpoint interno, pode pedir imóvel vendido por essa porta. Isso vale de graça para o portal público também, sem precisar reafirmar a regra em lugar nenhum novo.
- **`operacao` é obrigatória no domínio, não só na borda.** `FiltroDeBusca.__post_init__` (`domain/catalogo/schemas.py:203`) levanta `ValueError` se a operação não estiver em `COLUNA_DE_PRECO` (só `VENDA` e `ALUGUEL`): é ela que escolhe qual coluna de preço comparar, porque o imóvel tem `preco_venda` e `preco_aluguel` e a faixa que o cliente pede não diz de qual universo é.
- **Existe precedente de rota pública fora de `/api/v1`:** `GET /widget/aparencia` (`api/routes/aparencia_do_widget.py`) é lida pelo servidor do Next antes de qualquer visitante se identificar, sem `Depends(Exige(...))` nenhum, registrada em `ROTAS_PUBLICAS` (`api/autorizacao.py`) com a razão escrita. É o molde deste desenho.
- **`test_as_rotas_de_auth_sao_as_unicas_publicas_da_api_v1`** (`tests/unit/test_autorizacao_em_toda_rota.py:114`) afirma que as únicas rotas públicas sob `/api/v1/` são as quatro de `auth`. É uma trava deliberada contra rota de negócio virar pública sem ninguém perceber — e é exatamente por isso que o endpoint novo **não fica sob `/api/v1`**.
- **O rate limit por IP já cobre qualquer rota HTTP nova**, automaticamente: `RateLimitPorIP` é middleware global (`api/middleware.py`), 100 req/min/IP por padrão, sem precisar de nada específico para esta rota.
- **`CardDeImovel` (frontend) já é o card passivo que a vitrine precisa.** Sem os props opcionais de reação (TEC-350), ele é só exibição — título, bairro, preço, quartos, vagas, foto com placeholder quando nula (RN-FE-18.2). `ImovelCard.imovelDe()` (`frontend/src/lib/imovel.ts`) só exige `id, titulo, bairro, precoCentavos, quartos, vagas, areaUtilM2`; os outros quatro campos (`condominioCentavos, diferencial, foto, url`) toleram nulo.

## D1 — Endpoint novo, público, fora de `/api/v1`, reaproveitando a busca interna sem mudança nenhuma no domínio

`GET /portal/imoveis`, em módulo próprio `src/mobia/api/routes/portal.py` (mesmo molde de `aparencia_do_widget.py`): sem prefixo de router, caminho completo no decorator, sem `Depends(Exige(...))`, registrado em `ROTAS_PUBLICAS` com a razão escrita.

**Por que GET e não POST, divergindo do endpoint interno:** a tela é uma URL compartilhável/favoritável (filtros na query string), e só GET entra no Data Cache do Next (`revalidarEmSegundos`) sem o cuidado de correlação por usuário que `chamarApi` documenta para chamadas autenticadas — aqui não há usuário nenhum, então cachear é estritamente seguro.

**Por que um endpoint novo, e não relaxar `/busca`:** `BUSCAR_IMOVEIS` é a permissão interna que os quatro papéis têm porque buscar imóvel é tarefa de qualquer pessoa do time — inclusive o campo `consultaTexto`, hoje inerte mas pensado para ligar a um embedador pago no futuro (TEC-265). Tirar a guarda dali exporia esse campo ao público sem controle de custo por IP. Separar as rotas mantém a interna livre para crescer nessa direção sem decisão nenhuma sobre tráfego anônimo.

**`operacao` continua obrigatória no portal, e isso não é uma lacuna.** Todo portal imobiliário real (QuintoAndar, VivaReal) pede "Comprar" ou "Alugar" antes de mostrar resultado — nunca os dois misturados numa lista de preço comparável. O CA-01 ("sem nenhum filtro aplicado") descreve o estado inicial da TELA, não da requisição: a página carrega com uma operação pré-selecionada (`VENDA`, por ser o caso mais comum do catálogo hoje) e os outros filtros vazios, e é esse estado que gera a primeira chamada ao endpoint. Com isso, o portal reaproveita `FiltroDeBusca`/`buscar_com_relaxamento` **sem tocar uma linha do domínio** — zero risco sobre uma peça (`busca.py`) cuidadosamente calibrada (RN-09.6) e já testada.

**O que a rota faz:**

1. Valida `operacao` contra `COLUNA_DE_PRECO` (o mesmo `ValueError` que `FiltrosDaBusca._recusar_operacao_nao_buscavel` guarda no endpoint interno) e devolve 422 se for `AMBOS`.
2. Monta `FiltroDeBusca` com os mesmos seis campos do endpoint interno, **sem** `consulta_texto` (o portal não tem campo de busca livre — ver D3) e **sem** aceitar `status`.
3. Chama `buscar_com_relaxamento(session, filtro, consulta_texto=None, limite=MAX_CANDIDATOS)` — a mesma função, o mesmo relaxamento da RN-09.3, zero código de busca novo.
4. Devolve o mesmo formato de corpo que `/busca` (`itens`, `totalCandidatos`, `relaxamentoAplicado`, …), via uma função `payload_da_busca(resultado)` extraída de `imoveis.py` e reaproveitada pelas duas rotas — a serialização HTTP é a mesma, só a guarda muda.

## D2 — Paginação fica fora desta card

A card deixa "paginação/quantidade por página" como pergunta não bloqueante. `buscar()` tem um teto fixo de `MAX_CANDIDATOS=10` (RN-09.2) e nenhum parâmetro de offset — foi desenhada para o agente ("10 candidatos, 3 chegam ao lead"), não para navegação de catálogo. Estender `busca.py` para paginação arrisca uma peça compartilhada com o agente por um requisito que a própria card não exige. **Decisão: a primeira versão do portal mostra até 10 imóveis, sem paginação**, com uma nota explícita na tela ("mostrando os N mais relevantes de totalCandidatos") quando `totalCandidatos > itens.length`. Paginação de verdade é outra card, se o volume justificar.

## D3 — Sem texto livre nesta card

Pergunta não bloqueante da card. `consultaTexto` já existe no endpoint interno e está inerte (sem embedador injetado) — ligar busca semântica ao portal público é decisão de custo (chamada paga por caractere) que esta card não pede resolver. O portal só expõe os filtros estruturados.

## D4 — Resposta da API não muda de formato para caber no card

O card de UI (`CardDeImovel`) tolera os quatro campos que a busca não tem (`condominioCentavos`, `diferencial`, `foto`, `url` ficam `null`) — então a tela usa o mesmo item que `/busca` já devolve, só renomeando `preco` → `precoCentavos` no mapeamento do frontend. Sem mudança de contrato no backend, sem campo novo.

## D5 — Rota pública nova, no frontend, fora de `(painel)` e fora de `embed/`

`frontend/src/app/busca/page.tsx` — Server Component pública, sem `exigirPermissao`/`quemSou`, no molde de `embed/chat/page.tsx`. Lê os filtros da `searchParams` da própria URL (shareável/favoritável), chama `buscarVitrinePublica(filtros)` (novo arquivo `frontend/src/lib/servidor/vitrinePublica.ts`, via `chamarApi` **sem** `acesso` — o mesmo padrão que `buscarAparencia` já usa) e desenha um formulário de filtro (`FormularioDeBuscaPublica`, client component que atualiza a query string) + grade de `CardDeImovel`.

**Por que um arquivo novo e não acrescentar em `lib/servidor/imoveis.ts`:** aquele arquivo é só chamadas que levam `acesso` (token de sessão); misturar uma função pública lá created risco de alguém copiar o padrão errado para um contexto autenticado por engano.

## Critérios de aceite

| cenário | como é exercitado |
| --- | --- |
| CA-01 — sem filtro, lista imóveis ativos | integração: `GET /portal/imoveis?operacao=VENDA` sem mais nada, contra imóveis semeados `DISPONIVEL` |
| CA-02 — filtro combinado só casa compatíveis | integração: os seis filtros juntos, igual à suíte de `/busca` |
| CA-03 — sem resultado mostra mensagem, não lista vazia muda | componente: `itens.length === 0` renderiza o texto; a API já devolve `itens: []` |
| CA-04 — imóvel indisponível não aparece | já garantido por `busca.py:224` (RN-08.4), sem mudança |

## Lacunas declaradas

- **L1 — Paginação fica para outra card** (D2).
- **L2 — Busca por texto livre fica para outra card** (D3).
- **L3 — O catálogo é de uma cidade só.** `FiltroDeBusca` não tem filtro de cidade (herdado do endpoint interno) — inócuo hoje pelo mesmo motivo que já vale lá.
- **L4 — Métrica de sucesso não definida pela card.** Sugestões da própria card (nº de buscas, taxa sem resultado, filtros mais usados) ficam fora desta implementação; nenhum evento novo de auditoria/métrica é emitido.
