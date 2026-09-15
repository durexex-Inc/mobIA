# TEC-267 — Acento no texto que o agente envia ao lead

**Status:** desenho aprovado, implementação pendente
**Card:** [TEC-267](https://eduardodurieuxlopes.atlassian.net/browse/TEC-267) — Low, `divida-tecnica` + `produto`
**Branch:** `feat/tec-267-acento-na-fala-ao-lead`
**Levantada por:** [TEC-162](https://eduardodurieuxlopes.atlassian.net/browse/TEC-162), cuja D12 registrou que trocar a política seria card própria
**Dependências:** nenhuma

## Objetivo

Decidir se o texto que o lead recebe continua sem acento, e aplicar a decisão.

A resposta é **acentuar**, e a medição mudou a pergunta pelo caminho: a card apresenta três saídas, e a primeira delas — *"manter tudo sem acento, consistência preservada"* — **não existe**.

## A medição, e o que ela desfaz

Medido em 14/09/2026, sobre a `main` em `09e6a22`.

### O modelo já escreve acentuado, e nada o normaliza

Nenhum dos cinco prompts do sistema (`SISTEMA_DO_AGENTE`, `SISTEMA_DO_INVESTIDOR`, `SISTEMA_DA_DESAMBIGUACAO`, `SISTEMA_DA_REACAO`, `SISTEMA_DO_FOLLOWUP`) diz nada sobre acento — todos pedem apenas *"portugues do Brasil, em tom de conversa"*.

E o modelo acentua. Em `evals/relatorios/2026-08-31-tom-com-o-texto.md` há mais de vinte respostas reais voltadas ao lead, todas acentuadas: *"É ótima escolha"*, *"à vista"*, *"número"*, *"área"*.

Entre a resposta do modelo e o `outbound.send` **não há normalização nenhuma**. Os quatro usos de `unicodedata` no repositório normalizam outra coisa: `context/gatilhos.py` e `optout/deteccao.py` dobram a fala **de entrada** do lead para casar com palavras-gatilho; `texto.dobrar` dobra nome de bairro para casar com o catálogo; e `_sem_acento` em `followup/prosa.py` só decide se a abertura é "apenas saudação" — o texto devolvido ao lead é a string crua do modelo.

O repositório já sabia disso sem tirar a conclusão. A docstring de `dobrar()` registra que *"a TEC-248 mediu o modelo devolvendo `saude` COM acento e `butanta` SEM, na mesma execucao"*, e `followup/prosa.py` afirma como fato assente que *"o modelo escreve portugues acentuado"* — é por isso que `_sem_acento` existe.

### Portanto a justificativa da D12 é falsa

A D12 da TEC-162 manteve os literais sem acento com este argumento:

> ficha acentuada convivendo com fallback não-acentuado na mesma conversa é pior que uniformemente feio

O argumento pressupõe que a linha de base seja **uniformemente** sem acento. Ela não é. Hoje a conversa já mistura a voz acentuada do modelo com literais como `TEXTO_DA_IDENTIFICACAO` — *"Sou o assistente virtual da imobiliaria. Posso te ajudar a encontrar um imovel"* — enviados no mesmo fio.

**A escolha nunca foi entre uniforme e misto.** Era entre misto de um jeito e uniforme de verdade, e manter os literais sem acento não alcança o segundo: para isso seria preciso *tirar* o acento da saída do modelo, mecanismo que ninguém propôs e que faria a imobiliária soar pior de propósito.

### A convenção já estava quebrada, e ninguém notou

`TEXTO_DA_CONFIRMACAO_DE_OPTOUT` (`domain/optout/deteccao.py`) **já tem acento hoje** — "não" e "é", as duas únicas ocorrências de acento em texto de saída de todo o `src/`. "Manter tudo sem acento" não custaria zero: exigiria *remover* acento de um arquivo.

### O inventário é oito vezes maior do que a card supunha

A card nomeia três casos. São **24 literais em 8 arquivos**, 1.850 caracteres:

| Classe | Itens | Caracteres | Já acentuados |
| --- | ---: | ---: | ---: |
| **Frase** — fallback, aviso, identificação | 16 | 1.721 | 1 |
| **Rótulo de ficha** — `Condominio`, `Destaque`, `m2` | 8 | 129 | 0 |

Três não estavam em nenhuma lista, e um deles engana pelo nome: **`TEXTO_DA_JANELA_HUMANA` mora em `domain/notificacao/envio.py` e vai ao LEAD**, não ao corretor, apesar do módulo se chamar `notificacao`. Os outros dois são `TEXTO_DO_AVISO_DE_ERRO` (`workers/jobs/process_message.py`) e `TEXTO_DA_IDENTIFICACAO`, que mora em `domain/agente/identificacao.py` e não em `turno.py`, que apenas o importa.

## Decisões

### D1 — Acentua-se o texto que o lead lê, e a fronteira é essa

Os 24 literais passam a ser português acentuado correto. Comentários, docstrings e prompts de sistema **continuam sem acento**.

**A fronteira é "o lead lê isto", e não "é uma string".** É a única linha que se justifica sozinha: do lado de dentro está produto, e um cliente que recebe `Condominio R$ 550` de uma imobiliária lê descuido, não convenção; do lado de fora está código, onde a convenção nasceu e onde ninguém de fora olha.

**Por que não acentuar tudo:** medido, são ~23,5 mil linhas de prosa em português entre `src/` e `tests/` (6.099 comentários e 6.972 linhas de docstring em `src/`; 1.373 e 9.069 em `tests/`). O diff enterraria qualquer revisão e **não mudaria nada do que o lead vê** além do que a D1 já entrega. Traria também os prompts de sistema para a conta, e aí a margem de 6,2 tokens do orçamento vira risco concreto — ver `L3`.

**O que se perde:** passa a existir uma fronteira que alguém precisa saber onde fica, e nenhum linter a checa. É o mesmo defeito da convenção atual, num lugar novo — `L1`.

### D2 — `TEXTO_DO_FILTRO_AJUSTADO` ganha acento na moldura, e o nome do bairro continua ASCII

`aviso_de_ajuste` (`domain/agente/turno.py`) interpola nomes que chegam **na forma dobrada**: `recomendacao.bairros_a_excluir` guarda a chave de busca, minúscula e sem acento, e a docstring da função diz textualmente que *"o dobrado ja garante ASCII -- nao ha acento para perder na volta"*.

Acentuando só a moldura, o lead lê:

> Tirei Aclimacao da busca, que você já descartou.

**Desencontro dentro de uma frase, que é pior que entre mensagens** — e é justamente o medo da D12, um nível abaixo. Fica assim mesmo, declarado em `L2`.

A alternativa seria carregar a forma de exibição do bairro ao lado da chave dobrada por toda a cadeia de recomendação, ou consultar o catálogo dentro de uma função de formatação pura. As duas são desproporcionais a esta card, e a segunda é arquiteturalmente errada.

**A docstring de `aviso_de_ajuste` muda junto.** A frase sobre não haver acento a perder continua verdadeira *sobre o nome*, mas passa a conviver com uma moldura acentuada, e sem uma palavra a mais o próximo leitor a entende como se valesse para a frase inteira.

### D3 — O `CLAUDE.md` passa a dizer onde a fronteira fica

Hoje ele diz apenas *"Comentários e docstrings em `src/` e `tests/`: português SEM acento"*, e o repositório aplicava a regra mais amplamente do que o texto autoriza. **Essa divergência entre o documentado e o praticado é metade do problema que criou esta card** — e é a única razão pela qual `TEXTO_DA_CONFIRMACAO_DE_OPTOUT` pôde ganhar acento sem que ninguém reclamasse nem corrigisse.

Passa a dizer as duas metades: comentário e docstring sem acento; texto que o lead recebe com acento; e que nenhum linter checa nenhuma das duas.

### D4 — Os testes que quebram são cinco, e todos quebram pela mesma razão

Medido: **5 arquivos de teste** duplicam literais como string solta em vez de importar a constante, e são exatamente esses que quebram —

| Arquivo | O que duplica |
| --- | --- |
| `tests/unit/test_apresentacao.py` | `RESSALVA_DE_ESTIMATIVA`, `_ALUGUEL_AUSENTE`, `Condominio`, `Destaque:`, `Aluguel estimado`, `yield bruto` (~20 ocorrências) |
| `tests/integration/test_turno_investidor.py` | idem, 5 ocorrências |
| `tests/unit/test_recomendacao_regras.py` | `TEXTO_DO_FILTRO_AJUSTADO`, 4 ocorrências |
| `tests/integration/test_apresentacao_no_turno.py` | `TEXTO_DO_FILTRO_AJUSTADO` |
| `tests/unit/test_mensagem_do_followup.py` | `Condominio` |

Nenhum dos outros 16 literais quebra teste nenhum, porque todos os testes que os tocam **importam a constante** — comparar contra o próprio símbolo é tautológico e sobrevive à mudança de valor.

**Consequência declarada:** a correção é atualizar o literal duplicado, e **não** trocá-lo por um import. Trocar seria a mudança certa em outra card; aqui ela inflaria o diff e misturaria duas coisas numa revisão só.

## Lacunas declaradas

**L1 — A fronteira não é checada por nada.** Nenhum dos três gates olha para acento, nem antes nem depois desta card. Um literal novo voltado ao lead pode nascer sem acento e ninguém vê. Não há guarda automática possível barata: detectar "esta frase em português deveria ter acento" é o mesmo problema que nenhum linter resolve. O que muda é que agora a regra está escrita nos dois lados, em vez de existir só como hábito.

**L2 — Nome de bairro continua ASCII dentro de frase acentuada** (`D2`). O lead lê *"Tirei Aclimacao da busca, que você já descartou."* Restaurar a forma de exibição é card própria.

**L3 — O custo real em tokens é desconhecido, e só importa se alguém acentuar os prompts.** O gate do orçamento (`test_a_margem_do_orcamento_do_prompt_e_deliberada`) mede `len(texto)/4` sobre *code points*, e `você` tem os mesmos quatro caracteres que `voce` — então acentuar é **invisível** para ele: simulado sobre `SISTEMA_DO_AGENTE` inteiro, 1.222 caracteres antes e depois, diferença zero. Mas o tokenizador real opera sobre bytes, e a mesma simulação ganha **58 bytes** em UTF-8. Como os prompts **não** são texto que o lead vê, nada disto entra nesta card; fica registrado porque a margem atual é de **6,2 tokens** e quem um dia propuser acentuar os prompts precisa saber que o gate não o protegeria.

**L4 — `evals/` e os relatórios não entram.** São dados medidos e prosa de análise, não texto de produto.

## Riscos verificados, e o tamanho de cada um

| Risco | Verificação | Resultado |
| --- | --- | --- |
| Encoding no envio | `httpx` 0.28.1 serializa com `ensure_ascii=False`; `classificador.py` já usa o mesmo no histórico de tool-use | **Nulo.** Acento vai na rede como UTF-8 real |
| Encoding no banco | `messages.text_body` é `LargeBinary` cifrado; `infra/crypto.py` usa UTF-8 default | **Nulo.** Codificação de texto não toca a coluna |
| Casamento por texto | Todo uso dos 15 `TEXTO_*` fora da definição é atribuição, f-string ou passagem direta — nenhum `==`, `in` ou regex contra o valor | **Nulo** em `src/` |
| Log com `ensure_ascii` | `structlog.processors.JSONRenderer()` sem override em `app/logging.py` | **Teórico.** O repo documenta em vários pontos que o texto entregue ao lead nunca é logado |
| Orçamento de tokens | Ver `L3` | **Fora de escopo** |

Nenhum uso de `.encode("ascii")` ou `errors=` em `src/`.

## Testes

Esta card **não acrescenta teste novo**, e a razão é que não há o que asseverar que já não esteja asseverado: o valor dos literais é comparado pelos testes que os importam, e esses continuam passando por construção.

O que muda são os **cinco arquivos da D4**, cujos literais duplicados passam a trazer acento. Depois deles, a suíte inteira roda uma vez.

**Um teste que eu não vou escrever, e por quê:** seria possível listar as constantes voltadas ao lead num registro e asseverar que cada uma contém ao menos um caractere acentuado. Ele passaria sem provar nada — `"m2"` e `"De {} por {}"` não têm vogal que receba acento, e a asserção teria de excetuá-las, virando uma lista escrita à mão que envelhece sozinha. É o tipo de teste que dá confiança sem dar garantia.

## Fora de escopo

- Acentuar comentários, docstrings e prompts de sistema (`D1`).
- Restaurar a forma de exibição dos nomes de bairro (`L2`).
- Trocar literal duplicado em teste por import da constante (`D4`).
- Qualquer guarda automática da fronteira (`L1`).
