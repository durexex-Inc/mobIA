"""O que cada papel pode fazer. TEC-202, RNF-12.

**A rota exige PERMISSAO, e nao papel** (D1 do desenho). Uma rota que
declarasse `papeis={"ADMIN", "GERENTE"}` obrigaria quem muda a regra a varrer
onze arquivos de rota atras de conjuntos de strings que precisam concordar
entre si -- e nao teria onde guardar `VER_DADOS_COMPLETOS`, que a card concede
por papel e que rota nenhuma exige: ela e capacidade consultada DENTRO de um
handler, pela TEC-195.

A matriz abaixo e a unica fonte da resposta "quem pode o que" neste sistema.
"""

from enum import StrEnum

from mobia.domain.usuarios.models import PAPEIS


class Permissao(StrEnum):
    """O que se pode fazer, nomeado pela acao e nao pela rota.

    Nomear pela acao e o que deixa duas rotas compartilharem a mesma permissao
    sem que uma delas vire "a rota principal" -- `/handoffs/{id}/aceitar` e
    `/conversas/assumir` sao a mesma autorizacao vista de dois angulos.
    """

    GERIR_CATALOGO = "GERIR_CATALOGO"
    GERIR_CORRETORES = "GERIR_CORRETORES"
    BUSCAR_IMOVEIS = "BUSCAR_IMOVEIS"
    # **Os quatro papeis a tem, e o que muda entre eles e O QUE A LISTA
    # DEVOLVE** (TEC-192, D7): o CORRETOR recebe a consulta ja recortada pelo
    # proprio vinculo, e os outros veem a base inteira. Uma permissao separada
    # para "ver os leads dos outros" foi recusada -- ela viraria uma segunda
    # forma de dizer o que o PAPEL ja diz, livre para divergir dela.
    VER_LEADS = "VER_LEADS"
    VER_FUNIL = "VER_FUNIL"
    ATENDER_LEAD = "ATENDER_LEAD"
    VER_DADOS_COMPLETOS = "VER_DADOS_COMPLETOS"
    # TEC-206, D8, para a tela da TEC-343: "Somente leitura; somente ADMIN".
    # Nao aparece em `_CONCEDIDAS` -- o ADMIN a recebe por construcao, e
    # nenhum outro papel a tem. Leitura, e por isso fora de `DE_ESCRITA`.
    VER_AUDITORIA = "VER_AUDITORIA"


# As permissoes que MUDAM estado. Existe para que o terceiro cenario do
# Gherkin ("papel de leitura nao altera nada") seja afirmado uma vez sobre a
# matriz, em vez de uma vez por rota de escrita -- e continue valendo para as
# rotas de escrita que ainda nao existem.
#
# `VER_DADOS_COMPLETOS` fica de fora apesar de a TEC-195 exigir auditoria ao
# usa-la: revelar um telefone nao altera o telefone. O registro e efeito de
# conformidade, nao escrita de dominio.
DE_ESCRITA = frozenset(
    {
        Permissao.GERIR_CATALOGO,
        Permissao.GERIR_CORRETORES,
        Permissao.ATENDER_LEAD,
    }
)

# **`ADMIN` nao aparece aqui, de proposito** -- ele recebe o conjunto inteiro
# em `permissoes_de`, por construcao. Repetir as linhas dele seria criar
# a chance de alguem acrescentar uma permissao nova e esquecer uma das duas
# copias; a que esqueceria e sempre a do papel que ja podia tudo.
#
# Tres escolhas desta tabela nao sao obvias e estao no desenho (D1):
#
# - `LEITURA` tem `VER_FUNIL` e `CORRETOR` nao. E a matriz de navegacao da
#   RN-FE-03.1 (card de tela TEC-312): o funil e da operacao inteira, e o
#   corretor trabalha a propria carteira.
# - `GERENTE` tem `ATENDER_LEAD`, que a secao 6.2 do SRS nao preve. A escalada
#   de SLA da RN-16.3 chega A GERENTE quando ninguem aceita -- destinatario que
#   nao pode agir e beco sem saida. Emenda E-01 a RNF-12.
# - `LEITURA` nao tem nenhuma permissao de `DE_ESCRITA`, agora nem depois.
_CONCEDIDAS: dict[str, frozenset[Permissao]] = {
    "GERENTE": frozenset(
        {
            Permissao.BUSCAR_IMOVEIS,
            Permissao.VER_LEADS,
            Permissao.VER_FUNIL,
            Permissao.ATENDER_LEAD,
            Permissao.VER_DADOS_COMPLETOS,
        }
    ),
    "CORRETOR": frozenset(
        {
            Permissao.BUSCAR_IMOVEIS,
            Permissao.VER_LEADS,
            Permissao.ATENDER_LEAD,
        }
    ),
    "LEITURA": frozenset(
        {
            Permissao.BUSCAR_IMOVEIS,
            Permissao.VER_LEADS,
            Permissao.VER_FUNIL,
        }
    ),
}

TODAS = frozenset(Permissao)


def permissoes_de(papel: str) -> frozenset[Permissao]:
    """O que este papel pode. Papel desconhecido nao pode nada.

    **`ADMIN` recebe `TODAS`** -- ver o comentario de `_CONCEDIDAS`.

    **Papel desconhecido devolve vazio, e nao levanta.** Um papel que nao esta
    na `PAPEIS` so chega aqui vindo de um JWT assinado com o nosso segredo, ou
    de uma linha que passou pelo CHECK do banco -- as duas coisas sao anomalias
    que merecem resposta, e a resposta certa e negar tudo. Levantar daria 500
    onde 403 e a verdade: quem pediu nao pode.
    """
    if papel == "ADMIN":
        return TODAS
    return _CONCEDIDAS.get(papel, frozenset())


def papeis_com(permissao: Permissao) -> frozenset[str]:
    """Quem tem esta permissao. Para teste e para diagnostico, nao para rota.

    Rota nenhuma pergunta isto -- ela pergunta `permissao in permissoes_de(...)`.
    Esta funcao existe para que a matriz possa ser inspecionada pela ponta
    contraria, que e como se prova que nenhuma permissao ficou sem dono.
    """
    return frozenset(papel for papel in PAPEIS if permissao in permissoes_de(papel))
