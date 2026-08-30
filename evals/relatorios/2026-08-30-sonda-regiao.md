# Sonda dos 7 `divergiu` de `regiao` (TEC-248)

- data: 2026-08-30 13:42 UTC
- modelo: claude-opus-5
- chamadas: 9 (nao 7: `aluguel-06` e `compra-08` sao indice 1 e
  precisam do turno 0 para o historico e o estado acumulado)
- corpus: `evals/corpus`, o mesmo de `6d74cff`

Diagnostico, nao medicao: nenhum numero daqui entra em metrica ou faixa.
Replica `_rodar_conversa` turno a turno ate o alvo -- historico com as
duas partes e estado acumulado por `campos_a_gravar`.

## O que o modelo devolveu em `regiao`

| turno | anotado | obtido (cru) | anotado normalizado | obtido normalizado |
| --- | --- | --- | --- | --- |
| `aluguel-06[1]` | `'vila madalena'` | `'vila madalena (perto da estação), são paulo'` | `'vila madalena'` | `'vila madalena (perto da estação), são paulo'` |
| `aluguel-10[0]` | `'saude'` | `'saúde'` | `'saude'` | `'saúde'` |
| `borda-longa-01[0]` | `'aclimacao'` | `'aclimação'` | `'aclimacao'` | `'aclimação'` |
| `compra-08[1]` | `'paulista'` | `'avenida paulista'` | `'paulista'` | `'avenida paulista'` |
| `compra-12[0]` | `'sp'` | `'são paulo'` | `'sp'` | `'são paulo'` |
| `compra-13[0]` | `'sao roque'` | `'são roque (sp)'` | `'sao roque'` | `'são roque (sp)'` |
| `investimento-07[0]` | `'sp'` | `'são paulo (sp)'` | `'sp'` | `'são paulo (sp)'` |

## Fala do lead, e a extracao inteira do turno

### `aluguel-06[1]`

- lead: *precisa ser na mesma regiao, perto da estacao vila madalena*
- anotado: `'vila madalena'`
- obtido (`regiao`): `'vila madalena (perto da estação), são paulo'`
- extracao completa do turno: `{'regiao': 'vila madalena (perto da estação), são paulo'}`

### `aluguel-10[0]`

- lead: *oi, o anuncio do apartamento na saude, o valor la e so de aluguel ou ja inclui condominio?*
- anotado: `'saude'`
- obtido (`regiao`): `'saúde'`
- extracao completa do turno: `{'regiao': 'saúde', 'tipo_imovel': <TipoImovel.APARTAMENTO: 'APARTAMENTO'>}`

### `borda-longa-01[0]`

- lead: *vi um anuncio de vcs no instagram, sobre um apartamento na aclimacao*
- anotado: `'aclimacao'`
- obtido (`regiao`): `'aclimação'`
- extracao completa do turno: `{'regiao': 'aclimação', 'tipo_imovel': <TipoImovel.APARTAMENTO: 'APARTAMENTO'>}`

### `compra-08[1]`

- lead: *tem que ser proximo do trabalho, na regiao da paulista*
- anotado: `'paulista'`
- obtido (`regiao`): `'avenida paulista'`
- extracao completa do turno: `{'regiao': 'avenida paulista'}`

### `compra-12[0]`

- lead: *estou de mudanca pra sp e quero comprar um apartamento mobiliado pra ja morar*
- anotado: `'sp'`
- obtido (`regiao`): `'são paulo'`
- extracao completa do turno: `{'regiao': 'são paulo', 'tipo_imovel': <TipoImovel.APARTAMENTO: 'APARTAMENTO'>, 'urgencia': <Urgencia.IMEDIATA: 'IMEDIATA'>}`

### `compra-13[0]`

- lead: *queria comprar uma chacara pra passar os fins de semana com a familia, perto de sao roque*
- anotado: `'sao roque'`
- obtido (`regiao`): `'são roque (sp)'`
- extracao completa do turno: `{'regiao': 'são roque (sp)', 'tipo_imovel': <TipoImovel.RURAL: 'RURAL'>}`

### `investimento-07[0]`

- lead: *sou de fora, mas queria comprar aqui em sp so pra ter uma reserva que renda mais que poupanca*
- anotado: `'sp'`
- obtido (`regiao`): `'são paulo (sp)'`
- extracao completa do turno: `{'regiao': 'são paulo (sp)'}`

