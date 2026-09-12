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
        # 404 cobre o handoff que nao existe. O 502 nao cobre toda excecao do
        # provedor -- uma excecao real (APIError, timeout) escapa de
        # `gerar_resumo`, que so captura ResumoDeHandoffInvalido, e vira HTTP
        # 500; o que chega aqui como False e so a resposta bem formada que
        # reprova em `validar` (bloco ausente, fora de ordem, ou acima do
        # limite mesmo apos a compressao). `gerar_resumo` devolve o mesmo
        # False tambem para o handoff que sumiu (ver a docstring de la), e
        # distingui-los aqui exige consultar o banco depois: se a linha
        # existe, a falha foi do redator, e nao do handoff.
        async with session_factory() as session:
            existe = (
                await session.execute(select(Handoff.id).where(Handoff.id == handoff_id))
            ).scalar_one_or_none()
        if existe is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="handoff nao existe")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="resumo nao pode ser gerado"
        )

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
