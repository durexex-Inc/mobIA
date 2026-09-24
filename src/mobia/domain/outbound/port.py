import asyncio
import uuid
from typing import Any, Protocol

import structlog
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.atendimento.repositorio import esta_silenciada_por_mensagem
from mobia.domain.optout.deteccao import KIND_DA_CONFIRMACAO_DE_OPTOUT
from mobia.domain.optout.repositorio import esta_em_optout_por_mensagem
from mobia.domain.outbound.kinds import grupo_de
from mobia.domain.outbound.models import OutboundDispatch

log = structlog.get_logger(__name__)

# A UNIQUE (message_id, kind) de `outbound_dispatches` -- ver
# `OutboundDispatch.__table_args__`. E a unica violacao de integridade que
# significa "ja reservei este envio".
UNIQUE_DA_RESERVA = "uq_outbound_message_kind"


def _e_reserva_duplicada(exc: IntegrityError) -> bool:
    """Distingue a colisao da reserva de qualquer outra falha de integridade.

    Tratar todo IntegrityError como duplicata converte uma falha nao
    relacionada (FK quebrada, NOT NULL, um constraint novo que alguem
    adicionar amanha) no desfecho terminal do turno: `send()` devolve False, o
    turno vira "reentrega_suprimida", a linha fecha em PROCESSED -- terminal --
    e o lead nunca recebe nada, com uma linha de log que diz "duplicata
    suprimida" e manda quem investiga para o lado errado.

    **O nome estruturado do constraint mora um nivel abaixo de `exc.orig`.**
    Sondado contra o banco na TEC-230: `orig` e o
    `sqlalchemy.dialects.postgresql.asyncpg.IntegrityError`, que **nao** tem
    `constraint_name`; quem tem e o erro do proprio asyncpg, que o dialeto
    deixa no `__cause__` dele. A versao anterior desta funcao lia o atributo
    direto de `orig`, nunca o encontrava, e caia sempre no fallback por texto
    -- o ramo apresentado como principal era o que nunca rodava.

    **E o fallback por texto casa por substring, o que nao basta sozinho.** Um
    constraint chamado `uq_outbound_message_kind_v2` contem o nome do nosso:
    a busca no texto responde "duplicata" para uma violacao sem relacao com a
    reserva, que e exatamente o desfecho descrito acima chegando pela porta
    que ninguem vigiava. Por isso o nome estruturado, quando existe, e
    comparado por IGUALDADE e decide sozinho.

    O fallback continua porque serve quem nao expoe o campo -- outro driver,
    ou um erro que chegue sem `__cause__`. Apagar deixaria esses sem cobertura.
    """
    original = exc.orig
    # `getattr` nos dois passos, e nao `original.__cause__`: `exc.orig` e
    # tipado `BaseException | None`, e um erro que chegue sem causa e o caso
    # que o fallback abaixo existe para atender.
    nome = getattr(getattr(original, "__cause__", None), "constraint_name", None)
    if nome is not None:
        return bool(nome == UNIQUE_DA_RESERVA)
    return UNIQUE_DA_RESERVA in str(original)


