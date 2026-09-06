"""Os dominios enumerados do catalogo.

`StrEnum` sobre coluna `String(n)`, e nao `ENUM` do Postgres: nao existe um
unico tipo ENUM neste repositorio -- `MessageRole`, `MessageDirection`,
`MessageContentType` e a `temperatura` de `followups` seguem todos este molde.
O SRS diz "enum" na tabela Imovel; seguir a letra dele faria desta a unica
tabela cujo dominio so muda por ALTER TYPE em migration. Ver D10 do desenho.
"""

from enum import StrEnum


class TipoImovel(StrEnum):
    APARTAMENTO = "APARTAMENTO"
    CASA = "CASA"
    COBERTURA = "COBERTURA"
    TERRENO = "TERRENO"
    COMERCIAL = "COMERCIAL"


class Operacao(StrEnum):
    VENDA = "VENDA"
    ALUGUEL = "ALUGUEL"
    AMBOS = "AMBOS"


class Zona(StrEnum):
    NORTE = "NORTE"
    SUL = "SUL"
    LESTE = "LESTE"
    OESTE = "OESTE"
    CENTRO = "CENTRO"


class StatusImovel(StrEnum):
    DISPONIVEL = "DISPONIVEL"
    RESERVADO = "RESERVADO"
    VENDIDO = "VENDIDO"
    ALUGADO = "ALUGADO"
    INATIVO = "INATIVO"


class StatusImportacao(StrEnum):
    PROCESSANDO = "PROCESSANDO"
    CONCLUIDO = "CONCLUIDO"
    # Reservado ao que o lote NAO absorve: arquivo ilegivel, cabecalho
    # ausente, JSON malformado. Linha ruim nunca chega aqui -- ela vira
    # Rejeicao e o lote segue, que e a RN-08.5 inteira.
    FALHOU = "FALHOU"


class OrigemImportacao(StrEnum):
    CLI = "CLI"
    HTTP = "HTTP"
