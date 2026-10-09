"""A escalada do handoff sem aceite dentro do prazo. TEC-178, RN-16.3.

Molde do `sweep_followups`: um job `cron` que consulta trabalho vencido e
age. A diferenca esta na corrida com a rota de aceite (TEC-178, Task 6, que
tira o handoff de PENDENTE), e desde a TEC-179 tambem `assumir`
(`routes/conversas.py`) -- ver o comentario do UPDATE em `escalar_vencidos`.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.resumo import link_da_transcricao
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.notificacao.canais import CanalDeNotificacaoPort, FalhaDeCanal
from mobia.domain.notificacao.destinatario import gerente_ativo
from mobia.domain.notificacao.mensagem import Aviso

log = structlog.get_logger(__name__)


async def escalar_vencidos(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    canais: Sequence[CanalDeNotificacaoPort],
    limite: int = 100,
) -> int:
    """Escala os handoffs PENDENTE vencidos e tenta avisar o gerente. Devolve quantos.

    **A selecao e a garantia de nao repetir -- D6.** `status = 'PENDENTE' AND
    sla_limite_em IS NOT NULL AND sla_limite_em < agora`. Escalar muda o
    status para ESCALADO, e a linha SAI do conjunto sozinha na proxima
    passagem -- nenhuma coluna "ja escalei", nenhum `if`. E garantia de
    schema, nao disciplina de consulta.

    `sla_limite_em IS NOT NULL` nao e detalhe de implementacao: nulo
    significa "ainda nao notificado" ou "nao havia a quem cobrar" (o handoff
    sem destinatario ja nasce ESCALADO na notificacao da TEC-177, com
    `sla_limite_em` nulo para sempre) -- NUNCA "prazo zero". Um handoff sem
    prazo nao pode ser varrido por esta -- quem varre esse caso e a rede
    irma, `recuperar_sem_prazo` (`domain/handoff/recuperacao.py`, TEC-279).

    **A corrida real, e a razao de o UPDATE repetir a condicao do SELECT.** A
    rota de aceite (Task 6), e desde a TEC-179 tambem `assumir`
    (`routes/conversas.py`), tira o handoff de PENDENTE. Se qualquer uma
    commitar entre
    o SELECT abaixo e o UPDATE, marcar ESCALADO cobraria o gerente por um
    lead que ja tem dono -- e o gerente e quem paga o preco de um sinal
    errado. Por isso o UPDATE repete a condicao inteira do SELECT no proprio
    WHERE -- `status = 'PENDENTE'` E o prazo vencido --, e nao so no SELECT
    que trouxe os candidatos. O prazo entrou na TEC-404: a atribuicao do admin
    (`handoff/atribuicao.py`) devolve o handoff a PENDENTE com
    `sla_limite_em` nulo, e um UPDATE que olhasse so o status escalaria, logo
    depois, o handoff que acabou de ganhar dono e prazo novos. Quem arbitra a
    corrida e o banco, no mesmo raciocinio do `ON CONFLICT` de
    `registrar_handoff` (`handoff/repositorio.py`). O `RETURNING` devolve so
    as linhas que o UPDATE de fato mudou -- um id que a rota aceitou no meio
    do caminho nao aparece ali, e este job nunca notifica o gerente sobre
    ele: notificar depois de perder a corrida seria o mesmo defeito, so que
    no canal em vez do banco.

    **A notificacao ao gerente reusa os canais da TEC-177, e eles nao tem o
    mesmo desfecho aqui** -- o e-mail entrega por SMTP (TEC-280); o whatsapp
    falha, porque desde a TEC-281 ele exige template aprovado pela Meta e
    ESTA mensagem nao tem um. O template que aquela card configurou e o do
    aviso de lead pronto ao corretor, e manda-lo ao gerente diria a coisa
    errada -- ver o `Aviso` montado no laco abaixo. O status ESCALADO gravado
    no banco e o que existe de fato hoje; o aviso ao gerente e melhor esforco
    e so vira log.

    **Sem gerente cadastrado, o handoff escala do mesmo jeito.** A marcacao e
    o que importa -- e o gatilho para a rota da Task 6 seguinte parar de
    valer para este handoff; o aviso e so o que falta, e vira log.

    **M7 da revisao final, declarada e nao corrigida aqui:** o `commit()`
    acima vem ANTES de `gerente_ativo` e do laco que loga por handoff. Uma
    excecao no meio do laco (um `KeyError` de `destino_por_canal` por canal
    mal configurado, ou uma falha de banco em `gerente_ativo`) interrompe
    tudo depois do commit -- as linhas ja ficaram `ESCALADO`, mas nem todo
    handoff escalado nesta passagem ganha o `handoff.escalado` ou
    `handoff.escalado_sem_gerente` correspondente. Pela L4, o log e hoje o
    unico artefato observavel da escalada -- entao esse evento fica
    invisivel para quem so olha o log, embora o estado no banco continue
    correto.
    """
    agora = datetime.now(UTC)

    async with session_factory() as session:
        candidatos = (
            (
                await session.execute(
                    select(Handoff.id)
                    .where(
                        Handoff.status == Status.PENDENTE.value,
                        Handoff.sla_limite_em.is_not(None),
                        Handoff.sla_limite_em < agora,
                    )
                    # Mais vencido primeiro: sob o teto de `limite`, quem espera ha
                    # mais tempo nao fica esfomeado por handoffs vencidos depois.
                    .order_by(Handoff.sla_limite_em)
                    .limit(limite)
                )
            )
            .scalars()
            .all()
        )

        if not candidatos:
            return 0

        escalados = (
            await session.execute(
                update(Handoff)
                .where(
                    Handoff.id.in_(candidatos),
                    Handoff.status == Status.PENDENTE.value,
                    Handoff.sla_limite_em.is_not(None),
                    Handoff.sla_limite_em < agora,
                )
                .values(status=Status.ESCALADO.value, atualizado_em=agora)
                .returning(
                    Handoff.id,
                    Handoff.channel,
                    Handoff.conversation_key,
                    Handoff.etiqueta,
                    Handoff.prioridade,
                )
            )
        ).all()
        await session.commit()

        gerente = await gerente_ativo(session)

    if not escalados:
        return 0

    if gerente is None:
        for linha in escalados:
            log.warning(
                "handoff.escalado_sem_gerente",
                handoff_id=str(linha.id),
                motivo="nenhum gerente ativo cadastrado, ninguem foi avisado",
            )
        return len(escalados)

    # `canal.nome` -> destino, mesmo mapa de `notificacao/envio.py`. Um
    # `canal.nome` fora deste par e configuracao errada, e o KeyError sobe
    # cru -- nao vira "gerente nao avisado" por engano.
    destino_por_canal = {"email": gerente.email, "whatsapp": gerente.telefone}

    for linha in escalados:
        link = link_da_transcricao(linha.channel, linha.conversation_key)
        assunto = f"Handoff vencido [{linha.etiqueta}] prioridade {linha.prioridade}"
        # Nunca o resumo do handoff aqui -- esta mensagem e sobre o PRAZO
        # perdido, nao sobre o lead, e nao ha necessidade de decifrar nada
        # para escalar.
        corpo = (
            "Um handoff passou do prazo de aceite e ainda nao foi assumido.\n\n"
            f"Conversa completa: {link}"
        )
        # `template=None` (default): esta mensagem NAO tem template aprovado
        # pela Meta. O da TEC-281 e o do aviso de lead pronto ao corretor, e
        # mandar aquele texto ao gerente diria a coisa errada. Enquanto nao
        # houver um proprio, o canal de WhatsApp falha alto aqui -- que e o
        # mesmo desfecho pratico de antes (o gerente nunca recebeu WhatsApp),
        # so que agora dito em voz alta em vez de registrado como se fosse
        # entrega.
        aviso = Aviso(
            assunto=assunto,
            corpo=corpo,
            etiqueta=linha.etiqueta,
            prioridade=linha.prioridade,
            link=link,
        )

        motivos: dict[str, str] = {}
        algum_canal_aceitou = False
        # Sequencial, e nao paralelo -- e desde a TEC-280 isso nao e mais de
        # graca. Antes desta card nenhum canal falava rede e o laco era
        # instantaneo; agora o e-mail manda uma mensagem de verdade por SMTP,
        # ate `SEGUNDOS_DE_TIMEOUT` (15s) cada, contra um `job_timeout = 240`
        # do worker (`workers/main.py`) que o job `sweep_sla` (que chama
        # `escalar_vencidos`) tambem tem que caber. Margem para uns 16
        # handoffs escalados no mesmo sweep antes de estourar -- numero nao
        # medido em carga real, so contado; nao e motivo para mudar o laco
        # agora.
        for canal in canais:
            destino = destino_por_canal[canal.nome]
            try:
                await canal.enviar(destino=destino, aviso=aviso)
            except FalhaDeCanal as falha:
                motivos[canal.nome] = str(falha)
            else:
                algum_canal_aceitou = True

        # Nunca `corpo` nem `assunto` com o resumo -- so o que permite saber
        # SE e PARA QUEM o aviso saiu, mesma disciplina de `notificar`.
        #
        # `algum_canal_aceitou`, e NAO `gerente_avisado` ou equivalente: o
        # e-mail entrega por SMTP desde a TEC-280 e PODE levantar
        # `FalhaDeCanal`. **Ate a TEC-281 o whatsapp so registrava e NUNCA
        # levantava, entao este campo era sempre `True` mesmo com o e-mail
        # falhando** -- ja nao e: o canal de WhatsApp agora exige template
        # aprovado, esta mensagem nao tem um (ver o `Aviso` acima), e ele
        # falha alto. Na pratica o campo passou a refletir so o e-mail, que e
        # o unico canal que de fato entrega a escalada hoje. Um nome que
        # sugerisse entrega prometeria algo que nem o
        # e-mail garante: aceito pelo servidor nao e o mesmo que lido pelo
        # gerente. Mesmo raciocinio do comentario de `TEXTO_DA_JANELA_HUMANA`
        # em `notificacao/envio.py`: este repo ja pagou por essa frase exata
        # uma vez (TEC-174), e o `log` e hoje o UNICO artefato observavel da
        # escalada -- nao reintroduza a promessa aqui so porque ela sumiu do
        # texto.
        log.info(
            "handoff.escalado",
            handoff_id=str(linha.id),
            conversation_key=linha.conversation_key,
            etiqueta=linha.etiqueta,
            prioridade=linha.prioridade,
            algum_canal_aceitou=algum_canal_aceitou,
        )
        if not algum_canal_aceitou:
            log.warning("handoff.escalado_sem_entrega", handoff_id=str(linha.id), motivos=motivos)

    return len(escalados)
