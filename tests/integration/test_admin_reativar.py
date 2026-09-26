import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from mobia.admin.reativar import _executar, main
from mobia.app.config import get_settings
from mobia.domain.identidade.indice import chave_de, registrar
from mobia.domain.identidade.models import IdentidadeDeLead
from mobia.domain.optout.models import EVENTO_REATIVACAO, OptoutEvent
from mobia.domain.optout.repositorio import esta_em_optout, reativar, registrar_optout

# Valores inconfundiveis, e escolhidos assim de proposito: se `autor` e
# `motivo` trocarem de lugar em qualquer ponto da cadeia -- na montagem do
# `OptoutEvent`, ou no mapeamento `args.* -> kwarg` de `main` --, a troca
# aparece aqui. Com valores parecidos ("Paulo M." e "Paulo") a inversao
# passaria despercebida, e `mypy` nao pega nada: os dois campos sao `str`.
AUTOR = "Paulo M."
MOTIVO = "pediu por telefone"


def _fabrica_isolada() -> async_sessionmaker[AsyncSession]:
    """Sessionmaker com engine propria e `NullPool`, para uso sob `asyncio.run`.

    O teste que exercita `main` precisa ser SINCRONO (`main` chama
    `asyncio.run`, e chamar isso de dentro de um teste async estoura "cannot
    be called from a running event loop"). Cada `asyncio.run` abre um event
    loop novo, e conexao asyncpg nao sobrevive a troca de loop -- entao o
    engine global cacheado de `mobia.infra.db`, criado dentro do loop de um
    `asyncio.run`, ficaria inutilizavel para o proximo e envenenaria os testes
    seguintes. `NullPool` fecha a conexao quando a sessao a devolve: nada fica
    pendurado num loop que ja morreu, e nao ha engine para descartar depois.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _reativacao_gravada(*, channel: str, key: str) -> tuple[str | None, str | None]:
    """Le da tabela o `(autor, motivo)` do evento de reativacao daquele lead."""
    async with _fabrica_isolada()() as sessao:
        linha = (
            await sessao.execute(
                select(OptoutEvent.autor, OptoutEvent.motivo).where(
                    OptoutEvent.channel == channel,
                    OptoutEvent.conversation_key == key,
                    OptoutEvent.evento == EVENTO_REATIVACAO,
                )
            )
        ).one()
    return (linha.autor, linha.motivo)


async def test_reativacao_devolve_o_lead_ao_estado_respondivel(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Chama `_executar` direto, nao `main`.

    `main` chama `asyncio.run`, e este teste ja roda dentro de um loop -- ver
    a nota em `mobia.admin.reativar._executar`. `--key` e o telefone cru
    (TEC-203); `_executar` e que deriva o `conversation_key`.
    """
    chave = await _lead_em_optout(session, session_factory, "5548999998888")

    codigo = await _executar(
        channel="whatsapp", key="5548999998888", autor="Paulo M.", motivo="lead pediu por telefone"
    )

    assert codigo == 0
    assert await esta_em_optout(session, channel="whatsapp", conversation_key=chave) is False


async def _lead_em_optout(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], wa_id: str
) -> str:
    """Um lead do WhatsApp como a TEC-203 o grava: identidade e opt-out sob a chave."""
    chave = await registrar(session, "whatsapp", wa_id)
    await session.commit()
    await registrar_optout(
        session_factory, channel="whatsapp", conversation_key=chave, message_id=uuid.uuid4()
    )
    return chave