class OutboundPort(Protocol):
    """A porta de saida do turno -- e o contrato de excecoes que vem junto.

    A assinatura declara so `send`, mas a correcao de `executar_turno` depende
    inteiramente de **qual** excecao a implementacao levanta. Sem isto escrito,
    um adaptador novo (a TEC-124 traz o canal web) escolhe o tipo errado e
    muda o desfecho do turno sem tocar em nenhuma linha do dominio:

    - `EnvioRetentavel` -- rede, 5xx, 408, 429. A guarda libera as reservas do
      GRUPO de `kind` e propaga: a mensagem vira FAILED e o sweeper retenta. O
      lead recebe eventualmente. **Grupo** (TEC-273, `outbound/kinds.py`) e o
      conjunto de kinds que carregam UMA resposta regeneravel -- hoje so
      `KINDS_DA_RESPOSTA`, as duas partes de um texto longo. Liberar so o kind
      que falhou era o que a TEC-140 deixava: a retentativa roda o turno
      inteiro, com uma chamada NOVA ao modelo, e a reserva viva da parte ja
      entregue fazia essa parte da geracao NOVA ser suprimida -- o lead lia a
      primeira metade de um texto colada na segunda metade de outro. As fichas
      da apresentacao NAO formam grupo, e e decisao: a retentativa delas
      repete o lote persistido (TEC-275) em vez de chamar o modelo de novo,
      entao nao ha duas geracoes para misturar, e a reserva de cada ficha e o
      sinal que `_continuar_entrega` le para saber o que ja saiu -- poe-las num
      grupo apagaria esse sinal. Ver `GuardedOutbound._liberar`.

      **Emenda (TEC-124, 24/09/2026): o adaptador do canal web nao levanta
      nenhum dos tres tipos desta lista.** Ela pressupoe que a rede seja o
      caminho ate o lead, e no WhatsApp ela e. No web nao: assim que `send`
      devolve, o turno grava a fala em `messages`, e a reconexao a mostra.
      Falha de Redis, ausencia de ouvinte e kind sem forma viram log e o
      envio conta como entregue -- retentar cobraria uma chamada nova e paga
      ao modelo para reentregar o que a gravacao seguinte ja guarda. Ver
      `domain/outbound/web.py`, inclusive a janela que isso deixa aberta.
    - `EnvioForaDaJanela` -- o canal nao aceita mais mensagem livre nesta
      conversa. Turno `expirado`, PROCESSED, aviso no log. Expirar nao e
      falhar, e retentar nunca entregaria.
    - `EnvioRecusado` -- 4xx permanente. No caminho de texto unico: turno
      `sem_resposta`, PROCESSED, log `outbound.recusado_permanente` em `error`
      (e o alerta que observa isso). FAILED aqui faria o sweeper rodar o turno
      inteiro de novo, chamada paga ao modelo inclusa, por um payload que
      nunca sera aceito.
      **Na apresentacao de fichas (TEC-162, D10) o desfecho e outro:** a
      recusa de UMA ficha nao interrompe as outras. Ela loga
      `apresentacao.ficha_recusada` em `error`, com o `kind` da posicao, e o
      turno segue -- devolvendo `respondido` se qualquer outra ficha entrou. O
      `sem_resposta` so volta quando TODAS as fichas do turno foram
      recusadas -- que pode ser uma, duas ou tres. `MAX_IMOVEIS_POR_TURNO` e
      um teto, nao um piso: um turno com menos de tres candidatos, ou um em
      que `imoveis_por_ids` derrubou algum, tem menos de tres fichas para
      recusar em primeiro lugar. A divergencia e deliberada: a recusa
      provavel ali e a Meta rejeitando a URL da foto, e uma foto ruim nao
      pode apagar os outros imoveis bons do mesmo turno.
      Os dois nomes de evento importam por igual para quem configura alerta:
      **nao existe regra de alerta neste repositorio** -- ela vive no
      monitoramento externo, que casa por nome --, e este bullet e o unico
      lugar da arvore que diz quais nomes observar. Alertar so em
      `outbound.recusado_permanente` deixa uma apresentacao inteiramente
      recusada passar em silencio.
    - Qualquer outra excecao propaga crua: a reserva **fica**, a mensagem vira
      FAILED e a retentativa cai na supressao de reentrega. Levantar algo fora
      destes tres tipos e escolher esse desfecho sem querer.

    `asyncio.CancelledError` nao esta nessa lista porque nao e escolha de
    adaptador nenhum: e o `job_timeout` do worker ou o shutdown chegando de
    fora. A guarda a trata como retentavel (libera as reservas do grupo e
    propaga) -- ver TEC-227.

    `send` devolve `False`, sem levantar, em tres situacoes distintas, e
    quem le o retorno nao consegue distinguir uma da outra so pelo booleano:

    - Reentrega suprimida: a reserva em `outbound_dispatches` ja existia
      para este `(message_id, kind)` -- ver `GuardedOutbound.send` e
      `turno.reentrega_suprimida`.
    - Envio barrado pela guarda de opt-out: o lead deste `message_id` pediu
      para parar de receber mensagem, e `kind` nao e
      `KIND_DA_CONFIRMACAO_DE_OPTOUT` -- ver `GuardedOutbound.send` e
      `esta_em_optout_por_mensagem`.
    - Envio barrado pela guarda de atendimento humano: um corretor assumiu
      esta conversa e ainda nao a devolveu (TEC-179, RN-16.4) -- ver
      `GuardedOutbound.send` e `esta_silenciada_por_mensagem`. Mesma excecao
      por `kind` que a guarda de opt-out (emenda TEC-179, Task 7 -- a D5
      original barrava todo kind sem escotilha; ver `GuardedOutbound` para o
      raciocinio).

    `OutboundPort` e um Protocol estrutural: qualquer classe com um metodo
    `send` de assinatura compativel satisfaz o tipo, herdando de
    `GuardedOutbound` ou nao. As guardas de opt-out e de atendimento humano,
    porem, so existem dentro do corpo de `GuardedOutbound.send` -- nao ha
    nada no `Protocol` em si, nem no `mypy`, que as force. Um adaptador novo
    escrito direto contra este Protocol, sem herdar de `GuardedOutbound`,
    tipa igual e passa em qualquer checagem estatica, mas nao tem guarda
    nenhuma: ele manda mensagem para quem pediu para parar, e fala por cima
    do corretor que assumiu a conversa. Isso nao e um bug de performance ou
    um turno errado -- e uma violacao de LGPD no primeiro caso, e no segundo
    o proprio motivo de existir da TEC-179. Quem for por esse caminho
    precisa reimplementar as duas checagens por conta propria; a rota
    segura e herdar de `GuardedOutbound`.
    """

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool: ...


