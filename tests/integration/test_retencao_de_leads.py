"""A retencao do lead: transcricao de 12 meses, lead parado ha 24. TEC-207, D5.

**Para antedatar, os testes envelhecem via `clock_timestamp()` do banco**,
como `test_retencao_da_auditoria.py`: um `UPDATE ... SET created_at =
clock_timestamp() - make_interval(...)` depois de semear com `conftest.py`,
e nao um `datetime.now()` do processo de teste -- a retencao le contra o
relogio do banco, e um teste que gravasse a idade de outro jeito nao
provaria nada sobre o corte real.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import _falar, _handoff_aceito, _lead
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA
from mobia.domain.context.models import aad_do_resumo
from mobia.domain.identidade import indice
from mobia.domain.midia.armazem import ArmazemLocal
from mobia.domain.midia.politica import chave_do_objeto
from mobia.domain.titular import eliminacao
from mobia.domain.titular import retencao as retencao_mod
from mobia.domain.titular.repositorio import registrar_solicitacao
from mobia.domain.titular.retencao import (
    anonimizar_leads_vencidos,
    cumprir_eliminacoes_a_vencer,
    esvaziar_transcricoes_vencidas,
)
from mobia.domain.titular.vocabulario import OrigemDaSolicitacao, TipoDeSolicitacao
from mobia.infra.crypto import encrypt
from mobia.workers.jobs.sweep_retencao_de_leads import sweep_retencao_de_leads

CANAL = "whatsapp"


async def _envelhecer(session: AsyncSession, *, conversa: str, meses: int) -> None:
    """Poe toda mensagem do par com a idade pedida, pelo relogio do banco."""
    await session.execute(
        text(
            "UPDATE messages SET created_at = clock_timestamp() - make_interval(months => :meses)"
            " WHERE conversation_key = :k"
        ),
        {"meses": meses, "k": conversa},
    )
    await session.commit()


async def _com_identidade(session: AsyncSession, *, telefone: str, falas: int = 1) -> str:
    """Um lead com identidade registrada -- o par que a anonimizacao por
    retencao pode encontrar (ver a exclusao por `identidades_de_lead` na
    docstring de `domain/titular/retencao.py`)."""
    chave = await indice.registrar(session, CANAL, telefone)
    await session.commit()
    await _lead(session, conversa=chave, falas=falas)
    return chave


def _ctx(
    session_factory: async_sessionmaker[AsyncSession], armazem: ArmazemLocal
) -> dict[str, Any]:
    return {"session_factory": session_factory, "armazem": armazem}


async def _registrar_eliminacao(session: AsyncSession, *, conversa: str, prazo: str) -> Any:
    """Registra uma ELIMINACAO ABERTA e empurra o prazo para `prazo` (uma
    expressao de intervalo do Postgres, ex.: "now() - interval '1 day'")."""
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=conversa,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()
    await session.execute(
        text(f"UPDATE solicitacoes_de_titular SET prazo_em = {prazo} WHERE id = :id"),
        {"id": solicitacao_id},
    )
    await session.commit()
    return solicitacao_id


async def test_mensagem_de_13_meses_esvazia_e_apaga_midia_11_meses_fica_intacta(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Any
) -> None:
    conversa_velha = "conversa-13-meses"
    conversa_nova = "conversa-11-meses"
    await _lead(session, conversa=conversa_velha, falas=1)
    await _lead(session, conversa=conversa_nova, falas=1)

    id_velha = await session.scalar(
        text("SELECT id FROM messages WHERE conversation_key = :k"), {"k": conversa_velha}
    )
    armazem = ArmazemLocal(tmp_path)
    chave = chave_do_objeto(id_velha)
    await armazem.guardar(chave, b"blob-cifrado")
    await session.execute(
        text(
            "INSERT INTO midias_recebidas (message_id, media_id_da_meta, mime_type,"
            " chave_no_armazem, status) VALUES (:m, 'media-1', 'image/jpeg', :k, 'ARMAZENADA')"
        ),
        {"m": id_velha, "k": chave},
    )
    await session.commit()

    await _envelhecer(session, conversa=conversa_velha, meses=13)
    await _envelhecer(session, conversa=conversa_nova, meses=11)

    contagem = await esvaziar_transcricoes_vencidas(session_factory, armazem)

    assert contagem == 1
    async with session_factory() as sessao:
        velha = (
            await sessao.execute(
                text(
                    "SELECT text_body, raw_payload, envelope_context FROM messages"
                    " WHERE conversation_key = :k"
                ),
                {"k": conversa_velha},
            )
        ).one()
        assert velha == (None, None, None)
        nova = await sessao.scalar(
            text("SELECT text_body FROM messages WHERE conversation_key = :k"), {"k": conversa_nova}
        )
        assert nova is not None, "11 meses ainda nao venceu o corte de 12"
        assert await sessao.scalar(text("SELECT count(*) FROM midias_recebidas")) == 0
    assert not (tmp_path / chave).exists()


async def test_resumo_de_par_vencido_some_o_de_par_recente_fica(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Any
) -> None:
    conversa_velha = "conversa-resumo-velho"
    conversa_nova = "conversa-resumo-novo"
    await _lead(session, conversa=conversa_velha, falas=1)
    await _lead(session, conversa=conversa_nova, falas=1)
    for conversa in (conversa_velha, conversa_nova):
        watermark = await session.scalar(
            text("SELECT id FROM messages WHERE conversation_key = :k"), {"k": conversa}
        )
        await session.execute(
            text(
                "INSERT INTO conversation_summaries (channel, conversation_key, resumo,"
                " watermark_created_at, watermark_message_id, mensagens_cobertas, modelo)"
                " VALUES (:c, :k, :r, now(), :m, 1, 'modelo-de-teste')"
            ),
            {
                "c": CANAL,
                "k": conversa,
                "r": encrypt("resumo de teste", aad_do_resumo(CANAL, conversa)),
                "m": watermark,
            },
        )
    await session.commit()
    await _envelhecer(session, conversa=conversa_velha, meses=13)
    await _envelhecer(session, conversa=conversa_nova, meses=11)

    await esvaziar_transcricoes_vencidas(session_factory, ArmazemLocal(tmp_path))

    async with session_factory() as sessao:
        restantes = set(
            (
                await sessao.execute(text("SELECT conversation_key FROM conversation_summaries"))
            ).scalars()
        )
    assert restantes == {conversa_nova}


async def test_lead_sem_handoff_25_meses_e_anonimizado_23_meses_fica_intacto(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Any
) -> None:
    vencido = await _com_identidade(session, telefone="5548999990001")
    no_prazo = await _com_identidade(session, telefone="5548999990002")
    await _envelhecer(session, conversa=vencido, meses=25)
    await _envelhecer(session, conversa=no_prazo, meses=23)

    contagem = await anonimizar_leads_vencidos(session_factory, ArmazemLocal(tmp_path))

    assert contagem == 1
    async with session_factory() as sessao:
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM identidades_de_lead WHERE conversation_key = :k"),
                {"k": vencido},
            )
        ) == 0
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM identidades_de_lead WHERE conversation_key = :k"),
                {"k": no_prazo},
            )
        ) == 1
        solicitacao = (
            await sessao.execute(
                text("SELECT status, origem FROM solicitacoes_de_titular WHERE tipo = 'ELIMINACAO'")
            )
        ).one()
        assert tuple(solicitacao) == ("ATENDIDA", OrigemDaSolicitacao.RETENCAO.value)


async def test_lead_com_handoff_aceito_25_meses_nao_e_anonimizado_mas_conteudo_esvazia(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Any
) -> None:
    chave = await _com_identidade(session, telefone="5548999990003")
    await _handoff_aceito(session, conversa=chave, em=datetime.now(UTC))
    await _envelhecer(session, conversa=chave, meses=25)
    armazem = ArmazemLocal(tmp_path)

    await sweep_retencao_de_leads(_ctx(session_factory, armazem))

    async with session_factory() as sessao:
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM identidades_de_lead WHERE conversation_key = :k"),
                {"k": chave},
            )
        ) == 1, "handoff ACEITO protege da anonimizacao"
        conteudo = (
            await sessao.execute(
                text(
                    "SELECT text_body, raw_payload, envelope_context FROM messages"
                    " WHERE conversation_key = :k"
                ),
                {"k": chave},
            )
        ).all()
        assert all(linha == (None, None, None) for linha in conteudo), (
            "a regra de 12 meses e da transcricao, de qualquer lead"
        )


async def test_eliminacao_que_vence_ate_amanha_e_cumprida_a_de_3_dias_fica_aberta(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Any
) -> None:
    """O sweep passa uma vez por dia: cumprindo so o que ja venceu, todo pedido
    passaria do prazo. Com um dia de antecedencia, o de amanha e cumprido hoje
    (dentro do prazo), o ja vencido tambem (passagem perdida), e o de daqui a
    3 dias continua com o ADMIN."""
    await _lead(session, conversa="conversa-vencida", falas=1)
    await _lead(session, conversa="conversa-amanha", falas=1)
    await _lead(session, conversa="conversa-3-dias", falas=1)
    vencida_id = await _registrar_eliminacao(
        session, conversa="conversa-vencida", prazo="now() - interval '1 day'"
    )
    amanha_id = await _registrar_eliminacao(
        session, conversa="conversa-amanha", prazo="now() + interval '20 hours'"
    )
    tres_dias_id = await _registrar_eliminacao(
        session, conversa="conversa-3-dias", prazo="now() + interval '3 days'"
    )

    contagem = await cumprir_eliminacoes_a_vencer(session_factory, ArmazemLocal(tmp_path))

    assert contagem == 2
    async with session_factory() as sessao:
        status = dict(
            (await sessao.execute(text("SELECT id, status FROM solicitacoes_de_titular"))).all()
        )
    assert status[vencida_id] == "ATENDIDA"
    assert status[amanha_id] == "ATENDIDA"
    assert status[tres_dias_id] == "ABERTA"


async def test_sweep_rodado_duas_vezes_a_segunda_nao_muda_nada(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Any
) -> None:
    # Um de cada regra: transcricao vencida, lead sem handoff vencido, e uma
    # solicitacao de ELIMINACAO vencida.
    await _lead(session, conversa="conversa-transcricao", falas=1)
    await _envelhecer(session, conversa="conversa-transcricao", meses=13)

    chave_vencida = await _com_identidade(session, telefone="5548999990009")
    await _envelhecer(session, conversa=chave_vencida, meses=25)

    await _lead(session, conversa="conversa-solicitacao", falas=1)
    await _registrar_eliminacao(
        session, conversa="conversa-solicitacao", prazo="now() - interval '1 day'"
    )

    armazem = ArmazemLocal(tmp_path)
    ctx = _ctx(session_factory, armazem)

    primeira = await sweep_retencao_de_leads(ctx)
    assert primeira > 0

    async with session_factory() as sessao:
        solicitacoes_antes = sorted(
            (
                await sessao.execute(
                    text("SELECT id, tipo, status, origem FROM solicitacoes_de_titular")
                )
            ).all()
        )

    segunda = await sweep_retencao_de_leads(ctx)
    assert segunda == 0, "nada sobrou para a segunda passagem cumprir"

    async with session_factory() as sessao:
        solicitacoes_depois = sorted(
            (
                await sessao.execute(
                    text("SELECT id, tipo, status, origem FROM solicitacoes_de_titular")
                )
            ).all()
        )
    assert solicitacoes_depois == solicitacoes_antes, "nenhuma linha nova, nenhum status mudou"


async def test_lead_que_falha_nao_impede_os_outros_e_conteudo_esvazia_mesmo_assim(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IMPORTANT 1 da revisao: um lead que falha nao pode travar os outros
    nem impedir que a etapa seguinte (esvaziar transcricao) rode."""
    chave_ruim = await _com_identidade(session, telefone="5548999990020")
    chave_boa = await _com_identidade(session, telefone="5548999990021")
    await _envelhecer(session, conversa=chave_ruim, meses=25)
    await _envelhecer(session, conversa=chave_boa, meses=25)

    original = eliminacao.anonimizar

    async def _falha_para_a_ruim(
        session_factory: async_sessionmaker[AsyncSession],
        armazem: ArmazemLocal,
        *,
        solicitacao_id: Any,
    ) -> None:
        async with session_factory() as sessao:
            conversa = await sessao.scalar(
                text("SELECT conversation_key FROM solicitacoes_de_titular WHERE id = :id"),
                {"id": solicitacao_id},
            )
        if conversa == chave_ruim:
            raise RuntimeError("falha simulada")
        await original(session_factory, armazem, solicitacao_id=solicitacao_id)

    monkeypatch.setattr(eliminacao, "anonimizar", _falha_para_a_ruim)

    contagem = await anonimizar_leads_vencidos(session_factory, ArmazemLocal(tmp_path))

    assert contagem == 1, "a ruim falhou, so a boa conta"
    async with session_factory() as sessao:
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM identidades_de_lead WHERE conversation_key = :k"),
                {"k": chave_boa},
            )
        ) == 0
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM identidades_de_lead WHERE conversation_key = :k"),
                {"k": chave_ruim},
            )
        ) == 1, "a que falhou continua intacta, nao meio-anonimizada"

    # A etapa seguinte do sweep nao depende da anonimizacao ter dado certo: o
    # conteudo esvazia de qualquer jeito, porque 25 meses ja passou dos 12.
    await esvaziar_transcricoes_vencidas(session_factory, ArmazemLocal(tmp_path))
    async with session_factory() as sessao:
        linhas = (
            await sessao.execute(
                text("SELECT text_body FROM messages WHERE conversation_key = :k"),
                {"k": chave_ruim},
            )
        ).all()
    assert all(linha[0] is None for linha in linhas)


