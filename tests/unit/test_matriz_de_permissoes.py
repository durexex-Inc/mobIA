"""A matriz de papeis e permissoes. TEC-202, RNF-12, D1 do desenho.

Sem HTTP, sem banco e sem token: a pergunta "o LEITURA pode escrever alguma
coisa?" e sobre a matriz, e responde-la aqui vale para TODA rota -- inclusive
as que ainda nao existem. Os testes de rota, em `tests/integration`, exercitam
o caminho; estes exercitam a regra.
"""

import pytest

from mobia.domain.usuarios.models import PAPEIS
from mobia.domain.usuarios.permissoes import (
    DE_ESCRITA,
    TODAS,
    Permissao,
    papeis_com,
    permissoes_de,
)


def test_admin_tem_todas() -> None:
    """D2: o ADMIN e superconjunto, e por construcao e nao por repeticao.

    O que este teste protege nao e a linha `if papel == "ADMIN"` -- e a
    propriedade que a D2 declarou: uma permissao NOVA nasce valendo para o
    ADMIN sem ninguem precisar lembrar de acrescenta-la la.
    """
    assert permissoes_de("ADMIN") == TODAS


def test_leitura_nao_altera_nada() -> None:
    """Terceiro cenario do Gherkin, afirmado uma vez para todas as rotas.

    A card escreve o cenario sobre `PATCH /leads/{id}/qualificacao`, que nao
    existe (L2 do desenho). Ele e exercitado sobre as escritas que existem em
    `tests/integration/test_autorizacao_por_papel.py`, e esta asserta e o que
    faz a regra valer tambem para as que vierem depois.
    """
    assert not (permissoes_de("LEITURA") & DE_ESCRITA)


def test_corretor_nao_ve_o_funil_e_o_leitura_ve() -> None:
    """A linha menos obvia da matriz, e por isso a que tem teste proprio.

    E a matriz de navegacao da RN-FE-03.1 (TEC-312), nao uma escolha desta
    card: o funil e da operacao inteira, e o corretor trabalha a propria
    carteira. Quem inverter isto um dia vai reprovar aqui e ler a razao.
    """
    assert Permissao.VER_FUNIL not in permissoes_de("CORRETOR")
    assert Permissao.VER_FUNIL in permissoes_de("LEITURA")


def test_ver_leads_e_dos_quatro_papeis() -> None:
    """A lista e de todo mundo; o que muda e O QUE ELA DEVOLVE (TEC-192, D7).

    Uma permissao separada para "ver os leads dos outros" foi recusada: ela
    viraria uma segunda forma de dizer o que o PAPEL ja diz, livre para
    divergir dele. Quem recorta o CORRETOR e o repositorio, pela claim do
    token.
    """
    assert papeis_com(Permissao.VER_LEADS) == frozenset(PAPEIS)


def test_dados_completos_nao_vao_para_corretor_nem_para_leitura() -> None:
    """A permissao que ainda nao mascara nada (D7, L3).

    Ela e concedida por papel, como a card manda, e o unico consumidor hoje e
    `GET /auth/me`. Quem a for consumir de verdade e a TEC-195.
    """
    assert papeis_com(Permissao.VER_DADOS_COMPLETOS) == frozenset({"ADMIN", "GERENTE"})


@pytest.mark.parametrize("permissao", list(Permissao))
def test_nenhuma_permissao_fica_sem_dono(permissao: Permissao) -> None:
    """Permissao que nenhum papel tem tranca a rota para todo mundo.

    O ADMIN sozinho ja bastaria para passar, e e por isso que este teste e
    fraco de proposito: ele nao opina sobre QUEM deve ter, so recusa a
    permissao orfa -- aquela que alguem acrescenta a matriz, pendura numa rota
    e esquece de conceder.
    """
    assert papeis_com(permissao), f"{permissao.value} nao foi concedida a papel nenhum"


@pytest.mark.parametrize("papel", PAPEIS)
def test_todo_papel_pode_alguma_coisa(papel: str) -> None:
    """Papel sem permissao nenhuma e papel que nao serve para nada.

    Os quatro da `PAPEIS` vem da RNF-12 e cada um existe porque alguem vai
    receber esse cracha. Um deles vazio significaria que a matriz esqueceu de
    conceder, e nao que o papel e decorativo.
    """
    assert permissoes_de(papel)


def test_papel_desconhecido_nao_pode_nada() -> None:
    """Fail-closed, e sem levantar.

    Um papel fora da `PAPEIS` so chega aqui vindo de um JWT assinado com o
    nosso segredo ou de uma linha que passou pelo CHECK do banco -- as duas
    coisas sao anomalias. Negar tudo e a resposta; levantar daria 500 onde 403
    e a verdade.
    """
    assert permissoes_de("SUPERVISOR") == frozenset()
    assert permissoes_de("") == frozenset()