class EnvioRetentavel(Exception):
    """Falha de envio que uma nova tentativa pode resolver -- rede, 5xx."""


class EnvioRecusado(Exception):
    """Falha de envio permanente -- 4xx. Retentar nao muda nada."""


class EnvioForaDaJanela(EnvioRecusado):
    """O canal nao aceita mais mensagem livre nesta conversa.

    Herda de EnvioRecusado porque retentar nao ajuda. Mas e distinguivel de um
    4xx comum porque nao e erro nosso: o turno termina PROCESSED com aviso,
    nao com erro de payload.

    Mora aqui, e nao no adaptador do WhatsApp que a levanta hoje, porque
    `executar_turno` a captura e o turno e agnostico de canal em todo o resto
    -- ele recebe um `OutboundPort`. O nome ficou como estava, sem um
    "EnvioExpirado" neutro com subclasse do WhatsApp por cima: hoje ha uma
    unica encarnacao do conceito (a janela de 24h da Meta, citada aqui como
    exemplo e definida no adaptador, que e onde ela e regra), e uma hierarquia
    de dois niveis com um so habitante seria estrutura para um caso
    hipotetico. O canal web da TEC-124 nao tem janela nenhuma -- ele
    simplesmente nunca levanta esta excecao.

    **A regra da janela nao se escreve aqui** (TEC-230): que ela dure 24h, e
    que o gatilho seja um codigo especifico da Meta, e verdade de um canal so.
    Este modulo so sabe que existe uma janela e que ela fechou.
    """


