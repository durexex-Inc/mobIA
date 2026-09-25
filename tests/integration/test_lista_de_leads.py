"""Os quatro cenarios do Gherkin da TEC-192, contra banco de verdade.

Mais os que o desenho acrescentou: o empate de score (D5), a busca por telefone
nas duas origens (D3), o lead sem score (D4) e a escrita de
`handoffs.corretor_id` (D6), que e o que torna o terceiro cenario exercitavel.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status as StatusDoHandoff
from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.usuarios import tokens

ROTA = "/api/v1/leads"


def _bearer(papel: str, *, corretor_id: uuid.UUID | None = None) -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=corretor_id, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


async def _lead(
    session: AsyncSession,
    *,
    chave: str,
    score: int | None = None,
    regiao: str | None = None,
    temperatura: str | None = None,
    canal: str = "whatsapp",
    dono: uuid.UUID | None = None,
    encerrada: bool = False,
    falou_em: datetime | None = None,
) -> str:
    """Um lead com o minimo para aparecer na lista: uma mensagem.

    **A mensagem e obrigatoria e as outras tabelas nao**, porque a espinha
    dorsal da consulta e `messages` (D1). Semear qualificacao sem mensagem
    produziria um lead que a lista nao mostra -- e o teste passaria a afirmar
    algo que a rota nao faz.
    """
    agora = falou_em or datetime.now(UTC)
    session.add(
        Message(
            id=uuid.uuid4(),
            channel=canal,
            conversation_key=chave,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            sender_external_id=chave,
            created_at=agora,
        )
    )

    if regiao is not None or temperatura is not None:
        session.add(
            LeadQualification(
                channel=canal,
                conversation_key=chave,
                regiao=regiao,
                temperatura=temperatura,
            )
        )

    if score is not None:
        # Tudo em `completude` e o resto zero: `ck_lead_score_audit_total` exige
        # `total_novo` igual a soma dos cinco fatores, e esta e a composicao que
        # fecha para qualquer score sem amarrar o teste a uma distribuicao.
        session.add(
            LeadScoreAudit(
                id=uuid.uuid4(),
                channel=canal,
                conversation_key=chave,
                total_anterior=None,
                total_novo=score,
                completude=score,
                urgencia=0,
                catalogo=0,
                engajamento=0,
                capacidade=0,
                causas=["PRIMEIRO_CALCULO"],
            )
        )

    if dono is not None:
        session.add(
            Handoff(
                id=uuid.uuid4(),
                channel=canal,
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

    if encerrada:
        session.add(
            Conversa(
                channel=canal,
                conversation_key=chave,
                status=Status.ENCERRADA.value,
                motivo_do_encerramento=MotivoDoEncerramento.INATIVIDADE.value,
                encerrada_em=agora,
            )
        )

    await session.commit()
    return chave


def _chaves(resposta: Any) -> list[str]:
    return [item["conversationKey"] for item in resposta.json()["itens"]]


async def test_ordenacao_padrao_por_score(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Primeiro cenario, com os numeros da card: 82, 47 e 30."""
    await _lead(session, chave="5548990000047", score=47)
    await _lead(session, chave="5548990000082", score=82)
    await _lead(session, chave="5548990000030", score=30)

    resposta = await client.get(ROTA, headers=_bearer("GERENTE"))

    assert resposta.status_code == 200
    assert [item["score"] for item in resposta.json()["itens"]] == [82, 47, 30]


