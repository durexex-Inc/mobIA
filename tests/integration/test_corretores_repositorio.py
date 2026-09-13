"""A escrita e a leitura do cadastro."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.repositorio import (
    DadosDoCorretor,
    EmailJaCadastrado,
    atualizar_corretor,
    criar_corretor,
    listar_corretores,
    obter_corretor,
)


def _dados(**sobrescritas: object) -> DadosDoCorretor:
    campos: dict[str, object] = {
        "nome": "Paulo Ribeiro",
        "email": "Paulo@Imobiliaria.com.BR",
        "telefone": "5511988887777",
        "creci": "SP-123456",
        "especialidades": ["COMPRA", "INVESTIMENTO"],
        "regioes_atuacao": ["Zona Sul", "Vila Mariana"],
        "horario_inicio": 9,
        "horario_fim": 18,
        "capacidade_diaria": 4,
        "plantao": False,
        "gerente": False,
    }
    return DadosDoCorretor(**(campos | sobrescritas))  # type: ignore[arg-type]


async def test_criar_normaliza_email_e_regioes(session: AsyncSession) -> None:
    """D4: sem a dobra, "Zona Sul" e "zona sul" viram duas regioes.

    O e-mail cai para minuscula pelo mesmo motivo que o UNIQUE existe: dois
    cadastros do mesmo corretor com caixa diferente passariam pelo UNIQUE e
    a notificacao da TEC-177 sairia dobrada.
    """
    corretor = await criar_corretor(session, _dados())
    await session.commit()

    assert corretor.email == "paulo@imobiliaria.com.br"
    assert corretor.regioes_atuacao == ["zona sul", "vila mariana"]


async def test_email_repetido_em_outra_caixa_e_recusado(session: AsyncSession) -> None:
    await criar_corretor(session, _dados())
    await session.commit()

    with pytest.raises(EmailJaCadastrado):
        await criar_corretor(session, _dados(email="PAULO@imobiliaria.com.br"))


async def test_listar_traz_ativos_e_inativos_por_padrao(session: AsyncSession) -> None:
    ativo = await criar_corretor(session, _dados())
    inativo = await criar_corretor(session, _dados(email="ana@imobiliaria.com.br"))
    await session.commit()
    await atualizar_corretor(session, corretor_id=inativo.id, mudancas={"ativo": False})
    await session.commit()

    todos = await listar_corretores(session, apenas_ativos=False)
    so_ativos = await listar_corretores(session, apenas_ativos=True)

    assert {c.id for c in todos} == {ativo.id, inativo.id}
    assert {c.id for c in so_ativos} == {ativo.id}


async def test_desativar_preserva_a_linha(session: AsyncSession) -> None:
    """Terceiro cenario do Gherkin: desativar nao apaga."""
    corretor = await criar_corretor(session, _dados())
    await session.commit()

    await atualizar_corretor(session, corretor_id=corretor.id, mudancas={"ativo": False})
    await session.commit()

    de_volta = await obter_corretor(session, corretor_id=corretor.id)
    assert de_volta is not None
    assert de_volta.ativo is False
    assert de_volta.nome == "Paulo Ribeiro"


async def test_atualizar_dobra_as_regioes_novas(session: AsyncSession) -> None:
    corretor = await criar_corretor(session, _dados())
    await session.commit()

    await atualizar_corretor(
        session, corretor_id=corretor.id, mudancas={"regioes_atuacao": ["Moema"]}
    )
    await session.commit()

    de_volta = await obter_corretor(session, corretor_id=corretor.id)
    assert de_volta is not None
    assert de_volta.regioes_atuacao == ["moema"]


async def test_atualizar_corretor_inexistente_devolve_none(session: AsyncSession) -> None:
    assert (
        await atualizar_corretor(session, corretor_id=uuid.uuid4(), mudancas={"ativo": False})
        is None
    )


async def test_obter_corretor_inexistente_devolve_none(session: AsyncSession) -> None:
    assert await obter_corretor(session, corretor_id=uuid.uuid4()) is None


async def test_atualizar_recusa_campo_fora_da_lista(session: AsyncSession) -> None:
    """ "id" e o caso perigoso: reatribuir a chave primaria corrompe o identity map."""
    corretor = await criar_corretor(session, _dados())
    await session.commit()

    with pytest.raises(ValueError, match="id"):
        await atualizar_corretor(session, corretor_id=corretor.id, mudancas={"id": uuid.uuid4()})


async def test_atualizar_campo_da_lista_continua_funcionando(session: AsyncSession) -> None:
    corretor = await criar_corretor(session, _dados())
    await session.commit()

    atualizado = await atualizar_corretor(
        session, corretor_id=corretor.id, mudancas={"nome": " Paulo Novo "}
    )
    await session.commit()

    assert atualizado is not None
    assert atualizado.nome == "Paulo Novo"
