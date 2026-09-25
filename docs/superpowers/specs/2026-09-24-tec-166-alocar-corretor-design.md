# TEC-166 — Alocar o corretor por especialidade e região

**Status:** desenho aprovado em conversa, aguardando revisão do texto
**Card:** [TEC-166](https://eduardodurieuxlopes.atlassian.net/browse/TEC-166) — épico TEC-164
**Branch:** `feat/tec-166-alocar-corretor`
**Origem:** RF-11, RN-11.2; RN-07.4 (SRS v1.0).

## Objetivo

Decidir **qual corretor atende** um lead num dado dia — pela especialidade e pela região, respeitando a capacidade diária de visitas, com o generalista de plantão como rede — e gravar **por que** aquele corretor foi escolhido, para a gerente conseguir ler a decisão depois.

## O que esta card não entrega, dito antes

**Nada muda na conversa.** Como nas TEC-165, TEC-167 e TEC-168: o turno não reconhece pedido de horário, não oferece janela e não reserva nada. Esta card entrega a alocação e a liga ao cálculo de janelas e à reserva; nenhum caminho de produção chama nenhum dos três ainda.

**Fora, e continuam esperando:**

- `destinatario_do_handoff` (`domain/notificacao/destinatario.py`) segue escolhendo o plantão mais antigo. A RN-16.2 E-01 diz que a escolha "sai daqui" quando a TEC-166 chegar — ela chega, mas trocar o critério do handoff não entra nesta card.
- `handoffs.corretor_id` continua sem ninguém que o escreva (RN-16.1 E-03).
- O filtro `corretorId` do funil (TEC-190) continua recusado com 422, porque ele junta por `handoffs.corretor_id`.

Os comentários e mensagens que hoje dizem "espera a TEC-166" nesses lugares são reescritos para dizer o que de fato ainda falta — senão passam a mentir no dia do merge.

**Fora por decisão da card:** balanceamento de carga por desempenho ou ranking.

## D1 — O critério do lead

```python
@dataclass(frozen=True)
class CriterioDoLead:
    especialidade: Especialidade | None
    regiao: str | None
```

`criterio_de(qualificacao: LeadQualification) -> CriterioDoLead`:

- `intencao` COMPRA e ALUGUEL viram a especialidade de mesmo nome, por igualdade de string — é o que a TEC-196 D3 preparou ao grafar os dois vocabulários idênticos.
- `intencao` INVESTIMENTO passa por `especialidade_de(ticket_investimento_centavos)` (RN-07.4, `>=` R$ 1.000.000 → `INVESTIMENTO_ALTO_TICKET`). **Sem ticket, fica `INVESTIMENTO`**: não há como afirmar alto ticket sem o número.
- Qualquer outra intenção (INDEFINIDA, VENDER_IMOVEL, SUPORTE_CONTRATO, FORA_DE_ESCOPO) ou intenção nula → `especialidade = None`.
- `regiao` vem de `LeadQualification.regiao` como está (já canônica por `normalizar_regiao`); vazia vira `None`.

Critério com `especialidade` ou `regiao` nulos **não tem match exato**: a card pede especialidade *e* região.

## D2 — O casamento de região

Uma região do lead casa uma região do corretor quando:

1. `normalizar_regiao(lead) == normalizar_regiao(corretor)` — a do corretor foi gravada só com `dobrar()` (TEC-196 D4); passar as duas pela mesma função tira "região do" e "perto da" dos dois lados; **ou**
2. `zonas_de([lead])` e `zonas_de([corretor])` têm uma zona em comum — "zona sul" casa "sul".

**Bairro não vira zona.** Um lead em "moema" não casa um corretor de "zona sul": não existe mapeamento bairro→zona no repo (TEC-196 L4), e derivá-lo do catálogo usaria um dado nulo e sujeito a divergência. Decidido em conversa em 24/09/2026; o custo é que o lead de bairro só casa corretor que cadastrou o bairro, e os demais caem no plantão.

## D3 — A alocação é uma função pura

`domain/agendamento/alocacao.py`, sem I/O:

```python
def alocar(
    *,
    criterio: CriterioDoLead,
    corretores: Sequence[Corretor],
    visitas_na_data: Mapping[uuid.UUID, int],
) -> list[Alocacao]: ...

@dataclass(frozen=True)
class Alocacao:
    corretor: Corretor
    motivo: MotivoDaAlocacao
```

Devolve os **candidatos em ordem de preferência**, não um só — quem chama precisa descer para o próximo quando o primeiro não tem horário livre (D5):

1. Ativos com a especialidade do critério **e** região casada (D2), com capacidade sobrando na data → motivo `MATCH_EXATO`.
2. Depois, os plantões ativos com capacidade sobrando, que não estejam já na lista → motivo `SEM_MATCH` se **nenhum** corretor ativo tem match exato, ou `MATCH_SEM_CAPACIDADE` se existe algum match exato ativo — com ou sem capacidade na data. O motivo do plantão depende só de existir match, não de o match ter caído: se o plantão acabou escolhido havendo match, é porque o match não pôde naquele dia, por capacidade (aqui) ou por falta de horário livre (D5).

"Capacidade sobrando" é `visitas_na_data.get(id, 0) < capacidade_diaria`. Lista vazia é resposta válida: ninguém pode naquela data.

**Desempate: `criado_em` mais antigo primeiro**, nos dois grupos — o mesmo critério que `destinatario_do_handoff` já usa para plantão. Concentra no primeiro até ele esgotar a capacidade do dia; distribuir carga é o que a card põe fora.

**Alto ticket.** Com especialidade `INVESTIMENTO_ALTO_TICKET`, só quem tem essa especialidade conta como match exato — um corretor só de `INVESTIMENTO` não entra no grupo 1. Sem especialista, **cai no plantão com `SEM_MATCH`**, pela regra geral da RN-11.2. O "apenas especialistas são considerados" do Gherkin é lido como regra do match, não como proibição do fallback: um investidor de R$ 1,5 milhão sem especialista cadastrado é atendido pelo plantão, não fica sem ninguém.

## D4 — Motivo como vocabulário fechado

`MotivoDaAlocacao(StrEnum)` em `domain/agendamento/vocabulario.py` — módulo puro, no padrão de `handoff/vocabulario.py`:

| valor | quando |
| --- | --- |
| `MATCH_EXATO` | especialidade e região casaram |
| `SEM_MATCH` | nenhum corretor ativo com especialidade e região; foi o plantão |
| `MATCH_SEM_CAPACIDADE` | havia match exato, mas nenhum pôde naquele dia — sem capacidade ou sem horário livre (D5); foi o plantão |

Categoria, não texto livre. O que a gerente lê é o motivo **junto** do corretor e do lead — o texto se monta na tela que existir (E8), a partir do dado; texto gravado envelhece quando a regra muda.

## D5 — Janelas com corretor

`janelas_alocadas` em `janelas.py`, ao lado de `propor_janelas_do_corretor`:

```python
async def janelas_alocadas(
    *,
    criterio: CriterioDoLead,
    corretores: Sequence[Corretor],
    agenda: AgendaDoCorretor,
    visitas: ContadorDeVisitas,
    agora: datetime,
    ate: datetime,
    tipo: TipoDeCompromisso,
) -> list[JanelaAlocada]: ...

@dataclass(frozen=True)
class JanelaAlocada:
    janela: Intervalo
    corretor_id: uuid.UUID
    motivo: MotivoDaAlocacao
```

Para cada data local (`fuso_de_envio`, America/Sao_Paulo) entre `agora` e `ate`, em ordem:

1. `alocar` com as visitas daquela data.
2. Desce pelos candidatos até um ter janela livre naquele dia — `propor_janelas` com `de`/`ate` limitados ao dia e a jornada daquele corretor; fica a primeira janela, com o motivo que `alocar` deu àquele candidato.
3. Para quando juntar 3 janelas.

Um segundo match exato escolhido porque o primeiro não tinha horário continua `MATCH_EXATO` — ele casou. Um plantão escolhido porque nenhum match tinha horário já vem de `alocar` como `MATCH_SEM_CAPACIDADE` (D3).

Uma janela por dia preserva o espalhamento que a TEC-165 já fazia. Nenhuma data com candidato e horário → lista vazia, que é onde a TEC-169 (lista de espera) começa.

**Capacidade só barra visita.** Para `REUNIAO_REMOTA`, `visitas_na_data` entra vazio: reunião remota nunca é barrada por capacidade (decidido em conversa em 24/09/2026 — o SRS diz "máximo de visitas/dia").

## D6 — Contar as visitas

Um port **próprio**, ao lado de `AgendaDoCorretor`, e não um método a mais nele:

```python
class ContadorDeVisitas(Protocol):
    async def visitas_por_dia(
        self, corretor_ids: Sequence[uuid.UUID], *, de: date, ate: date, agora: datetime
    ) -> dict[tuple[uuid.UUID, date], int]: ...
```

Separado porque `AgendaDoCorretor` já tem fakes nos testes da TEC-165 e da TEC-167 que só implementam `ocupados`; um método a mais no mesmo Protocol reprovaria o mypy em todos eles sem que nada neles tivesse mudado. `AgendaPostgres` implementa os dois.

As datas são **datas locais inteiras**, não o intervalo `[agora, ate]`: a visita das 9h de hoje gasta capacidade de hoje mesmo quando a busca começa às 14h. E a vida da reserva é avaliada em `agora`, não no começo do dia.

`AgendaPostgres` conta linhas `tipo = VISITA_PRESENCIAL` com `status = CONFIRMADO`, ou `RESERVADO` com `reservado_ate > agora` — **o mesmo predicado de vida de `ocupados`**, extraído para uma função só, para a capacidade e a disponibilidade nunca discordarem sobre uma reserva vencida. A data é a de `inicio` convertido para `fuso_de_envio` no SQL (`timezone(:fuso, inicio)`), não a data UTC: uma visita às 22h30 de quinta em São Paulo é de quinta.

Uma consulta para todos os corretores e o horizonte inteiro, não uma por corretor por dia.

## D7 — O motivo fica no agendamento

Migration `0045`, `agendamentos.motivo_da_alocacao String(24) NOT NULL` com `CHECK` nos três valores (String + CHECK, a regra desde a 0016).

`NOT NULL` sem valor padrão é seguro porque **nenhum caminho de produção grava em `agendamentos`** hoje (D5 da TEC-168). A migration não inventa motivo para linha antiga.

`reservar` ganha `motivo: MotivoDaAlocacao` obrigatório; `reservar_ou_alternativas` também, e o repassa. **As alternativas continuam no mesmo corretor** (o que a E-02 da TEC-168 descreve): o conflito é sobre um slot dele, e realocar no meio da disputa trocaria o corretor sem que nada na alocação tivesse mudado.

Consequência aceita: uma alocação que só propôs janelas e nunca reservou não deixa rastro. Decidido em conversa em 24/09/2026 contra uma tabela `alocacoes` própria.

## Testes

**Unitários** (sem banco):

- `alocar`, um por cenário do Gherkin: match exato escolhido com `MATCH_EXATO`; alto ticket só considera `INVESTIMENTO_ALTO_TICKET`; sem match → plantão com `SEM_MATCH`; capacidade esgotada exclui na data.
- As bordas: plantão também esgotado → lista vazia; lead sem região; intenção INDEFINIDA; alto ticket sem especialista → plantão; empate por `criado_em`; "zona sul" × "sul"; "moema" × "zona sul" não casa; corretor inativo nunca entra; plantão que também tem match aparece uma vez só.
- `criterio_de`: as quatro intenções, investimento sem ticket, limiar exato de R$ 1.000.000.
- `janelas_alocadas` com agenda fake: quinta esgotada vai para o próximo candidato; match sem horário livre cai no plantão com `MATCH_SEM_CAPACIDADE`; reunião remota ignora capacidade; no máximo 3, uma por dia.

**Integração** (Postgres):

- `visitas_por_dia`: conta confirmada e reserva viva; ignora reserva vencida, expirada e reunião remota; visita às 23h30 local cai na data local, não na UTC.
- `reservar` grava o motivo; o `CHECK` recusa motivo fora do vocabulário.

## Emendas ao SRS

Nenhuma. As decisões D2 (bairro não vira zona), D3 (desempate e fallback do alto ticket) e D5 (capacidade só de visita) interpretam a RN-11.2 e a RN-07.4 sem contrariá-las; ficam registradas aqui e no comentário da card.
