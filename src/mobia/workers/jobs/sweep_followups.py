"""A varredura da cadencia de reengajamento.

TEC-183, RN-13.1 e RN-13.4. Molde do `sweep_stalled`: um job `cron` que
consulta trabalho vencido e age. A diferenca esta no relogio -- ver o
comentario do registro em `workers/main.py`.

**A mensagem e montada e entregue aqui** (TEC-184): a varredura escolhe a
informacao nova, pede a abertura ao modelo, monta o texto e manda pela porta
de saida, ancorada na ultima fala do lead. Ate a TEC-184 esta card so gravava
a tentativa e emitia `followup.devido` -- nada saia, porque a RN-13.2 proibe
follow-up sem informacao nova e um texto provisorio violaria a regra de
frente.
"""

import time
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import Settings, get_settings
from mobia.domain.agente.apresentacao import Ficha
from mobia.domain.agente.ferramenta_de_busca import fichas_do_catalogo
from mobia.domain.atendimento.repositorio import esta_silenciada
from mobia.domain.catalogo.models import Imovel
from mobia.domain.followup.cadencia import CADENCIA, tentativa_devida
from mobia.domain.followup.mensagem import QuedaDePreco, texto_do_followup
from mobia.domain.followup.prosa import redigir_abertura
from mobia.domain.followup.repositorio import (
    Candidato,
    candidatos_a_followup,
    imovel_novo_compativel,
    queda_de_preco,
    registrar_followup,
)
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import esta_em_optout
from mobia.domain.outbound.antispam import MAXIMO_SEM_RESPOSTA, antispam_permite_envio
from mobia.domain.outbound.horario import horario_permite_envio
from mobia.domain.outbound.kinds import KIND_DO_FOLLOWUP
from mobia.domain.outbound.port import EnvioForaDaJanela

log = structlog.get_logger(__name__)

# TEC-184, D7. Nao e medicao -- a chamada que ele limita nao existia quando o
# numero foi escolhido. E um limite derivado do `job_timeout = 240 s`: supondo
# ~4 s de pior caso por follow-up (uma chamada de prosa com `max_tokens`
# pequeno, mais o POST para a Meta), 25 envios sao ~100 s, menos da metade do
# orcamento. Quem medir o custo real deve corrigir este numero -- e a direcao
# certa e medir, nao subir por intuicao quando a varredura parecer lenta.
# Com 25 por execucao e uma varredura a cada 5 minutos, a vazao e de 300
# follow-ups por hora, muito acima de qualquer acumulo plausivel.
MAXIMO_DE_ENVIOS_POR_EXECUCAO = 25

# O segundo teto, e ele tambem NAO e medido -- emenda a D7. Existe porque o de
# cima, sozinho, nao limita o que diz limitar: o cliente do provedor tem
# `TIMEOUT_SEGUNDOS = 60` com uma retentativa (ate 120 s por chamada), entao o
# pior caso de 25 envios nao e o de ~100 s que aquele numero supoe -- e de
# 3000 s contra um `job_timeout` de 240. Um teto que so vale na media e
# decorativo no unico cenario em que um teto importa.
#
# 180 s e derivado do mesmo `job_timeout = 240`, deixando ~60 s de margem para
# a agregacao que produz os candidatos e para o commit do ultimo envio. O que
# muda esta conta e o TIMEOUT do cliente (`outbound/whatsapp.py`) ou o proprio
# `job_timeout`: mexer num dos dois sem mexer aqui volta a deixar o teto
# frouxo.
#
# Quem sobra CONTINUA DEVIDO e entra na varredura seguinte, cinco minutos
# depois -- a cadencia e ancorada e nao encadeada (docstring de
# `cadencia.py`), entao nada se desloca por causa do corte.
TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS = 180


