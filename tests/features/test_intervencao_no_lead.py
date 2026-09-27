"""Criterios de aceite da TEC-194 como testes executaveis. RF-18, RN-18.3, RN-18.4.

Os quatro cenarios do Gherkin da card, e o que o desenho acrescentou: os
desfechos do envio (D3), as duas guardas vistas pela fala do corretor, a trilha
da edicao (D4), o autor na trilha de score (D6) e o vinculo de corretor (D2).
E o 409 de assumir com o nome de quem tem a conversa (TEC-327, D3).

**A porta de saida e falsa, mas as guardas sao as de verdade.** `PortaFalsa`
herda de `GuardedOutbound` e so troca `_deliver`: e o que deixa o teste afirmar
que a fala atravessa a guarda de atendimento humano e e barrada pela de
opt-out -- uma porta falsa sem as guardas passaria nos dois casos, e o teste
de opt-out afirmaria so o que ele mesmo montou.

**O terceiro cenario e exercitado pelo que a rota faz, e nao pelo que ele
promete** (L2 do desenho): o fator de catalogo e sempre zero, entao "o
catalogo mudou" nao move o score. O teste afirma a linha nova com
`RECALCULO_MANUAL`, que e o "novo score e gravado com o motivo" da card.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import _corretor
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.app.main import create_app
from mobia.domain.atendimento.models import AtendimentoHumano
from mobia.domain.atendimento.repositorio import esta_silenciada
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.vocabulario import Acao
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status as StatusDoHandoff
from mobia.domain.leads.repositorio import referencias_para
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import registrar_optout
from mobia.domain.outbound.kinds import KIND_DA_RESPOSTA, kind_da_fala_do_corretor
from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRetentavel, GuardedOutbound
from mobia.domain.usuarios import tokens
from mobia.infra.crypto import aad_de, decrypt, encrypt
from mobia.infra.db import get_sessionmaker

ROTA = "/api/v1/leads"
CANAL = "whatsapp"
TELEFONE = "5548990000021"
NOSSO_NUMERO = "554830000000"


class PortaFalsa(GuardedOutbound):
    """As guardas de verdade, e a entrega registrada em vez de feita."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(session_factory)
        self.entregues: list[tuple[str, dict[str, Any]]] = []
        self.falha: Exception | None = None

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        if self.falha is not None:
            raise self.falha
        self.entregues.append((kind, payload))


@pytest.fixture
def porta() -> PortaFalsa:
    return PortaFalsa(get_sessionmaker())