async def test_busca_por_bairro_de_interesse(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Segundo cenario, e o unico dos tres campos de busca que a card pede que
    tem de onde sair -- nao ha nome em tabela nenhuma (L1)."""
    await _lead(session, chave="5548990000001", score=10, regiao="Trindade")
    await _lead(session, chave="5548990000002", score=90, regiao="Centro")

    resposta = await client.get(ROTA, params={"busca": "Trindade"}, headers=_bearer("GERENTE"))

    assert _chaves(resposta) == ["5548990000001"]


async def test_busca_por_bairro_ignora_a_caixa(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    await _lead(session, chave="5548990000001", score=10, regiao="Trindade")

    resposta = await client.get(ROTA, params={"busca": "trINDade"}, headers=_bearer("GERENTE"))

    assert _chaves(resposta) == ["5548990000001"]


async def test_corretor_ve_apenas_os_proprios_leads(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, semear_corretor: Any
) -> None:
    """Terceiro cenario. O dono e o destinatario do handoff (D6).

    Ate esta card `handoffs.corretor_id` nao tinha escritor nenhum -- a Emenda
    E-05 da RN-16.1 declarou o criterio inexercitavel por isso.
    """
    paulo = (await semear_corretor(email="paulo@imobiliaria.com")).id
    marcia = (await semear_corretor(email="marcia@imobiliaria.com")).id
    await _lead(session, chave="5548990000001", score=10, dono=paulo)
    await _lead(session, chave="5548990000002", score=90, dono=marcia)
    await _lead(session, chave="5548990000003", score=99)

    resposta = await client.get(ROTA, headers=_bearer("CORRETOR", corretor_id=paulo))

    assert _chaves(resposta) == ["5548990000001"]


async def test_corretor_nao_alarga_o_recorte_pela_query(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, semear_corretor: Any
) -> None:
    """`corretorId=<outro>` na query nao vence a claim do token (D7).

    Sem esta asserta, o recorte do papel seria uma sugestao -- bastaria a tela
    mandar outro id para ver a carteira do colega.
    """
    paulo = (await semear_corretor(email="paulo@imobiliaria.com")).id
    marcia = (await semear_corretor(email="marcia@imobiliaria.com")).id
    await _lead(session, chave="5548990000002", score=90, dono=marcia)

    resposta = await client.get(
        ROTA, params={"corretorId": str(marcia)}, headers=_bearer("CORRETOR", corretor_id=paulo)
    )

    assert _chaves(resposta) == []


async def test_corretor_sem_vinculo_ve_lista_vazia(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, semear_corretor: Any
) -> None:
    """Cadastro incompleto nao e passe livre -- mesmo argumento da D4 da TEC-202."""
    paulo = (await semear_corretor(email="paulo@imobiliaria.com")).id
    await _lead(session, chave="5548990000001", score=10, dono=paulo)

    resposta = await client.get(ROTA, headers=_bearer("CORRETOR"))

    assert _chaves(resposta) == []


async def test_gerente_ve_a_base_inteira(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, semear_corretor: Any
) -> None:
    """O outro lado do recorte: so o CORRETOR e limitado ao proprio."""
    paulo = (await semear_corretor(email="paulo@imobiliaria.com")).id
    await _lead(session, chave="5548990000001", score=10, dono=paulo)
    await _lead(session, chave="5548990000002", score=90)

    resposta = await client.get(ROTA, headers=_bearer("GERENTE"))

    assert len(_chaves(resposta)) == 2


async def test_paginacao_preserva_a_ordenacao(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Quarto cenario, com os 120 leads da card.

    **Duas assertas, e a segunda e a que importa**: a ordem continua
    decrescente E nenhuma linha aparece em duas paginas. Um `OFFSET` passaria
    na primeira e reprovaria na segunda assim que o score mudasse -- e a
    primeira sozinha nao distingue keyset de offset.
    """
    for i in range(120):
        await _lead(session, chave=f"55489900{i:05d}", score=i % 40)

    vistos: list[str] = []
    scores: list[int] = []
    cursor: str | None = None
    for _ in range(3):
        params: dict[str, object] = {"limite": 50}
        if cursor:
            params["cursor"] = cursor
        resposta = await client.get(ROTA, params=params, headers=_bearer("GERENTE"))
        corpo = resposta.json()
        vistos.extend(item["conversationKey"] for item in corpo["itens"])
        scores.extend(item["score"] for item in corpo["itens"])
        cursor = corpo["proximoCursor"]
        if cursor is None:
            break

    assert len(vistos) == 120
    assert len(set(vistos)) == 120, "a mesma linha apareceu em duas paginas"
    assert scores == sorted(scores, reverse=True)


async def test_empate_de_score_sai_em_ordem_estavel(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """O desempate da D5, que o empate torna o caso comum e nao a borda.

    Score e inteiro de 0 a 100: numa base de milhares, empatar e a regra. Sem
    desempate deterministico a ordem entre empatados fica por conta do plano do
    Postgres, e a paginacao passa a pular linha.
    """
    for i in range(5):
        await _lead(session, chave=f"554899000000{i}", score=50)

    primeira = await client.get(ROTA, headers=_bearer("GERENTE"))
    segunda = await client.get(ROTA, headers=_bearer("GERENTE"))

    assert _chaves(primeira) == _chaves(segunda)
    assert _chaves(primeira) == sorted(_chaves(primeira))


async def test_lead_sem_score_aparece_por_ultimo(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """`score: null` e nao zero (D4): "ainda nao foi pontuado" nao e "pontuou zero"."""
    await _lead(session, chave="5548990000001")
    await _lead(session, chave="5548990000002", score=1)

    itens = (await client.get(ROTA, headers=_bearer("GERENTE"))).json()["itens"]

    assert [item["score"] for item in itens] == [1, None]


async def test_busca_por_telefone_do_whatsapp(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """No WhatsApp o proprio `conversation_key` e o numero."""
    await _lead(session, chave="5548988887777", score=10)
    await _lead(session, chave="5511999996666", score=20)

    resposta = await client.get(ROTA, params={"busca": "48988887777"}, headers=_bearer("GERENTE"))

    assert _chaves(resposta) == ["5548988887777"]


async def test_busca_por_telefone_aceita_pontuacao(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Quem digita "+55 (48) 98888-7777" procura `5548988887777`.

    Sem a normalizacao para digitos, o ILIKE do texto cru nao acha nada -- e
    quem buscou leria isso como "este lead nao existe".
    """
    await _lead(session, chave="5548988887777", score=10)

    resposta = await client.get(
        ROTA, params={"busca": "+55 (48) 98888-7777"}, headers=_bearer("GERENTE")
    )

    assert _chaves(resposta) == ["5548988887777"]


async def test_busca_por_telefone_do_chat_web(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """No web a sessao e anonima: o numero so existe se o lead o digitou.

    A origem e `vinculos_de_sessao` (TEC-129), e a busca precisa alcanca-la --
    de outro modo o lead do site seria inencontravel por telefone mesmo tendo
    informado um.
    """
    sessao = "sessao-web-abc123"
    await _lead(session, chave=sessao, score=10, canal="web")
    mensagem = uuid.uuid4()
    session.add(
        Message(
            id=mensagem,
            channel="web",
            conversation_key=sessao,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            sender_external_id=sessao,
        )
    )
    await session.flush()
    session.add(
        VinculoDeSessao(
            channel="web",
            conversation_key=sessao,
            telefone="5548977776666",
            message_id=mensagem,
        )
    )
    await session.commit()

    resposta = await client.get(ROTA, params={"busca": "977776666"}, headers=_bearer("GERENTE"))

    assert _chaves(resposta) == [sessao]


async def test_filtro_de_status_trata_ausencia_como_ativa(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D8: `conversas` so tem linha depois do encerramento.

    Sem tratar a ausencia como ATIVA, filtrar por ATIVA devolveria so os leads
    que foram encerrados e reabertos -- o oposto do pedido.
    """
    await _lead(session, chave="5548990000001", score=10)
    await _lead(session, chave="5548990000002", score=20, encerrada=True)

    ativas = await client.get(ROTA, params={"status": "ATIVA"}, headers=_bearer("GERENTE"))
    encerradas = await client.get(ROTA, params={"status": "ENCERRADA"}, headers=_bearer("GERENTE"))

    assert _chaves(ativas) == ["5548990000001"]
    assert _chaves(encerradas) == ["5548990000002"]


async def test_filtros_de_canal_e_temperatura(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    await _lead(session, chave="5548990000001", score=10, temperatura="QUENTE")
    await _lead(session, chave="sessao-web-1", score=20, canal="web", temperatura="FRIO")

    por_canal = await client.get(ROTA, params={"canal": "web"}, headers=_bearer("GERENTE"))
    por_temp = await client.get(ROTA, params={"temperatura": "QUENTE"}, headers=_bearer("GERENTE"))

    assert _chaves(por_canal) == ["sessao-web-1"]
    assert _chaves(por_temp) == ["5548990000001"]


@pytest.mark.parametrize(
    ("params", "porque"),
    [
        ({"limite": 0}, "limite abaixo da faixa"),
        ({"limite": 500}, "limite acima do teto"),
        ({"status": "QUALIFICADO"}, "status que existe no SRS e nao neste sistema"),
        ({"cursor": "nao-e-base64-valido!!"}, "cursor corrompido"),
    ],
)
async def test_pedido_invalido_e_422_e_nao_lista_vazia(
    client: AsyncClient, banco_limpo: None, params: dict[str, object], porque: str
) -> None:
    """Lista vazia se leria como "nao ha lead assim", que e afirmacao sobre o
    negocio -- e o erro e de quem chamou. Mesma decisao do funil."""
    resposta = await client.get(ROTA, params=params, headers=_bearer("GERENTE"))

    assert resposta.status_code == 422, porque


async def test_ultima_interacao_e_a_fala_mais_recente(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A card pede o momento da ultima interacao em cada linha."""
    ontem = datetime.now(UTC) - timedelta(days=1)
    await _lead(session, chave="5548990000001", score=10, falou_em=ontem)
    session.add(
        Message(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5548990000001",
            role=MessageRole.AGENTE,
            direction=MessageDirection.OUTBOUND,
            content_type=MessageContentType.TEXTO,
            sender_external_id="agente",
        )
    )
    await session.commit()

    item = (await client.get(ROTA, headers=_bearer("GERENTE"))).json()["itens"][0]

    assert datetime.fromisoformat(item["ultimaInteracaoEm"]) > ontem


async def test_a_lista_nao_devolve_telefone_nem_nome(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """L1 e L3, presas por teste.

    O nome nao existe em tabela nenhuma, e o telefone so poderia sair
    mascarado (TEC-195). Esta asserta e o que impede alguem de "completar" a
    resposta com o `conversation_key` renomeado para `telefone`, que entregaria
    em claro justamente o dado que a TEC-195 existe para proteger.
    """
    await _lead(session, chave="5548990000001", score=10)

    item = (await client.get(ROTA, headers=_bearer("GERENTE"))).json()["itens"][0]

    assert "nome" not in item
    assert "telefone" not in item


async def test_leitura_le_a_lista_e_ninguem_sem_credencial_le(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """`VER_LEADS` e dos quatro papeis (D7), e de mais ninguem."""
    await _lead(session, chave="5548990000001", score=10)

    com_leitura = await client.get(ROTA, headers=_bearer("LEITURA"))
    sem_nada = await client.get(ROTA)

    assert com_leitura.status_code == 200
    assert sem_nada.status_code == 403
