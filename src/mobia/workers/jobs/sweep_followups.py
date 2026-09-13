"""A varredura da cadencia de reengajamento.

TEC-183, RN-13.1 e RN-13.4. Molde do `sweep_stalled`: um job `cron` que
consulta trabalho vencido e age. A diferenca esta no relogio -- ver o
comentario do registro em `workers/main.py`.

**Nada e enviado ao lead.** A card grava a tentativa e emite `followup.devido`;
o texto e a entrega sao da TEC-184, e a RN-13.2 proibe follow-up sem
informacao nova, entao um texto provisorio violaria a regra de frente. Lacuna
declarada no desenho.
"""

from datetime import UTC, datetime
from typing import Any

import structlog

from mobia.app.config import Settings, get_settings
from mobia.domain.atendimento.repositorio import esta_silenciada
from mobia.domain.followup.cadencia import CADENCIA, tentativa_devida
from mobia.domain.followup.repositorio import candidatos_a_followup, registrar_followup
from mobia.domain.optout.repositorio import esta_em_optout
from mobia.domain.outbound.antispam import MAXIMO_SEM_RESPOSTA, antispam_permite_envio
from mobia.domain.outbound.horario import horario_permite_envio

log = structlog.get_logger(__name__)


async def sweep_followups(
    ctx: dict[str, Any], limite: int = 500, *, agora: datetime | None = None
) -> int:
    """Registra as tentativas de follow-up que venceram. Devolve quantas.

    **A ordem das quatro guardas POR CANDIDATO e proposital: `tentativa_devida`,
    depois `antispam_permite_envio`, depois `esta_em_optout`, e por ultimo
    `esta_silenciada` (TEC-179) -- as duas ultimas so para quem passou todas as
    anteriores.** As duas primeiras sao funcao pura, sem I/O; as duas ultimas
    sao ida ao banco. Checar opt-out ou silencio antes pagaria essa consulta
    para todo candidato, inclusive os que nem estao devidos ou ja esgotaram o
    maximo -- e a premissa que justifica consultar por candidato em vez de
    juntar na query (comentario abaixo) e que o conjunto que sobra depois dos
    cortes puros e pequeno. Invertida, essa premissa deixa de valer.

    O opt-out e a conversa silenciada sao consultados por candidato, e nao
    juntados na consulta: `esta_em_optout` e `esta_silenciada` sao a unica
    implementacao de cada fato, e escreve-los uma segunda vez em SQL criaria
    duas fontes que divergem em silencio -- o defeito que a TEC-146 gastou uma
    card inteira consertando. O preco e duas consultas por candidato devido, e
    esses sao poucos por construcao: so quem tem temperatura, calou ha mais de
    duas horas, ainda nao esgotou e tem tentativa vencida agora.

    Um `registrar_followup` que devolve `None` significa que outra varredura
    chegou primeiro (o `ON CONFLICT DO NOTHING` absorveu). Nao e erro e nao
    entra na contagem.

    **O `followup.devido` so e emitido depois do `commit`, nunca dentro do
    loop.** O evento e o efeito observavel desta card (o desenho e explicito
    sobre isso), entao logar antes de confirmar mente em duas direcoes se algo
    falhar depois -- um `ConnectionResetError` no meio do lote (rotineiro
    neste repo), um erro de statement, ou o `job_timeout` do ARQ cancelando a
    meio caminho: o rollback desfaz a linha, mas o log ja saiu, e a proxima
    varredura reemite o mesmo evento para a mesma tentativa porque o UNIQUE
    nao tem o que absorver -- nunca houve linha para conflitar. Os eventos
    ficam numa lista dentro do loop e so saem depois que `session.commit()`
    retorna, com o lote inteiro ja confirmado.

    **A guarda de horario (TEC-185, RN-13.3) roda antes da consulta, e e a
    unica das quatro que roda antes.** Sob fuso unico (PR-04) a janela e
    propriedade de `agora` e nao do candidato, entao nada do que a consulta
    trouxesse mudaria a resposta -- e o `GROUP BY` sobre `messages` e a parte
    cara desta varredura. Por treze das vinte e quatro horas o job nao toca o
    banco.

    **Quando o fuso virar por lead, esta chamada desce para dentro do laco**,
    ao lado de `esta_em_optout`, e a funcao pura nao muda: ela ja recebe o
    fuso por parametro. Nao reescreva o predicado achando que ele e global por
    natureza. O que muda tambem: a candidatura de um lead nao depende mais so
    de estar devido, mas de estar devido E dentro do PROPRIO horario -- e quem
    esta fora do proprio horario nao sai da consulta, so nao dispara. Esses
    leads ficam no topo do `ORDER BY ancora_em` e consomem vagas de `limite`
    sem produzir `followup.devido`, a mesma forma de esfomeamento que o corte
    de esgotamento e a lacuna 6 do desenho da TEC-183 ja registram.

    **Nao ha codigo de adiamento, e nao falta nenhum.** A card pede que o
    disparo fora da janela seja "adiado para a proxima abertura, nao
    descartado" e que "o adiamento nao consuma a tentativa". Como nada e
    gravado quando a janela recusa, `ja_disparada` -- que e o MAX sob a ancora
    -- nao se move, e a proxima varredura dentro da janela reencontra a mesma
    tentativa devida. As duas regras sao consequencia da cadencia derivada, e
    nao implementacao.

    **`agora` entra por parametro pela razao que `candidatos_a_followup` ja
    escreveu para a consulta**: sem isso nenhum teste consegue posicionar o
    relogio. Com a guarda de horario isso deixou de ser conveniencia -- sem o
    parametro, a suite inteira desta varredura passaria ou reprovaria conforme
    a hora do dia em que o CI rodasse. Producao nao passa o argumento.

    **A guarda do maximo (TEC-188, RN-13.7) entra antes do opt-out por ser
    pura.** Ela conta mensagens que sairam -- `ja_enviadas`, o COUNT sob a
    ancora --, e nao a posicao da regua. Hoje ela nao pode
    disparar pela consulta real: o UNIQUE limita a quatro linhas por ancora e
    o QUENTE para em quatro, entao o maximo coincide com o esgotamento. A
    TEC-184 herda esta guarda de fato -- vai editar este mesmo laco e manter a
    chamada --, mas nao por um mecanismo de linguagem como o de
    `GuardedOutbound`, so por tocar o mesmo codigo. A TEC-171 nao herda nada:
    sera outro job sobre outra tabela e tera de lembrar de chamar o predicado;
    o que ganha e so a facilidade de acha-lo em `outbound/` (D8). Nenhuma das
    duas torna a guarda alcancavel -- isso exige um segundo produtor que
    componha a propria contagem em `ja_enviadas` (lacuna 4 do desenho).

    O retorno continua sendo o numero de linhas GRAVADAS. O evento de maximo
    sai numa lista propria e nao entra nessa contagem: gravar e atingir o
    maximo sao fatos diferentes, e somar os dois faria o retorno mentir para
    quem mede a varredura.
    """
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()
    if agora is None:
        agora = datetime.now(UTC)
    eventos: list[dict[str, Any]] = []
    eventos_de_maximo: list[dict[str, Any]] = []

    if not horario_permite_envio(
        momento=agora,
        inicio=settings.followup_horario_inicio,
        fim=settings.followup_horario_fim,
        fuso=settings.fuso_de_envio,
    ):
        # debug, e nao info: a cadencia de 5 minutos faz isto disparar por
        # treze das vinte e quatro horas, cerca de 156 vezes ao dia. Sem esta
        # linha, uma janela VALIDA mas ERRADA (FOLLOWUP_HORARIO_FIM=10 por
        # typo, ou FOLLOWUP_FUSO=UTC deslocando a janela em tres horas) produz
        # o mesmo sintoma que o validator de Settings existe para evitar --
        # ausencia de `followup.devido` indistinguivel de "nenhum lead devido"
        # -- e so o validator nao alcanca essa classe de erro, porque a janela
        # continua sendo POSSIVEL.
        log.debug(
            "sweep.fora_do_horario",
            agora=agora.isoformat(),
            inicio=settings.followup_horario_inicio,
            fim=settings.followup_horario_fim,
            fuso=settings.followup_fuso,
        )
        return 0

    async with session_factory() as session:
        candidatos = await candidatos_a_followup(session, agora=agora, limite=limite)

        for candidato in candidatos:
            tentativa = tentativa_devida(
                temperatura=candidato.temperatura,
                ultima_fala=candidato.ancora_em,
                ja_disparada=candidato.ja_disparada,
                agora=agora,
            )
            if tentativa is None:
                continue

            # A guarda do maximo entra ANTES do opt-out porque e pura: a
            # premissa que justifica consultar o opt-out por candidato e que o
            # conjunto que sobra depois dos cortes baratos e pequeno.
            #
            # **Esta guarda nao pode disparar pela consulta real hoje**, e isso
            # e declarado, nao esquecido: o UNIQUE limita a quatro linhas por
            # ancora e a cadencia do QUENTE para em quatro, entao
            # `ja_enviadas=4` implica `ja_disparada=4`, que o corte de
            # esgotamento ja excluiu. A TEC-184 herda esta guarda de fato --
            # vai editar este mesmo laco e manter a chamada --, mas nao por um
            # mecanismo de linguagem como o de `GuardedOutbound`, so por tocar
            # o mesmo codigo. A TEC-171 nao herda nada: sera outro job sobre
            # outra tabela e tera de lembrar de chamar o predicado; o que
            # ganha e so a facilidade de acha-lo em `outbound/`. Nenhuma das
            # duas torna a guarda alcancavel -- isso exige um segundo produtor
            # que componha a propria contagem em `ja_enviadas` (lacuna 4 do
            # desenho).
            if not antispam_permite_envio(ja_enviadas=candidato.ja_enviadas):
                continue

            if await esta_em_optout(
                session,
                channel=candidato.channel,
                conversation_key=candidato.conversation_key,
            ):
                continue

            # TEC-179, RN-16.4: nenhuma automacao dispara em conversa que um
            # corretor assumiu. A guarda da porta de saida (`outbound/port.py`)
            # barraria o envio de qualquer jeito, mas so DEPOIS de esta funcao
            # registrar a tentativa em `followups`, que e append-only. Sem a
            # checagem aqui, uma conversa silenciada acumularia tentativas que
            # nunca sairam, e o antispam da RN-13.1 as contaria contra o lead
            # quando a conversa fosse devolvida.
            if await esta_silenciada(
                session,
                channel=candidato.channel,
                conversation_key=candidato.conversation_key,
            ):
                continue

            devido_em = candidato.ancora_em + CADENCIA[candidato.temperatura][tentativa - 1]
            linha = await registrar_followup(
                session, candidato=candidato, tentativa=tentativa, devido_em=devido_em
            )
            if linha is None:
                continue

            # O texto do lead nao entra: a regra de PII que
            # `moderacao.entrada_bloqueada` respeita vale igual aqui.
            eventos.append(
                {
                    "channel": candidato.channel,
                    "tentativa": tentativa,
                    "temperatura": candidato.temperatura.value,
                    "ancora_em": candidato.ancora_em.isoformat(),
                    "devido_em": devido_em.isoformat(),
                }
            )

            # `==` e nao `>=` porque a guarda acima ja garante
            # `ja_enviadas < MAXIMO_SEM_RESPOSTA`, entao a soma nunca passa do
            # maximo -- e o evento e sobre o INSTANTE em que a contagem fecha.
            #
            # Emitir a cada supressao, em vez de uma vez aqui, repetiria a
            # mesma linha a cada cinco minutos para sempre, porque um lead que
            # nunca responde nunca sai do estado. "Atingir o teto" e um
            # instante; o estado e derivavel da tabela a qualquer momento.
            if candidato.ja_enviadas + 1 == MAXIMO_SEM_RESPOSTA:
                eventos_de_maximo.append(
                    {
                        "channel": candidato.channel,
                        "conversation_key": candidato.conversation_key,
                        "ancora_em": candidato.ancora_em.isoformat(),
                        "ja_enviadas": MAXIMO_SEM_RESPOSTA,
                    }
                )

        await session.commit()

    for evento in eventos:
        log.info("followup.devido", **evento)

    for evento in eventos_de_maximo:
        # `warning` e nao `info`: nao e erro, mas e um lead saindo do alcance
        # da automacao, que a RN-13.7 quer visivel para a gerente. Mesmo nivel
        # de `followup.candidatos_saturados` e `outbound.optout_bloqueou`, que
        # tambem sao "funcionou como desenhado, e alguem precisa saber".
        #
        # `conversation_key` viaja aqui e nao em `followup.devido`: o proposito
        # da propria regra e que alguem consiga agir sobre O LEAD especifico
        # que saiu do alcance da automacao, e um evento sem identificador nao
        # da para isso. `structlog` mascara o campo (`_CHAVES_MASCARADAS` em
        # `app/logging.py`) para os quatro ultimos digitos antes de qualquer
        # coisa chegar ao log de verdade.
        log.warning("followup.antispam_atingido", **evento)

    return len(eventos)
