"""A regeneracao do resumo sob demanda e o aceite pelo corretor.

TEC-175, RN-15.2 e D8 do desenho para a regeneracao. TEC-178 e a secao 6.5
do SRS para o aceite.

O Gherkin diz "pelo dashboard", e o dashboard (E8) esta fora do escopo das
duas cards. Estas rotas sao o mecanismo que ele vai chamar; ate la, e por
elas que os criterios de aceite correspondentes sao exercitados.

Guardadas por `exigir_admin` como as rotas de catalogo: o resumo carrega
dado pessoal do lead e o aceite move o estado do handoff, e rota aberta nao
e opcao em nenhum dos dois casos.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update

from mobia.api.deps import exigir_admin
from mobia.domain.handoff.geracao import gerar_resumo
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.resumo import RedatorAnthropic, link_da_transcricao
from mobia.domain.handoff.vocabulario import Status
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
        # L1 do desenho: a rota e hoje o unico lugar de onde alguem pode ler
        # que o resumo e o template (o painel e a E8 e nao existe). Segundo
        # cenario do Gherkin: "fica indicado que se trata de resumo
        # automatico simplificado".
        "resumoFallback": linha.resumo_fallback,
    }


# Estados que uma chamada a /aceitar pode transformar em ACEITO. ESCALADO
# entra por decisao da Task 6 (TEC-178): aceitar depois da escalada e o caso
# real -- o gerente cobrou e alguem pegou -- e recusar penalizaria
# justamente o comportamento que a card quer provocar. Ver a Emenda E-01 da
# secao 6.5 do SRS: o 410 "escalado por SLA" que o texto original previa
# nunca e levantado por este codigo.
_ACEITAVEIS = (Status.PENDENTE.value, Status.ESCALADO.value)


@router.post("/{handoff_id}/aceitar")
async def aceitar(handoff_id: uuid.UUID, _: None = Depends(exigir_admin)) -> dict[str, object]:
    """O corretor aceita o handoff -- TEC-178, secao 6.5 do SRS.

    **A corrida com `escalar_vencidos` (`domain/handoff/escalada.py`) e o
    motivo do UPDATE abaixo, e nao um SELECT seguido de UPDATE.** Aquela
    varredura seleciona PENDENTE e condiciona o proprio UPDATE a
    `status = 'PENDENTE'`, usando o RETURNING para saber quem de fato virou
    ESCALADO. Este endpoint e o outro lado da mesma corrida: se o SELECT
    decidisse "pode aceitar" e o UPDATE gravasse depois, um aceite e uma
    escalada simultaneos poderiam os dois se achar vencedores. Por isso quem
    decide 200 ou erro aqui e o RETURNING deste UPDATE, nao uma leitura
    anterior -- o banco arbitra, no mesmo raciocinio do ON CONFLICT de
    `registrar_handoff`.

    **Idempotente ate o primeiro aceite, recusado depois (D8).** Uma vez
    ACEITO (ou CONCLUIDO, fora do escopo desta card), uma nova chamada nao
    bate a condicao do WHERE, o RETURNING vem vazio e a resposta e 409 --
    sem tocar em `aceito_em`, que so pode ser gravado uma vez: e ele que
    alimenta a taxa de aceite no prazo da RN-17.1, e um carimbo que anda
    para frente faria um aceite atrasado parecer pontual.
    """
    session_factory = get_sessionmaker()
    agora = datetime.now(UTC)

    async with session_factory() as session:
        linha = (
            await session.execute(
                update(Handoff)
                .where(Handoff.id == handoff_id, Handoff.status.in_(_ACEITAVEIS))
                .values(status=Status.ACEITO.value, aceito_em=agora, atualizado_em=agora)
                .returning(Handoff.sla_limite_em)
            )
        ).first()

        if linha is not None:
            await session.commit()
            return {
                "status": Status.ACEITO.value,
                "aceitoEm": agora.isoformat(),
                # `sla_limite_em` nulo tem DOIS significados possiveis (ver o
                # modelo e a migration 0028): "ainda nao notificado" (o
                # handoff acabou de nascer e `notificar` nao rodou) ou "nao
                # havia a quem cobrar" (handoff sem destinatario, Emenda E-02
                # da RN-16.3, nulo PARA SEMPRE). Nos dois casos nao ha prazo
                # para estourar -- conta como dentro do prazo por vacuidade,
                # nunca como "prazo zero".
                "dentroDoSla": linha.sla_limite_em is None or agora <= linha.sla_limite_em,
            }

        existe = (
            await session.execute(select(Handoff.id).where(Handoff.id == handoff_id))
        ).scalar_one_or_none()

    if existe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="handoff nao existe")
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="handoff ja aceito")
