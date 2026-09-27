"""Criterios de aceite do TEC-195 como testes executaveis. RF-18, RN-18.5.

Os quatro cenarios do Gherkin da card, e o que aconteceu com cada um:

- **"Corretor sem permissao ve telefone parcial"** -- aqui, e mais forte do
  que o cenario pede: a asserta e sobre o CORPO INTEIRO, e nao sobre o campo.
  Foi assim que o vazamento pelo `proximoCursor` apareceu.
- **"Revelar o dado gera evento de auditoria"** -- aqui.
- **"Mascaramento vale na exportacao"** -- **nao exercitavel**: nao existe
  exportacao de lead neste sistema, e a propria card de tela registra que
  "hoje nenhuma exportacao de lead esta no escopo (RN-FE-10.4)". Escrever o
  cenario contra um endpoint criado so para ele e o modo de falha que o
  CLAUDE.md nomeia -- teste que inventa a entidade que falta para se
  auto-satisfazer.
- **"Registro de auditoria e imutavel"** -- ja feito pela TEC-206, e o teste
  vive em `tests/integration/test_trilha_de_auditoria.py`. O trigger
  `eventos_auditoria_imutavel` da migration 0053 recusa todo UPDATE.
  Reescreve-lo aqui seria um segundo teste afirmando a mesma coisa.

O e-mail nao aparece em cenario nenhum porque nenhuma tabela deste sistema o
guarda (D7). A regra de mascaramento dele esta em
`tests/unit/test_mascara_de_dado_pessoal.py`, escrita e sem chamador.
"""

import base64
import json
import uuid
from datetime import UTC, datetime

import pytest
from conftest import _corretor
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.vocabulario import Acao
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status as StatusDoHandoff
from mobia.domain.identidade.indice import registrar
from mobia.domain.leads.repositorio import referencias_para
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.usuarios import tokens

ROTA = "/api/v1/leads"
TELEFONE = "5548990000021"
MASCARA = "+55 48 9****-**21"


def _bearer(papel: str, *, corretor_id: uuid.UUID | None = None) -> dict[str, str]:
    token = tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=corretor_id, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


