"""O vocabulario dos direitos do titular. TEC-207, D2 e D6 do desenho."""

from datetime import timedelta

from mobia.domain.titular.vocabulario import PRAZO_DO_TITULAR
from mobia.domain.usuarios.permissoes import DE_ESCRITA, Permissao, permissoes_de


def test_prazo_do_titular_e_15_dias() -> None:
    assert PRAZO_DO_TITULAR == timedelta(days=15)


def test_so_o_admin_tem_atender_titular() -> None:
    assert Permissao.ATENDER_TITULAR in permissoes_de("ADMIN")
    assert Permissao.ATENDER_TITULAR not in permissoes_de("GERENTE")
    assert Permissao.ATENDER_TITULAR not in permissoes_de("CORRETOR")
    assert Permissao.ATENDER_TITULAR not in permissoes_de("LEITURA")


def test_atender_titular_e_de_escrita() -> None:
    assert Permissao.ATENDER_TITULAR in DE_ESCRITA