async def test_handoff_concluido_tambem_protege_da_anonimizacao(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession], tmp_path: Any
) -> None:
    chave = await _com_identidade(session, telefone="5548999990022")
    await _handoff_aceito(session, conversa=chave, em=datetime.now(UTC), status="CONCLUIDO")
    await _envelhecer(session, conversa=chave, meses=25)

    contagem = await anonimizar_leads_vencidos(session_factory, ArmazemLocal(tmp_path))

    assert contagem == 0
    async with session_factory() as sessao:
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM identidades_de_lead WHERE conversation_key = :k"),
                {"k": chave},
            )
        ) == 1


@pytest.mark.parametrize("status", ["PENDENTE", "ESCALADO"])
async def test_handoff_pendente_ou_escalado_nao_protege_e_lead_e_anonimizado(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Any,
    status: str,
) -> None:
    """So ACEITO e CONCLUIDO protegem (D5) -- os dois estados de handoff que
    ainda esperam alguem (PENDENTE, ESCALADO) nao impedem a anonimizacao."""
    chave = await _com_identidade(session, telefone="5548999990030")
    await _handoff_aceito(
        session, conversa=chave, em=datetime.now(UTC), status=status, ja_aceito=False
    )
    await _envelhecer(session, conversa=chave, meses=25)

    contagem = await anonimizar_leads_vencidos(session_factory, ArmazemLocal(tmp_path))

    assert contagem == 1
    async with session_factory() as sessao:
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM identidades_de_lead WHERE conversation_key = :k"),
                {"k": chave},
            )
        ) == 0