class GuardedOutbound:
    """Barra quem pediu opt-out, barra quem esta em atendimento humano, reserva, e so entao entrega.

    As duas guardas (opt-out, TEC-182; atendimento humano, TEC-179) rodam
    antes da reserva, e sao a razao de o docstring de `OutboundPort` apontar
    esta classe como a rota segura: herdar daqui e o que garante que um
    caminho de envio novo nao fale com quem pediu silencio nem por cima de
    quem assumiu a conversa. As duas tem a MESMA excecao unica --
    `KIND_DA_CONFIRMACAO_DE_OPTOUT` atravessa as duas, ver `send`.

    A guarda de atendimento humano nao nasceu com essa excecao: a D5 original
    do desenho decidia "barra TODO kind, sem escotilha", e o argumento era
    sobre o caminho HUMANO de envio (a rota `POST /conversas/{id}/mensagens`
    do SRS, que nao existe ainda). Emenda TEC-179 (Task 7): esse argumento
    nunca cobriu a confirmacao de opt-out, que nao e mensagem de conversa --
    e reconhecimento legal de um pedido que o LEAD fez, e o unico envio que
    a D1 da TEC-182 autoriza depois do registro. Sem esta excecao, a
    correcao que fez a guarda de atendimento humano nao mais engolir o
    registro do opt-out (ver `executar_turno`) deixava a confirmacao ser
    barrada pela MESMA guarda que acabou de deixar o registro passar -- o
    lead pedia para sair, o pedido era gravado, e a unica prova disso que ele
    recebe nunca saia.

    A linha em outbound_dispatches e commitada antes do efeito externo. Queda
    entre a reserva e a entrega so perde aquele envio quando a falha e
    permanente (EnvioRecusado); queda depois nunca duplica. Falha retentavel
    (EnvioRetentavel) e cancelamento (`asyncio.CancelledError`, TEC-227)
    liberam as reservas do GRUPO do kind -- nao so a dele (TEC-273, ver
    `_liberar`) -- para a proxima tentativa poder entregar. O criterio de
    aceite exige "nenhuma resposta duplicada" -- a troca e essa, e continua
    valendo no caminho de sucesso e na falha permanente.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def send(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> bool:
        # A guarda de opt-out mora AQUI, e nao em `executar_turno`, de
        # proposito. No turno ela protegeria o caminho de hoje e nada mais, e a
        # TEC-183 vai criar um segundo caminho de envio. Quem HERDA desta
        # classe ganha a guarda de graca, sem precisar lembrar dela -- e e por
        # isso que ela mora aqui. Mas herdar e o mecanismo, nao uma garantia
        # da linguagem: quem implementar `OutboundPort` direto, sem herdar,
        # nao tem a guarda -- ver o aviso no docstring do Protocol acima.
        #
        # Antes da reserva: barrar depois deixaria linha orfa em
        # `outbound_dispatches`, e o sweeper leria isso como tentativa feita.
        if kind != KIND_DA_CONFIRMACAO_DE_OPTOUT:
            async with self._session_factory() as session:
                if await esta_em_optout_por_mensagem(session, message_id):
                    # `warning` e nao `info`: um envio barrado aqui significa
                    # que algum caminho tentou falar com quem pediu silencio.
                    # Nao e erro nosso -- a guarda funcionou --, mas e o
                    # sintoma que denuncia um caminho sem a checagem barata do
                    # turno.
                    log.warning(
                        "outbound.optout_bloqueou",
                        message_id=str(message_id),
                        kind=kind,
                    )
                    return False

        # A guarda de atendimento humano (TEC-179, RN-16.4). Mora aqui pela
        # mesma razao que a de opt-out logo acima, e o docstring do
        # `OutboundPort` ja escreve: quem herda ganha a guarda de graca. No
        # turno ela protegeria so o caminho de hoje.
        #
        # **`kind != KIND_DA_CONFIRMACAO_DE_OPTOUT` -- a MESMA excecao unica
        # que a guarda de opt-out tem, e nao a copia distraida do padrao dela
        # que parece a primeira vista.** A D5 original do desenho decidia
        # "barra TODO kind, sem escotilha", e o argumento era sobre o caminho
        # HUMANO de envio -- a rota `POST /conversas/{id}/mensagens` do SRS,
        # que nao existe ainda; nao existe caminho humano para deixar passar,
        # entao uma lista de excecoes seria para um chamador hipotetico.
        # Emenda TEC-179 (Task 7): esse argumento nunca cobriu a confirmacao
        # de opt-out. Ela nao e mensagem de conversa, e reconhecimento legal
        # de um pedido que o proprio lead fez -- o unico envio que a D1 da
        # TEC-182 autoriza depois do registro. Sem esta excecao, a correcao
        # que fez `executar_turno` parar de deixar esta guarda engolir o
        # registro do opt-out (ver o comentario la, na saida barata) ficava
        # incompleta: o registro passava a acontecer, mas a confirmacao dele
        # -- gravada com o kind proprio -- seria barrada por ESTA MESMA
        # guarda, e o lead que pediu para sair nao receberia reconhecimento
        # nenhum. A L3 do desenho continua valendo: quando a rota de envio
        # manual do corretor chegar, ela ainda encontra o proprio envio
        # barrado aqui -- esta excecao e so para o reconhecimento do
        # opt-out, nao abre um segundo caminho para envio humano.
        #
        # Antes da reserva pelo mesmo motivo do bloco acima: barrar depois
        # deixaria linha orfa em `outbound_dispatches`.
        if kind != KIND_DA_CONFIRMACAO_DE_OPTOUT:
            async with self._session_factory() as session:
                if await esta_silenciada_por_mensagem(session, message_id):
                    # `warning` e nao `info`, pelo mesmo criterio do opt-out:
                    # um envio barrado aqui significa que algum caminho tentou
                    # falar por cima do corretor que assumiu.
                    log.warning(
                        "outbound.atendimento_humano_bloqueou",
                        message_id=str(message_id),
                        kind=kind,
                    )
                    return False

        async with self._session_factory() as session:
            session.add(OutboundDispatch(id=uuid.uuid4(), message_id=message_id, kind=kind))
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if not _e_reserva_duplicada(exc):
                    raise
                # `info` de proposito, e nao `error` como o desfecho do turno:
                # aqui a supressao ainda pode ser o caso benigno (um ACK
                # reentregue). Quem sabe que o que se perdeu foi a resposta ao
                # lead e `executar_turno`, e e la que o nivel sobe -- ver
                # `turno.reentrega_suprimida`.
                log.info(
                    "outbound.duplicate_suppressed",
                    message_id=str(message_id),
                    kind=kind,
                )
                return False

        try:
            await self._deliver(message_id, kind, payload)
        except (EnvioRetentavel, asyncio.CancelledError):
            # A reserva foi desenhada na TEC-122 para um ACK, e ali perder o
            # envio nao custava nada. Agora o que se perde e a resposta ao
            # lead: a reserva commitada faz o sweeper reenfileirar, o worker
            # reivindicar e a guarda responder "ja entreguei isso" -- e o lead
            # nunca recebe nada sobre aquele turno. Liberar inverte a troca
            # para uma duplicata possivel, que e visivel e recuperavel.
            #
            # `CancelledError` entra na mesma clausula, e nao numa propria, de
            # proposito: o que fazer e identico, e duas copias do bloco
            # divergiriam. O gatilho e que e diferente -- ele nao e excecao
            # tipada nossa, e sim o `job_timeout` do worker ou o shutdown, e
            # cai em qualquer ponto do `_deliver`, inclusive depois de o POST
            # ter chegado a Meta. Nesse caso a duplicata acontece de verdade;
            # a TEC-227 escolheu esse lado pelo mesmo criterio da TEC-134.
            try:
                await self._liberar(message_id, kind)
            except Exception as exc:
                # Se o proprio delete da liberacao falhar (deadlock, conexao
                # caida), quem chama send() ainda precisa ver a excecao
                # original -- o EnvioRetentavel ou o cancelamento -- e nao um
                # erro de infra do release: senao um retentavel vira permanente
                # por engano, ou o cancelamento some, e a reserva fica presa do
                # mesmo jeito que este bloco existe para evitar. Um
                # cancelamento *da propria liberacao* nao cai aqui, porque
                # `CancelledError` nao e Exception -- ele propaga, que e o
                # desfecho certo. O erro de liberacao vira
                # seu proprio evento de log, porque e um problema operacional
                # diferente de perder o envio.
                log.error(
                    "outbound.liberacao_falhou",
                    message_id=str(message_id),
                    kind=kind,
                    # Sem o tipo, este evento nao tem nada de que se depurar --
                    # um TypeError daqui de dentro fica indistinguivel de um
                    # deadlock do banco. So o nome da classe, como no resto do
                    # projeto: nao vaza conteudo.
                    reason=type(exc).__name__,
                )
            raise

        log.info("outbound.delivered", message_id=str(message_id), kind=kind)
        return True

    async def _liberar(self, message_id: uuid.UUID, kind: str) -> None:
        """Apaga a reserva de `kind` e as dos kinds do mesmo grupo. TEC-273.

        **Por que o grupo, e nao so o kind que falhou.** Uma resposta longa sai
        em duas mensagens, com kind proprio para cada (TEC-140). Liberando so
        a que falhou, a retentativa do sweeper -- que roda o turno inteiro, com
        uma chamada NOVA ao modelo -- encontra a reserva da parte 1 viva, tem
        essa parte suprimida, e entrega a parte 2 do texto NOVO. O lead le a
        primeira metade de um texto colada na segunda metade de outro.

        Este repo ja decidiu que duplicata e melhor que perda ("a duplicata e
        visivel e recuperavel e o silencio nao", TEC-134/TEC-227). O caso acima
        nao e nenhum dos dois: e corrupcao silenciosa de conteudo, e o lead nao
        tem como saber que leu duas fontes. Liberando o grupo, a retentativa
        reentrega a parte 1 da geracao nova -- uma duplicata visivel, que e o
        lado que aquele precedente ja escolheu.

        **Grupo, e nao `message_id`.** As fichas compartilham a mensagem com a
        resposta e NAO formam grupo (ver `kinds.py`): a retentativa delas
        repete o lote persistido em vez de regenerar, e a reserva de cada uma
        e o sinal que `_continuar_entrega` (TEC-275) le para saber o que ja
        saiu. Apagar por `message_id` esvaziaria esse sinal e faria a
        continuacao nunca ser tomada.
        """
        irmaos = grupo_de(kind)
        async with self._session_factory() as session:
            await session.execute(
                delete(OutboundDispatch).where(
                    OutboundDispatch.message_id == message_id,
                    OutboundDispatch.kind.in_(irmaos),
                )
            )
            await session.commit()
        log.warning(
            "outbound.reserva_liberada",
            message_id=str(message_id),
            kind=kind,
            kinds_liberados=list(irmaos),
        )

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError
