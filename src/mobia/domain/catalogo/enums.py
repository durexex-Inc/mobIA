"""Os dominios enumerados do catalogo.

`StrEnum` sobre coluna `String(n)`, e nao `ENUM` do Postgres: nao existe um
unico tipo ENUM neste repositorio -- `MessageRole`, `MessageDirection`,
`MessageContentType` e a `temperatura` de `followups` seguem todos este molde.
O SRS diz "enum" na tabela Imovel; seguir a letra dele faria desta a unica
tabela cujo dominio so muda por ALTER TYPE em migration. Ver D10 do desenho.
"""

from enum import StrEnum


class TipoImovel(StrEnum):
    """O vocabulario de tipo do CATALOGO, que nao e o mesmo do agente.

    `agente/schemas.py` tem o seu, e os dois nao se importam -- `catalogo` nao
    importa `agente` (D2 da TEC-158), e a seta contraria seria igualmente
    errada. Depois da TEC-262 eles tem os mesmos seis valores, mas seguem
    sendo dois tipos Python distintos: quem liga a busca ao turno converte
    por nome.

    **`COBERTURA` existe aqui e NAO existe no do agente, de proposito.** A D1
    da TEC-242 mapeia "cobertura" para `APARTAMENTO` nas regras de anotacao do
    corpus, e deixou escrito que nada muda no schema da chamada nem no prompt:
    o modelo devolve `APARTAMENTO` para quem diz cobertura, e os tres turnos
    de `compra-06` estao anotados assim. Acrescentar o membro la faria as tres
    anotacoes virarem discrepancia. Quem alcanca a cobertura e o filtro da
    busca, pela `_INCLUSOES` em `busca.py`.
    """

    APARTAMENTO = "APARTAMENTO"
    CASA = "CASA"
    COBERTURA = "COBERTURA"
    TERRENO = "TERRENO"
    COMERCIAL = "COMERCIAL"
    # TEC-262. O agente ja devolvia RURAL e o catalogo nao tinha onde guardar:
    # o lead dizia "chacara", gravava-se `tipo_imovel = RURAL`, e a busca
    # filtrava contra uma coluna que nao podia conter o valor -- zero
    # resultados, sem erro e sem log. O membro aqui e o que fecha isso, e
    # tambem o que faz o parser aceitar a linha, porque ele valida por
    # `enumerado("tipo", TipoImovel)`.
    RURAL = "RURAL"


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


class EstadoDoRelaxamento(StrEnum):
    """O que aconteceu com o relaxamento da RN-09.3 nesta busca. TEC-160, D6.

    **Tres estados e nao um booleano, e a regra 4 da card e quem exige.** Ela
    manda que, sem resultado mesmo depois de relaxar, o agente informe e
    ofereca o corretor. O turno precisa entao separar "nao relaxei" de
    "relaxei e nao achei" -- as duas mensagens ao lead sao diferentes, e um
    `relaxamento_aplicado: false` colapsa as duas num valor so.

    Com o enum, o estado impossivel ("nao tentei, mas apliquei") deixa de ser
    representavel. As bordas (tool_result e o POST da secao 6.3) continuam
    expondo booleano, derivado num lugar so.
    """

    NAO_HOUVE = "NAO_HOUVE"
    APLICADO = "APLICADO"
    SEM_RESULTADO = "SEM_RESULTADO"