async def _novidade_do_followup(
    session: AsyncSession, session_factory: Any, candidato: Candidato
) -> tuple[Ficha | None, QuedaDePreco | None]:
    """A informacao nova desta mensagem, na ordem de precedencia da D2.

    Devolve o PAR que vai inteiro para `redigir_abertura` e para
    `texto_do_followup`: os dois recebem os MESMOS dois valores, e e isso que
    impede a abertura de falar de um imovel e o corpo de outro. O par
    `(None, queda)` nunca sai daqui -- `texto_do_followup` o recusa com
    `ValueError`, e a unica forma de nao construi-lo e escolher a novidade num
    lugar so.

    A ordem (queda, depois imovel novo, depois nada) e a mesma que
    `texto_do_followup` assume; ela nao esta escrita duas vezes, porque la o
    que existe e a renderizacao do par e aqui o que existe e a consulta que o
    produz.

    `fichas_do_catalogo` e a unica rota daqui ate `domain/catalogo` -- a
    invariante esta no docstring de `ferramenta_de_busca.py`. Remontar a ficha
    aqui criaria a segunda fonte de "como um imovel e mostrado ao lead" que a
    D3 recusa.
    """
    queda = await queda_de_preco(
        session, channel=candidato.channel, conversation_key=candidato.conversation_key
    )
    if queda is not None:
        # O preco da ficha e o de HOJE (`preco_agora_centavos`), e nao o que o
        # lead viu: a legenda diz quanto custa agora, e quem carrega o valor
        # antigo e a linha da queda, uma linha abaixo.
        fichas = await fichas_do_catalogo(
            session_factory,
            ids=(queda.imovel_id,),
            precos={queda.imovel_id: queda.preco_agora_centavos},
        )
        if fichas:
            return fichas[0], queda
        # Imovel inativado entre a consulta da queda e a montagem da ficha:
        # `imoveis_por_ids` devolve a tupla mais curta em vez de `None` no meio
        # dela. Cair para a proxima fonte e o unico desfecho possivel -- queda
        # sem ficha e exatamente o par que `texto_do_followup` recusa.

    novo = await imovel_novo_compativel(
        session,
        channel=candidato.channel,
        conversation_key=candidato.conversation_key,
        desde=candidato.ancora_em,
    )
    if novo is not None:
        # `preco_venda` e nulavel: o CHECK de `imoveis` exige UM dos dois
        # precos, entao um imovel so de aluguel tem esta coluna vazia, e
        # `imovel_novo_compativel` so filtra por ela quando o lead declarou
        # faixa. Sem numero nao ha legenda -- `reais_de` precisa de um --,
        # entao a novidade cede o lugar ao convite em vez de o follow-up
        # inteiro quebrar por um imovel de aluguel no catalogo.
        preco = await session.scalar(select(Imovel.preco_venda).where(Imovel.id == novo))
        if preco is not None:
            fichas = await fichas_do_catalogo(session_factory, ids=(novo,), precos={novo: preco})
            if fichas:
                return fichas[0], None

    return None, None


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

    **O commit e POR CANDIDATO, e nao um so depois do laco** (TEC-184). Ver o
    comentario no corpo: com envio dentro do laco, um rollback de lote deixa
    mensagens ENTREGUES e nenhuma linha em `followups`.

    **O `followup.devido` so e emitido depois do `commit`, nunca antes.** O
    evento e o efeito observavel desta card (o desenho e explicito sobre
    isso), entao logar antes de confirmar mente se algo falhar depois -- um
    `ConnectionResetError` (rotineiro neste repo), um erro de statement, ou o
    `job_timeout` do ARQ cancelando a meio caminho: o rollback desfaz a linha,
    mas o log ja saiu, e a proxima varredura reemite o mesmo evento para a
    mesma tentativa porque o UNIQUE nao tem o que absorver -- nunca houve
    linha para conflitar. Os eventos ficam numa lista e so saem no fim, depois
    de a sessao fechar: com o commit por candidato eles ja poderiam sair
    dentro do laco sem mentir, e continuam na lista porque o retorno da funcao
    e `len(eventos)` e emitir junto mantem uma leitura so do lote.

    **Depois de gravar, a varredura MONTA e ENTREGA** (TEC-184): escolhe a
    informacao nova (`_novidade_do_followup`), pede a abertura ao modelo
    (`redigir_abertura`, cujo `None` e "sem prefixo" e nunca erro), monta o
    texto e manda pela porta, com `kind=followup_<n>` sobre a mensagem-ancora.
    A idempotencia por tentativa sai de graca dai: a UNIQUE
    `(message_id, kind)` de `outbound_dispatches` espelha a UNIQUE
    `(channel, conversation_key, ancora_em, tentativa)` de `followups`.

    **`EnvioForaDaJanela` e capturado por candidato e vira log.** Hoje so a
    tentativa de 2h do QUENTE cabe na janela de 24h da Meta (L1 do desenho);
    as outras oito posicoes batem nessa recusa, e um lead fora da janela nao
    pode custar o follow-up dos outros. **A linha de `followups` permanece** --
    a tabela e append-only e a linha e gravada antes do envio, entao a
    tentativa e CONSUMIDA e nao volta quando a TEC-186 entrar. E decisao da
    L1, nao descuido.

    **Dois tetos por execucao** (D7 e a emenda dela): `MAXIMO_DE_ENVIOS_POR_EXECUCAO`
    e `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS`, ambos no topo do modulo. Quem
    fica de fora continua devido e entra na varredura seguinte.

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
    TEC-184 herdou esta guarda de fato -- editou este mesmo laco e manteve a
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
    # A mesma chave que `process_message` e `notificar_corretor` leem, e nao
    # uma nova: `startup` ja grava `ctx["outbound"] = WhatsAppOutbound(...)`,
    # entao producao entra aqui sem uma linha de mudanca em `workers/main.py`.
    outbound = ctx["outbound"]
    settings: Settings = ctx.get("settings") or get_settings()
    if agora is None:
        agora = datetime.now(UTC)
    # `monotonic` e nao `agora`: `agora` e o relogio da REGUA, que os testes
    # posicionam no futuro ou no passado, e medir duracao contra ele daria
    # numeros sem sentido. O teto de tempo e de parede.
    comeco = time.monotonic()
    enviados = 0
    corte: str | None = None
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
            # Os dois tetos ficam no TOPO do laco, e cortam com `break` e nao
            # com `continue`: todo candidato que passa das guardas termina em
            # envio, entao nao ha nada barato a fazer com o resto da lista
            # depois que o orcamento acabou. Quem sobra continua devido.
            if enviados >= MAXIMO_DE_ENVIOS_POR_EXECUCAO:
                corte = "teto_de_envios"
                break
            if time.monotonic() - comeco >= TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS:
                corte = "teto_de_tempo"
                break

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
            # esgotamento ja excluiu. A TEC-184 herdou esta guarda de fato --
            # editou este mesmo laco e manteve a chamada --, mas nao por um
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

            # TEC-184. **Commit POR CANDIDATO, e nao um so depois do laco.**
            # Ate esta card o laco acumulava e commitava uma vez no fim, o que
            # era certo enquanto nada saia daqui. Com envio dentro do laco vira
            # defeito: um rollback de lote -- um `ConnectionResetError` no
            # decimo candidato, o `job_timeout` cancelando -- deixaria
            # mensagens JA ENTREGUES e nenhuma linha em `followups`. E como
            # `ja_disparada` nao avanca, a varredura seguinte reprocessaria as
            # mesmas tentativas para sempre, pagando a chamada de prosa toda
            # vez, com a reserva de `outbound_dispatches` (que sobreviveu ao
            # rollback, porque e commitada noutra sessao) bloqueando cada
            # duplicata em silencio. O preco desta escolha sao ate 25
            # transacoes pequenas por execucao em vez de uma.
            #
            # Antes do envio, e nao depois: e o que torna a tentativa
            # CONSUMIDA mesmo quando a Meta recusa (L1).
            await session.commit()

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

            # Conta TENTATIVAS de envio, e nao entregas: o que os dois tetos
            # limitam e o TRABALHO, e uma recusa da Meta custa a mesma chamada
            # de prosa e o mesmo POST que uma entrega. Incrementar so no
            # sucesso faria a varredura de hoje -- em que oito das nove
            # posicoes da cadencia sao recusadas (L1) -- nunca cortar nada.
            enviados += 1

            ficha, queda = await _novidade_do_followup(session, session_factory, candidato)
            # `None` daqui e "sem prefixo", NUNCA erro: a prosa e ornamento, e
            # uma falha nela nao pode custar ao lead o follow-up inteiro. Ver
            # o docstring de `redigir_abertura`, que ja trata as quatro causas
            # la dentro e nunca levanta.
            #
            # A MESMA `ficha` e a MESMA `queda` vao para as duas chamadas:
            # escolher a novidade duas vezes deixaria a abertura falar de um
            # imovel e o corpo de outro, e o par invalido (ficha=None com
            # queda) faria `texto_do_followup` levantar depois de a chamada ao
            # modelo ja ter sido paga.
            prefixo = await redigir_abertura(
                session,
                channel=candidato.channel,
                conversation_key=candidato.conversation_key,
                ficha=ficha,
                queda=queda,
            )
            texto = texto_do_followup(ficha=ficha, queda=queda, prefixo=prefixo)

            # O `de` do payload e o nosso numero, que so existe na linha da
            # mensagem -- `Candidato` nao o carrega. Mesma leitura que
            # `notificacao/envio.py` ja faz para montar o aviso ao lead, so
            # que aqui a mensagem certa e conhecida: e a propria ancora.
            #
            # `None` e inalcancavel pelo caminho da varredura --
            # `ancora_message_id` sai de uma agregacao sobre `messages` e a FK
            # de `outbound_dispatches` aponta para a mesma tabela --, e o
            # guard existe porque `scalar` devolve `str | None` e engolir isso
            # com um `cast` esconderia o dia em que alguem chamar o job com um
            # candidato construido a mao.
            de = await session.scalar(
                select(Message.recipient_external_id).where(
                    Message.id == candidato.ancora_message_id
                )
            )
            if de is None:
                log.warning(
                    "followup.ancora_sem_mensagem",
                    channel=candidato.channel,
                    tentativa=tentativa,
                )
                continue

            try:
                await outbound.send(
                    candidato.ancora_message_id,
                    KIND_DO_FOLLOWUP(tentativa),
                    {
                        "para": candidato.conversation_key,
                        "de": de,
                        "texto": texto,
                    },
                )
            except EnvioForaDaJanela:
                # Por candidato, e o laco SEGUE: um lead fora da janela de 24h
                # da Meta nao pode custar o follow-up dos outros. Hoje so a
                # tentativa de 2h do QUENTE cabe na janela, entao esta e a
                # ramificacao mais percorrida da varredura (L1 do desenho).
                #
                # **A linha de `followups` permanece, e a tentativa e
                # CONSUMIDA.** A tabela e append-only e a linha foi commitada
                # antes do envio, entao ela nao volta a vencer quando a
                # TEC-186 (template fora da janela) entrar -- o lead perde
                # aquela posicao da cadencia para sempre. E decisao da L1, com
                # o custo declarado, e nao efeito colateral: desfaze-la aqui
                # faria a varredura reprocessar a mesma tentativa a cada cinco
                # minutos, pagando a prosa toda vez para bater na mesma
                # recusa.
                #
                # `info` e nao `warning`: enquanto a TEC-186 nao entra, isto e
                # o caminho esperado para oito das nove posicoes da cadencia, e
                # alarmar em cada uma afogaria o log.
                log.info(
                    "followup.fora_da_janela_de_24h",
                    channel=candidato.channel,
                    tentativa=tentativa,
                    temperatura=candidato.temperatura.value,
                )
                continue

        if corte is not None:
            # Nao e erro: e o teto funcionando, e o excedente continua devido.
            # Visivel porque a alternativa e a varredura entregar menos do que
            # deve sem nada no log dizendo por que.
            log.info(
                "followup.corte_por_teto",
                motivo=corte,
                enviados=enviados,
                candidatos=len(candidatos),
                decorrido_s=int(time.monotonic() - comeco),
            )

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