async def test_lead_ainda_vencido_fica_falso_apos_handoff_aceito(session: AsyncSession) -> None:
    chave = await _com_identidade(session, telefone="5548999990031")
    await _envelhecer(session, conversa=chave, meses=25)
    assert (
        await retencao_mod._lead_ainda_vencido(session, channel=CANAL, conversation_key=chave)
        is True
    )

    await _handoff_aceito(session, conversa=chave, em=datetime.now(UTC))

    assert (
        await retencao_mod._lead_ainda_vencido(session, channel=CANAL, conversation_key=chave)
        is False
    )


async def test_lead_ainda_vencido_fica_falso_apos_nova_mensagem(session: AsyncSession) -> None:
    chave = await _com_identidade(session, telefone="5548999990032")
    await _envelhecer(session, conversa=chave, meses=25)
    assert (
        await retencao_mod._lead_ainda_vencido(session, channel=CANAL, conversation_key=chave)
        is True
    )

    await _falar(session, conversa=chave, em=datetime.now(UTC))
    await session.commit()

    assert (
        await retencao_mod._lead_ainda_vencido(session, channel=CANAL, conversation_key=chave)
        is False
    )


async def test_lead_que_deixou_de_estar_vencido_e_pulado(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MINOR 3 da revisao: o lote e um snapshot, e o par pode ter deixado de
    valer a condicao entre a selecao e o processamento -- simulado aqui
    forcando `_lead_ainda_vencido` a negar, como uma mudanca concorrente
    faria."""
    chave = await _com_identidade(session, telefone="5548999990033")
    await _envelhecer(session, conversa=chave, meses=25)

    async def _nunca_mais_vencido(
        session: AsyncSession, *, channel: str, conversation_key: str
    ) -> bool:
        return False

    monkeypatch.setattr(retencao_mod, "_lead_ainda_vencido", _nunca_mais_vencido)

    contagem = await anonimizar_leads_vencidos(session_factory, ArmazemLocal(tmp_path))

    assert contagem == 0
    async with session_factory() as sessao:
        assert (
            await sessao.scalar(
                text("SELECT count(*) FROM identidades_de_lead WHERE conversation_key = :k"),
                {"k": chave},
            )
        ) == 1
        assert await sessao.scalar(text("SELECT count(*) FROM solicitacoes_de_titular")) == 0
