"""A varredura da cadencia de reengajamento.

TEC-183, RN-13.1 e RN-13.4. Molde do `sweep_stalled`: um job `cron` que
consulta trabalho vencido e age. A diferenca esta no relogio -- ver o
comentario do registro em `workers/main.py`.

**A mensagem e montada e entregue aqui** (TEC-184): a varredura escolhe a
informacao nova, monta o texto e manda pela porta de saida, ancorada na ultima
fala do lead. Ate a TEC-184 esta card so gravava a tentativa e emitia
`followup.devido` -- nada saia, porque a RN-13.2 proibe follow-up sem
informacao nova e um texto provisorio violaria a regra de frente.

**O CANAL e decidido pela janela de 24h** (TEC-186, RN-13.6), a partir da
ancora e antes do envio: dentro da janela sai o texto livre da TEC-184, com a
abertura do modelo; fora dela sai um template aprovado escolhido pelo contexto
(`domain/followup/template.py`), e sem template aplicavel o follow-up vira uma
tarefa para o corretor (`tarefas_de_corretor`) em vez de um envio que a Meta
recusaria. Hoje so a tentativa de +2h do QUENTE cai dentro da janela; as outras
oito posicoes caem fora.
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
from mobia.domain.followup.cadencia import CADENCIA, esta_dormente, tentativa_devida
from mobia.domain.followup.mensagem import QuedaDePreco, texto_do_followup
from mobia.domain.followup.prosa import redigir_abertura
from mobia.domain.followup.repositorio import (
    MOTIVO_SEM_TEMPLATE,
    Candidato,
    candidatos_a_followup,
    imovel_novo_compativel,
    queda_de_preco,
    registrar_followup,
    registrar_tarefa_de_corretor,
)
from mobia.domain.followup.template import (
    categoria_da_novidade,
    dentro_da_janela,
    escolher_template,
    parametros_do_template,
)
from mobia.domain.messages.models import Message
from mobia.domain.optout.repositorio import esta_em_optout
from mobia.domain.outbound.antispam import MAXIMO_SEM_RESPOSTA, antispam_permite_envio
from mobia.domain.outbound.horario import horario_permite_envio
from mobia.domain.outbound.kinds import KIND_DO_FOLLOWUP
from mobia.domain.outbound.port import EnvioForaDaJanela, EnvioRecusado, EnvioRetentavel

log = structlog.get_logger(__name__)

# TEC-184, D7. O teto de CONTAGEM, e so isso -- **quem limita o tempo de
# execucao e o `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS` logo abaixo, nao este
# numero.** A D7 escolheu o 25 a partir de uma estimativa de ~4 s por
# follow-up, que dava ~100 s de pior caso; essa estimativa **esta errada** --
# o bloco de baixo refaz a conta com os clientes reais e chega a ~3250 s --, e
# e por isso que ela nao esta repetida aqui como se fosse fato. Nao e
# medicao: a chamada que o 25 limita nao existia quando o numero foi
# escolhido.
#
# O que o 25 continua valendo: um limite de VOLUME por passagem. Com 25 por
# execucao e uma varredura a cada 5 minutos, a vazao e de 300 follow-ups por
# hora, muito acima de qualquer acumulo plausivel -- e o excedente continua
# devido. Quem medir o custo real deve corrigir este numero, e a direcao certa
# e medir, nao subir por intuicao quando a varredura parecer lenta.
MAXIMO_DE_ENVIOS_POR_EXECUCAO = 25

# O segundo teto, e ele tambem NAO e medido -- emenda a D7. Existe porque o de
# cima, sozinho, nao limita o que diz limitar.
#
# **Os dois CLIENTES EXTERNOS de um candidato custam ate ~70 s, e 60 deles sao
# do provedor de MODELO, nao da Meta** -- e esses ~70 s sao a parte grande do
# custo de um candidato, nunca o custo inteiro dele (ver a conta do teto, mais
# abaixo). A chamada de `redigir_abertura` usa o cliente de
# `infra/anthropic.py` e **nao manda teto proprio**, entao cai no piso de
# construcao: `TIMEOUT_SEGUNDOS = 60.0`. Desde a TEC-228 o `MAX_TENTATIVAS` de
# la e 0, entao sao 60 s e nao os 120 s que esta conta usava. O POST para a
# Meta custa no maximo os `TIMEOUT_SEGUNDOS = 10.0` de
# `outbound/whatsapp.py`, que nao retenta -- o 5xx/408/429 vira
# `EnvioRetentavel`, e **nesta varredura ninguem retenta**: ver o `except
# EnvioRetentavel` no corpo, que registra por que o nome do tipo desmente o
# desfecho aqui. Nao confunda os dois clientes: e o de `infra/anthropic.py`
# que domina esta conta.
#
# Com isso, o pior caso de 25 envios nao e o de ~100 s que a estimativa da D7
# supunha -- e de ~1750 s contra um `job_timeout` de 240. Um teto que so vale
# na media e decorativo no unico cenario em que um teto importa.
#
# **90 s, e a conta NAO fecha em igualdade -- ela deixa margem de proposito.**
# A checagem roda no TOPO do laco, o que significa que mais um candidato
# inteiro pode comecar imediatamente depois de ela passar: o tempo total no
# pior caso e o teto MAIS um candidato.
#
# **E um candidato nao custa os ~130 s dos dois clientes externos: custa esses
# ~130 s MAIS o proprio custo de banco.** Depois da checagem ele ainda paga
# `esta_em_optout`, `esta_silenciada`, `registrar_followup` e o commit, as
# tres consultas de `_novidade_do_followup`, a sessao de `fichas_do_catalogo`,
# o `ler_resumo` de dentro de `redigir_abertura`, o `scalar` do `de` e as tres
# sessoes proprias que `GuardedOutbound.send` abre. A versao anterior deste
# comentario dizia `110 + 130 = 240` como igualdade exata; o proprio codigo a
# desmentia, porque nenhuma dessas idas ao banco entrava na soma -- e um teto
# que fecha exatamente numa soma incompleta nao tem margem nenhuma, tem margem
# NEGATIVA.
#
# A conta honesta: 240 (`job_timeout`) - 70 (os dois clientes externos) - 20
# = 150. **E o numero abaixo continua 90, que e MENOS do que a formula
# permite.** A TEC-228 baixou o custo do cliente de modelo de 120 s para 60 s e
# abriu 60 s de espaco aqui; reclamar esse espaco mudaria quantos follow-ups
# uma varredura entrega, que e efeito visivel para o lead e nao cabe a uma card
# que fala de timeout. Um teto mais apertado que o permitido e seguro: o que
# sobra continua devido e entra na varredura seguinte, cinco minutos depois.
# Subir para 150 e outra card.
#
# Os 20 s sao uma RESERVA declarada para o custo de banco do candidato,
# e nao uma medicao -- ninguem mediu, e e exatamente por isso que ela e
# generosa em vez de justa. Quem medir o custo real corrige este numero; a
# direcao certa continua sendo medir, e nao subir por intuicao.
#
# O teto e um numero so, e nao uma condicao com o pior caso subtraido dentro
# dela, de proposito: dois termos derivados multiplicam o palpite, e um numero
# unico com a conta escrita e mais facil de corrigir quando alguem medir.
#
# O que muda esta conta: o `TIMEOUT_SEGUNDOS`/`MAX_TENTATIVAS` de
# `infra/anthropic.py` e o `job_timeout` do worker. Mexer num dos dois sem
# refazer a soma acima volta a deixar o teto frouxo.
#
# Quem sobra CONTINUA DEVIDO e entra na varredura seguinte, cinco minutos
# depois -- a cadencia e ancorada e nao encadeada (docstring de
# `cadencia.py`), entao nada se desloca por causa do corte.
TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS = 90


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
        # Tupla vazia aqui e a LINHA do imovel ter sumido entre as duas
        # consultas -- `imoveis_por_ids` filtra so por id, entao ela encurta a
        # tupla quando nao ha linha, e NAO quando o status muda. "Inativado"
        # neste repo e valor de coluna, nao DELETE.
        #
        # **Nao existe rede de seguranca a jusante para o status**: quem
        # garante que a queda e de imovel ainda disponivel e o
        # `Imovel.status == DISPONIVEL` de `queda_de_preco`, e nada aqui. A
        # versao anterior deste comentario afirmava o contrario, e foi por
        # acreditar nela que aquele filtro passou sete tasks faltando --
        # anunciando queda de preco em imovel VENDIDO.
        #
        # Cair para a proxima fonte e o unico desfecho possivel -- queda sem
        # ficha e exatamente o par que `texto_do_followup` recusa.

    novo = await imovel_novo_compativel(
        session,
        channel=candidato.channel,
        conversation_key=candidato.conversation_key,
        desde=candidato.ancora_em,
    )
    if novo is not None:
        # `preco_venda` e nulavel na tabela, mas NAO no que chega aqui:
        # `imovel_novo_compativel` filtra `preco_venda IS NOT NULL` desde o fix
        # de revisao desta task -- um imovel so de locacao nao e novidade
        # entregavel, e escolher um para descartar depois em silencio era o
        # defeito que aquele filtro fechou.
        #
        # O guard abaixo sobrevive porque `scalar` devolve `int | None` e
        # engolir isso com um `cast` esconderia a unica forma de ele voltar a
        # acontecer: alguem afrouxar o filtro de la sem olhar para ca.
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
    linha para conflitar. **O evento sai imediatamente DEPOIS do commit
    daquele candidato, e nao de uma lista lida no fim** (TEC-184): com o
    commit por candidato, guardar os eventos para o fim faria um aborto no
    meio do lote apagar o registro de trabalho que ja aconteceu e ja foi
    entregue. Ate esta card a lista era coerente, porque o mesmo aborto
    desfazia as linhas junto.

    **Depois de gravar, a varredura MONTA e ENTREGA** (TEC-184, TEC-186):
    escolhe a informacao nova (`_novidade_do_followup`) e entao decide o canal
    pela janela de 24h (`dentro_da_janela`, a partir da ancora). Dentro da
    janela pede a abertura ao modelo (`redigir_abertura`, cujo `None` e "sem
    prefixo" e nunca erro), monta o texto e manda o texto livre; fora dela
    escolhe um template aprovado pelo contexto e o manda, ou -- sem template
    aplicavel -- grava uma tarefa em `tarefas_de_corretor` sem enviar nada.
    O envio vai com `kind=followup_<n>` sobre a mensagem-ancora, e a
    idempotencia por tentativa sai de graca dai: a UNIQUE `(message_id, kind)`
    de `outbound_dispatches` espelha a UNIQUE
    `(channel, conversation_key, ancora_em, tentativa)` de `followups`.

    **Nenhuma falha de envio derruba o lote: as tres viram log e o laco
    segue.** `EnvioForaDaJanela` em `info` (desde a TEC-186 e RESIDUAL -- a
    janela e decidida antes do envio, entao fora dela nem se tenta texto livre;
    so a posicao de +2h do QUENTE, dentro da janela, pode bate-la por desacordo
    de relogio na borda), qualquer outro `EnvioRecusado` em `error`, e
    `EnvioRetentavel` em `warning`. **A linha de `followups` permanece nos
    tres** -- a tabela e append-only e a linha e gravada antes do envio, entao
    a tentativa e CONSUMIDA. Para as recusas isso e a L1, declarada; para o
    retentavel e uma perda que o nome do tipo desmente, e o `warning` existe
    para que ela nao seja silenciosa (ver o comentario no corpo).

    **E nenhuma falha POS-COMMIT derruba o lote tampouco** (fix de revisao,
    TEC-184; ampliado na TEC-186): a escolha da novidade, a leitura do `de`, a
    prosa (so dentro da janela), e -- fora dela -- a escolha do template ou a
    gravacao da tarefa acontecem DEPOIS do commit que consome a tentativa, e
    todas vao ao banco. Um erro ali vira `followup.montagem_falhou` em `error`,
    com `rollback` antes do `continue` -- sem o rollback a sessao ficaria
    envenenada e o candidato SEGUINTE morreria no `esta_em_optout`, que roda
    fora do bloco protegido. A promessa acima so era verdadeira sobre o envio
    ate esta correcao, e a superficie pos-commit desta card e maior que a do
    envio.

    `asyncio.CancelledError` continua propagando: nao e `Exception`.

    **Dois tetos por execucao** (D7 e a emenda dela): `MAXIMO_DE_ENVIOS_POR_EXECUCAO`
    e `TETO_DE_TEMPO_POR_EXECUCAO_SEGUNDOS`, ambos no topo do modulo. Quem
    fica de fora continua devido e entra na varredura seguinte. A conta que
    justifica o segundo mora no comentario da constante, e nao aqui, para nao
    existir em duas copias -- e ela inclui uma reserva declarada para o custo
    de banco do candidato, que nao esta medido.

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

    O retorno continua sendo o numero de linhas GRAVADAS, e nao o de mensagens
    entregues: uma recusa da Meta consome a tentativa e conta aqui do mesmo
    jeito. O evento de maximo nao entra nessa contagem -- gravar e atingir o
    maximo sao fatos diferentes, e somar os dois faria o retorno mentir para
    quem mede a varredura.

    **RN-13.5 tambem sai desta varredura**: quando a tentativa recem-gravada
    fecha o teto da temperatura (`esta_dormente`), sai `followup.dormente` --
    o instante em que o lead sai do alcance da automacao, e nao um estado
    gravado em lugar nenhum. Quem quiser o estado consulta `listar_dormentes`.
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
    gravadas = 0
    corte: str | None = None

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

            gravadas += 1

            # **Emitido AQUI, logo depois do commit deste candidato, e nao
            # numa lista lida no fim.** A regra da TEC-183 continua a mesma --
            # o evento nunca sai antes de a linha estar confirmada --, o que
            # mudou foi onde o commit acontece. Com o commit por candidato, a
            # lista passou a ter uma assimetria nova e errada: um aborto no
            # meio do lote (um `ConnectionResetError` no decimo, o
            # `job_timeout` cancelando) deixaria as linhas dos candidatos
            # anteriores gravadas E AS MENSAGENS ENTREGUES, mas jogaria fora
            # os eventos de todos eles -- silencio sobre trabalho que de fato
            # aconteceu. Antes desta card a lista era coerente, porque o
            # mesmo aborto desfazia as linhas junto.
            #
            # O texto do lead nao entra: a regra de PII que
            # `moderacao.entrada_bloqueada` respeita vale igual aqui.
            log.info(
                "followup.devido",
                channel=candidato.channel,
                tentativa=tentativa,
                temperatura=candidato.temperatura.value,
                ancora_em=candidato.ancora_em.isoformat(),
                devido_em=devido_em.isoformat(),
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
                # `warning` e nao `info`: nao e erro, mas e um lead saindo do
                # alcance da automacao, que a RN-13.7 quer visivel para a
                # gerente. Mesmo nivel de `followup.candidatos_saturados` e
                # `outbound.optout_bloqueou`, que tambem sao "funcionou como
                # desenhado, e alguem precisa saber".
                #
                # `conversation_key` viaja aqui e nao em `followup.devido`: o
                # proposito da propria regra e que alguem consiga agir sobre O
                # LEAD especifico que saiu do alcance da automacao, e um evento
                # sem identificador nao da para isso. `structlog` mascara o
                # campo (`_CHAVES_MASCARADAS` em `app/logging.py`) para os
                # quatro ultimos digitos antes de qualquer coisa chegar ao log
                # de verdade.
                log.warning(
                    "followup.antispam_atingido",
                    channel=candidato.channel,
                    conversation_key=candidato.conversation_key,
                    ancora_em=candidato.ancora_em.isoformat(),
                    ja_enviadas=MAXIMO_SEM_RESPOSTA,
                )

            # RN-13.5. Depois do `commit` acima, pela mesma regra do
            # `followup.devido` logo acima: nada e logado antes de estar
            # gravado.
            #
            # **`DORMENTE` nao e gravado em lugar nenhum** -- e derivado de
            # `followups` por `esta_dormente`, e esta linha e so o instante
            # ficando visivel. Quem quiser o estado consulta
            # `listar_dormentes`; quem quiser o momento le este evento.
            #
            # **Dispara quando a ultima tentativa E ENVIADA, e nao depois de
            # ela ficar sem resposta.** O cenario 1 da card diz "quando a
            # ultima tentativa se esgota", e no desenho derivado esse instante
            # nao existe: nao ha tentativa pendente que expire, ha uma linha
            # que e gravada. Um lead que responder dez minutos depois ja tera
            # gerado esta linha -- e saira de dormente na varredura seguinte,
            # porque a fala move a ancora. Divergencia declarada na D3.
            #
            # `esta_dormente` e nao `tentativa == len(CADENCIA[...])`: a conta
            # e a mesma, mas escrita aqui seria uma quarta copia do teto.
            if esta_dormente(temperatura=candidato.temperatura, ja_disparada=tentativa):
                # `warning` e nao `info`, mesmo nivel do
                # `followup.antispam_atingido` logo acima e pela mesma razao:
                # funcionou como desenhado, e alguem precisa saber -- um lead
                # acabou de sair do alcance da automacao. `conversation_key`
                # viaja porque o proposito da RN-13.5 e que a gerente consiga
                # agir sobre ESTE lead; `structlog` o mascara para os quatro
                # ultimos digitos antes de chegar ao log de verdade.
                log.warning(
                    "followup.dormente",
                    channel=candidato.channel,
                    conversation_key=candidato.conversation_key,
                    temperatura=candidato.temperatura.value,
                    # `ja_disparada`, e nao `tentativas`: no instante em que
                    # este evento sai, `tentativa` E o maior numero de
                    # tentativa gravado sob a ancora -- a mesma grandeza que
                    # `Candidato.ja_disparada` e `LeadDormente.ja_disparada`
                    # nomeiam no resto do dominio. "Tentativas" no plural e a
                    # mesma ambiguidade contagem-vs-posicao que o dataclass
                    # deixou de ter, e este e o evento que uma pessoa le.
                    ja_disparada=tentativa,
                    ancora_em=candidato.ancora_em.isoformat(),
                )

            # Conta TENTATIVAS de envio, e nao entregas: o que os dois tetos
            # limitam e o TRABALHO, e uma recusa da Meta custa a mesma chamada
            # de prosa e o mesmo POST que uma entrega. Incrementar so no
            # sucesso faria a varredura de hoje -- em que oito das nove
            # posicoes da cadencia sao recusadas (L1) -- nunca cortar nada.
            enviados += 1

            # **Todo o trabalho POS-COMMIT deste candidato mora dentro deste
            # `try`** (fix de revisao, TEC-184). O commit acima tornou a
            # tentativa CONSUMIDA e irrecuperavel -- a linha e append-only e
            # `ja_disparada` nao volta --, e o que vem depois dele ainda sao
            # tres idas ao banco antes do envio: `_novidade_do_followup`, o
            # `ler_resumo` de dentro de `redigir_abertura`, e o `scalar` do
            # `de`. Com elas fora de qualquer `except`, um `DBAPIError` num
            # candidato subia pelo `for` e abortava o job: aquele candidato
            # ficava com a linha commitada e nenhuma mensagem, e os SEGUINTES
            # perdiam a propria posicao da cadencia por uma falha que nao era
            # deles. E a mesma razao que ja justificava o `except
            # EnvioRecusado` logo abaixo, estendida para a causa que escapava.
            #
            # A mais provavel delas nao e nem um erro de statement aqui:
            # `redigir_abertura` engole a propria excecao por contrato (o
            # `None` dela e "sem prefixo", nunca erro) e, depois de um erro de
            # statement, a transacao fica desativada -- a operacao seguinte, o
            # `scalar` do `de`, levantaria `PendingRollbackError`. Por isso o
            # `except` de la faz `rollback` e este aqui tambem faz: sem o
            # rollback, o candidato SEGUINTE morreria no `esta_em_optout`, que
            # roda fora deste bloco.
            #
            # `asyncio.CancelledError` continua propagando em todos os tres:
            # nao e `Exception`.
            try:
                # A novidade e escolhida SEMPRE, e a MESMA `ficha`/`queda` vai
                # para tudo que segue: dentro da janela ela vira o texto livre,
                # fora dela a categoria do template ou da tarefa. Escolher duas
                # vezes deixaria a categoria divergir do texto que o outro
                # caminho montaria (D2), e o par invalido (ficha=None com queda)
                # faria `texto_do_followup` levantar depois de a chamada ao
                # modelo ja ter sido paga.
                ficha, queda = await _novidade_do_followup(session, session_factory, candidato)

                # O `de` do payload e o nosso numero, que so existe na linha da
                # mensagem -- `Candidato` nao o carrega. Mesma leitura que
                # `notificacao/envio.py` ja faz para montar o aviso ao lead, so
                # que aqui a mensagem certa e conhecida: e a propria ancora.
                #
                # **A ancora ser uma fala do LEAD e o que torna este valor CERTO,
                # e nao so nao-nulo.** `falas_do_lead` filtra `direction =
                # 'INBOUND'`, e numa linha de ENTRADA `recipient_external_id`
                # responde "para quem foi" -- o NOSSO numero. Numa linha de SAIDA
                # a mesma coluna guarda o numero do LEAD, e e por isso que
                # `notificacao/envio.py` se chaveia na mensagem mais recente DO
                # LEAD e nao na mais recente da conversa: a outra faria o envio
                # sair do numero errado.
                #
                # `None` e inalcancavel hoje pela COLUNA, e nao pela existencia da
                # linha: `Message.recipient_external_id` e `nullable=True`
                # (`messages/models.py`), entao a FK nao diz nada sobre isto --
                # quem garante o valor e a ingestao, onde
                # `ParsedMessage.recipient_external_id` e `str` obrigatorio
                # (`messages/schemas.py`). O guard fica porque `scalar` devolve
                # `str | None` e porque essa garantia mora noutro modulo: engolir
                # com um `cast` esconderia tanto a ingestao afrouxar quanto alguem
                # chamar o job com um candidato construido a mao.
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

                # TEC-186, D1. A janela e decidida A PARTIR DA ANCORA, antes de
                # qualquer envio: fora dela nenhuma mensagem livre pode ser
                # tentada (cenario 1 do Gherkin). `ancora_em` e a ultima fala do
                # LEAD, entao uma resposta do agente no meio nao move a janela
                # (cenario 4). Hoje so a tentativa de +2h do QUENTE cai dentro; as
                # outras oito posicoes caem fora -- consequencia de `CADENCIA` e
                # da janela de 24h, nao de um caso escrito a mao.
                if dentro_da_janela(ancora_em=candidato.ancora_em, agora=agora):
                    # `None` de `redigir_abertura` e "sem prefixo", NUNCA erro: a
                    # prosa e ornamento, e uma falha nela nao pode custar o
                    # follow-up inteiro. Ela so roda AQUI, dentro da janela (D5):
                    # fora, o template e texto fixo aprovado e nao ha abertura
                    # livre a escrever, e as oito posicoes de fora deixam de
                    # pagar a chamada ao modelo.
                    prefixo = await redigir_abertura(
                        session,
                        channel=candidato.channel,
                        conversation_key=candidato.conversation_key,
                        ficha=ficha,
                        queda=queda,
                    )
                    texto = texto_do_followup(ficha=ficha, queda=queda, prefixo=prefixo)
                    await outbound.send(
                        candidato.ancora_message_id,
                        KIND_DO_FOLLOWUP(tentativa),
                        {"para": candidato.conversation_key, "de": de, "texto": texto},
                    )
                    log.info(
                        "followup.entregue",
                        canal="livre",
                        channel=candidato.channel,
                        tentativa=tentativa,
                    )
                else:
                    # Fora da janela: so template aprovado, escolhido pela
                    # categoria da novidade. `templates_aprovados` e configuracao
                    # externa (RT-03), vazia por padrao.
                    categoria = categoria_da_novidade(ficha=ficha, queda=queda)
                    template = escolher_template(
                        categoria=categoria, aprovados=settings.templates_aprovados
                    )
                    if template is None:
                        # RN-13.6: sem template aplicavel, o follow-up NAO vira
                        # tentativa de envio livre -- a Meta a recusaria --, vira
                        # tarefa para o corretor. Commit proprio; a tentativa ja
                        # foi consumida pelo commit anterior. `warning` e o nivel
                        # de `followup.dormente`: funcionou como desenhado, e
                        # alguem precisa saber. Com `aprovados` vazio (o default
                        # do RT-03) este e o caminho de todo follow-up fora da
                        # janela.
                        await registrar_tarefa_de_corretor(
                            session,
                            candidato=candidato,
                            tentativa=tentativa,
                            categoria=categoria,
                            motivo=MOTIVO_SEM_TEMPLATE,
                        )
                        await session.commit()
                        log.warning(
                            "followup.tarefa_de_corretor",
                            channel=candidato.channel,
                            conversation_key=candidato.conversation_key,
                            tentativa=tentativa,
                            categoria=categoria,
                        )
                    else:
                        # Template aprovado: o unico envio que a Meta aceita fora
                        # da janela. Sem prosa do modelo (D5); os parametros saem
                        # de `ficha`/`queda`, numero nenhum passa pelo modelo.
                        parametros = parametros_do_template(
                            template=template, ficha=ficha, queda=queda
                        )
                        await outbound.send(
                            candidato.ancora_message_id,
                            KIND_DO_FOLLOWUP(tentativa),
                            {
                                "para": candidato.conversation_key,
                                "de": de,
                                "tipo": "template",
                                "template": template.nome,
                                "idioma": template.idioma,
                                "parametros": parametros,
                            },
                        )
                        log.info(
                            "followup.entregue",
                            canal="template",
                            template=template.nome,
                            channel=candidato.channel,
                            tentativa=tentativa,
                        )
            except EnvioRecusado as falha:
                # **`EnvioRecusado`, a superclasse, e nao so a
                # `EnvioForaDaJanela`.** As duas sao permanentes -- retentar
                # nao muda nada -- e nenhuma pode custar o follow-up dos
                # outros candidatos do lote. Capturar so a filha deixava um
                # 4xx de payload ou um 401 de token abortar a varredura
                # inteira, com os candidatos seguintes adiados por uma falha
                # que nao e deles.
                #
                # **A linha de `followups` permanece nos dois casos, e a
                # tentativa e CONSUMIDA.** A tabela e append-only e a linha foi
                # commitada antes do envio. E decisao da L1 (TEC-184), com o
                # custo declarado: desfaze-la aqui faria a varredura reprocessar
                # a mesma tentativa a cada cinco minutos, pagando a prosa toda
                # vez para bater na mesma recusa.
                #
                # **Desde a TEC-186 esta recusa e RESIDUAL, e nao o caminho de
                # oito posicoes.** A janela agora e decidida a partir da ancora
                # ANTES do envio (D1): fora dela nao se tenta texto livre --
                # vai template ou tarefa --, entao `EnvioForaDaJanela` so e
                # alcancavel pela posicao DENTRO da janela (a de +2h do QUENTE)
                # que a Meta recuse por desacordo de relogio na borda (D7). Ela
                # NAO vira template nem tarefa: um envio que nos decidimos estar
                # dentro da janela e a Meta recusou e discordancia de relogio,
                # nao a regra da RN-13.6, e converte-lo reintroduziria o "tentou
                # a mensagem livre primeiro" que o cenario 1 do Gherkin proibe.
                #
                # Os NIVEIS separam as duas: a recusa residual de janela e
                # `info`, porque nao e erro nosso; qualquer outra recusa e
                # `error`, o mesmo nivel de `outbound.recusado_permanente`,
                # porque ai o payload ou a credencial estao errados e ninguem vai
                # descobrir isso sozinho.
                if isinstance(falha, EnvioForaDaJanela):
                    log.info(
                        "followup.fora_da_janela_de_24h",
                        channel=candidato.channel,
                        tentativa=tentativa,
                        temperatura=candidato.temperatura.value,
                    )
                else:
                    log.error(
                        "followup.recusado_permanente",
                        channel=candidato.channel,
                        tentativa=tentativa,
                        # So o nome da classe, como no resto do projeto: o
                        # texto da excecao pode carregar corpo de resposta.
                        reason=type(falha).__name__,
                    )
                continue
            except EnvioRetentavel as falha:
                # **O laco segue aqui tambem, e este e o caso que mais merece
                # o cuidado.** `whatsapp.py` levanta `EnvioRetentavel` para
                # 5xx, erro de rede e 408/429 -- e 429 e exatamente o que uma
                # rajada de ate 25 mensagens provoca. Propagando, UM 429
                # abortaria o lote inteiro e adiaria todos os seguintes; e
                # como cada um deles ja teria commitado a propria linha, o
                # adiamento seria definitivo.
                #
                # **Retentavel aqui NAO quer dizer que alguem vai retentar.**
                # `GuardedOutbound.send` libera a reserva antes de propagar
                # (`_liberar`), mas a linha de `followups` ja esta commitada e
                # e append-only: `ja_disparada` nao volta, a tentativa nao
                # vence de novo, e nao ha sweeper deste lado -- o
                # `sweep_stalled` reenfileira MENSAGEM do lead, nao follow-up.
                # A tentativa se perde igual a uma recusa permanente. E por
                # isso que isto e `warning` e carrega o tipo da falha: sem esta
                # linha, a perda seria silenciosa, que e o unico desfecho que
                # este repo trata como inaceitavel.
                #
                # O caminho de retentativa de verdade -- reentregar a tentativa
                # perdida numa varredura seguinte -- exigiria `followups`
                # deixar de ser append-only ou uma coluna de desfecho, e e
                # decisao de outra card.
                #
                # `asyncio.CancelledError` NAO cai em nenhum dos tres
                # `except` deste bloco -- nem no `except Exception` mais
                # abaixo: nao e `Exception`, e propaga sozinho. E o desfecho
                # certo -- o `job_timeout` ou o shutdown chegou, e seguir
                # enviando depois de cancelado seria pior.
                log.warning(
                    "followup.envio_falhou",
                    channel=candidato.channel,
                    tentativa=tentativa,
                    reason=type(falha).__name__,
                )
                continue
            except Exception as falha:
                # A rede que faltava. Nivel `error` e nao `warning`: ao
                # contrario da recusa da Meta, isto nao e caminho esperado de
                # nenhuma posicao da cadencia -- e a tentativa ja foi
                # consumida pelo commit, entao o lead perdeu essa posicao sem
                # nunca ter recebido nada.
                #
                # O `rollback` vem ANTES do `continue` e e o que torna o
                # `continue` honesto: depois de um erro de statement a sessao
                # fica em estado de rollback pendente, e o proximo candidato
                # bateria nisso no `esta_em_optout` -- fora deste `try` --,
                # transformando uma falha em aborto do lote pelo caminho
                # longo.
                #
                # So o nome da classe, como no resto do projeto: o texto da
                # excecao pode carregar corpo de resposta ou dado do lead.
                await session.rollback()
                log.error(
                    "followup.montagem_falhou",
                    channel=candidato.channel,
                    tentativa=tentativa,
                    erro=type(falha).__name__,
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

    return gravadas
