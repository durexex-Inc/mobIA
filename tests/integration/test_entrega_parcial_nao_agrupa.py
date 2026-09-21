"""A guarda de superacao nao pode descartar entrega parcial pendente.

TEC-128, onda final, Important 2. Cenario: o turno da mensagem A apresenta
tres fichas, so a primeira sai, e a mensagem vira FAILED; nos minutos de
silencio antes do sweeper reenfileirar, o lead manda uma mensagem B. Sem a
excecao, a retentativa de A se descobre superada por B e fecha como
"agrupado" -- as fichas 2 e 3 nunca saem, e as linhas de `recomendacoes` de A
ficam orfas. Ver `_tem_entrega_parcial_pendente` em
`workers/jobs/process_message.py`, que reusa a mesma consulta que
`executar_turno` usa para decidir o ramo de continuacao (TEC-275, D4).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from test_process_message_agrupado import _ctx  # type: ignore[import-not-found]
from test_rajada import gravar  # type: ignore[import-not-found]

from mobia.domain.agente.models import Recomendacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.outbound.models import OutboundDispatch
from mobia.workers.jobs.process_message import process_message

CANAL = "whatsapp"
LEAD = "5511911112222"


async def _imovel(session: Any, codigo: str, preco: int) -> uuid.UUID:
    """Copiado e nao importado de proposito -- os arquivos de integracao deste
    repo sao autocontidos. Molde de `_imovel` em `test_apresentacao_no_turno.py`.
    """
    identificador = uuid.uuid4()
    session.add(
        Imovel(
            id=identificador,
            codigo=codigo,
            titulo=f"Apartamento {codigo}",
            descricao="Sala ampla com varanda.",
            tipo="APARTAMENTO",
            operacao="VENDA",
            preco_venda=preco,
            condominio=55000,
            bairro="Lagoa da Conceicao",
            bairro_busca="lagoa da conceicao",
            cidade="Florianopolis",
            uf="SC",
            area_util_m2=54,
            quartos=4,
            suites=1,
            banheiros=2,
            vagas=2,
            caracteristicas=["churrasqueira", "mobiliado"],
            fotos=[f"https://exemplo.com/{codigo}.jpg"],
            status="DISPONIVEL",
        )
    )
    await session.commit()
    return identificador


async def test_entrega_parcial_pendente_nao_agrupa(session, redis_pool, monkeypatch) -> None:
    agora = datetime.now(UTC)
    mensagem_a = await gravar(session, created_at=agora, texto="mostra ai")
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="e os outros?")

    ids = [await _imovel(session, f"AP-{n:03d}", 50000000 + n) for n in range(3)]
    for posicao, imovel_id in enumerate(ids):
        session.add(
            Recomendacao(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=LEAD,
                imovel_id=imovel_id,
                score_match=Decimal("0.900") - Decimal(posicao) / 1000,
                motivo_match="3 quartos",
                apresentado_em=agora,
                message_id=mensagem_a.id,
                preco_centavos=50000000 + posicao,
                kind=f"ficha_{posicao + 1}",
            )
        )
    # So a ficha_1 saiu antes da falha -- ficha_2 e ficha_3 seguem sem reserva.
    session.add(OutboundDispatch(id=uuid.uuid4(), message_id=mensagem_a.id, kind="ficha_1"))
    await session.commit()

    rodou = {"turno": False}

    async def turno_espiao(*args, **kwargs):
        rodou["turno"] = True
        return "respondido"

    monkeypatch.setattr("mobia.workers.jobs.process_message.executar_turno", turno_espiao)

    resultado = await process_message(_ctx(), str(mensagem_a.id))

    assert rodou["turno"] is True
    assert resultado != "agrupado"


async def test_apresentacao_sem_reserva_nenhuma_continua_agrupando(
    session, redis_pool, monkeypatch
) -> None:
    """Controle: lote existe, mas NADA saiu (nenhum kind reservado) -- o ramo
    (a) do comentario de `turno.py` em torno de 1373-1376, "nao e continuar, e
    recomecar". Sem reserva nenhuma nao ha entrega parcial, e a mensagem
    superada continua agrupando.
    """
    agora = datetime.now(UTC)
    mensagem_a = await gravar(session, created_at=agora, texto="mostra ai")
    await gravar(session, created_at=agora + timedelta(seconds=1), texto="e os outros?")

    imovel_id = await _imovel(session, "AP-900", 50000000)
    session.add(
        Recomendacao(
            id=uuid.uuid4(),
            channel=CANAL,
            conversation_key=LEAD,
            imovel_id=imovel_id,
            score_match=Decimal("0.900"),
            motivo_match="3 quartos",
            apresentado_em=agora,
            message_id=mensagem_a.id,
            preco_centavos=50000000,
            kind="ficha_1",
        )
    )
    await session.commit()

    async def turno_que_nao_devia_rodar(*args, **kwargs):
        raise AssertionError("executar_turno rodou para uma mensagem superada sem entrega parcial")

    monkeypatch.setattr(
        "mobia.workers.jobs.process_message.executar_turno", turno_que_nao_devia_rodar
    )

    resultado = await process_message(_ctx(), str(mensagem_a.id))

    assert resultado == "agrupado"
