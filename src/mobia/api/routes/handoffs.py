"""A regeneracao do resumo sob demanda. TEC-175, RN-15.2 e D8 do desenho.

O Gherkin diz "pelo dashboard", e o dashboard (E8) esta fora do escopo da
card. Esta rota e o mecanismo que ele vai chamar; ate la, e por ela que o
criterio de aceite da regeneracao e exercitado.

Guardada por `exigir_admin` como as rotas de catalogo: o resumo carrega dado
pessoal do lead, e rota aberta nao e opcao.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from mobia.api.deps import exigir_admin
from mobia.domain.handoff.geracao import gerar_resumo
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.resumo import RedatorAnthropic, link_da_transcricao
from mobia.infra.crypto import decrypt
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/handoffs", tags=["handoffs"])


@router.post("/{handoff_id}/resumo")
async def regenerar(handoff_id: uuid.UUID, _: None = Depends(exigir_admin)) -> dict[str, object]:
    session_factory = get_sessionmaker()

    gravou = await gerar_resumo(session_factory, redator=RedatorAnthropic(), handoff_id=handoff_id)
    if not gravou:
        # Desde a TEC-176, `gerar_resumo` so devolve False quando o dossie
        # esta ausente (RN-15.4: o corretor nunca fica sem resumo). Uma
        # resposta invalida do redator e qualquer excecao do provedor agora
        # caem no template deterministico e gravam -- ja nao ha mais "resposta
        # bem formada que reprova em validar()" para separar de um 404 aqui.
        # O ramo 502 que existia para essa distincao deixou de ser
        # alcancavel; ver a Task 3 (TEC-176) e `test_rota_de_resumo.py`.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="handoff nao existe")

    async with session_factory() as session:
        linha = (
            await session.execute(select(Handoff).where(Handoff.id == handoff_id))
        ).scalar_one()

    return {
        "resumo": decrypt(linha.resumo, aad_do_resumo_de_handoff(handoff_id)),
        "link": link_da_transcricao(linha.channel, linha.conversation_key),
        "geradoEm": linha.resumo_gerado_em.isoformat() if linha.resumo_gerado_em else None,
        "modelo": linha.resumo_modelo,
    }
