"""A regeneracao do resumo sob demanda, o aceite pelo corretor e a atribuicao pelo admin.

TEC-175, RN-15.2 e D8 do desenho para a regeneracao. TEC-178 e a secao 6.5
do SRS para o aceite. TEC-404, D1 e D7, para a atribuicao.

O Gherkin diz "pelo dashboard", e o dashboard (E8) esta fora do escopo das
duas primeiras cards. Estas rotas sao o mecanismo que ele vai chamar; ate la,
e por elas que os criterios de aceite correspondentes sao exercitados.

A regeneracao e o aceite sao guardados por `ATENDER_LEAD` (TEC-202), que
ADMIN, GERENTE e CORRETOR tem e LEITURA nao: o resumo carrega dado pessoal do
lead e o aceite move o estado do handoff, e rota aberta nao e opcao em nenhum
dos dois casos. A atribuicao e do ADMIN so: `GERIR_CORRETORES`, porque trocar o
dono de um handoff e decidir sobre a equipe, nao atender o lead.

**E o papel CORRETOR so alcanca os PROPRIOS handoffs** -- `_exigir_dono_do`
abaixo, segundo cenario do Gherkin da TEC-202. E aqui que a regra "o corretor
ve apenas os proprios leads" (RNF-12) nasceu aqui: o handoff era a unica
entidade deste sistema que tinha dono E era enderecavel por identificador.
Desde a TEC-193 `GET /api/v1/leads/{leadId}` existe, e o dono do lead e
justamente "existe handoff para ele" -- o recorte de la le esta tabela.

**A regeneracao tem trava de 60 s desde a TEC-193** (D6, para a TEC-326), e e
por esta rota que o botao do detalhe regenera: o `POST /leads/{leadId}/resumo`
que o SRS escreve nao foi criado, porque o resumo e do handoff.
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao, exigir_dono
from mobia.api.middleware import origem_da_requisicao
from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import CAMPO_RESUMO, Acao, Entidade
from mobia.domain.handoff.atribuicao import (
    AtribuicaoRecusada,
    atribuir,
    id_do_job_de_atribuicao,
)
from mobia.domain.handoff.geracao import gerar_resumo
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.resumo import RedatorAnthropic, link_da_transcricao
from mobia.domain.handoff.vocabulario import ACEITAVEIS, Status
from mobia.domain.notificacao.envio import NOTIFICAR_JOB
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.crypto import decrypt
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/handoffs", tags=["handoffs"])

# O intervalo minimo entre dois resumos do mesmo handoff. TEC-326: "Regenerar
# fica desabilitado por 60 s apos o pedido".
_TRAVA_DA_REGENERACAO = timedelta(seconds=60)


async def _exigir_dono_do(
    handoff_id: uuid.UUID, request: Request, identidade: IdentidadeDaRequisicao
) -> None:
    """Recusa o CORRETOR que mexe no handoff de outro. TEC-202, D5.

    **Roda ANTES do trabalho das duas rotas**, e no caso da regeneracao isso e
    o ponto: `gerar_resumo` chama o modelo, e deixar a checagem para depois
    faria uma tentativa negada custar uma chamada paga ao Anthropic.

    **Handoff inexistente passa por aqui sem erro**, de proposito: quem
    responde 404 e o corpo da rota, que ja sabe distinguir "nao existe" de "nao
    pode". Levantar 403 aqui para um id que nao existe transformaria esta
    guarda num oraculo ao contrario -- diria "este id nao e seu" sobre um id
    que nao e de ninguem.

    **E "nao existe" NAO e a mesma coisa que "sem destinatario"**, por isso a
    linha inteira e nao so a coluna: um `scalar_one_or_none` sobre
    `Handoff.corretor_id` devolve `None` nos dois casos, e confundi-los faria o
    handoff sem destinatario (Emenda E-02 da RN-16.3, que existe de verdade
    neste sistema) passar a ser de quem pedisse. Foi assim que este codigo
    nasceu, e foi `test_handoff_sem_destinatario_nao_e_de_ninguem` que pegou.
    """
    if not identidade.e_corretor:
        return
    async with get_sessionmaker()() as session:
        linha = (
            await session.execute(
                select(Handoff.id, Handoff.corretor_id).where(Handoff.id == handoff_id)
            )
        ).first()
    if linha is None:
        return
    await exigir_dono(
        request, identidade, permissao=Permissao.ATENDER_LEAD, corretor_id=linha.corretor_id
    )


@router.post("/{handoff_id}/resumo")
async def regenerar(
    handoff_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.ATENDER_LEAD)),
) -> dict[str, object]:
    await _exigir_dono_do(handoff_id, request, identidade)

    session_factory = get_sessionmaker()

    # TEC-193, D6, para a TEC-326: menos de 60 s desde o ultimo resumo e 429.
    # ANTES de `gerar_resumo`, porque a trava existe para poupar a chamada paga
    # ao modelo -- checada depois, nao pouparia nada. Pelo carimbo que ja
    # existe, e nao por contador novo: a geracao automatica do handoff tambem
    # conta como "a ultima", e e o certo, porque o resumo tem segundos de idade
    # de qualquer jeito. Nenhum resumo sai, entao nada vai para a trilha.
    async with session_factory() as session:
        gerado_em = (
            await session.execute(select(Handoff.resumo_gerado_em).where(Handoff.id == handoff_id))
        ).scalar_one_or_none()
    if gerado_em is not None:
        faltam = _TRAVA_DA_REGENERACAO - (datetime.now(UTC) - gerado_em)
        if faltam > timedelta(0):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="resumo regenerado ha menos de 60 segundos",
                headers={"Retry-After": str(math.ceil(faltam.total_seconds()))},
            )

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
        # TEC-206, D1 e D7. O resumo carrega dado pessoal do lead. Esta rota
        # NAO e o unico caminho que o le: `GET /api/v1/leads/{leadId}` devolve
        # o mesmo texto desde a TEC-193, e registra la com `campo=detalhe`. E o
        # `link` abaixo leva a `conversation_key`, que no WhatsApp ERA o
        # telefone ate a TEC-203 -- hoje e o HMAC dele
        # (`identidade/indice.py::chave_de`), e o link deixou de carregar o
        # telefone sem mudar de forma. A lista deixou de devolver a chave na
        # TEC-195, este `link` nao. O registro daqui nomeia so o campo
        # `resumo`. Ele commita AQUI, antes do `return`: se a escrita falhar, a
        # resposta e erro, e o resumo nao sai sem o registro. O texto do resumo
        # nao vai para a trilha -- ela diz qual campo foi lido, nao o que ele
        # dizia.
        # Registra a TENTATIVA, de proposito: se o `decrypt` abaixo falhar, a
        # trilha diz "acessado" e a resposta e 500 -- trilha de auditoria erra
        # para o lado de registrar.
        await registrar_evento(
            session,
            ator=identidade.como_ator(),
            acao=Acao.DADO_PESSOAL_ACESSADO,
            entidade=Entidade.HANDOFF,
            entidade_id=str(handoff_id),
            campo=CAMPO_RESUMO,
            lead=(linha.channel, linha.conversation_key),
            origem=origem_da_requisicao(request),
        )
        await session.commit()

    return {
        "resumo": decrypt(linha.resumo, aad_do_resumo_de_handoff(handoff_id)),
        "link": link_da_transcricao(linha.channel, linha.conversation_key),
        "geradoEm": linha.resumo_gerado_em.isoformat() if linha.resumo_gerado_em else None,
        "modelo": linha.resumo_modelo,
        # Segundo cenario do Gherkin da TEC-176: "fica indicado que se trata
        # de resumo automatico simplificado". Ate a TEC-193 esta rota era o
        # unico lugar de onde alguem lia isso; desde ela, o detalhe do lead
        # devolve o mesmo sinal em `resumo.fallback`.
        "resumoFallback": linha.resumo_fallback,
    }


# Os estados que `aceitar` transforma em ACEITO. Moram em
# `handoff/vocabulario.py` desde a TEC-194, com o porque de cada um -- a
# tomada da conversa pelo corretor (`atendimento/tomada.py`) decide a mesma
# pergunta, e o dominio nao importa de rota.
_ACEITAVEIS = ACEITAVEIS


@router.post("/{handoff_id}/aceitar")
async def aceitar(
    handoff_id: uuid.UUID,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.ATENDER_LEAD)),
) -> dict[str, object]:
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
    # A leitura de `_exigir_dono_do` NAO decide nada sobre o aceite -- quem
    # decide continua sendo o RETURNING do UPDATE abaixo, pela corrida descrita
    # no docstring. Ela responde outra pergunta ("este handoff e seu?"), cuja
    # resposta nao muda com a escalada concorrente: `escalar_vencidos` nao toca
    # `corretor_id`. Quem o grava e a notificacao (Emenda E-06 da RN-16.2), so
    # quando nulo, e desde a TEC-404 a atribuicao do admin
    # (`domain/handoff/atribuicao.py::atribuir`, Emenda E-07), que o
    # sobrescreve -- e esta sim pode mudar a resposta entre esta leitura e o
    # UPDATE. Por isso, para o CORRETOR, o UPDATE repete a condicao de dono
    # (abaixo): sem ela, o aceite do dono anterior que chegasse nesse intervalo
    # seria reavaliado pelo Postgres contra a linha ja atribuida (PENDENTE,
    # outro dono), passaria, e gravaria ACEITO no handoff de outro.
    await _exigir_dono_do(handoff_id, request, identidade)

    session_factory = get_sessionmaker()
    agora = datetime.now(UTC)

    condicao = [Handoff.id == handoff_id, Handoff.status.in_(_ACEITAVEIS)]
    if identidade.e_corretor:
        condicao.append(Handoff.corretor_id == identidade.corretor_id)

    async with session_factory() as session:
        linha = (
            await session.execute(
                update(Handoff)
                .where(*condicao)
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
            await session.execute(
                select(Handoff.id, Handoff.corretor_id).where(Handoff.id == handoff_id)
            )
        ).first()

    if existe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="handoff nao existe")
    # RETURNING vazio para um CORRETOR pode ser "ja aceito" OU "deixou de ser
    # seu" (a atribuicao da TEC-404 trocou o dono depois de `_exigir_dono_do`).
    # O segundo caso e negado pelo mesmo caminho da checagem inicial -- 403,
    # com ACESSO_NEGADO na trilha --, e nao vira um 409 que esconderia a troca.
    # Fora da sessao acima: `exigir_dono` grava a negativa numa sessao propria.
    await exigir_dono(
        request, identidade, permissao=Permissao.ATENDER_LEAD, corretor_id=existe.corretor_id
    )
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="handoff ja aceito")


class PedidoDeAtribuicao(BaseModel):
    corretorId: uuid.UUID  # noqa: N815


_STATUS_DA_RECUSA = {
    "corretor_invalido": (status.HTTP_422_UNPROCESSABLE_CONTENT, "corretor inexistente ou inativo"),
    "nao_existe": (status.HTTP_404_NOT_FOUND, "handoff nao existe"),
    "concluido": (status.HTTP_409_CONFLICT, "handoff concluido"),
}


@router.post("/{handoff_id}/atribuir")
async def atribuir_handoff(
    handoff_id: uuid.UUID,
    pedido: PedidoDeAtribuicao,
    request: Request,
    identidade: IdentidadeDaRequisicao = Depends(Exige(Permissao.GERIR_CORRETORES)),
) -> dict[str, object]:
    """O admin troca o corretor do handoff -- TEC-404, D1 e D7.

    `GERIR_CORRETORES`, que so o ADMIN tem: e a mesma permissao de
    `GET /api/v1/corretores`, que preenche o seletor da tela. A notificacao e
    enfileirada DEPOIS do commit: um job que rodasse antes leria o handoff
    ainda com o corretor antigo.
    """
    async with get_sessionmaker()() as session:
        try:
            resultado = await atribuir(
                session,
                handoff_id=handoff_id,
                corretor_id=pedido.corretorId,
                ator=identidade.como_ator(),
                origem=origem_da_requisicao(request),
            )
        except AtribuicaoRecusada as recusa:
            codigo, detalhe = _STATUS_DA_RECUSA[recusa.motivo]
            raise HTTPException(status_code=codigo, detail=detalhe) from recusa
        await session.commit()

    if resultado.mudou:
        # A atribuicao ja esta commitada. Se o enfileiramento falhar daqui em
        # diante (Redis fora, pool ausente), a resposta e erro, mas o handoff
        # nao fica perdido: ele esta PENDENTE, sem prazo, sem `notificado_em` e
        # sem `aviso_manual_pendente` -- exatamente o que
        # `recuperar_sem_prazo` (`domain/handoff/recuperacao.py`) seleciona e
        # reenfileira. Por isso nao se tenta desfazer nada aqui.
        pool = getattr(request.app.state, "redis_pool", None)
        if pool is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="sem pool do Redis no app: a notificacao nao foi enfileirada",
            )
        await pool.enqueue_job(
            NOTIFICAR_JOB, str(handoff_id), _job_id=id_do_job_de_atribuicao(handoff_id)
        )

    return {
        # PENDENTE nos dois ramos: o no-op da D7 so acontece com o handoff ja
        # PENDENTE, e a atribuicao efetiva o deixa PENDENTE.
        "status": Status.PENDENTE.value,
        "corretorId": str(pedido.corretorId),
        "aceitoDesfeito": resultado.aceito_desfeito,
    }