async def test_numero_digitado_com_mascara_acha_o_wa_id_sem_o_nove(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O operador digita o numero como o lead o dita -- com `+`, parenteses e
    o 9 --, e a Meta entregou o `wa_id` sem o 9. A chave calculada sobre o
    que foi digitado nao existe; a certa e a da grafia que tem identidade."""
    chave = await _lead_em_optout(session, session_factory, "554899998888")

    codigo = await _executar(
        channel="whatsapp", key="+55 (48) 99999-8888", autor=AUTOR, motivo=MOTIVO
    )

    assert codigo == 0
    assert await esta_em_optout(session, channel="whatsapp", conversation_key=chave) is False


async def test_numero_com_o_nove_quando_o_wa_id_tem_o_nove(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """E o inverso: digitado sem o 9, o `wa_id` que a Meta mandou tem."""
    chave = await _lead_em_optout(session, session_factory, "5548999998888")

    codigo = await _executar(channel="whatsapp", key="4899998888", autor=AUTOR, motivo=MOTIVO)

    assert codigo == 0
    assert await esta_em_optout(session, channel="whatsapp", conversation_key=chave) is False


@pytest.mark.parametrize(
    ("channel", "key"),
    [
        ("whatsapp", "5548911112222"),
        # O exemplo que a docstring deste script trazia: `wa` nao e canal.
        ("wa", "5548999998888"),
        ("web", "0b6f5d8e-3c1a-4e2b-9f7d-1a2b3c4d5e6f"),
    ],
)
async def test_lead_desconhecido_e_recusado_e_nada_e_gravado(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    channel: str,
    key: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Gravar mesmo assim poria na trilha de LGPD uma reativacao de um lead
    que nao existe -- e o lead de verdade continuaria em opt-out, sem que
    ninguem soubesse."""
    await _lead_em_optout(session, session_factory, "5548999998888")

    codigo = await _executar(channel=channel, key=key, autor=AUTOR, motivo=MOTIVO)

    assert codigo != 0
    assert "nenhum lead" in capsys.readouterr().err
    reativacoes = (
        await session.scalars(select(OptoutEvent.id).where(OptoutEvent.evento == EVENTO_REATIVACAO))
    ).all()
    assert reativacoes == []
    identidades = (await session.scalars(select(IdentidadeDeLead.conversation_key))).all()
    assert identidades == [chave_de("whatsapp", "5548999998888")]


def test_sem_motivo_o_comando_falha() -> None:
    """A RN-14.3 exige justificativa.

    `argparse` sai com SystemExit(2) em argumento obrigatorio ausente, e e o
    comportamento certo: sem justificativa a reativacao nao acontece.
    """
    with pytest.raises(SystemExit) as erro:
        main(["--channel", "wa", "--key", "5548999998888", "--autor", "Paulo M."])

    assert erro.value.code == 2


async def test_reativar_grava_autor_e_motivo_em_colunas_distintas(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A metade de baixo da cadeia: `reativar()` -> linha gravada.

    Os testes que existiam antes desta revisao afirmavam so que o ESTADO
    mudou (o lead deixou de estar em opt-out), e o estado nao depende de
    `autor` nem de `motivo`. Trocar `autor=motivo, motivo=autor` dentro de
    `reativar()` passava na suite inteira, e o efeito seria a justificativa de
    LGPD gravada na coluna do autor e vice-versa -- no registro de
    conformidade, em silencio.
    """
    await reativar(
        session_factory,
        channel="wa",
        conversation_key="5548999998888",
        autor=AUTOR,
        motivo=MOTIVO,
    )

    gravado = (
        await session.execute(select(OptoutEvent).where(OptoutEvent.evento == EVENTO_REATIVACAO))
    ).scalar_one()

    assert gravado.autor == AUTOR
    assert gravado.motivo == MOTIVO


def test_main_fia_cada_argumento_no_kwarg_certo(monkeypatch: pytest.MonkeyPatch) -> None:
    """A metade de cima da cadeia: `--autor`/`--motivo` -> kwarg -> linha gravada.

    Este e o teste que prova a fiacao de `main`, e nenhum outro a exercita: o
    de `_executar` pula `main`, e o de argumento faltando morre no `argparse`
    antes de tocar o banco. Trocar `autor=args.motivo, motivo=args.autor` no
    `asyncio.run` de `main` passava em tudo.

    Sincrono de proposito -- ver `_fabrica_isolada`. A chave e unica por
    execucao porque este teste nao pode contar com a limpeza do banco
    (a fixture que trunca e async, e este teste nao roda em event loop
    nenhum): filtrar por uma chave que so ele usa deixa o resto da tabela
    irrelevante.
    """
    # `main` chamaria o `get_sessionmaker` global, e o engine cacheado la
    # ficaria preso ao loop que o `asyncio.run` de `main` fecha na saida --
    # envenenando o proximo teste que abrisse uma sessao. Descartar esse
    # engine de fora nao e opcao: `engine.dispose()` fecha as conexoes, e
    # fechar conexao asyncpg de um loop diferente do que a criou levanta
    # "attached to a different loop". A fabrica isolada resolve pela raiz --
    # ver `_fabrica_isolada`. O que este teste prova continua intacto: a
    # fiacao `args.* -> kwarg`, que nao passa pelo sessionmaker.
    monkeypatch.setattr("mobia.admin.reativar.get_sessionmaker", _fabrica_isolada)
    # Numero unico por execucao, sempre celular valido: 9 e oito digitos.
    telefone_cru = f"55489{uuid.uuid4().int % 10**8:08d}"
    asyncio.run(_registrar_identidade(telefone_cru))

    codigo = main(
        ["--channel", "whatsapp", "--key", telefone_cru, "--autor", AUTOR, "--motivo", MOTIVO]
    )

    assert codigo == 0
    assert asyncio.run(
        _reativacao_gravada(channel="whatsapp", key=chave_de("whatsapp", telefone_cru))
    ) == (AUTOR, MOTIVO)


async def _registrar_identidade(wa_id: str) -> None:
    async with _fabrica_isolada()() as sessao:
        await registrar(sessao, "whatsapp", wa_id)
        await sessao.commit()


async def test_duas_conversas_do_mesmo_numero_exigem_o_wa_id_exato(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Com e sem o 9 sao duas conversas, e o numero sem o DDI nao diz qual.
    O `wa_id` exato diz -- e so a conversa dele e reativada."""
    com_o_nove = await _lead_em_optout(session, session_factory, "5548999998888")
    sem_o_nove = await _lead_em_optout(session, session_factory, "554899998888")

    assert await _executar(channel="whatsapp", key="48999998888", autor=AUTOR, motivo=MOTIVO) == 1
    assert await _executar(channel="whatsapp", key="554899998888", autor=AUTOR, motivo=MOTIVO) == 0

    assert await esta_em_optout(session, channel="whatsapp", conversation_key=sem_o_nove) is False
    assert await esta_em_optout(session, channel="whatsapp", conversation_key=com_o_nove) is True
