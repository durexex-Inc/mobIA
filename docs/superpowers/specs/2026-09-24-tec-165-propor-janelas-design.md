# TEC-165 — O motor que propõe até 3 janelas de horário

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-165](https://eduardodurieuxlopes.atlassian.net/browse/TEC-165) — épico TEC-164
**Branch:** `feat/tec-165-propor-janelas`
**Origem:** RF-11, RN-11.1 (SRS v1.0); PR-06.

## Objetivo

Dado um corretor, o momento atual, um horizonte e o tipo de compromisso, devolver **até 3 janelas** em que uma visita (60 min) ou uma reunião remota (30 min) caberia: dentro da jornada do corretor e da janela da imobiliária (segunda a sábado, 9h às 19h), com pelo menos 3 horas de antecedência e sem sobrepor compromisso já existente do corretor, tudo no fuso `America/Sao_Paulo`.

## O que esta card não entrega, dito antes

**Nada disto aparece para o lead ainda.** O agente não oferece horário nenhum na conversa: não existe intenção de agendar no classificador, e oferecer um horário que o sistema não consegue gravar seria prometer o que ele não faz (o mesmo erro que a TEC-174 teve de desfazer no texto). A conversa entra quando houver o que fazer com a escolha do lead:

| falta | card |
| --- | --- |
| qual corretor atende | TEC-166 |
| "quinta de manhã" vira data | TEC-167 |
| gravar o agendamento, lock de 5 min, restrição de exclusão | TEC-168 |
| confirmação e notificação | TEC-170 |
| lista de espera sem vaga em 72h | TEC-169 |

**Não existe agenda gravada.** Não há tabela, modelo nem enum de agendamento no sistema — o SRS registra o mesmo na Emenda E-01 da RN-17.1 (TEC-190). Os compromissos que bloqueiam janelas entram por uma porta (D5) cuja implementação real nasce com a tabela da TEC-168. Esta card **não** cria a tabela: fazê-lo adiantaria decisões da TEC-168 (restrição de exclusão por intervalo, lock otimista) sem o resto dela, e um teste que grava numa tabela inventada para si mesmo é o que a Emenda E-01 da TEC-190 proíbe.

## D1 — Um módulo de domínio puro

`src/mobia/domain/agendamento/janelas.py`. Não toca banco, rede nem relógio: `agora` entra como parâmetro, que é o padrão do repo (não há `freezegun` nem abstração de relógio; os testes passam `datetime` literais com fuso).

- `TipoDeCompromisso(StrEnum)`: `VISITA_PRESENCIAL` e `REUNIAO_REMOTA` — os mesmos nomes do campo `tipo` do contrato `POST /api/v1/agendamentos` do SRS (6.4), para a TEC-168 não precisar traduzir.
- `Intervalo(inicio, fim)`: `dataclass(frozen=True)`, os dois com fuso, `inicio < fim`.
- `propor_janelas(*, agora, ate, jornada_inicio, jornada_fim, ocupados, tipo) -> list[Intervalo]`: de 0 a 3 janelas, ordenadas por início.

`datetime` sem fuso reprova com `ValueError`, como `dentro_da_janela_de_atendimento` já faz: um horário ingênuo é ambíguo exatamente no eixo que esta função existe para acertar.

## D2 — Onde uma janela pode cair

Uma janela candidata `[inicio, inicio + duração]` é válida se, e só se:

1. **Janela da imobiliária:** `dentro_da_janela_de_atendimento(inicio)` **e** `dentro_da_janela_de_atendimento(fim)`. É a função da TEC-285 (`domain/humano/deteccao.py`), que já é a fonte única de "segunda a sábado, das `atendimento_horario_inicio` às `atendimento_horario_fim`, no `followup_fuso`" — domingo como regra em código, horas de `Settings`, borda inclusiva no minuto (`fim=19` aceita 19:00). Reaproveitar em vez de reescrever é o que impede as duas janelas de divergirem; como a borda é inclusiva, uma visita das 18h às 19h cabe e uma das 18h30 às 19h30 não.
2. **Jornada do corretor:** no fuso local, `inicio >= jornada_inicio:00` e `fim <= jornada_fim:00`. São as colunas `Corretor.horario_inicio`/`horario_fim` (inteiros de hora). A janela efetiva é a **interseção** com o item 1: um corretor das 10h às 20h só recebe proposta das 10h às 19h. A jornada não tem dia da semana — lacuna já declarada no modelo e na Emenda E-02 da TEC-285 —, então os dias vêm só do item 1.
3. **Antecedência:** `inicio >= agora + 3h`.
4. **Sem conflito:** não sobrepõe nenhum intervalo de `ocupados`. Sobrepor é `a.inicio < b.fim and b.inicio < a.fim`: **encostar não é sobrepor**, e um compromisso das 10h às 11h deixa livre uma janela das 11h às 12h.
5. **Dentro do horizonte:** `fim <= ate`.

**Os inícios caem numa grade de 30 minutos** (:00 e :30, no fuso local), começando no primeiro ponto da grade em ou depois de `agora + 3h`. Sem grade, "agora + 3h" produziria inícios como 17h07; com grade de uma hora, uma reunião de 30 minutos ou uma janela logo após um compromisso que termina às 10h30 nunca seriam oferecidas.

## D3 — Quais 3, entre as válidas

**Espalhar por dia** (decidido no desenho, com o partido de dar escolha real de dia):

1. Percorre as válidas em ordem cronológica e pega a **primeira de cada dia local distinto**, até 3.
2. Se ficaram menos de 3 (poucos dias com vaga no horizonte), completa com as próximas válidas ainda não escolhidas, em ordem cronológica.
3. Devolve ordenado por início.

Terça às 14h, agenda livre, visita: `ter 17:00–18:00`, `qua 09:00–10:00`, `qui 09:00–10:00`.

## D4 — Constantes em código, não em `Settings`

`ANTECEDENCIA_MINIMA = 3h`, `DURACAO[VISITA_PRESENCIAL] = 60 min`, `DURACAO[REUNIAO_REMOTA] = 30 min`, `GRADE = 30 min`, `MAXIMO_DE_JANELAS = 3`. É o argumento da D4 da TEC-285: são regra do SRS (RN-11.1), não configuração de implantação, e uma constante com um único valor legal em `Settings` convida a ser mexida sem que o texto e a spec acompanhem.

O **horizonte** não é constante: `ate` vem de quem chama. A TEC-169 vai chamar com 72h para decidir a lista de espera (RN-11.5); esta card não escolhe por ela.

## D5 — A porta da agenda

```python
class AgendaDoCorretor(Protocol):
    async def ocupados(self, corretor_id: uuid.UUID, de: datetime, ate: datetime) -> list[Intervalo]: ...
```

E uma função fina, `propor_janelas_do_corretor(*, corretor, agenda, agora, ate, tipo)`, que busca `ocupados` na porta entre `agora` e `ate` e chama `propor_janelas` com `corretor.horario_inicio`/`horario_fim`. Ela existe para a costura ficar no lugar certo e com o nome certo quando a TEC-168 trouxer a implementação; nesta card o único implementador é o fake dos testes. **Nenhum código de produção a chama ainda** — dito aqui para ninguém procurar o chamador.

## Testes

Unitários, sobre `propor_janelas` (e um sobre a função da porta com agenda falsa). Todos com `agora` literal com fuso, e com a janela da imobiliária nos valores padrão de `Settings`.

Os cinco cenários Gherkin da card:

| cenário | como |
| --- | --- |
| propor três janelas livres | agenda vazia na próxima semana → 3 janelas, cada uma de 60 min |
| respeitar a antecedência mínima | terça 14h → nenhuma começa antes das 17h daquele dia |
| não oferecer fora da janela comercial | horizonte que cruza um domingo → nenhuma no domingo, nenhuma começa antes das 9h nem termina depois das 19h |
| compromisso existente bloqueia | quinta 10h–11h ocupado, horizonte só na quinta → nenhuma sobrepõe 10h–11h |
| reunião remota usa duração menor | `REUNIAO_REMOTA` → cada janela de 30 min |

Bordas: interseção com a jornada do corretor (10h–20h e 8h–12h); compromisso que encosta (fim 11h, janela 11h–12h aceita); visita 18h–19h aceita e 18h30–19h30 recusada; `agora` depois das 19h empurra para o dia seguinte; sábado à noite pula domingo e cai na segunda; `agora` fora da grade arredonda para cima; horizonte sem vaga → lista vazia; só um dia com vaga → as três saem dele (regra de completar); `datetime` sem fuso → `ValueError`.
