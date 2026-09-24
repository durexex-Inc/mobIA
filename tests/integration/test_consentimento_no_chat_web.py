"""O evento `consentimento` do chat web. TEC-363, RN-FE-20.2.

Os dois cenarios do Gherkin da card, mais o que o protocolo tem de continuar
fazendo depois de ganhar um ramo novo.
"""

from datetime import UTC, datetime

from sqlalchemy import select

from mobia.domain.consentimento.models import Consentimento
from mobia.domain.consentimento.repositorio import tem_consentimento_de_marketing
from mobia.domain.messages.canais import CANAL_WEB

AVISO = "Ao continuar, voce aceita receber ofertas de imoveis por WhatsApp."


async def _cumprimentar(ws) -> str:
    await ws.aceitar()
    await ws.enviar({"tipo": "ola", "sessao": None})
    frame = await ws.receber()
    assert frame["tipo"] == "sessao"
    return str(frame["sessao"])


async def test_aceite_guarda_texto_data_hora_e_canal(ws_cliente, session) -> None:
    """O primeiro cenario do Gherkin, item por item."""
    exibido = datetime(2026, 9, 24, 18, 30, tzinfo=UTC)

    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)
        await ws.enviar(
            {
                "tipo": "consentimento",
                "marketing": True,
                "textoExibido": AVISO,
                "exibidoEm": exibido.isoformat(),
            }
        )
        assert await ws.receber() == {"tipo": "consentimento_registrado"}

    linha = (
        await session.execute(select(Consentimento).where(Consentimento.conversation_key == sessao))
    ).scalar_one()
    assert linha.channel == CANAL_WEB
    assert linha.marketing is True
    assert linha.texto_exibido == AVISO
    assert linha.exibido_em == exibido
    # A data que serve de evidencia e a do Postgres, e nao a do cliente.
    assert linha.created_at is not None
    assert linha.created_at != exibido


async def test_quem_nao_aceitou_NAO_fica_com_consentimento_de_marketing(
    ws_cliente, session
) -> None:
    """O segundo cenario do Gherkin, e a D3 do desenho junto.

    A recusa VIRA linha -- e evidencia de que o aviso foi exibido e de que a
    resposta foi nao. O que o criterio de aceite afirma, e o que este teste
    exercita, e que ela nao acaba com consentimento: a pergunta se faz por
    `tem_consentimento_de_marketing`, e nao contando linhas.
    """
    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)
        await ws.enviar({"tipo": "consentimento", "marketing": False, "textoExibido": AVISO})
        assert await ws.receber() == {"tipo": "consentimento_registrado"}

    assert not await tem_consentimento_de_marketing(
        session, channel=CANAL_WEB, conversation_key=sessao
    )

    linha = (
        await session.execute(select(Consentimento).where(Consentimento.conversation_key == sessao))
    ).scalar_one()
    assert linha.marketing is False
    assert linha.texto_exibido == AVISO


async def test_o_ultimo_evento_vence_quando_a_pessoa_muda_de_ideia(ws_cliente, session) -> None:
    """Append-only: a revogacao nao apaga o aceite, so passa a valer."""
    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)
        for marketing in (True, False):
            await ws.enviar(
                {"tipo": "consentimento", "marketing": marketing, "textoExibido": AVISO}
            )
            assert await ws.receber() == {"tipo": "consentimento_registrado"}

    assert not await tem_consentimento_de_marketing(
        session, channel=CANAL_WEB, conversation_key=sessao
    )
    linhas = (
        (
            await session.execute(
                select(Consentimento).where(Consentimento.conversation_key == sessao)
            )
        )
        .scalars()
        .all()
    )
    assert len(linhas) == 2, "a evidencia do aceite anterior tem de continuar la"


async def test_sem_evento_nao_ha_consentimento(session) -> None:
    """Ausencia e `False`, e nao erro.

    Sem esta asserta, a de cima seria asserta de ausencia sempre satisfeita:
    passaria igual se a funcao devolvesse `False` para tudo (TEC-289).
    """
    assert not await tem_consentimento_de_marketing(
        session, channel=CANAL_WEB, conversation_key="sessao-que-nunca-existiu"
    )


async def test_marketing_que_nao_e_booleano_e_recusado_SEM_fechar(ws_cliente, session) -> None:
    """Coagir aceitaria `"nao"` e `0` como resposta, e uma string nao vazia
    viraria consentimento. Num registro que serve de prova, recusar e melhor.
    """
    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)
        await ws.enviar({"tipo": "consentimento", "marketing": "nao", "textoExibido": AVISO})
        assert await ws.receber() == {"tipo": "erro", "motivo": "consentimento_invalido"}

        # E o socket continua servindo: a recusa nao custa a conversa.
        await ws.enviar({"tipo": "mensagem", "id": "m-1", "texto": "e o apartamento?"})
        assert await ws.receber() == {"tipo": "recebido", "id": "m-1"}

    assert (
        await session.execute(select(Consentimento).where(Consentimento.conversation_key == sessao))
    ).first() is None


async def test_aviso_vazio_e_recusado_sem_fechar(ws_cliente) -> None:
    """Sem o texto nao ha evidencia: gravar seria fingir que ha."""
    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        await ws.enviar({"tipo": "consentimento", "marketing": True, "textoExibido": "   "})
        assert await ws.receber() == {"tipo": "erro", "motivo": "aviso_ausente"}


async def test_aviso_longo_demais_e_recusado_sem_fechar(ws_cliente) -> None:
    """Entrada de cliente indo para uma coluna -- a mesma licao do teto do
    `id`, tres funcoes acima no modulo."""
    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        await ws.enviar({"tipo": "consentimento", "marketing": True, "textoExibido": "a" * 4001})
        assert await ws.receber() == {"tipo": "erro", "motivo": "aviso_longo_demais"}


async def test_exibido_em_ilegivel_nao_custa_o_registro(ws_cliente, session) -> None:
    """O carimbo do cliente e diagnostico; a evidencia e o `created_at`.

    Perder o registro por causa de um campo auxiliar seria trocar o que
    importa pelo que nao importa.
    """
    async with ws_cliente() as ws:
        sessao = await _cumprimentar(ws)
        await ws.enviar(
            {
                "tipo": "consentimento",
                "marketing": True,
                "textoExibido": AVISO,
                "exibidoEm": "ontem de tarde",
            }
        )
        assert await ws.receber() == {"tipo": "consentimento_registrado"}

    linha = (
        await session.execute(select(Consentimento).where(Consentimento.conversation_key == sessao))
    ).scalar_one()
    assert linha.exibido_em is None
    assert linha.marketing is True


async def test_frame_desconhecido_CONTINUA_fechando_com_1002(ws_cliente) -> None:
    """A regressao que o ramo novo poderia causar.

    `consentimento` entrou antes do `close(1002)` que todo frame desconhecido
    leva. Afrouxar essa checagem junto nao reprovaria em mais nada.
    """
    async with ws_cliente() as ws:
        await _cumprimentar(ws)
        await ws.enviar({"tipo": "inventado", "seja_la_o_que": 1})
        assert await ws.fechamento() == 1002