async def _lead(session: AsyncSession, *, valor: str, canal: str = "whatsapp") -> str:
    """O minimo para o lead aparecer na lista: uma mensagem. Devolve a chave.

    Desde a TEC-203 o par guarda `chave_de(canal, valor)`, e o valor cru mora
    cifrado na identidade -- de onde a lista e a revelacao o tiram.
    """
    chave = await registrar(session, canal, valor)
    session.add(
        Message(
            id=uuid.uuid4(),
            channel=canal,
            conversation_key=chave,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            sender_external_id=chave,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return chave


async def _apelido(session: AsyncSession, *, chave: str, canal: str = "whatsapp") -> uuid.UUID:
    apelidos = await referencias_para(session, [(canal, chave)])
    await session.commit()
    return apelidos[(canal, chave)]


async def test_quem_nao_pode_ver_nao_recebe_o_telefone_em_lugar_nenhum(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 1, e mais forte do que ele pede.

    **A asserta e sobre o corpo inteiro serializado**, e nao sobre o campo
    `telefone`. Um teste que olhasse so o campo passaria com o
    `conversationKey` em claro ao lado dele, e passou -- era esse o estado ate
    esta card. E passaria de novo com o telefone dentro do `proximoCursor`,
    que e base64 e nao cifra nada.

    **`LEITURA` e nao `CORRETOR`, e a diferenca nao e cosmetica**: o corretor
    sem vinculo recebe lista VAZIA (D4 da TEC-202), e uma asserta de "o
    telefone nao aparece" sobre lista vazia passa por vacuidade -- ela
    continuaria verde com a mascara inteira removida. `LEITURA` tem
    `VER_LEADS`, nao tem `VER_DADOS_COMPLETOS` e ve a base inteira.
    """
    await _lead(session, valor=TELEFONE)

    corpo = (await client.get(ROTA, headers=_bearer("LEITURA"))).json()

    assert corpo["itens"], "lista vazia faria esta asserta passar por vacuidade"
    assert TELEFONE not in json.dumps(corpo)


async def test_o_telefone_sai_mascarado_na_lista(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """A outra metade do cenario 1: mascarado nao e ausente."""
    await _lead(session, valor=TELEFONE)

    itens = (await client.get(ROTA, headers=_bearer("LEITURA"))).json()["itens"]

    assert itens[0]["telefone"] == MASCARA


async def test_gerente_com_permissao_tambem_ve_mascarado_na_lista(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D4: a lista nao tem ramo por papel, e nao deve ganhar um.

    Esta asserta e o que impede alguem de "otimizar" devolvendo o valor cheio
    a quem pode ve-lo -- o que devolveria o dado pessoal a resposta e faria a
    trilha deixar de registrar o acesso.
    """
    await _lead(session, valor=TELEFONE)

    itens = (await client.get(ROTA, headers=_bearer("GERENTE"))).json()["itens"]

    assert itens[0]["telefone"] == MASCARA


async def test_o_cursor_nao_carrega_o_telefone(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """O vazamento que nao estava declarado em lugar nenhum (D1).

    `Cursor.codificar` e base64, e a docstring dele ja avisava que "opaco nao
    e seguranca". Era verdade e inofensivo -- ate o conteudo dele ser o
    telefone do lead.
    """
    for final in ("21", "22", "23"):
        await _lead(session, valor=f"554899000000{final}")

    corpo = (await client.get(ROTA, params={"limite": 1}, headers=_bearer("LEITURA"))).json()

    assert corpo["proximoCursor"] is not None
    cru = base64.urlsafe_b64decode(corpo["proximoCursor"].encode("ascii")).decode("utf-8")
    assert "5548990000" not in cru


async def test_revelar_devolve_o_numero_e_grava_a_trilha(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Cenario 2: autor, lead, campo e horario.

    **O `lead` da trilha e o `lead_ref`, e nao o par** -- a D4 da TEC-206
    proibiu guardar o telefone ali, e esta card nao abre excecao.
    """
    chave = await _lead(session, valor=TELEFONE)
    lead_id = await _apelido(session, chave=chave)

    # O `antes` sai do relogio do banco, e nao do host: `criado_em` e carimbado
    # pelo trigger com `clock_timestamp()`, na VM do Docker, e os dois relogios
    # ja foram medidos ~0,6 s fora de sincronia (TEC-379).
    antes = await session.scalar(text("SELECT clock_timestamp()"))
    resposta = await client.post(
        f"{ROTA}/{lead_id}/revelar", json={"campo": "telefone"}, headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 200
    assert resposta.json() == {"campo": "telefone", "valor": f"+{TELEFONE}"}

    evento = (
        await session.execute(
            select(EventoAuditoria).where(EventoAuditoria.acao == Acao.DADO_PESSOAL_ACESSADO.value)
        )
    ).scalar_one()
    assert evento.ator_tipo == "USUARIO"
    assert evento.ator_id is not None
    assert evento.entidade == "lead"
    assert evento.entidade_id == str(lead_id)
    assert evento.campo == "telefone"
    assert evento.criado_em >= antes
    assert evento.lead_ref == lead_ref(
        "whatsapp", chave, chave=get_settings().auditoria_chave_do_lead
    )
    # O que foi lido, nunca o que ele dizia.
    assert TELEFONE not in json.dumps(evento.detalhes)


async def test_quem_nao_tem_a_permissao_nao_revela_e_nao_gera_acesso(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """403, e NENHUM `DADO_PESSOAL_ACESSADO`.

    A negativa ja e registrada como `ACESSO_NEGADO` pelo middleware da
    TEC-206. Um `DADO_PESSOAL_ACESSADO` aqui mentiria: ninguem acessou nada.
    """
    chave = await _lead(session, valor=TELEFONE)
    lead_id = await _apelido(session, chave=chave)

    resposta = await client.post(
        f"{ROTA}/{lead_id}/revelar", json={"campo": "telefone"}, headers=_bearer("CORRETOR")
    )

    assert resposta.status_code == 403
    acessos = (
        await session.execute(
            select(EventoAuditoria).where(EventoAuditoria.acao == Acao.DADO_PESSOAL_ACESSADO.value)
        )
    ).all()
    assert acessos == []


async def test_apelido_que_nao_existe_e_404(client: AsyncClient, banco_limpo: None) -> None:
    resposta = await client.post(
        f"{ROTA}/{uuid.uuid4()}/revelar", json={"campo": "telefone"}, headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 404


async def test_campo_fora_do_vocabulario_e_422(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """422 e nao 500: o campo vem de quem chamou."""
    chave = await _lead(session, valor=TELEFONE)
    lead_id = await _apelido(session, chave=chave)

    resposta = await client.post(
        f"{ROTA}/{lead_id}/revelar", json={"campo": "cpf"}, headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 422


async def test_revelar_email_devolve_nulo_porque_nao_ha_fonte(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """D7: nenhuma tabela deste sistema guarda e-mail de lead.

    O campo e aceito pelo vocabulario para que a tela nao precise mudar no dia
    em que a coluna nascer; ate la, nulo diz "nao ha", que e a verdade.
    """
    chave = await _lead(session, valor=TELEFONE)
    lead_id = await _apelido(session, chave=chave)

    resposta = await client.post(
        f"{ROTA}/{lead_id}/revelar", json={"campo": "email"}, headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 200
    assert resposta.json() == {"campo": "email", "valor": None}


@pytest.mark.parametrize("papel", ["GERENTE", "ADMIN"])
async def test_so_gerente_e_admin_revelam(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, papel: str
) -> None:
    """A matriz de `permissoes_de`, vista pela rota que a exige."""
    chave = await _lead(session, valor=TELEFONE)
    lead_id = await _apelido(session, chave=chave)

    resposta = await client.post(
        f"{ROTA}/{lead_id}/revelar", json={"campo": "telefone"}, headers=_bearer(papel)
    )

    assert resposta.status_code == 200


async def test_lead_web_sem_telefone_digitado_sai_nulo(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Nulo e "nao ha numero", e nao "nao pode ver".

    A identidade do canal web e a sessao, e nao um telefone: o numero so
    existe se o lead o digitou (TEC-129).
    """
    await _lead(session, valor="sessao-web-sem-numero", canal="web")

    itens = (await client.get(ROTA, headers=_bearer("LEITURA"))).json()["itens"]

    assert itens[0]["telefone"] is None


async def test_corretor_dono_do_lead_nao_e_barrado_pelo_recorte(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """O recorte de dono da revelacao, exercitado pela unica via que resta.

    `CORRETOR` nao tem `VER_DADOS_COMPLETOS` na matriz de hoje, entao o
    `Exige` o barra antes do recorte -- e por isso a asserta e sobre o 403, e
    nao sobre o 200. O que este teste guarda e que o barramento EXISTE:
    no dia em que a matriz conceder a permissao ao corretor, o recorte de dono
    e o que impede a revelacao de virar a porta dos fundos da lista.
    """
    corretor = await _corretor(session)
    chave = await _lead(session, valor=TELEFONE)
    lead_id = await _apelido(session, chave=chave)
    session.add(
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key=chave,
            gatilho="QUENTE",
            etiqueta="LEAD_QUENTE",
            prioridade="ALTA",
            status=StatusDoHandoff.ACEITO.value,
            corretor_id=corretor,
            criado_em=datetime.now(UTC),
            atualizado_em=datetime.now(UTC),
        )
    )
    await session.commit()

    resposta = await client.post(
        f"{ROTA}/{lead_id}/revelar",
        json={"campo": "telefone"},
        headers=_bearer("CORRETOR", corretor_id=corretor),
    )

    assert resposta.status_code == 403
