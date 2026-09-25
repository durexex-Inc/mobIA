"""As causas de um recalculo de score, derivadas do que se moveu.

TEC-152. Pura de proposito: sem I/O, sem banco, sem chamada ao modelo --
mesma forma de `score.py` e `qualificacao.py`. Quem grava e o repositorio;
aqui so se decide o que mudou.

**Tupla vazia e o sinal de "nao grave" para o que ESTE modulo deriva.** A
regra da RN-06.4 emendada -- so grava quando o resultado muda -- nao e um `if`
no chamador: e a ausencia de causa. Assim a regra de QUANDO gravar a partir de
um diff mora no mesmo lugar que a de O QUE o diff produz, e as duas nao tem
como divergir.

**A TEC-136 abriu a segunda metade da regra, de proposito.** `causas_do_recalculo`
so enxerga os cinco fatores, e ha fato que merece trilha sem mover nenhum
deles -- a troca de intencao do lead e o primeiro. Por isso `registrar_recalculo`
recebe `causas_externas` e as une ANTES da guarda: causa informada pelo
chamador e razao suficiente para gravar. O que continua valendo e a forma
negativa da frase acima -- nenhum `if` decide gravar; quem decide e a tupla,
agora somada. O que deixou de valer e que a tupla saia toda daqui.
"""

from mobia.domain.context.score import Score

CAUSA_PRIMEIRO_CALCULO = "PRIMEIRO_CALCULO"
CAUSA_CAMPOS_OBRIGATORIOS = "CAMPOS_OBRIGATORIOS"
CAUSA_URGENCIA = "URGENCIA"
CAUSA_CATALOGO = "CATALOGO"
CAUSA_ENGAJAMENTO = "ENGAJAMENTO"
CAUSA_FORMA_DE_PAGAMENTO = "FORMA_DE_PAGAMENTO"
# TEC-172. Derivada do diff como os outros cinco, e nao informada pelo
# chamador: ela diz O QUE se moveu. Quem diz POR QUE e
# `CAUSA_NAO_COMPARECIMENTO`, logo abaixo, que entra como causa externa na
# mesma linha. As duas juntas sao a resposta inteira; uma so e metade dela.
CAUSA_PENALIDADE = "PENALIDADE"

# Fatos sobre a ORIGEM do gatilho, e nao sobre o que se moveu -- por isso
# informados pelo chamador, e nao derivaveis de diff nenhum.
#
# `CAUSA_EDICAO_MANUAL` continua sem produtor, esperando o dashboard da
# TEC-192. `CAUSA_NAO_COMPARECIMENTO` ganhou o seu na TEC-172
# (`agendamento/ciclo.py::marcar_nao_comparecimento`), e chega acompanhada:
# a penalidade que ela explica MOVE um fator, entao a linha carrega tambem a
# `CAUSA_PENALIDADE` derivada.
CAUSA_EDICAO_MANUAL = "EDICAO_MANUAL"
CAUSA_NAO_COMPARECIMENTO = "NAO_COMPARECIMENTO"

# Da mesma natureza das duas acima -- fato sobre a ORIGEM do gatilho, e nao
# sobre o que se moveu --, e por isso tambem informada pelo chamador em vez de
# derivada do diff. A diferenca e que esta e a PRIMEIRA da familia a ter
# produtor: a TEC-136, no bloco transacional de `executar_turno`, quando
# `aplicar_mudanca_de_intencao` devolve uma troca.
CAUSA_MUDANCA_DE_INTENCAO = "MUDANCA_DE_INTENCAO"

# Os nomes sao do dominio e nao da direcao: um vocabulario com _SUBIU/_CAIU
# dobraria de tamanho para dizer o que as colunas de fator ja dizem.
#
# `capacidade` vira FORMA_DE_PAGAMENTO porque e o que o leitor da trilha
# reconhece -- "capacidade" e nome interno do fator, e o campo que se moveu
# tem nome proprio no produto.
#
# A ordem e a de `Score`, e a tupla de saida a respeita: duas execucoes com o
# mesmo diff devolvem a mesma tupla, e o teste pode comparar por igualdade em
# vez de por conjunto.
_CAUSA_POR_FATOR: tuple[tuple[str, str], ...] = (
    ("completude", CAUSA_CAMPOS_OBRIGATORIOS),
    ("urgencia", CAUSA_URGENCIA),
    ("catalogo", CAUSA_CATALOGO),
    ("engajamento", CAUSA_ENGAJAMENTO),
    ("capacidade", CAUSA_FORMA_DE_PAGAMENTO),
    ("penalidade", CAUSA_PENALIDADE),
)


def causas_do_recalculo(anterior: Score | None, novo: Score) -> tuple[str, ...]:
    """O que mudou entre dois calculos. Vazio quando nada mudou.

    Compara os cinco fatores, e **nao** o total. O total pode ficar identico
    com a composicao mudando -- completude +15 e urgencia -15 no mesmo turno --
    e e justamente o caso em que a trilha explica algo que ninguem deduz do
    estado atual.

    `anterior is None` e o primeiro registro do lead, e devolve so
    `PRIMEIRO_CALCULO`: nao houve movimento a explicar, e listar os fatores
    diferentes de zero fingiria que houve.
    """
    if anterior is None:
        return (CAUSA_PRIMEIRO_CALCULO,)

    return tuple(
        causa
        for fator, causa in _CAUSA_POR_FATOR
        if getattr(anterior, fator) != getattr(novo, fator)
    )
