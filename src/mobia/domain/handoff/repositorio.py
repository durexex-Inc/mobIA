"""A escrita do handoff, com a deduplicacao que a RN-16.1 exige."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import any_, case, func, literal, literal_column, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.models import Recomendacao
from mobia.domain.catalogo.models import Imovel
from mobia.domain.context.models import LeadQualification, LeadScoreAudit
from mobia.domain.handoff.dossie import Dossie, ImovelApresentado
from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho, Prioridade, Status
from mobia.domain.messages.enums import MessageRole
from mobia.domain.messages.models import Message
from mobia.infra.crypto import encrypt


@dataclass(frozen=True)
class HandoffRegistrado:
    """O que `registrar_handoff` devolve.

    Dataclass e nao tupla porque os tres chamadores leem pelo nome, e porque
    `ResumoGerado` e `Score` ja estabeleceram a forma neste repo.

    `id` e sempre o da linha que EXISTE no banco depois do statement -- a
    recem-inserida quando `criado`, a que ja estava aberta quando nao. O
    `values()` calcula um uuid novo a cada chamada e o descarta no caminho do
    UPDATE; devolver aquele daria um id fantasma a quem chama.
    """

    id: uuid.UUID
    criado: bool


async def registrar_handoff(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    gatilho: Gatilho,
) -> HandoffRegistrado:
    """Cria o handoff da conversa, ou acumula o gatilho no que ja esta aberto.

    Devolve `HandoffRegistrado`, com `criado=True` quando criou linha nova e
    `criado=False` quando atualizou uma aberta. **Nao commita** -- o commit e
    de quem chama, como em
    `registrar_recalculo`. E isso que poe o handoff na MESMA transacao do
    recalculo no gatilho QUENTE: ou o lead vira QUENTE e tem handoff, ou nem
    uma coisa nem outra. O estado intermediario -- lead quente, ninguem
    avisado -- e exatamente o que a card existe para impedir.

    **Um statement, e nao um SELECT seguido de INSERT.** A corrida e prevista:
    `turno.py` declara que `lead.esquentou` reemite para o MESMO lead desde a
    TEC-148, e a suite roda com oito workers. Quem arbitra e o indice parcial
    `uq_handoffs_conversa_pendente`, nao a ordem do codigo.
    """
    agora = datetime.now(UTC)
    prioridade = PRIORIDADE_DE[gatilho]

    statement = pg_insert(Handoff).values(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        gatilho=gatilho.value,
        etiqueta=ETIQUETA_DE[gatilho],
        prioridade=prioridade.value,
        status=Status.PENDENTE.value,
        gatilhos_adicionais=[],
        criado_em=agora,
        atualizado_em=agora,
    )

    resultado = await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            index_where=text("status = 'PENDENTE'"),
            set_={
                # TEC-174, fix wave (Important 3). So acrescenta quando o
                # gatilho ainda NAO esta presente -- nem como o que CRIOU o
                # handoff (coluna `gatilho`), nem como um dos
                # `gatilhos_adicionais` ja gravados. Sem isto, um gatilho sem
                # condicao de borda (a intencao dispara em TODO turno com a
                # classificacao certa, ao contrario do QUENTE) acumulava o
                # mesmo valor uma vez por turno. `= ANY(...)` testa
                # pertinencia a array em Postgres.
                "gatilhos_adicionais": case(
                    (
                        or_(
                            literal(gatilho.value) == Handoff.gatilho,
                            literal(gatilho.value) == any_(Handoff.gatilhos_adicionais),
                        ),
                        Handoff.gatilhos_adicionais,
                    ),
                    else_=func.array_append(Handoff.gatilhos_adicionais, literal(gatilho.value)),
                ),
                # A escalada de `vocabulario.escalada`, em SQL: o Python nao ve
                # a linha existente neste caminho, e ler antes para decidir
                # devolveria a corrida que este statement existe para evitar.
                "prioridade": case(
                    (
                        literal(prioridade.value) == Prioridade.ALTA.value,
                        literal(Prioridade.ALTA.value),
                    ),
                    else_=Handoff.prioridade,
                ),
                "atualizado_em": agora,
            },
        ).returning(
            Handoff.id,
            # xmax e o sinal nativo do Postgres para distinguir INSERT de
            # UPDATE num ON CONFLICT: vale 0 na linha recem-inserida e
            # diferente de zero na que foi atualizada. NAO comparar carimbos
            # de tempo aqui -- `agora` e calculado em Python antes do
            # statement, e duas escritas concorrentes para a mesma conversa
            # podem calcular o MESMO valor. Nesse caso a chamada que fez
            # UPDATE bateria com o `criado_em` que a vencedora gravou e
            # devolveria True por coincidencia de relogio, nao por sinal do
            # banco -- exatamente a corrida que este statement existe para
            # arbitrar, so que agora no booleano de retorno em vez de na
            # linha.
            (literal_column("xmax") == 0).label("inseriu"),
        )
    )

    # TEC-174, fix wave (Important 2). Nao loga aqui: esta funcao nao commita,
    # entao um log daqui roda dentro da transacao de quem chama e sobrevive a
    # um rollback -- log sem linha, se o commit do chamador falhar. Quem
    # chama ja recebe o registro e loga DEPOIS do proprio commit.
    #
    # O id vem do RETURNING, e nao do uuid calculado no values() acima: esse
    # uuid e descartado quando o statement cai no caminho do UPDATE, e o
    # RETURNING devolve a linha que de fato existe no banco -- a recem-criada
    # ou a que ja estava aberta, conforme `inseriu`.
    linha = resultado.one()
    return HandoffRegistrado(id=linha.id, criado=linha.inseriu)


def _preco_centavos(imovel: Imovel) -> tuple[int, str]:
    """O preco a exibir de um imovel apresentado, com o rotulo de qual e.

    `Imovel` nao tem uma coluna `preco_centavos` unica -- ela so existe em
    `Candidato` (`catalogo/schemas.py`), derivada da OPERACAO que a busca
    pediu (`COLUNA_DE_PRECO`). Aqui nao ha filtro de busca para escolher a
    coluna -- `recomendacoes` nao guarda qual operacao a busca pediu --,
    entao esta funcao usa o preco de venda quando existe e cai para o de
    aluguel (`ck_imoveis_ao_menos_um_preco` garante que ao menos um dos dois
    esta preenchido), mas devolve o ROTULO junto: escolher em silencio
    poria um preco de venda no resumo de um lead que quer alugar, e rotular
    e mais barato que casar o preco com a intencao do lead.
    """
    if imovel.preco_venda is not None:
        return imovel.preco_venda, "venda"
    assert imovel.preco_aluguel is not None, "ck_imoveis_ao_menos_um_preco garante que existe"
    return imovel.preco_aluguel, "aluguel"


def _imovel_apresentado(recomendacao: Recomendacao, imovel: Imovel) -> ImovelApresentado:
    preco, tipo_de_preco = _preco_centavos(imovel)
    return ImovelApresentado(
        codigo=imovel.codigo,
        preco_centavos=preco,
        tipo_de_preco=tipo_de_preco,
        reacao=recomendacao.reacao_lead,
        motivo_descarte=recomendacao.motivo_descarte,
    )


async def carregar_dossie(session: AsyncSession, *, handoff_id: uuid.UUID) -> Dossie | None:
    """Monta o dossie das quatro tabelas. `None` quando o handoff nao existe.

    `None` e nao excecao: o job pode chegar depois de a linha sumir (um
    TRUNCATE de teste, uma limpeza futura), e isso nao e erro do job -- e
    trabalho que perdeu o objeto. Quem chama loga e sai.

    Le em quatro consultas e nao num JOIN so: `recomendacoes` e um-para-muitos
    e o JOIN multiplicaria as linhas das outras tres, obrigando a desduplicar
    em Python o que quatro SELECTs simples ja entregam prontos.
    """
    handoff = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one_or_none()
    if handoff is None:
        return None

    qualificacao = (
        await session.execute(
            select(LeadQualification).where(
                LeadQualification.channel == handoff.channel,
                LeadQualification.conversation_key == handoff.conversation_key,
            )
        )
    ).scalar_one_or_none()

    # O ultimo recalculo, que e o score corrente: a trilha e append-only e so
    # grava quando o resultado muda, entao a linha mais nova E o estado de
    # hoje. Mesmo ORDER BY do `registrar_recalculo`, e servido pelo mesmo
    # indice `ix_lead_score_audit_lead`.
    auditoria = (
        await session.execute(
            select(LeadScoreAudit)
            .where(
                LeadScoreAudit.channel == handoff.channel,
                LeadScoreAudit.conversation_key == handoff.conversation_key,
            )
            .order_by(LeadScoreAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    recomendacoes = (
        (
            await session.execute(
                select(Recomendacao, Imovel)
                .join(Imovel, Imovel.id == Recomendacao.imovel_id)
                .where(
                    Recomendacao.channel == handoff.channel,
                    Recomendacao.conversation_key == handoff.conversation_key,
                )
                .order_by(Recomendacao.apresentado_em)
            )
        )
        .tuples()
        .all()
    )

    origem = (
        await session.execute(
            select(func.min(Message.created_at), func.count()).where(
                Message.channel == handoff.channel,
                Message.conversation_key == handoff.conversation_key,
                Message.role == MessageRole.LEAD,
            )
        )
    ).one()

    return Dossie(
        canal=handoff.channel,
        conversa=handoff.conversation_key,
        primeira_mensagem_em=origem[0] or handoff.criado_em,
        mensagens_do_lead=origem[1],
        intencao=qualificacao.intencao if qualificacao else None,
        faixa_min_centavos=qualificacao.faixa_preco_min_centavos if qualificacao else None,
        faixa_max_centavos=qualificacao.faixa_preco_max_centavos if qualificacao else None,
        regiao=qualificacao.regiao if qualificacao else None,
        tipo_imovel=qualificacao.tipo_imovel if qualificacao else None,
        quartos=qualificacao.quartos if qualificacao else None,
        vagas=qualificacao.vagas if qualificacao else None,
        urgencia=qualificacao.urgencia if qualificacao else None,
        forma_pagamento=qualificacao.forma_pagamento if qualificacao else None,
        tem_imovel_para_vender=qualificacao.tem_imovel_para_vender if qualificacao else None,
        score_total=auditoria.total_novo if auditoria else None,
        score_fatores=(
            (
                ("completude", auditoria.completude),
                ("urgencia", auditoria.urgencia),
                ("catalogo", auditoria.catalogo),
                ("engajamento", auditoria.engajamento),
                ("capacidade", auditoria.capacidade),
            )
            if auditoria
            else ()
        ),
        score_causas=tuple(auditoria.causas) if auditoria else (),
        temperatura=qualificacao.temperatura if qualificacao else None,
        # `or ()` nas duas: NULL e vazio nao sao sinonimos na gravacao, mas na
        # LEITURA sao -- e o que os comentarios das colunas em
        # `context/models.py` mandam fazer.
        temperatura_forcada_motivos=tuple(
            (qualificacao.temperatura_forcada_motivos if qualificacao else None) or ()
        ),
        imoveis=tuple(
            _imovel_apresentado(recomendacao, imovel) for recomendacao, imovel in recomendacoes
        ),
        campos_recusados=tuple((qualificacao.campos_recusados if qualificacao else None) or ()),
        perguntados_sem_resposta=tuple(
            (qualificacao.perguntados_sem_resposta if qualificacao else None) or ()
        ),
        gatilho=handoff.gatilho,
        etiqueta=handoff.etiqueta,
        prioridade=handoff.prioridade,
        criado_em=handoff.criado_em,
    )


async def gravar_resumo(
    session: AsyncSession, *, handoff_id: uuid.UUID, texto: str, modelo: str
) -> None:
    """Grava o resumo cifrado. **Nao commita** -- o commit e de quem chama.

    Mesma disciplina de `registrar_handoff`, e pela mesma razao: e o chamador
    que sabe o que mais precisa entrar na transacao.
    """
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(
            resumo=encrypt(texto, aad_do_resumo_de_handoff(handoff_id)),
            resumo_gerado_em=datetime.now(UTC),
            resumo_modelo=modelo,
        )
    )
