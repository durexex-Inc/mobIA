# TEC-196 — Cadastrar corretores com especialidade, região e capacidade

**Status:** desenhado em 2026-09-12.

**Card:** [TEC-196](https://eduardodurieuxlopes.atlassian.net/browse/TEC-196) — História, Must (MoSCoW), prioridade Highest. Origem: RF-19, RN-19.2 (SRS v1.0). Épico [TEC-189](https://eduardodurieuxlopes.atlassian.net/browse/TEC-189).

**A história:** *"Como administrador da imobiliária, quero cadastrar os corretores com especialidade, região e agenda, para que o sistema saiba a quem encaminhar cada lead."*

**Raiz, sem dependências.** Destrava TEC-166 (alocação por especialidade e região) e — descoberto em 12/09/2026, não declarado na card — **TEC-177**, a notificação ao corretor.

## Por que ela entrou na frente da TEC-177

A TEC-177 foi levantada em 12/09/2026, logo depois de a TEC-175 entregar o resumo, e parou antes do desenho. A regra dela diz *"o corretor **designado** é notificado"* e não há designado nenhum: não existe tabela `corretores`, o `corretor_id` de `handoffs` nasceu nulável e sem FK pela emenda E-02 da RN-16.1, e **nada escreve nessa coluna**.

Não é detalhe que se contorna com um destinatário fixo em configuração: sem a entidade, a TEC-177 não tem endereço, nem telefone, nem regra de quem recebe. O bloqueio ficou registrado no comentário da TEC-177, junto com o link `TEC-196 blocks TEC-177` no Jira.

Esta card também resolve o caso que a TEC-177 teria de inventar sozinha: o **generalista de plantão**, que recebe o que não tem match.

## O estado de hoje

Não existe `corretores`, não existe `usuarios`, não existe `agendamentos`. O que existe e importa:

| Peça | Estado | Consequência para esta card |
|---|---|---|
| `handoffs.corretor_id` | coluna nulável, **sem FK**, sem escritor | a FK entra aqui (D5) |
| `exigir_admin` (`api/deps.py`) | token compartilhado, sem papel | é a guarda possível hoje (D8) |
| `Intencao` (`agente/schemas.py`) | `COMPRA`, `ALUGUEL`, `INVESTIMENTO`, … | a grafia das especialidades vem daí (D3) |
| `dobrar()` (`domain/texto.py`) | normaliza texto para busca; produz `bairro_busca` | normaliza as regiões (D4) |
| tabela `agendamentos` | **não existe** (TEC-170) | o `409` do SRS não é implementável (L2) |
| papéis e usuários | **não existem** (TEC-201) | o 4º cenário do Gherkin não é exercitável (L1) |

## Decisões

### D1 — O contato do corretor fica em claro, e isso contraria o SRS de propósito

A linha 691 do SRS diz que campos marcados **DP** estão sujeitos a *"criptografia em repouso"*, e `nome`, `email` e `telefone` do Corretor estão marcados. Esta card não os cifra.

**Primeiro, porque o repo não faz isso nem com o lead.** `messages.sender_external_id` e `messages.conversation_key` guardam o telefone do lead e são `String`, não `LargeBinary`. O que este sistema cifra é **conteúdo** — `text_body`, `raw_payload`, `conversation_summaries.resumo`, `handoffs.resumo` —, nunca **identificador**. Cifrar o contato do corretor instituiria uma terceira política, mais estrita para o funcionário que para o titular cujos dados a LGPD protege.

**Segundo, porque cifrar mataria a única defesa contra corretor duplicado.** O comentário de `infra/crypto.py` é explícito: o nonce novo a cada chamada faz com que *"busca por igualdade sobre conteúdo deixe de existir. É intencional"*. Com `email` cifrado não existe `UNIQUE(email)` — duas linhas do mesmo corretor passariam, e a notificação da TEC-177 sairia em duplicata sem ninguém entender por quê.

A alternativa que preservaria as duas coisas — cifrar e guardar um HMAC determinístico numa coluna `UNIQUE` — foi descartada: acrescenta um segredo ao ciclo de vida e produz um identificável estável, que é exatamente o que a cifra existia para evitar.

**Vira emenda ao modelo Corretor da seção 5.**

### D2 — O horário é uma janela só, e não `jsonb` por dia da semana

O modelo da seção 5 pede `horario_trabalho jsonb`, *"janelas por dia da semana"*. O Gherkin da card exercita outra coisa: *"um corretor com jornada de 9h às 18h"* — uma janela, sem dia.

Escolhida a janela: `horario_inicio` e `horario_fim`, inteiros de hora. **É a forma que o repo já usa** — `followup_horario_inicio: int = 9` e `followup_horario_fim: int = 20` em `app/config.py` representam janela de atendimento exatamente assim, e `outbound/horario.py` consome nesse formato.

Consequência declarada, porque ela vai cobrar: **sábado meio período não cabe.** O PR-06 do SRS já diz que o corretor atende *"de segunda a sábado, 9h–19h"*, e quando a agenda real aparecer isso é migration e mudança em quem consome. A card é de cadastro e o critério de aceite dela é de uma janela; alargar agora seria construir para um consumidor (TEC-170) que ainda não existe e não disse o que precisa.

**Vira emenda ao modelo Corretor da seção 5.**

### D3 — As especialidades reusam a grafia de `Intencao`, sem reusar o enum

Três das quatro especialidades da card — `COMPRA`, `ALUGUEL`, `INVESTIMENTO` — são membros literais de `Intencao`. A quarta, `INVESTIMENTO_ALTO_TICKET`, não tem correspondente: é segmentação de ticket, não intenção de conversa.

Enum próprio, portanto, mas com os três valores **grafados idênticos**. É o que deixa a TEC-166 mapear intenção do lead para especialidade do corretor por igualdade de string, sem tabela de tradução — e tabela de tradução seria um segundo lugar para a mesma verdade divergir, que é o defeito que a TEC-146 gastou uma card inteira consertando.

Não reusar o enum em si porque os conjuntos não coincidem: `Intencao` tem `VENDER_IMOVEL`, `SUPORTE_CONTRATO` e `INDEFINIDA`, que não são especialidade de ninguém, e acrescentar `INVESTIMENTO_ALTO_TICKET` a `Intencao` mudaria o schema estrito da chamada ao modelo — a docstring de lá avisa que *"acrescentar um membro aqui muda o conjunto de valores que o modelo pode devolver"*.

### D4 — As regiões são normalizadas com `dobrar()` na escrita

`dobrar()` (`domain/texto.py`) é a mesma função que produz `bairro_busca` no catálogo. Sem ela, "Zona Sul" e "zona sul" viram duas regiões diferentes, e a alocação da TEC-166 falha por acidente de digitação em vez de por regra.

Uma coluna, não duas: `bairro_busca` existe ao lado de `bairro` porque a busca precisa das duas formas — a original para exibir, a dobrada para casar. Aqui não há quem exiba (é a E8) nem quem case (é a TEC-166), e uma segunda coluna sem leitor seria o peso morto que a D1 da TEC-174 recusou.

### D5 — A FK de `handoffs.corretor_id` entra nesta card

A emenda E-02 da RN-16.1 prometeu por escrito: *"a TEC-196 acrescenta a restrição quando criar a tabela"*. Esta é a card, e a restrição entra.

`ON DELETE RESTRICT`, que é o default: corretor se desativa, não se apaga (D6), então a cascata não tem caso de uso e apagar por engano deve doer.

### D6 — Desativar é `ativo = false`, e não existe rota DELETE

A card manda: *"desativar um corretor não apaga o histórico dele nem os leads já atribuídos"*. Apagar a linha quebraria a FK que a D5 acabou de criar, e a `RESTRICT` recusaria — o `DELETE` existiria só para devolver erro.

### D7 — Pode haver mais de um plantão, e escolher entre eles não é desta card

A card diz *"é possível marcar **um** corretor como generalista de plantão"*. Ela não diz "um só", e forçar unicidade com índice parcial `WHERE plantao AND ativo` inventaria uma regra que ninguém escreveu — e que quebraria uma imobiliária com plantão por turno.

Declarado: **com dois plantões ativos, quem recebe o lead sem match é problema da TEC-166**, e a TEC-177 vai precisar da mesma resposta.

### D8 — O acesso é o `exigir_admin` de hoje, e isso estende a um dado pessoal uma guarda que foi aceita por não haver dado pessoal

A card pede *"acesso restrito ao papel `ADMIN`"*. Não há papéis: a TEC-201 é que os traz. A guarda possível é o `exigir_admin` de `api/deps.py`, o mesmo header `X-Admin-Token` do catálogo.

**A diferença em relação ao catálogo é material e precisa estar escrita.** A emenda E-01 da TEC-156 aceitou o token compartilhado com uma justificativa explícita: *"aceito porque o objeto é o catálogo de imóveis e **não dado pessoal**, ao contrário da reativação de opt-out da TEC-182, que por isso ficou sem rota HTTP"*.

Aqui o objeto **é** dado pessoal — nome, e-mail e telefone de pessoas reais. Reusar o token estende a um dado pessoal a guarda que foi aceita justamente por não haver dado pessoal em jogo, e o repo já escolheu o caminho mais estrito uma vez, quando a TEC-182 ficou sem rota.

Decisão tomada com o Eduardo em 12/09/2026: **entra com o token, e a exposição fica declarada** na emenda, no comentário da card e aqui. **Consequência prática, sem rodeio: quem tem `CATALOGO_ADMIN_TOKEN` passa a poder ler nome, e-mail e telefone de todos os corretores — um segredo sem expiração, sem rotação e sem papel.** É o argumento escrito para a TEC-201 vir antes do que viria.

Como no catálogo, **com a variável vazia o router não é registrado** e a rota devolve `404`: rota que não existe não pode ser exposta por engano de configuração.

### D9 — `creci` entra, mesmo sem leitor

A card não o lista nas regras; o modelo da seção 5 o tem, opcional. Entra porque o escritor existe — é o administrador preenchendo o cadastro — e porque CRECI é o registro profissional que identifica um corretor de imóveis no Brasil: um cadastro de corretores sem ele é um cadastro incompleto por omissão, não por escopo.

Isto **não** contradiz a D1 da TEC-174, que recusou coluna nulável sem escritor: aquela recusa era sobre colunas que nenhum código preenchia. Esta tem quem a preencha desde o primeiro `POST`.

## Emendas ao SRS

Entram como item aninhado abaixo da regra que alteram, sem reescrever o texto de 22/08/2026.

- **Seção 5, modelo Corretor** — `nome`, `email` e `telefone` ficam **em claro**, contra a regra de criptografia em repouso da linha 691, pelo precedente do telefone do lead e pela perda do `UNIQUE(email)` (D1).
- **Seção 5, modelo Corretor** — `horario_trabalho jsonb` vira `horario_inicio` e `horario_fim`, inteiros de hora, no formato que `app/config.py` já usa (D2).
- **RN-19.5** — o papel `ADMIN` é, enquanto a TEC-201 não existir, o header `X-Admin-Token` do catálogo, **agora cobrindo dado pessoal** (D8).
- **RN-16.1, complemento à E-02** — a FK de `handoffs.corretor_id` passa a existir; a ausência declarada como "provisória por construção" terminou (D5).

## Os cenários do Gherkin

| Cenário da card | Como fica |
|---|---|
| Cadastrar corretor com especialidade e região | exercitado |
| Horário de trabalho alimenta a proposta de agenda | exercitado **até onde dá** — ver L3 |
| Desativar corretor preserva histórico | exercitado, com um handoff apontando para o corretor |
| Acesso restrito ao administrador | **não exercitado** — ver L1 |

## Lacunas declaradas

### L1 — O cenário de papéis não é exercitável

*"Um usuário com papel de corretor tenta abrir a tela e o acesso é negado."* Não há usuários, não há papéis e não há tela. O que existe é token ou não-token, e isso é o que o teste exercita. A TEC-201 traz o resto.

### L2 — O `409` do SRS não é implementável

A seção 6 do SRS especifica *"409 ao inativar corretor com agendamento futuro — exige reatribuição antes"*. Não existe tabela de agendamentos: é a TEC-170. A desativação desta card não tem como consultar o que não existe, e o `409` entra junto com os agendamentos.

### L3 — O segundo cenário só é exercitável do lado do cadastro

*"Quando janelas de agendamento são propostas para ele, nenhuma janela é oferecida após as 18h."* Quem propõe janelas é a TEC-170, que não existe. O que esta card exercita é que o horário é gravado e lido de volta íntegro — a asserção sobre a proposta fica para quem a construir.

### L4 — "Zona sul" não é vocabulário do catálogo

O Gherkin cadastra *"atuação na zona sul"*. O catálogo guarda **bairros** (`bairro`, `bairro_busca`), e "zona sul" não é um bairro. Esta card grava o que o administrador digitar, dobrado; **casar região de corretor com bairro de imóvel vai exigir um mapeamento zona→bairros que esta card não entrega**, e a TEC-166 precisa saber disso antes de começar.

## Fora de escopo

Ranking de corretores por desempenho e balanceamento automático de carga (exclusão da própria card). Alocação por especialidade e região (TEC-166). Usuários, papéis e JWT (TEC-201). Agendamentos e a proposta de janelas (TEC-170). A notificação ao corretor (TEC-177). A tela de administração (E8).
