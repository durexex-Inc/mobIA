"""O desfecho da visita, marcado pelo corretor. TEC-374, RF-12, RN-12.4 e RN-12.5.

**O Gherkin diz "pelo dashboard", e o dashboard nao existe.** Esta card mora no
epico `[FE]` e depende da TEC-323 para saber onde os botoes ficam. A casca do
painel -- login e menu por papel -- passou a existir (TEC-309, TEC-312), mas a
lista e o detalhe do lead nao (TEC-321, TEC-323). Entao o que esta aqui e
o mecanismo que a tela vai chamar, e ate ela chegar e por estas rotas que os
criterios de aceite correspondentes sao exercitados -- o mesmo arranjo que
`handoffs.py` ja assumiu por escrito.

**Guardadas por `ATENDER_LEAD`** (TEC-202), que ADMIN, GERENTE e CORRETOR tem
e LEITURA nao, **mais a checagem de dono**: e exatamente o "so o corretor dono
do agendamento -- ou um gerente" que a card pede. Mais simples que o caso do
handoff, porque `agendamentos.corretor_id` e NOT NULL: a sutileza de "nao
existe nao e a mesma coisa que sem destinatario" nao se aplica aqui.

**Duas rotas e nao uma com `{"desfecho": ...}`** (D4). As duas nao sao o mesmo
ato com um parametro: uma nao custa nada ao lead, e a outra tira 15 pontos de
forma irreversivel -- nao ha transicao de volta a partir de `NO_SHOW`. Um
corpo com enum faria a diferenca entre elas caber num caractere.

**Os literais daqui levam ACENTO**, ao contrario dos comentarios: e texto que
uma pessoa le, e a fronteira do CLAUDE.md o poe do lado do produto. E a razao
de a frase morar aqui e nao em `ciclo.py`, que nao tem literal nenhum voltado
ao usuario.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao, exigir_dono
from mobia.domain.agendamento.ciclo import (
    MOTIVO_ANTES_DA_HORA,
    MOTIVO_INEXISTENTE,
    PONTOS_POR_NAO_COMPARECIMENTO,
    NaoCompareceu,
    Recusado,
    Transicionado,
    marcar_nao_comparecimento,
    marcar_realizado,
)
from mobia.domain.agendamento.models import Agendamento, StatusDoAgendamento
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/agendamentos", tags=["agendamentos"])

# A recusa dita como tal, e nao como erro generico -- e a regra que a card
# escreve por extenso. O status vem em `Recusado.status_atual`, que existe
# para isto (D3).
#
# As seis entradas cobrem `StatusDoAgendamento` inteiro menos `CONFIRMADO`,
# que e o unico estado de onde a transicao PASSA. `RESERVADO` entra porque
# marcar desfecho de reserva nao confirmada e possivel de tentar.
_FRASE_DO_STATUS: dict[str, str] = {
    StatusDoAgendamento.RESERVADO: "esta visita ainda não foi confirmada",
    StatusDoAgendamento.EXPIRADO: "esta reserva expirou",
    StatusDoAgendamento.CANCELADO: "este agendamento já foi cancelado",
    StatusDoAgendamento.REAGENDADO: "este agendamento foi remarcado",
    StatusDoAgendamento.REALIZADO: "esta visita já foi marcada como realizada",
    StatusDoAgendamento.NO_SHOW: "esta visita já foi marcada como não comparecimento",
}

_ANTES_DA_HORA = "esta visita ainda não começou"


def _recusar(recusa: Recusado) -> HTTPException:
    """A recusa do dominio traduzida em HTTP, com a frase que a tela mostra.

    **404 para inexistente, 409 para o resto.** Nao 422: o corpo do pedido nao
    esta errado -- quem mudou foi o estado do recurso. E a mesma distincao que
    `reservar` faz ao traduzir a recusa do banco em `Conflito`.

    **O `_FRASE_DO_STATUS.get` tem fallback**, e ele nao e decorativo: um
    status novo no enum sem linha no mapa sairia como `KeyError` -- 500 sobre
    uma recusa que o dominio soube explicar.
    """
    if recusa.motivo == MOTIVO_INEXISTENTE:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agendamento nao existe")

    if recusa.motivo == MOTIVO_ANTES_DA_HORA:
        detalhe = _ANTES_DA_HORA
    else:
        detalhe = _FRASE_DO_STATUS.get(
            recusa.status_atual or "", "este agendamento não aceita mais esta ação"
        )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detalhe)


async def _exigir_dono_do_agendamento(
    agendamento_id: uuid.UUID, request: Request, identidade: IdentidadeDaRequisicao
) -> None:
    """Recusa o CORRETOR que marca o desfecho da visita de outro. TEC-202, D5.

    **Agendamento inexistente passa por aqui sem erro**, de proposito: quem
    responde 404 e o corpo da rota, que ja sabe distinguir "nao existe" de
    "nao pode". Levantar 403 aqui para um id que nao existe transformaria esta
    guarda num oraculo ao contrario -- diria "este id nao e seu" sobre um id
    que nao e de ninguem. Molde de `handoffs.py::_exigir_dono_do`.
    """
    if not identidade.e_corretor:
        return
    async with get_sessionmaker()() as session:
        dono = (
            await session.execute(
                select(Agendamento.corretor_id).where(Agendamento.id == agendamento_id)
            )
        ).scalar_one_or_none()
    if dono is None:
        return
    await exigir_dono(request, identidade, permissao=Permissao.ATENDER_LEAD, corretor_id=dono)


@router.post("/{agendamento_id}/realizado")
async def realizado(
    agendamento_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.ATENDER_LEAD)),
) -> dict[str, object]:
    """A visita aconteceu. Primeiro cenario do Gherkin.

    **Nao custa nada ao lead**, e e essa a diferenca para a rota vizinha. O
    score nao se move, e ha teste afirmando que nao se move.
    """
    await _exigir_dono_do_agendamento(agendamento_id, request, identidade)

    async with get_sessionmaker()() as session:
        resultado = await marcar_realizado(
            session, agendamento_id=agendamento_id, agora=datetime.now(UTC)
        )
        if isinstance(resultado, Recusado):
            raise _recusar(resultado)
        await session.commit()

    assert isinstance(resultado, Transicionado)
    return {"id": str(resultado.id), "status": resultado.para}


@router.post("/{agendamento_id}/nao-comparecimento")
async def nao_comparecimento(
    agendamento_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.ATENDER_LEAD)),
) -> dict[str, object]:
    """O lead faltou. Segundo cenario do Gherkin, e o que custa 15 pontos.

    **A resposta carrega o custo para a tela nao o inventar** (D7). A card pede
    que o painel avise quanto custa ANTES de confirmar, e aviso previo e coisa
    de interface -- a API nao avisa, ela faz. O que ela pode fazer e devolver
    o numero que o dominio de fato aplicou, em vez de deixar um 15 escrito a
    mao no frontend envelhecer no dia em que a RN-12.4 mudar.

    **Sem flag de confirmacao no corpo.** Seria uma segunda trava para o mesmo
    mau clique que o botao de confirmacao ja cobre, e nao protege de nada que
    um cliente automatizado nao possa mandar junto.

    `scoreNovo` e nulo quando o lead nao tem linha em `lead_qualification` --
    a penalidade foi somada mesmo assim, e o proximo calculo a usa. Ver
    `NaoCompareceu.recalculo`.
    """
    await _exigir_dono_do_agendamento(agendamento_id, request, identidade)

    async with get_sessionmaker()() as session:
        resultado = await marcar_nao_comparecimento(
            session, agendamento_id=agendamento_id, agora=datetime.now(UTC)
        )
        if isinstance(resultado, Recusado):
            raise _recusar(resultado)
        await session.commit()

    assert isinstance(resultado, NaoCompareceu)
    return {
        "id": str(resultado.id),
        "status": StatusDoAgendamento.NO_SHOW.value,
        "penalidade": PONTOS_POR_NAO_COMPARECIMENTO,
        "penalidadeTotal": resultado.penalidade_total,
        "scoreNovo": resultado.recalculo.total if resultado.recalculo is not None else None,
    }