@pytest.fixture
async def cliente(
    banco_limpo: None, redis_pool: Any, porta: PortaFalsa
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.state.redis_pool = redis_pool
    app.state.outbound = porta
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def _bearer(papel: str, *, corretor_id: uuid.UUID | None = None) -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=corretor_id, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


async def _lead(
    session: AsyncSession,
    *,
    dono: uuid.UUID | None,
    chave: str = TELEFONE,
    falou_em: datetime | None = None,
    orcamento: int | None = None,
) -> uuid.UUID:
    """Um lead que falou, com handoff para `dono` e qualificacao opcional."""
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            conversation_key=chave,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            sender_external_id=chave,
            recipient_external_id=NOSSO_NUMERO,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            # Um minuto no passado: a fala do corretor e carimbada pelo `now()`
            # do Postgres, e o relogio do container pode estar atras do host --
            # com `datetime.now` aqui a transcricao sairia fora de ordem.
            created_at=falou_em or datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    if orcamento is not None:
        session.add(
            LeadQualification(
                channel=CANAL,
                conversation_key=chave,
                intencao="COMPRA",
                faixa_preco_max_centavos=orcamento,
                regiao="Campeche",
            )
        )
    if dono is not None:
        agora = datetime.now(UTC)
        session.add(
            Handoff(
                id=uuid.uuid4(),
                channel=CANAL,
                conversation_key=chave,
                gatilho="PEDIU_HUMANO",
                etiqueta="PEDIU_HUMANO",
                prioridade="NORMAL",
                status=StatusDoHandoff.PENDENTE.value,
                corretor_id=dono,
                criado_em=agora,
                atualizado_em=agora,
            )
        )
    await session.commit()
    apelidos = await referencias_para(session, [(CANAL, chave)])
    await session.commit()
    return apelidos[(CANAL, chave)]


async def _eventos(session: AsyncSession, acao: Acao) -> list[EventoAuditoria]:
    return list(
        (await session.execute(select(EventoAuditoria).where(EventoAuditoria.acao == acao.value)))
        .scalars()
        .all()
    )


async def _trilha_de_score(session: AsyncSession) -> list[LeadScoreAudit]:
    return list(
        (
            await session.execute(
                select(LeadScoreAudit)
                .where(LeadScoreAudit.conversation_key == TELEFONE)
                .order_by(LeadScoreAudit.created_at)
            )
        )
        .scalars()
        .all()
    )


# --- os quatro cenarios do Gherkin ---------------------------------------------


async def test_enviar_pelo_dashboard_chega_ao_lead_e_silencia_o_agente(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    """Cenario 1. A fala sai pelo canal do lead, vira linha CORRETOR na
    transcricao, e a conversa fica assumida por quem falou."""
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)

    resposta = await cliente.post(
        f"{ROTA}/{lead_id}/mensagens",
        json={"texto": "Oi, aqui e o Paulo"},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert resposta.status_code == 201, resposta.text
    ((kind, payload),) = porta.entregues
    assert kind.startswith("corretor:")
    assert payload == {"para": TELEFONE, "de": NOSSO_NUMERO, "texto": "Oi, aqui e o Paulo"}
    assert await esta_silenciada(session, channel=CANAL, conversation_key=TELEFONE)

    fala = await session.get(Message, uuid.UUID(resposta.json()["id"]))
    assert fala is not None
    assert (fala.role, fala.direction) == (MessageRole.CORRETOR, MessageDirection.OUTBOUND)
    assert decrypt(fala.text_body, aad_de(fala.id, "text_body")) == "Oi, aqui e o Paulo"

    transcricao = await cliente.get(
        f"{ROTA}/{lead_id}/mensagens", headers=_bearer("CORRETOR", corretor_id=paulo)
    )
    assert [i["autor"] for i in transcricao.json()["itens"]] == ["LEAD", "CORRETOR"]


async def test_edicao_de_orcamento_recalcula_e_registra_o_autor(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    """Cenario 2, com os numeros da card: de R$ 500.000 para R$ 800.000."""
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo, orcamento=50_000_000)
    usuario = uuid.uuid4()
    token = tokens.emitir(
        usuario, "CORRETOR", mfa=False, corretor_id=paulo, settings=get_settings()
    )

    resposta = await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao",
        json={"faixaPrecoMaxCentavos": 80_000_000},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["alterados"] == ["faixaPrecoMaxCentavos"]
    assert corpo["scoreAtual"] is not None

    (linha,) = await _trilha_de_score(session)
    assert "EDICAO_MANUAL" in linha.causas
    assert linha.autor == str(usuario)

    (evento,) = await _eventos(session, Acao.QUALIFICACAO_ALTERADA)
    assert (evento.campo, evento.ator_id) == ("faixaPrecoMaxCentavos", str(usuario))
    assert evento.criado_em is not None
    assert "80000000" not in str(evento.detalhes)


async def test_forcar_recalculo_grava_o_motivo_manual(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    """Cenario 3. A linha nasce mesmo com o total igual ao anterior."""
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo, orcamento=50_000_000)
    cabecalho = _bearer("CORRETOR", corretor_id=paulo)
    await cliente.post(f"{ROTA}/{lead_id}/score/recalcular", headers=cabecalho)

    resposta = await cliente.post(f"{ROTA}/{lead_id}/score/recalcular", headers=cabecalho)

    assert resposta.status_code == 200, resposta.text
    linhas = await _trilha_de_score(session)
    assert len(linhas) == 2
    assert linhas[-1].causas == ["RECALCULO_MANUAL"]
    assert linhas[-1].total_anterior == linhas[-1].total_novo


async def test_devolver_a_conversa_reativa_o_agente_e_registra(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    """Cenario 4. `devolvido_por` e `devolvido_em` sao o registro (D7)."""
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)
    cabecalho = _bearer("CORRETOR", corretor_id=paulo)
    await cliente.post(f"{ROTA}/{lead_id}/assumir", headers=cabecalho)

    resposta = await cliente.post(f"{ROTA}/{lead_id}/devolver", headers=cabecalho)

    assert resposta.status_code == 200, resposta.text
    assert not await esta_silenciada(session, channel=CANAL, conversation_key=TELEFONE)
    atendimento = (
        await session.execute(
            select(AtendimentoHumano).where(AtendimentoHumano.conversation_key == TELEFONE)
        )
    ).scalar_one()
    assert atendimento.devolvido_por == paulo
    assert atendimento.devolvido_em is not None


# --- os desfechos do envio (D3) ------------------------------------------------


async def test_janela_fechada_e_409_e_nao_grava_fala(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)
    porta.falha = EnvioForaDaJanela("131047")

    resposta = await cliente.post(
        f"{ROTA}/{lead_id}/mensagens",
        json={"texto": "oi"},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert (resposta.status_code, resposta.json()["detail"]) == (409, "janela_fechada")
    assert await _falas_do_corretor(session) == []


async def test_falha_do_canal_e_502_e_nao_grava_fala(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)
    porta.falha = EnvioRetentavel("503")

    resposta = await cliente.post(
        f"{ROTA}/{lead_id}/mensagens",
        json={"texto": "oi"},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert (resposta.status_code, resposta.json()["detail"]) == (502, "canal_falhou")
    assert await _falas_do_corretor(session) == []


async def test_lead_em_optout_nao_recebe_nem_do_corretor(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    """D3, decisao do Eduardo: a guarda de opt-out vale para gente tambem."""
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)
    mensagem = (await session.execute(select(Message.id))).scalar_one()
    await registrar_optout(
        get_sessionmaker(), channel=CANAL, conversation_key=TELEFONE, message_id=mensagem
    )

    resposta = await cliente.post(
        f"{ROTA}/{lead_id}/mensagens",
        json={"texto": "oi"},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert (resposta.status_code, resposta.json()["detail"]) == (409, "lead_em_optout")
    assert porta.entregues == []


async def test_duas_falas_seguidas_saem_as_duas(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    """O kind por fala: as duas ancoram na mesma mensagem do lead, e um kind
    fixo faria a segunda ser suprimida como reentrega."""
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)
    cabecalho = _bearer("CORRETOR", corretor_id=paulo)

    for texto in ("primeira", "segunda"):
        resposta = await cliente.post(
            f"{ROTA}/{lead_id}/mensagens", json={"texto": texto}, headers=cabecalho
        )
        assert resposta.status_code == 201, resposta.text

    assert [p["texto"] for _, p in porta.entregues] == ["primeira", "segunda"]


async def test_conversa_de_outro_corretor_e_409(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    """Nao se fala por cima de um colega. O GERENTE assume em nome dele e o
    CORRETOR dono do lead tenta falar."""
    paulo = await _corretor(session)
    gerente = await _corretor(session, gerente=True)
    lead_id = await _lead(session, dono=paulo)
    await cliente.post(f"{ROTA}/{lead_id}/assumir", headers=_bearer("GERENTE", corretor_id=gerente))

    resposta = await cliente.post(
        f"{ROTA}/{lead_id}/mensagens",
        json={"texto": "oi"},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert (resposta.status_code, resposta.json()["detail"]) == (409, "conversa_de_outro")
    assert porta.entregues == []


async def test_assumir_conversa_de_outro_e_409_com_o_nome_e_o_dono_nao_muda(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    """Terceiro cenario da TEC-327: a tela diz com quem a conversa esta (D3)."""
    paulo = await _corretor(session)
    ana = await _corretor(session, gerente=True)
    await session.execute(update(Corretor).where(Corretor.id == ana).values(nome="Ana"))
    await session.commit()
    lead_id = await _lead(session, dono=paulo)
    await cliente.post(f"{ROTA}/{lead_id}/assumir", headers=_bearer("GERENTE", corretor_id=ana))

    resposta = await cliente.post(
        f"{ROTA}/{lead_id}/assumir", headers=_bearer("CORRETOR", corretor_id=paulo)
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"] == {
        "motivo": "conversa_de_outro",
        "assumidoPor": {"corretorId": str(ana), "nome": "Ana"},
    }
    dono = await session.scalar(
        select(AtendimentoHumano.assumido_por).where(AtendimentoHumano.conversation_key == TELEFONE)
    )
    assert dono == ana


async def test_texto_vazio_ou_longo_demais_e_422(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)
    cabecalho = _bearer("CORRETOR", corretor_id=paulo)

    for texto in ("   ", "x" * 4097):
        resposta = await cliente.post(
            f"{ROTA}/{lead_id}/mensagens", json={"texto": texto}, headers=cabecalho
        )
        assert resposta.status_code == 422


async def _falas_do_corretor(session: AsyncSession) -> list[Message]:
    return list(
        (await session.execute(select(Message).where(Message.role == MessageRole.CORRETOR)))
        .scalars()
        .all()
    )


# --- a guarda de atendimento humano --------------------------------------------


async def test_so_a_fala_do_corretor_atravessa_a_guarda_de_silencio(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    """Com a conversa assumida, o kind do agente continua barrado e o do
    corretor passa. E a outra metade do cenario 1: o agente CALA."""
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)
    await cliente.post(f"{ROTA}/{lead_id}/assumir", headers=_bearer("CORRETOR", corretor_id=paulo))
    mensagem = (await session.execute(select(Message.id))).scalar_one()
    payload = {"para": TELEFONE, "de": NOSSO_NUMERO, "texto": "x"}

    do_agente = await porta.send(mensagem, KIND_DA_RESPOSTA, payload)
    do_corretor = await porta.send(mensagem, kind_da_fala_do_corretor(uuid.uuid4()), payload)

    assert (do_agente, do_corretor) == (False, True)


# --- a edicao (D4) -------------------------------------------------------------


async def test_campo_com_o_mesmo_valor_nao_conta_como_alterado(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo, orcamento=50_000_000)

    resposta = await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao",
        json={"faixaPrecoMaxCentavos": 50_000_000, "quartos": 3},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert resposta.json()["alterados"] == ["quartos"]
    assert [e.campo for e in await _eventos(session, Acao.QUALIFICACAO_ALTERADA)] == ["quartos"]


async def test_nada_alterado_nao_grava_trilha_nenhuma(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo, orcamento=50_000_000)

    resposta = await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao",
        json={"faixaPrecoMaxCentavos": 50_000_000},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert resposta.json()["alterados"] == []
    assert await _trilha_de_score(session) == []
    assert await _eventos(session, Acao.QUALIFICACAO_ALTERADA) == []


async def test_null_explicito_limpa_e_ausente_nao_muda(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo, orcamento=50_000_000)

    await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao",
        json={"regiao": None},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    await session.commit()
    linha = (
        await session.execute(
            select(LeadQualification)
            .where(LeadQualification.conversation_key == TELEFONE)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert (linha.regiao, linha.faixa_preco_max_centavos) == (None, 50_000_000)


@pytest.mark.parametrize(
    ("digitado", "gravado"),
    [
        ("Perto do Campeche", "campeche"),
        ("  Lagoa da Conceição ", "lagoa da conceicao"),
        ("perto da", None),
    ],
)
async def test_regiao_editada_e_gravada_na_forma_canonica(
    session: AsyncSession, cliente: AsyncClient, digitado: str, gravado: str | None
) -> None:
    """TEC-329, D1: a correcao manual nao e a porta que grava regiao fora da forma do agente.

    O filtro estruturado da TEC-158 compara `regiao` por igualdade -- "Perto do
    Campeche" nunca casaria com o `campeche` do catalogo.
    """
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo, orcamento=50_000_000)

    resposta = await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao",
        json={"regiao": digitado},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert resposta.status_code == 200
    await session.commit()
    linha = (
        await session.execute(
            select(LeadQualification)
            .where(LeadQualification.conversation_key == TELEFONE)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert linha.regiao == gravado


@pytest.mark.parametrize(
    "corpo",
    [
        {"urgencia": "ONTEM"},
        {"intencao": "ALUGUEL"},
        {"quartos": -1},
        {"faixaPrecoMinCentavos": 90_000_000},
    ],
    ids=["enumerado-fora", "intencao-nao-editavel", "negativo", "faixa-invertida"],
)
async def test_edicao_invalida_e_422(
    session: AsyncSession, cliente: AsyncClient, corpo: dict[str, object]
) -> None:
    """A faixa invertida e conferida contra o maximo que JA havia (80 mil
    abaixo do minimo pedido), e nao so contra o pedido."""
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo, orcamento=50_000_000)

    resposta = await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao",
        json=corpo,
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert resposta.status_code == 422, resposta.text


async def test_conversa_encerrada_nao_se_edita(session: AsyncSession, cliente: AsyncClient) -> None:
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo, orcamento=50_000_000)
    session.add(
        Conversa(
            channel=CANAL,
            conversation_key=TELEFONE,
            status=Status.ENCERRADA.value,
            motivo_do_encerramento=MotivoDoEncerramento.INATIVIDADE.value,
            encerrada_em=datetime.now(UTC),
        )
    )
    await session.commit()

    resposta = await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao",
        json={"quartos": 2},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert (resposta.status_code, resposta.json()["detail"]) == (409, "conversa_encerrada")


async def test_recalcular_sem_qualificacao_e_409(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    paulo = await _corretor(session)
    lead_id = await _lead(session, dono=paulo)

    resposta = await cliente.post(
        f"{ROTA}/{lead_id}/score/recalcular", headers=_bearer("CORRETOR", corretor_id=paulo)
    )

    assert resposta.status_code == 409


# --- o recorte e o vinculo (D2) ------------------------------------------------


async def test_corretor_de_outro_lead_leva_403_nas_cinco_rotas(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    paulo = await _corretor(session)
    marcia = await _corretor(session)
    lead_id = await _lead(session, dono=marcia, orcamento=50_000_000)
    cabecalho = _bearer("CORRETOR", corretor_id=paulo)

    respostas = [
        await cliente.post(f"{ROTA}/{lead_id}/assumir", headers=cabecalho),
        await cliente.post(f"{ROTA}/{lead_id}/devolver", headers=cabecalho),
        await cliente.post(f"{ROTA}/{lead_id}/mensagens", json={"texto": "oi"}, headers=cabecalho),
        await cliente.patch(
            f"{ROTA}/{lead_id}/qualificacao", json={"quartos": 2}, headers=cabecalho
        ),
        await cliente.post(f"{ROTA}/{lead_id}/score/recalcular", headers=cabecalho),
    ]

    assert [r.status_code for r in respostas] == [403] * 5
    assert porta.entregues == []
    assert len(await _eventos(session, Acao.ACESSO_NEGADO)) == 5


async def test_leitura_nao_intervem(session: AsyncSession, cliente: AsyncClient) -> None:
    lead_id = await _lead(session, dono=None, orcamento=50_000_000)

    resposta = await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao", json={"quartos": 2}, headers=_bearer("LEITURA")
    )

    assert resposta.status_code == 403


async def test_gerente_sem_cadastro_de_corretor_nao_fala_mas_edita(
    session: AsyncSession, cliente: AsyncClient, porta: PortaFalsa
) -> None:
    """D2, decisao do Eduardo: falar e assumir exigem um corretor em nome de
    quem gravar o atendimento; editar a ficha, nao."""
    lead_id = await _lead(session, dono=None, orcamento=50_000_000)
    cabecalho = _bearer("GERENTE")

    fala = await cliente.post(
        f"{ROTA}/{lead_id}/mensagens", json={"texto": "oi"}, headers=cabecalho
    )
    edicao = await cliente.patch(
        f"{ROTA}/{lead_id}/qualificacao", json={"quartos": 2}, headers=cabecalho
    )

    assert fala.status_code == 409
    assert porta.entregues == []
    assert edicao.status_code == 200, edicao.text


async def test_as_rotas_antigas_continuam_aceitando_o_handoff_junto(
    session: AsyncSession, cliente: AsyncClient
) -> None:
    """A extracao para `tomada.py` nao pode ter mudado o efeito da D6."""
    paulo = await _corretor(session)
    await _lead(session, dono=paulo, falou_em=datetime.now(UTC) - timedelta(minutes=1))

    resposta = await cliente.post(
        "/api/v1/conversas/assumir",
        json={"channel": CANAL, "conversation_key": TELEFONE, "corretor_id": str(paulo)},
        headers=_bearer("CORRETOR", corretor_id=paulo),
    )

    assert resposta.status_code == 200, resposta.text
    status_do_handoff = (
        await session.execute(
            select(Handoff.status)
            .where(Handoff.conversation_key == TELEFONE)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert status_do_handoff == StatusDoHandoff.ACEITO.value
