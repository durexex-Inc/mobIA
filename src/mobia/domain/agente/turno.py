import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import MODELO_SEM_CHAMADA
from mobia.domain.agente.apresentacao import Ficha, legenda_de
from mobia.domain.agente.citacao import divergencias_de
from mobia.domain.agente.classificador import ClassificadorPort, LacoDeBuscaExcedido
from mobia.domain.agente.desambiguacao import deve_desambiguar
from mobia.domain.agente.ferramenta_de_busca import (
    _PortaComScore,
    fichas_do_catalogo,
    porta_de_busca,
)
from mobia.domain.agente.formato import quebrar_em_mensagens
from mobia.domain.agente.identificacao import (
    SEPARADOR_DA_IDENTIFICACAO,
    TEXTO_DA_IDENTIFICACAO,
    e_conversa_nova,
)
from mobia.domain.agente.recomendacao import bairros_a_excluir, resolver_ordinais
from mobia.domain.agente.repositorio import (
    LinhaDaApresentacao,
    apagar_apresentacao_da_mensagem,
    apagar_recomendacao_nao_entregue,
    conciliar_apresentacao,
    gravar_intencao,
    gravar_reacoes,
    gravar_recomendacoes,
    ler_apresentacao_da_mensagem,
    ler_descartes_por_distancia,
    ler_intencao,
    ler_pendentes,
    marcar_desambiguacao,
)
from mobia.domain.agente.schemas import Intencao, PerguntaDeDesambiguacao, RespostaDoAgente
from mobia.domain.atendimento.repositorio import esta_silenciada
from mobia.domain.context.gatilhos import gatilhos_de
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import ContextoIrreducivel, montar_contexto
from mobia.domain.context.qualificacao import esta_qualificado
from mobia.domain.context.repositorio import gravar_estado, marcar_perguntados, registrar_recalculo
from mobia.domain.context.resumo import ContadorPort, ResumidorPort
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.handoff.agendador import AgendadorDeResumoPort
from mobia.domain.handoff.repositorio import HandoffRegistrado, registrar_handoff
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho
from mobia.domain.messages.bloqueio import marcar_bloqueada, registrar_bloqueio_de_saida
from mobia.domain.messages.models import Message
from mobia.domain.messages.recorder import MessageRecorder
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
    Direcao,
    ModeracaoIndisponivel,
    ModeradorPort,
)

# Consumida no corpo deste modulo (a checagem de opt-out e a entrega da
# confirmacao), entao o import normal ja basta -- sem o "as X" que so existia
# para calar o ruff quando o nome era so reexportado, nunca usado aqui. Quem
# importava `from mobia.domain.agente.turno import KIND_DA_CONFIRMACAO_DE_OPTOUT`
# continua funcionando: o nome fica no namespace do modulo do mesmo jeito.
from mobia.domain.optout.deteccao import (
    KIND_DA_CONFIRMACAO_DE_OPTOUT,
    TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
    pediu_optout,
)
from mobia.domain.optout.repositorio import esta_em_optout, registrar_optout
from mobia.domain.outbound.port import (
    EnvioForaDaJanela,
    EnvioRecusado,
    EnvioRetentavel,
    OutboundPort,
)
from mobia.domain.outbound.repositorio import kinds_reservados
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.embeddings import embedar

log = structlog.get_logger(__name__)

KIND_DA_RESPOSTA = "reply"

# Dois kinds e nao um repetido, pelo mesmo motivo de `KINDS_DAS_FICHAS`: a
# `UNIQUE (message_id, kind)` de `outbound_dispatches` e o que torna o
# reprocessamento seguro, e duas mensagens com o mesmo kind fariam a segunda
# ser suprimida como reentrega -- o lead receberia metade da resposta em
# silencio.
#
# O primeiro continua sendo `KIND_DA_RESPOSTA` e nao um nome novo: ha linhas
# gravadas com "reply" e testes que afirmam `_kinds_reservados() == ["reply"]`.
#
# A reserva por kind faz a parte ja entregue ser suprimida de novo numa
# retentativa -- mas isso NAO quer dizer "a retentativa completa a mesma
# resposta". `sweep_stalled` reenfileira a MENSAGEM, e o turno roda inteiro de
# novo, com uma chamada NOVA ao classificador: texto diferente do da tentativa
# anterior. A parte com reserva (`reply`, se foi ela que ja saiu) devolve False
# de novo e e suprimida; a parte sem reserva sai, mas com o texto da chamada
# NOVA -- nao com a continuacao do texto antigo. O lead pode acabar com a
# primeira metade de uma resposta seguida da segunda metade de outra. Fix
# review final (TEC-140): este comentario prometia "reentrega SO ela", que e
# falso -- a parte que falta reentrega, mas o texto ao redor dela mudou. Ver o
# `except EnvioRetentavel` do laco de entrega em `executar_turno`, que so torna
# isso visivel em log, sem evitar.
KINDS_DA_RESPOSTA = (KIND_DA_RESPOSTA, "reply_2")

# TEC-162. Kinds fixos POR POSICAO, e nao derivados do id do imovel: o
# UNIQUE (message_id, kind) de `outbound_dispatches` precisa de um valor que
# a retentativa reproduza. Um kind com o id dentro deixaria de colidir assim
# que a retentativa escolhesse outro imovel, e a idempotencia sumiria
# justamente no caso em que ela importa -- ver a D9 e a L1 do desenho.
KINDS_DAS_FICHAS = ("ficha_1", "ficha_2", "ficha_3")

# RN-10.2: maximo de 3 por turno, mesmo quando a busca devolveu 10.
MAX_IMOVEIS_POR_TURNO = len(KINDS_DAS_FICHAS)

# TEC-265, D4. O lead nunca fica em silencio porque o teto do laco funcionou.
TEXTO_DA_BUSCA_INCONCLUSIVA = (
    "Deixa eu confirmar algumas coisas com um corretor para nao te passar "
    "informacao errada. Ja te retorno com as opcoes."
)

# Regra 4 da card e cenario 2 do Gherkin. TEC-160, D14.
#
# **Constante nova, e nao reuso de TEXTO_DA_BUSCA_INCONCLUSIVA.** Aquele
# promete "ja te retorno com as opcoes", e aqui nao ha opcao nenhuma para
# retornar -- seria o sistema prometendo o que sabe que nao tem. O laco
# excedido e a citacao bloqueada podem prometer porque nos dois casos os
# imoveis existem e o problema e nosso.
#
# A card manda oferecer "a lista de espera ou o corretor", e poe a lista de
# espera fora de escopo (E5). Este texto entrega a metade disponivel; quando o
# E5 existir, e aqui que se volta.
TEXTO_SEM_RESULTADO_APOS_AMPLIAR = (
    "Procurei tambem um pouco alem do que voce pediu e mesmo assim nao achei "
    "nada que valha a pena te mostrar agora. Quer que um corretor olhe isso "
    "com voce?"
)

# RN-09.3 / CA-09.3, e a regra "avisado ... e EM QUE" da card. TEC-160, D11.
#
# Tres variantes e nao uma constante: quando so o preco foi relaxado (o lead
# nao deu regiao), dizer "inclui bairros vizinhos" e informacao falsa sobre o
# que o sistema fez -- num aviso cujo proposito inteiro e ser explicito.
#
# Nenhum numero, de proposito: o teto ampliado e conta nossa, e nao fato do
# banco. Os nomes dos bairros tambem ficam de fora, e essa e a escolha mais
# discutivel -- nome de bairro E fato do catalogo. Ficam fora porque a lista e
# variavel (a Trindade amplia para tres, o Itacorubi para quatro) e uma
# mensagem que cresce com o grau do no e uma mensagem cujo pior caso ninguem
# mediu. O lead ve o bairro na ficha, que e onde ele importa.
_ABERTURA_DA_AMPLIACAO = "Nao achei nada exatamente no que voce pediu, entao "

TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO = (
    f"{_ABERTURA_DA_AMPLIACAO}ampliei um pouco a busca: valor um pouco acima e "
    "bairros vizinhos. Veja se algum destes serve."
)
TEXTO_DO_CRITERIO_AMPLIADO_PRECO = (
    f"{_ABERTURA_DA_AMPLIACAO}ampliei um pouco o valor. Veja se algum destes serve."
)
TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO = (
    f"{_ABERTURA_DA_AMPLIACAO}inclui bairros vizinhos. Veja se algum destes serve."
)

# Kind proprio e OBRIGATORIO, nao preferencia: `outbound_dispatches` tem
# UNIQUE (message_id, kind) -- a constraint `uq_outbound_message_kind`, criada
# na `0002` e nomeada em `outbound/port.py` --, e no caminho de apresentacao a
# identificacao ja envia com KIND_DA_RESPOSTA. Duas mensagens com o mesmo kind
# no mesmo message_id colidiriam na reserva, e a segunda seria descartada como
# se fosse reprocessamento. E o mesmo motivo que deu `reply_2` a segunda
# mensagem de texto da TEC-140.
#
# String fixa, sem id dentro, pelo argumento de idempotencia que o comentario
# de KINDS_DAS_FICHAS registra: kind que muda entre retentativas perde a dedup
# justamente quando ela importa. A coluna e String(32); isto tem 17.
KIND_DO_CRITERIO_AMPLIADO = "criterio_ampliado"

# RN-03.4: estas duas intencoes nao sao trabalho de SDR, e o comentario de
# `qualificacao.py` ja dizia que elas vao "direto para handoff" -- um destino
# que so passou a existir na TEC-174. O lead segue recebendo a resposta deste
# turno: silenciar e a RN-16.4, que e a TEC-179.
_GATILHO_DA_INTENCAO = {
    Intencao.VENDER_IMOVEL: Gatilho.VENDA_IMOVEL,
    Intencao.SUPORTE_CONTRATO: Gatilho.SUPORTE_CONTRATO,
}


def aviso_de_ampliacao(relaxou_preco: bool, relaxou_bairro: bool) -> str:
    """A variante que corresponde ao que de fato foi relaxado. D11.

    Levanta `ValueError` quando os dois sao False. Esse par e inalcancavel
    porque NINGUEM O CONSTROI, e nao porque a natureza o proiba: o catalogo
    nao congela entre dois round-trips, e uma importacao concorrente ou um
    `RESERVADO -> DISPONIVEL` faz uma consulta identica a anterior devolver
    linha. O que fecha o caso e o unico produtor: `buscar_com_relaxamento` so
    faz o segundo passe depois de confirmar que preco ou bairro de fato
    mudou, entao `APLICADO` com as duas dimensoes False nao chega a existir
    para `executar_turno` propagar.

    Cair no caso do bairro por default aqui repetiria exatamente o erro que a
    doc do modulo (acima) existe para evitar: dizer "inclui bairros vizinhos"
    para quem nao teve bairro nenhum ampliado, so porque nenhum booleano
    chegou True. Barulhento e melhor que uma mentira silenciosa. E a guarda do
    chamador (`relaxou_preco or relaxou_bairro`) nao e cinto-e-suspensorio: a
    invariante que torna o par impossivel mora em OUTRO modulo, e e ela que
    mantem o turno vivo -- perdendo so o aviso -- no dia em que aquele modulo
    mudar de ideia.
    """
    if relaxou_preco and relaxou_bairro:
        return TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO
    if relaxou_preco:
        return TEXTO_DO_CRITERIO_AMPLIADO_PRECO
    if relaxou_bairro:
        return TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO
    raise ValueError("aviso_de_ampliacao chamado sem preco nem bairro relaxados")


# TEC-163, Task 10. RN-10.4: o lead sabe que um bairro que ele descartou duas
# vezes parou de entrar nas buscas seguintes desta conversa -- a mesma
# exigencia de "nunca silencioso" que fez a TEC-160 escrever
# `KIND_DO_CRITERIO_AMPLIADO`.
#
# Kind proprio e OBRIGATORIO, pelo mesmo motivo daquele: `outbound_dispatches`
# tem UNIQUE (message_id, kind) -- a constraint `uq_outbound_message_kind`,
# criada na `0002` --, e no caminho de apresentacao a identificacao ja envia
# com KIND_DA_RESPOSTA. Duas mensagens com o mesmo kind no mesmo message_id
# colidiriam na reserva, e este aviso seria descartado como reprocessamento.
#
# String fixa, sem id dentro, pelo argumento de idempotencia que o comentario
# de `KINDS_DAS_FICHAS` registra: kind que muda entre retentativas perde a
# dedup justamente quando ela importa. A coluna e String(32); isto tem 15.
KIND_DO_FILTRO_AJUSTADO = "filtro_ajustado"

TEXTO_DO_FILTRO_AJUSTADO = "Tirei {bairros} da busca, que voce ja descartou."


def aviso_de_ajuste(bairros: Sequence[str]) -> str:
    """O aviso da RN-10.4, com os NOMES dos bairros que saem da busca. D15.

    **Diverge de proposito de `aviso_de_ampliacao` (D11 da TEC-160), que NAO
    nomeia bairro nenhum.** La os bairros incluidos sao escolha NOSSA (a
    tabela de adjacencia), e calar o nome evita uma mensagem cujo tamanho
    cresce com o grau do no, sem teto medido. Aqui os bairros sao os que o
    LEAD rejeitou -- duas ou tres vezes, nunca a arvore de adjacencia inteira
    --, e nomea-los e a propria confirmacao de que ele foi ouvido: "Tirei o
    Campeche da busca, que voce descartou" faz um trabalho que "ajustei o
    filtro" nao faz.

    `bairros` chega na forma dobrada (`recomendacao.bairros_a_excluir`,
    minuscula e sem acento -- ver `texto.dobrar`); `.title()` basta para virar
    nome legivel, e o dobrado ja garante ASCII -- nao ha acento para perder
    na volta.

    Levanta `ValueError` com a lista vazia: o chamador (`executar_turno`) so
    invoca isto quando o conjunto excluido mudou desde antes deste turno, e o
    par vazio nao chega a existir por construcao -- mesmo molde de guarda que
    `aviso_de_ampliacao` documenta para o par impossivel dela.
    """
    if not bairros:
        raise ValueError("aviso_de_ajuste chamado sem bairro nenhum")
    nomes = [bairro.title() for bairro in bairros]
    lista = nomes[0] if len(nomes) == 1 else f"{', '.join(nomes[:-1])} e {nomes[-1]}"
    return TEXTO_DO_FILTRO_AJUSTADO.format(bairros=lista)


SUBAGENTE_CLASSIFICADOR = "classificador"
SUBAGENTE_DESAMBIGUADOR = "desambiguador"
SUBAGENTE_MODERACAO = "moderacao"
SUBAGENTE_OPTOUT = "optout"

# Conjunto fechado de proposito (Literal, nao str): um typo num dos dois
# lugares que compara contra esta string (process_message, os testes) vira
# erro de tipo no mypy em vez de um `if resultado == "processed"` que nunca
# bate e falha em silencio.
ResultadoDoTurno = Literal[
    "respondido",
    "sem_resposta",
    "expirado",
    "reentrega_suprimida",
    # A TEC-182 acrescentou os tres abaixo. Separados de proposito:
    # "opt_out" e o turno que ATENDEU o pedido (gravou e confirmou);
    # "silenciado" e o turno que nao fez nada porque o pedido ja valia;
    # "bloqueado_por_optout" e o turno que tentou responder normalmente e a
    # guarda da porta de saida (Task 4) barrou o envio porque outro turno da
    # MESMA conversa registrou o opt-out entre a checagem do topo deste turno
    # e este envio -- ver `_bloqueado_por_optout_concorrente`. Somar os tres
    # num valor so esconderia quantos opt-outs de fato acontecem, e faria o
    # terceiro caso soar como perda de dado quando a guarda so fez o trabalho
    # dela.
    "opt_out",
    "silenciado",
    "bloqueado_por_optout",
    # A TEC-179 acrescentou os dois abaixo, separados pelo mesmo criterio que
    # o comentario acima aplica aos tres do opt-out:
    # "atendimento_humano" e o turno que nao fez nada porque um corretor ja
    # tinha assumido a conversa; "bloqueado_por_atendimento_humano" e o turno
    # que tentou responder e a guarda da porta barrou, porque alguem assumiu
    # ENTRE a checagem do topo deste turno e este envio.
    #
    # Nao reuse "silenciado": aquele valor ja significa opt-out, e soma-los
    # tornaria impossivel saber se o agente calou por pedido do lead ou por
    # um corretor ter assumido -- duas historias diferentes, com donos
    # diferentes.
    "atendimento_humano",
    "bloqueado_por_atendimento_humano",
]


def _recusados_de(estado: LeadQualification | None) -> frozenset[str]:
    """A recusa da linha, na forma que `esta_qualificado` recebe.

    `or ()` porque `NULL` e `{}` na coluna significam coisas diferentes e a
    leitura trata as duas iguais -- ver o comentario da coluna. `frozenset` e
    nao `set` porque e o que a assinatura da TEC-147 pede.
    """
    if estado is None:
        return frozenset()
    return frozenset(estado.campos_recusados or ())


def _faixa_declarada(estado: LeadQualification | None) -> tuple[int | None, int | None]:
    """O orcamento que o lead ja declarou, na forma que `divergencias_de` recebe.

    Existe para a guarda da TEC-161 nao bloquear o modelo ecoando o proprio
    lead: "entendi, ate R$ 600 mil" nao e imovel inventado. Linha ausente vira
    faixa vazia, que `_na_faixa` trata como ausencia de declaracao -- e nao
    como faixa aberta.
    """
    if estado is None:
        return (None, None)
    return (estado.faixa_preco_min_centavos, estado.faixa_preco_max_centavos)


async def _agendar_resumo(agendador: AgendadorDeResumoPort, registro: HandoffRegistrado) -> None:
    """Pede a geracao do resumo, mas so quando o handoff e NOVO.

    Gatilho adicional nao reagenda: a intencao dispara em TODO turno com a
    classificacao certa -- o `CASE` do `ON CONFLICT` em `repositorio.py` ja
    documenta isso --, entao reagendar aqui seria uma chamada de LLM por
    turno para um resumo que ninguem pediu. Ver a D3 do desenho.

    **Nao propaga excecao.** O handoff ja esta commitado neste ponto; uma
    falha do Redis aqui derrubaria o turno DEPOIS de o lead ter sido
    atendido, e o que se perde e o resumo e, com ele, a notificacao e o
    prazo -- `gerar_resumo` e quem enfileira `notificar`. A rota de
    regeneracao (`POST /handoffs/{id}/resumo`) recupera so o resumo, em
    processo, sem enfileirar nada; quem recupera o handoff inteiro e
    `recuperar_sem_prazo` (`domain/handoff/recuperacao.py`, TEC-279).
    """
    if not registro.criado:
        return
    try:
        await agendador.agendar(registro.id)
    except Exception:
        log.warning("resumo_handoff.nao_agendado", handoff_id=str(registro.id), exc_info=True)


async def _continuar_entrega(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    lote: Sequence[LinhaDaApresentacao],
    ja_reservados: frozenset[str],
) -> ResultadoDoTurno:
    """Termina a entrega que a passada anterior comecou. TEC-275, D1.

    **Nao rebusca, nao chama o classificador, nao chama `reagir`.** E isso que
    fecha os DOIS caminhos pelos quais a retentativa apagava a lista de
    pendentes: nenhum dos dois chega a rodar. Fechar cada um com uma guarda
    propria seria fragil -- a terceira rota que aparecesse ficaria de fora.

    **Concilia com o carimbo ORIGINAL do lote, e nao com um `now()` novo.**
    E a outra metade do conserto: com o carimbo do lote, as linhas dele
    deixam de ser `apresentado_em < agora` e a conciliacao nao tem o que
    fechar. Com um carimbo novo, fechava as tres -- que era o defeito.

    **O ramo do imovel que sumiu do catalogo (D7) e defensivo: hoje ele nao
    dispara**, porque a FK de `recomendacoes.imovel_id` impede que um imovel
    deste lote seja apagado. O comentario no corpo diz por que ele fica assim
    mesmo, e por que so os ainda NAO entregues podem entrar nele.
    """
    # **Um `message_id` quase sempre tem UM carimbo, mas pode ter dois.**
    # `gravar_recomendacoes` grava o lote inteiro com um `agora` unico, so que
    # `apagar_apresentacao_da_mensagem` (o ramo do meio) carrega
    # `reacao_lead IS NULL`: uma linha que um `gravar_reacoes` intercalado ja
    # fechou SOBREVIVE ao descarte, o turno inteiro roda de novo e grava linhas
    # novas com o MESMO `message_id` e carimbo NOVO. `lote` vem ordenado por
    # `apresentado_em` ASC, entao `lote[0]` pegaria o carimbo MAIS ANTIGO --
    # o da linha sobrevivente, que nao e o lote que esta sendo continuado --, e
    # com ele a conciliacao nao casa nada: o recorte dela e
    # `apresentado_em == agora`, entao nem a linha da ficha que nao saiu e
    # apagada nem as pendentes anteriores sao fechadas.
    #
    # O carimbo e o MAIS RECENTE, e o lote se restringe as linhas que o
    # carregam: a sobrevivente pertence a uma apresentacao anterior desta mesma
    # mensagem, e continua-la significaria reentregar o que o lead ja reagiu.
    apresentado_em = max(linha.apresentado_em for linha in lote)
    lote = [linha for linha in lote if linha.apresentado_em == apresentado_em]
    ids = [linha.imovel_id for linha in lote]
    precos = {linha.imovel_id: linha.preco_centavos for linha in lote}
    kind_de = {linha.imovel_id: linha.kind for linha in lote}

    fichas = await fichas_do_catalogo(session_factory, ids=ids, precos=precos)
    encontrados = {ficha.id for ficha in fichas}

    # **Este ramo e defensivo e hoje NAO dispara** -- dizer o contrario seria a
    # justificativa falsa que este repo trata como defeito. `recomendacoes.
    # imovel_id` tem FK para `imoveis` sem `ON DELETE`, entao um imovel
    # referenciado por linha deste lote nao pode ser apagado: todo id daqui tem
    # linha em `imoveis` por construcao, e `fichas_do_catalogo` nao derruba
    # nenhum. A D7 foi escrita para o caminho de `_apresentar`, onde os ids vem
    # da busca vetorial e NAO de linhas com FK -- la o imovel some entre a
    # busca e a entrega, e o ramo equivalente dispara de verdade.
    #
    # Fica porque a FK e que o torna inalcancavel, e ela pode mudar: no dia em
    # que ganhar `ON DELETE CASCADE`, sem este ramo o lead receberia uma ficha
    # a menos com a linha dela viva como pendente -- ordinal deslocado, que e
    # exatamente o defeito que esta card existe para fechar.
    #
    # **So os ainda NAO entregues entram.** Um imovel cuja ficha ja saiu na
    # passada anterior o lead VIU; manda-lo para `nao_entregues` faria a
    # conciliacao apagar a linha dele e deslocar todo ordinal seguinte -- o
    # mesmo defeito, entrando pela porta do conserto.
    sumiram = [
        linha.imovel_id
        for linha in lote
        if linha.imovel_id not in encontrados and linha.kind not in ja_reservados
    ]
    if sumiram:
        # Mesmo criterio de nivel do `fichas_sumiram_do_catalogo` de
        # `_apresentar`: quem opera precisa saber QUAL imovel sumiu.
        log.warning(
            "continuacao.fichas_sumiram_do_catalogo",
            channel=message.channel,
            message_id=str(message.id),
            imovel_ids_faltantes=[str(i) for i in sumiram],
        )

    try:
        entrega = await _entregar_fichas(
            session_factory,
            message=message,
            outbound=outbound,
            fichas=fichas,
            kinds=[kind_de[ficha.id] for ficha in fichas],
            apresentado_em=apresentado_em,
            prosa=None,
            pular=ja_reservados,
        )
    except EnvioForaDaJanela as exc:
        # Espelha o handler do turno normal, e a clausula precisa existir AQUI
        # porque o desvio que chama esta funcao esta fora daquele `try`: sem
        # ela a excecao sai crua de `executar_turno`, a linha vira FAILED, a
        # varredura queima as tentativas restantes reentrando numa continuacao
        # que nunca vai suceder, e o fim e handoff de erro para um corretor.
        #
        # E a janela fechar entre as passadas nao e hipotese remota: a
        # retentativa e atrasada POR CONSTRUCAO -- ela depende da varredura.
        # `_entregar_fichas` repropaga de proposito (ver o comentario dela) e
        # quem converte em desfecho e o chamador; aqui o chamador e este.
        log.warning(
            "outbound.fora_da_janela",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "expirado"

    await conciliar_apresentacao(
        session_factory,
        channel=message.channel,
        conversation_key=message.conversation_key,
        agora=apresentado_em,
        nao_entregues=tuple(entrega.nao_entregues) + tuple(sumiram),
        houve_entrega=True,
    )

    if entrega.entregues:
        # Sem esta gravacao a apresentacao some da linha do tempo para sempre,
        # e o dano nao e de auditoria: a protecao contra o turno SEGUINTE
        # reapresentar estes mesmos imoveis E o texto gravado (D16 da TEC-162),
        # nao exclusao por id. O docstring de `_apresentar` descreve o buraco
        # por extenso.
        #
        # **So as legendas que ESTA passada entregou.** As da passada anterior
        # sairam com ela; regrava-las duplicaria a fala do agente na linha do
        # tempo. `_entregar_fichas` ja devolve so o que passou por `send` aqui
        # -- o que `pular` deixou de fora nao entra em `legendas`.
        #
        # `MODELO_SEM_CHAMADA` pelo mesmo motivo de `_entregar_texto_fixo`:
        # nesta passada nao houve chamada ao modelo. A legenda e montada por
        # `legenda_de` a partir da ficha, e a prosa -- a unica parte que veio
        # do modelo -- saiu com a ficha 1, na passada anterior. Com "" a
        # telemetria abriria um `telemetry.unknown_model`.
        recorder = MessageRecorder(session_factory)
        await recorder.record_agent_message(
            conversation_key=message.conversation_key,
            channel=message.channel,
            text="\n\n".join(entrega.legendas),
            model=MODELO_SEM_CHAMADA,
            # O rotulo de quem originou a apresentacao, e nao um valor novo:
            # estas fichas saem da busca que o classificador fez na passada
            # anterior. Um rotulo proprio partiria a MESMA apresentacao em dois
            # valores de `subagent` para quem le a telemetria depois.
            subagent=SUBAGENTE_CLASSIFICADOR,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            sender_external_id=message.recipient_external_id,
            recipient_external_id=message.conversation_key,
        )

    log.info(
        "turno.entrega_continuada",
        channel=message.channel,
        message_id=str(message.id),
        entregues=entrega.entregues,
        ja_estavam_fora=len(ja_reservados),
    )
    return "respondido" if entrega.entregues else "reentrega_suprimida"


async def executar_turno(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    classificador: ClassificadorPort,
    resumidor: ResumidorPort,
    contador: ContadorPort,
    outbound: OutboundPort,
    moderador: ModeradorPort,
    agendador: AgendadorDeResumoPort,
) -> ResultadoDoTurno:
    """Um turno inteiro: contexto, classificacao, entrega, registro.

    **Nem sempre inteiro, desde a TEC-275 (D4).** Reprocessada uma mensagem
    cuja apresentacao parou no meio, o desvio logo antes de montar contexto
    devolve `_continuar_entrega` e nada abaixo dele roda: sem contexto, sem
    classificador, sem `reagir`. O comentario daquele desvio diz por que.

    A ordem no fim nao e arbitraria. Gravar a fala **depois** da entrega
    significa que uma queda no meio deixa o lead com a resposta e a linha do
    tempo sem ela, e o turno seguinte pode se repetir. Gravar antes deixaria
    uma fala fantasma no historico -- texto que o lead nunca viu, que entra no
    contexto do proximo turno e depois e dobrado permanentemente no resumo. O
    agente se repetir o lead perdoa; memoria inventada contamina tudo o que vem
    depois e ninguem percebe.

    Abaixo de `LIMIAR_DE_DESAMBIGUACAO` e com o episodio ainda limpo, a
    resposta da chamada 1 e descartada e o texto da segunda chamada
    (`classificador.desambiguar`) e entregue no lugar dela. O que o codigo
    garante e so esse desvio -- nada aqui garante que o texto devolvido seja
    uma pergunta aberta em vez de um menu numerado; a regra vive inteira no
    system prompt de `desambiguar` (ver a secao de lacunas do spec). O
    marcador que impede a repeticao so e gravado depois da entrega confirmada
    **e** so quando a pergunta foi de fato a coisa entregue -- marca-lo antes
    queimaria a unica chance de perguntar num 5xx da Meta, e marca-lo com a
    saida bloqueada queimaria a mesma chance por um texto neutro que nao
    pergunta nada.

    A marca de `perguntou` da TEC-257 segue a mesma regra, pelo mesmo motivo:
    e um fato sobre a nossa resposta, nao sobre a fala do lead, entao so entra
    depois da entrega confirmada e so quando `gerada` foi de fato o texto
    entregue -- nunca no caminho de desambiguacao (a chamada 1 foi descartada)
    nem com a saida bloqueada (o texto neutro nao pergunta nada). Diferente do
    marcador de desambiguacao, esta marca e permanente e a uniao no SQL nunca
    remove: marcar de mais aqui perde a chance de perguntar aquele campo para
    sempre e em silencio, nao so ate o proximo episodio.
    """
    # Antes de montar contexto de proposito: bloquear aqui economiza o turno
    # inteiro, inclusive as chamadas pagas ao modelo. E o texto do lead ainda
    # nao passou por lugar nenhum.
    corpo = decrypt(message.text_body, aad_de(message.id, "text_body"))

    # `bool(...)` por fora, e nao `bool(corpo) and ...`: so a forma curta-
    # circuitada estreita `corpo` de `str | None` para `str` dentro da chamada.
    pedido_de_optout = bool(corpo and pediu_optout(corpo))

    # Ao lado do opt-out de proposito: mesmo insumo (o texto decifrado), mesmo
    # ponto do fluxo, e nenhuma consulta. A fala bloqueada pela moderacao nunca
    # chega ao gancho -- `executar_turno` retorna por `_entregar_texto_fixo`
    # antes do bloco transacional --, entao um turno que o resto do produto
    # trata como nao-dito nao forca QUENTE, e isso sai de graca.
    #
    # `if corpo else ()` e nao `bool(corpo) and ...` porque a saida e uma
    # tupla, nao um bool: so a forma condicional estreita `corpo` de
    # `str | None` para `str` E preserva o tipo de retorno.
    gatilhos = gatilhos_de(corpo) if corpo else ()

    # Antes de tudo, inclusive da moderacao: quem ja pediu silencio nao paga
    # moderacao nem recebe resposta. Fica FORA do `if corpo:` de proposito: o
    # silencio e sobre o LEAD (o par channel/conversation_key), nao sobre a
    # mensagem ter texto. Uma imagem ou audio de quem ja pediu opt-out
    # tambem nao pode receber resposta, e dentro do `if corpo:` essa
    # mensagem sem texto escaparia do silencio. A guarda da porta de saida
    # (Task 4) ja impediria o envio de qualquer jeito; esta checagem existe
    # so para nao pagar o turno inteiro ate la.
    #
    # `not pedido_de_optout` e o fix de revisao (Important). Sem ele a
    # confirmacao se perdia PARA SEMPRE numa falha retentavel: turno 1 grava o
    # OPT_OUT, `_deliver` levanta `EnvioRetentavel` (5xx da Meta), a guarda
    # libera a reserva, a linha vira FAILED e o sweeper reenfileira -- e o
    # turno 2, sobre a MESMA mensagem, batia aqui, devolvia "silenciado" e
    # fechava em PROCESSED sem nunca reentregar. A D5 aceitou o lead ficar sem
    # confirmacao nas saidas TERMINAIS de `_entregar_texto_fixo` (janela
    # fechada, recusa permanente, reentrega suprimida); falha retentavel nao e
    # nenhuma delas, e o custo caiu entre duas tasks sem ninguem escolher.
    #
    # A idempotencia de quem JA recebeu a confirmacao continua vindo da
    # reserva em `outbound_dispatches`: se a confirmacao de fato saiu, a
    # reserva ainda existe, `send` devolve False e o desfecho e
    # `reentrega_suprimida`, com o alarme certo.
    #
    # O custo aceito: um lead que ja optou e digita "parar" de novo recebe a
    # confirmacao de novo -- mensagem nova para quem pediu silencio. E
    # defensavel porque e a excecao que a D1 ja nomeia (a confirmacao do
    # proprio pedido e o unico envio permitido depois do registro), e o
    # gatilho e sempre uma fala do lead pedindo exatamente isso.
    if not pedido_de_optout:
        async with session_factory() as sessao:
            if await esta_em_optout(
                sessao, channel=message.channel, conversation_key=message.conversation_key
            ):
                log.info(
                    "turno.silenciado_por_optout",
                    channel=message.channel,
                    message_id=str(message.id),
                )
                return "silenciado"

    # A guarda de atendimento humano (TEC-179, RN-16.4). `if not
    # pedido_de_optout:`, espelhando a checagem de opt-out logo acima -- e NAO
    # incondicional, que era o bug (fix de revisao, Critical). O opt-out e
    # direito do lead e vence tudo, inclusive um corretor que tenha assumido,
    # mas so vence de fato se este bloco nunca rodar antes do registro do
    # proprio pedido (`if pedido_de_optout:`, logo abaixo). Incondicional, um
    # lead que digitasse "pare" numa conversa ja assumida caia aqui, devolvia
    # "atendimento_humano" e o opt-out nunca era gravado -- o oposto do que
    # este comentario ja afirmava, e defeito de LGPD: a pessoa pediu para sair
    # e o sistema fica sem o registro.
    #
    # Barata de proposito -- antes do classificador, entao um turno silenciado
    # nao paga chamada ao modelo. A guarda autoritativa e a da porta de saida
    # (`outbound/port.py`); esta so evita o trabalho.
    if not pedido_de_optout:
        async with session_factory() as sessao:
            if await esta_silenciada(
                sessao, channel=message.channel, conversation_key=message.conversation_key
            ):
                log.info(
                    "turno.atendimento_humano",
                    channel=message.channel,
                    message_id=str(message.id),
                )
                return "atendimento_humano"

    if pedido_de_optout:
        # ANTES da moderacao de entrada, de proposito -- fix de revisao
        # (Critical): o bloco de moderacao logo abaixo tem `return` proprio.
        # Se este bloco rodasse depois dele, uma mensagem que e AO MESMO
        # TEMPO um pedido de opt-out e algo que a moderacao reprova (ex.:
        # "pare de mandar mensagem" seguido de um xingamento) nunca chegaria
        # aqui: a moderacao bloquearia e devolveria antes, o opt-out nunca
        # seria registrado, e continuariamos mandando mensagem (a recusa de
        # entrada) para quem pediu para sair -- a violacao que a D5 existe
        # para evitar, entrando por outra porta. Checar opt-out primeiro
        # tambem poupa a chamada paga de moderacao no caminho de opt-out, que
        # e o que o docstring de
        # `test_pedido_de_optout_grava_confirma_e_nao_paga_o_modelo` promete.
        #
        # Gravado ANTES da entrega, pelo precedente de `marcar_bloqueada`. Se
        # a entrega falhar depois, o lead fica em silencio sem confirmacao --
        # ruim e conforme. Na ordem inversa, um opt-out nao registrado nos
        # deixaria mandando mensagem, que e a violacao.
        await registrar_optout(
            session_factory,
            channel=message.channel,
            conversation_key=message.conversation_key,
            message_id=message.id,
        )
        # Nome distinto de `entregue` (o bool que `outbound.send` devolve mais
        # abaixo, no caminho principal): mypy infere um tipo unico por nome de
        # variavel na funcao inteira, e este aqui e o `ResultadoDoTurno` que
        # `_entregar_texto_fixo` devolve, nao o booleano cru.
        desfecho_da_confirmacao = await _entregar_texto_fixo(
            session_factory,
            message=message,
            outbound=outbound,
            recorder_texto=TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
            kind=KIND_DA_CONFIRMACAO_DE_OPTOUT,
            subagent=SUBAGENTE_OPTOUT,
        )
        # `_entregar_texto_fixo` devolve "expirado", "sem_resposta" ou
        # "reentrega_suprimida" quando nao entrega -- nunca
        # "bloqueado_por_optout" nem "bloqueado_por_atendimento_humano" NESTE
        # chamador especifico, porque o proprio `_entregar_texto_fixo` pula as
        # DUAS checagens para o kind da confirmacao (ver o comentario la
        # dentro, nos dois `if kind != KIND_DA_CONFIRMACAO_DE_OPTOUT`). Esses
        # desfechos sao sobre o ENVIO da confirmacao, e o opt-out ja esta
        # gravado -- entao eles passam adiante como estao, e so o caminho de
        # sucesso vira "opt_out".
        return "opt_out" if desfecho_da_confirmacao == "respondido" else desfecho_da_confirmacao

    if corpo:
        try:
            veredito = await moderador.moderar(corpo, direcao=Direcao.ENTRADA)
        except ModeracaoIndisponivel as exc:
            # Falha aberta, e assimetrica de proposito: a fala do lead ja esta
            # cifrada no banco (a ingestao a gravou antes de o worker existir),
            # e negar atendimento a lead legitimo porque um servico caiu pune o
            # inocente. Na saida a escolha e a oposta -- ver o bloco de saida.
            log.error(
                "moderacao.indisponivel",
                direcao=Direcao.ENTRADA.value,
                message_id=str(message.id),
                reason=str(exc),
            )
        else:
            if veredito.bloqueado:
                # `error` e nao `warning`: e o nivel que o alerta observa, pelo
                # mesmo criterio de `outbound.recusado`. O texto julgado **nao**
                # entra no log -- e fala do lead, coberta pela regra de PII.
                log.error(
                    "moderacao.entrada_bloqueada",
                    message_id=str(message.id),
                    motivo=veredito.motivo,
                    categoria=veredito.categoria,
                )
                # A marca vem ANTES da entrega, e a ordem e o ponto (TEC-236).
                # `_entregar_texto_fixo` tem cinco saidas que nao entregam
                # nada -- janela fechada, recusa permanente da Meta, reentrega
                # suprimida, bloqueio por opt-out concorrente (TEC-182),
                # bloqueio por atendimento humano concorrente (TEC-179) --, e
                # a maioria delas fecha a linha em PROCESSED, que e terminal.
                # Marcar depois deixaria a fala bloqueada sem marca exatamente
                # nos casos em que ninguem mais volta nesta linha, e ela
                # entraria no contexto do proximo turno.
                #
                # Se a marca falhar, a excecao sobe: a linha vira FAILED e o
                # sweeper retenta. Custa uma moderacao paga a mais e nao vaza a
                # fala -- ver `messages/bloqueio.py`.
                #
                # `TEC-142`: a marca e a auditoria de ENTRADA saem no mesmo
                # commit (ver `marcar_bloqueada`). `categoria or CATEGORIA_OUTRO`
                # porque `ModeradorPort` e um `Protocol` -- um adaptador futuro
                # pode devolver `Veredito(bloqueado=True)` sem categoria, e a
                # coluna e `not null`. A alternativa seria o turno estourar por
                # causa de um campo de auditoria.
                await marcar_bloqueada(
                    session_factory,
                    message.id,
                    channel=message.channel,
                    conversation_key=message.conversation_key,
                    categoria=veredito.categoria or CATEGORIA_OUTRO,
                )
                return await _entregar_texto_fixo(
                    session_factory,
                    message=message,
                    outbound=outbound,
                    recorder_texto=TEXTO_DA_RECUSA_DE_ENTRADA,
                )

    # TEC-275, D4. Antes de montar contexto de proposito: a continuacao nao
    # precisa de contexto, nao chama o classificador e nao chama `reagir` --
    # e e justamente por nao chamar `reagir` que ela nao fecha como NEUTRO as
    # pendentes da passada anterior.
    #
    # Tres ramos, e o do meio existe por um caso limite real: se a ficha que
    # falhou foi a PRIMEIRA, nada chegou ao lead -- nem as fichas, nem a prosa,
    # que viaja junto com a ficha 1 e nao esta persistida em lugar nenhum se
    # nao chegou a sair. Continuar uma entrega em que nada saiu nao e
    # continuar; e recomecar. E as linhas orfas tem de ser APAGADAS, nao
    # ignoradas: o `ON CONFLICT DO NOTHING` da passada nova preservaria o
    # carimbo velho, e o UNIQUE por conversa impediria a linha nova de nascer.
    lote = await ler_apresentacao_da_mensagem(session_factory, message_id=message.id)
    if lote:
        ja_reservados = await kinds_reservados(session_factory, message_id=message.id)
        if ja_reservados & {linha.kind for linha in lote}:
            return await _continuar_entrega(
                session_factory,
                message=message,
                outbound=outbound,
                lote=lote,
                ja_reservados=ja_reservados,
            )
        log.warning(
            "turno.apresentacao_sem_entrega_descartada",
            channel=message.channel,
            message_id=str(message.id),
            linhas=len(lote),
        )
        await apagar_apresentacao_da_mensagem(session_factory, message_id=message.id)

    try:
        contexto = await montar_contexto(
            session_factory,
            channel=message.channel,
            conversation_key=message.conversation_key,
            resumidor=resumidor,
            contador=contador,
        )
    except ContextoIrreducivel as exc:
        # Uma unica mensagem que nao cabe no teto. Retentar nao encolhe nada.
        log.warning(
            "turno.contexto_irreducivel",
            channel=message.channel,
            reason=str(exc),
        )
        return "sem_resposta"

    # D9. A reacao e capturada ANTES da busca deste turno, e nao depois.
    # O lead escreve "nao gostei desses, tem outros?" -- reacao e busca nova no
    # MESMO turno. Capturando depois, a busca deste turno nao saberia do
    # descarte e devolveria mais do mesmo, que e literalmente a dor da
    # historia da card.
    #
    # `except Exception` amplo: provedor fora, timeout e resposta malformada
    # tem a mesma consequencia aqui, e distinguir nao muda o que o turno faz.
    # Molde de `vetor_da_consulta` e da D6 da TEC-265 -- derrubar a dimensao,
    # nao a busca. O lead perde o ajuste neste turno, nao o atendimento.
    pendentes = await ler_pendentes(
        session_factory, channel=message.channel, conversation_key=message.conversation_key
    )
    # TEC-163, Task 10. RN-10.4: o aviso de ajuste (`aviso_de_ajuste`, acima)
    # so sai quando o conjunto excluido NASCE ou MUDA neste turno -- avisar em
    # toda busca repetiria a mesma frase por todo o tempo em que a exclusao
    # durasse. Comeca vazio; so o `else:` de sucesso logo abaixo (a reacao
    # deste turno foi capturada e gravada) pode preenche-lo.
    bairros_do_ajuste: tuple[str, ...] = ()
    if pendentes:
        # `apresentados` (o texto que o modelo le) e `ids` (o que
        # `resolver_ordinais` casa contra o ordinal devolvido) sao montadas
        # num UNICO laco sobre `pendentes`, e nao em duas list comprehensions
        # separadas: e o proprio laco -- um `pendentes[i]` alimentando as
        # duas listas na mesma iteracao -- que torna a posicao N de uma
        # SEMPRE a mesma posicao N da outra, por construcao. Com dois lacos
        # (ou duas consultas) o alinhamento seria acidental, nao garantido:
        # bastaria um filtro, uma ordenacao ou um `continue` entrar num dos
        # dois no futuro para as listas dessincronizarem em silencio, e a
        # reacao do lead grudaria no imovel errado sem nada acusar.
        apresentados: list[str] = []
        ids: list[uuid.UUID] = []
        for ordinal, pendente in enumerate(pendentes, start=1):
            apresentados.append(f"{ordinal}. {pendente.titulo} -- {pendente.bairro}")
            ids.append(pendente.imovel_id)
        # TEC-163, Task 10. O retrato de ANTES desta reacao. Se `reagir`
        # descartar um imovel e esse for o SEGUNDO descarte por distancia
        # naquele bairro (RN-10.4, `recomendacao.LIMIAR_DE_DESCARTES`), a
        # exclusao nasce ou cresce NESTE turno -- e comparar este retrato com
        # o de depois (no `else:` abaixo) e o que decide se o aviso sai.
        #
        # Nenhuma tabela nova para lembrar "ja avisei este conjunto": os
        # descartes JA sao o estado persistido, e append-only -- RN-10.4 nao
        # tem caminho de remocao, entao o conjunto excluido so cresce, nunca
        # encolhe. Mesmo molde de `buscar_com_relaxamento` (TEC-160): o aviso
        # de ampliacao tambem compara um antes e um depois dentro da mesma
        # chamada, em vez de lembrar do turno anterior.
        #
        # **Isto NAO basta, e a lacuna e conhecida, nao corrigida.** O retrato
        # decide se o aviso PRECISA sair neste turno, mas nao se ele CONSEGUE:
        # mais abaixo, o envio mora dentro de `if apresentando:`, e o turno em
        # que a exclusao nasce pode nunca chegar la -- zero candidato (busca
        # sem resultado), uma excecao no meio do turno, ou uma desambiguacao
        # que adia as fichas. Quando isso acontece, o aviso nao fica adiado
        # para o proximo turno: ele se PERDE para sempre. O `bairros_antes_da_
        # reacao` do PROXIMO turno ja e lido DEPOIS que este `gravar_reacoes`
        # commitou, entao ja inclui a mudanca de hoje -- os dois retratos
        # batem, nada parece ter mudado, e o aviso nunca mais dispara para
        # este conjunto. Um caso nada raro: e exatamente numa busca que
        # devolve zero que duas rejeicoes por distancia tem mais chance de
        # ter acabado de se acumular. Fechar isto de verdade exige um estado
        # persistido de "ja avisei este conjunto" (uma coluna ou tabela nova),
        # fora do alcance desta task -- que so tem `turno.py` e testes no
        # escopo.
        bairros_antes_da_reacao = bairros_a_excluir(
            await ler_descartes_por_distancia(
                session_factory,
                channel=message.channel,
                conversation_key=message.conversation_key,
            )
        )
        try:
            reacoes_do_turno = await classificador.reagir(contexto, apresentados=apresentados)
        except Exception as exc:
            log.warning(
                "turno.reacao_nao_capturada",
                channel=message.channel,
                tipo=type(exc).__name__,
                detalhe="linhas seguem pendentes, o filtro nao se ajusta neste turno",
            )
        else:
            # Chamada incondicional, mesmo com `reacoes` vazio (cenario 4 do
            # Gherkin: "tem mais alguma coisa?" nao fala de nenhum imovel
            # especifico): `gravar_reacoes` fecha toda pendente nao
            # mencionada como NEUTRO, e e essa uniao que garante no maximo
            # uma chamada de reacao por apresentacao -- ver o docstring dela.
            resolvidas = resolver_ordinais(reacoes_do_turno.reacoes, ids)
            await gravar_reacoes(
                session_factory,
                channel=message.channel,
                conversation_key=message.conversation_key,
                resolvidas=resolvidas,
            )
            # O retrato de DEPOIS, contra o de antes. `set(...)` e nao
            # comparacao de tupla: as duas consultas nao tem `ORDER BY`
            # (`ler_descartes_por_distancia`), e a ordem devolvida nao e
            # garantia de schema nenhuma -- comparar tupla arriscaria um
            # aviso disparando por reordenacao, sem bairro nenhum novo.
            # `sorted(...)` na gravacao final e so para a mensagem sair
            # estavel, nao para a comparacao.
            bairros_depois_da_reacao = bairros_a_excluir(
                await ler_descartes_por_distancia(
                    session_factory,
                    channel=message.channel,
                    conversation_key=message.conversation_key,
                )
            )
            if set(bairros_depois_da_reacao) != set(bairros_antes_da_reacao):
                bairros_do_ajuste = tuple(sorted(bairros_depois_da_reacao))

    # `cast`: `porta_de_busca` declara devolver `PortaDeBusca` (o Callable que
    # o classificador precisa -- D3 do desenho), mas sempre constroi e
    # devolve um `_PortaComScore` por baixo (TEC-163, D17). O turno precisa
    # do `.score_de` dessa classe concreta depois da busca, para gravar
    # `Recomendacao.score_match` sem que o score passe pelo `tool_result`
    # que o modelo le.
    #
    # `channel=message.channel, conversation_key=message.conversation_key`:
    # TEC-163, Task 10. Ate aqui esta chamada nao passava os dois, e
    # `_bairros_excluidos_desta_busca` (`ferramenta_de_busca.py`) desliga a
    # exclusao inteira sem identidade de conversa -- a feature das Tasks 7-9
    # inteira (limiar, categoria, dobra, o lift de D14) rodava em teste e
    # NUNCA em producao. Sem os dois nomeados aqui, `recomendacao.
    # exclusao_desligada_sem_identidade` loga em TODO turno; com eles, so
    # loga quando de fato faltar identidade -- nenhum turno normal.
    porta = cast(
        _PortaComScore,
        porta_de_busca(
            session_factory,
            embedador=embedar,
            channel=message.channel,
            conversation_key=message.conversation_key,
        ),
    )
    try:
        gerada = await classificador.classificar(
            contexto,
            # A porta e montada aqui porque e aqui que existe `session_factory`.
            # O classificador recebe um callable pronto e nao sabe o que e uma
            # sessao -- D3 do desenho.
            #
            # `embedador=embedar` liga a busca do turno ao provedor de verdade
            # -- o mesmo `embedar` que `indexar_catalogo` usa para o catalogo.
            # Sem isto, `consulta_texto` do tool call seria aceito e nunca
            # mudaria um resultado: `vetor_da_consulta` (busca.py) devolve
            # None sem embedador injetado, a similaridade fica 0 para todo
            # candidato, e a busca hibrida da TEC-158 nunca aconteceria dentro
            # de um turno -- so pela rota HTTP, que nao injeta embedador (ver
            # `api/routes/imoveis.py`). A degradacao por falha continua
            # coberta pelo mesmo `except Exception` de `vetor_da_consulta`:
            # o embedador real pode falhar, e a busca segue pelo filtro
            # estruturado -- D9.
            porta=porta,
        )
    except LacoDeBuscaExcedido:
        # Nao propaga: `process_message` marcaria FAILED e o sweeper
        # reenfileiraria o mesmo turno, que pediria a ferramenta duas vezes de
        # novo -- gastando duas chamadas ao modelo por tentativa para chegar
        # ao mesmo lugar. O lead recebe texto conservador; nenhum handoff nasce
        # aqui -- este `return` sai por `_entregar_texto_fixo`, ANTES do bloco
        # transacional que registra handoff mais abaixo.
        log.warning("turno.laco_de_busca_excedido", channel=message.channel)
        return await _entregar_texto_fixo(
            session_factory,
            message=message,
            outbound=outbound,
            recorder_texto=TEXTO_DA_BUSCA_INCONCLUSIVA,
            subagent=SUBAGENTE_CLASSIFICADOR,
        )

    # Gravada antes da entrega de proposito: a classificacao e sobre a mensagem
    # do lead, que existe, e nao sobre a resposta que pode nao sair.
    #
    # A leitura vem **antes** da gravacao no mesmo bloco: `gravar_intencao`
    # limpa o marcador quando a confianca sustenta a classificacao, entao
    # depois dela nao da mais para saber se este episodio ja tinha perguntado.
    #
    # O estado de qualificacao entra no mesmo commit pela mesma razao, e ela
    # vale mais forte aqui: o que o lead disse que procura e fato sobre a fala
    # dele, nao sobre a nossa resposta. Saida bloqueada e envio fora da janela
    # nao descartam a extracao.
    #
    # `perguntou` fica de fora deste `gravar_estado`, de proposito: ao
    # contrario da intencao e da extracao, ele e um fato sobre a NOSSA
    # resposta, nao sobre a fala do lead -- e a resposta pode nao ser a coisa
    # entregue (desambiguacao descarta a chamada 1; moderacao troca o texto
    # pelo neutro). A marca dele so e gravada mais abaixo, depois da entrega
    # confirmada -- ver o comentario la.
    #
    # `recusou` entra AQUI, ao contrario de `perguntou`: e fato sobre a fala
    # do lead, nao sobre a nossa resposta. Saida bloqueada e envio fora da
    # janela nao descartam uma recusa que o lead de fato disse.
    antes = esta_qualificado(contexto.estado, _recusados_de(contexto.estado))
    # TEC-174, fix wave (Important 2). Os dois ficam None quando a condicao que
    # os preenche nao roda -- e viram o `HandoffRegistrado` de `registrar_handoff`
    # quando roda. `registrar_handoff` nao loga mais (ver o comentario de la);
    # quem loga e este modulo, e so DEPOIS do commit abaixo.
    handoff_do_quente: HandoffRegistrado | None = None
    handoff_da_intencao: HandoffRegistrado | None = None
    async with session_factory() as session:
        anterior = await ler_intencao(session, message.channel, message.conversation_key)
        await gravar_intencao(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            confianca=gerada.confianca,
            modelo=gerada.modelo,
        )
        depois_do_estado = await gravar_estado(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            extracao=gerada.extracao,
            recusou=gerada.recusou,
        )
        # A trilha entra no mesmo commit que o estado, pela mesma razao que a
        # intencao e a extracao entram: ou os dois fatos existem, ou nenhum.
        #
        # Chamada em cada turno com estado, e nao so quando `gravar_estado`
        # devolveu linha: o engajamento depende da contagem de mensagens, que
        # sobe em todo turno, e as travessias de faixa dele podem cair num
        # turno sem campo nenhum. Amarrar o recalculo a escrita de campo
        # deixaria essas subidas fora da trilha.
        #
        # Nao recebe `depois_do_estado`: `registrar_recalculo` rele a linha sob
        # lock, e o motivo esta na docstring dele. `depois_do_estado` continua
        # valendo abaixo -- a releitura acontece na mesma sessao e na mesma
        # transacao, entao as duas referencias apontam para a mesma linha.
        recalculo = await registrar_recalculo(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            gatilhos=gatilhos,
        )
        # TEC-174. Aqui dentro, e nao junto ao `lead.esquentou` la embaixo: este
        # `commit` e o que torna indivisivel "o lead esquentou" e "o corretor
        # tem tarefa". Do lado de fora seria sessao nova, e existiria a janela
        # em que o lead esta QUENTE e ninguem foi avisado -- que e o "lead
        # qualificado morre no banco" que a card existe para impedir.
        if (
            recalculo is not None
            and recalculo.anterior is not Temperatura.QUENTE
            and recalculo.temperatura is Temperatura.QUENTE
        ):
            handoff_do_quente = await registrar_handoff(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=Gatilho.LEAD_QUENTE,
            )

        if (gatilho_da_intencao := _GATILHO_DA_INTENCAO.get(gerada.intencao)) is not None:
            handoff_da_intencao = await registrar_handoff(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=gatilho_da_intencao,
            )
        await session.commit()

    # TEC-174, fix wave (Important 2). Depois do commit acima -- o gatilho da
    # intencao dispara em todo turno com a classificacao certa (sem condicao
    # de borda, ao contrario do QUENTE logo abaixo), entao nao ha um evento
    # vizinho pronto para emprestar a posicao; loga aqui, e so aqui.
    if gatilho_da_intencao is not None and handoff_da_intencao is not None:
        log.info(
            "handoff.criado" if handoff_da_intencao.criado else "handoff.gatilho_adicional",
            channel=message.channel,
            gatilho=gatilho_da_intencao.value,
            etiqueta=ETIQUETA_DE[gatilho_da_intencao],
            prioridade=PRIORIDADE_DE[gatilho_da_intencao].value,
        )
        await _agendar_resumo(agendador, handoff_da_intencao)

    # A borda, nao o estado: um lead ja qualificado que segue conversando nao
    # gera o evento de novo, senao a taxa de qualificacao da RN-17.1 contaria
    # conversas em vez de leads. `antes` sai de `contexto.estado`, que
    # `montar_contexto` ja leu para montar o prompt -- nenhuma consulta extra.
    # Um turno FORA_DE_ESCOPO que so grava recusa (o caminho do Achado 1 em
    # `gravar_estado`) pode devolver a linha em vez de `None` -- mas isso
    # nunca dispara o evento: aquele caminho so acrescenta nomes a
    # `campos_recusados` (uniao, sem `array_remove`, porque nao ha campo
    # respondido neste turno) e nunca toca as colunas de valor, entao a
    # qualificacao de `depois_do_estado` so pode piorar ou empatar com a de
    # `contexto.estado` -- nunca melhorar. Como o evento exige `not antes and
    # esta_qualificado(depois...)`, ele so dispararia se `depois` fosse MAIS
    # qualificado que `antes`, o que este caminho nunca produz.
    #
    # TEC-148 quebrou a premissa que sustentava "uma vez qualificado, sempre
    # qualificado" por tras do primeiro paragrafo acima: antes desta card
    # nenhum valor gravado era apagado, entao a borda so era cruzada uma vez
    # por lead, para sempre. Agora uma recusa pode derrubar `esta_qualificado`
    # (o campo deixa de contar enquanto recusado) e uma resposta seguinte pode
    # devolve-lo (o `array_remove` de `gravar_estado` tira a recusa quando o
    # valor chega) -- turno A completa os quatro obrigatorios e emite; turno B
    # recusa um deles; turno C comeca com `antes` False (o estado que
    # `contexto.estado` leu ja carrega a recusa do turno B), o lead responde e
    # a borda e cruzada de novo, para o MESMO lead. O evento reemite. Isto NAO
    # esta corrigido aqui: tornar a emissao idempotente por lead exige estado
    # persistido de "ja emiti uma vez", que e decisao de quem e dono da
    # metrica RN-17.1, nao desta card -- so fica declarado, para quem ler essa
    # metrica saber que uma travessia de ida-e-volta agora conta duas vezes.
    if not antes and esta_qualificado(depois_do_estado, _recusados_de(depois_do_estado)):
        log.info(
            "lead.qualificado",
            channel=message.channel,
            message_id=str(message.id),
        )

    # A borda, e nao o estado: um lead que continua QUENTE nao reemite, senao
    # a RN-06.5 viraria um ping por mensagem. `recalculo.anterior` sai da
    # coluna `temperatura`, e nao da trilha de auditoria -- a trilha grava so
    # quando o score muda e tem retencao de 12 meses (RNF-18), entao um lead
    # cujo ultimo registro fosse expurgado voltaria a parecer nunca-calculado
    # e reemitiria como se tivesse acabado de esquentar. (`anterior`, sem
    # prefixo, e OUTRA variavel nesta funcao -- a linha de intencao que
    # `ler_intencao` devolveu, la em cima; nao confundir as duas.)
    #
    # `recalculo.anterior is None` (coluna nula) com QUENTE emite: um lead
    # cujo primeiro recalculo ja cai em QUENTE de fato esquentou, e tratar
    # NULL como "ja era quente" perderia a unica travessia que ele tem.
    #
    # `recalculo is not None` nao e so defensivo: e "nao havia
    # `lead_qualification` para pontuar" (ver a docstring de
    # `registrar_recalculo`). Uma linha so nasce quando `campos_a_gravar`
    # devolve algo -- `gravar_estado` documenta o caminho "Deliberadamente NAO
    # cria linha" --, entao um lead que AINDA NAO TEM linha (primeiro turno, ou
    # so turnos FORA_DE_ESCOPO/INDEFINIDA sem extracao ate agora) e que peca
    # visita justo num turno assim continua sem linha: `registrar_recalculo`
    # nao acha o que pontuar, devolve `None`, e o pedido se perde em silencio,
    # sem forcar e sem emitir. Um lead que JA TEM linha (de um turno COMPRA
    # anterior, por exemplo) nao sofre disto -- `registrar_recalculo` acha a
    # linha existente e aplica o gatilho normalmente, mesmo num turno
    # FORA_DE_ESCOPO. Nao corrigido aqui -- lacuna declarada no desenho.
    #
    # Depois do commit, como `lead.qualificado`: logar uma transicao que o
    # rollback desfez e mentir para quem le o log.
    #
    # **A fiacao da RN-06.5 existe desde a TEC-177, e roda FORA deste
    # turno -- a ENTREGA ao corretor, nao.** Desde a TEC-174 a travessia para
    # QUENTE cria um `handoff` na MESMA transacao deste recalculo -- ou o lead
    # vira QUENTE e tem handoff, ou nem uma coisa nem outra. E
    # `_agendar_resumo` (chamada abaixo, para este mesmo handoff) que
    # enfileira o job que redige o resumo e, ao terminar, enfileira
    # `notificar_corretor` (`workers/jobs/gerar_resumo.py`), que so REGISTRA:
    # os dois canais de `notificacao/canais.py` aceitam a chamada e nao
    # entregam nada a corretor nenhum ainda -- Emenda E-02 da RN-16.2 no SRS.
    # O orcamento de 60 segundos da RN-16.2 fecharia pela soma das duas
    # etapas assincronas -- resumo com p95 de 8s (RNF-05) mais uma chamada
    # por canal --, mas isso descreve o encadeamento, nao uma entrega que
    # ainda nao existe.
    #
    # O texto do lead nao entra: `motivos` e vocabulario nosso, nao fala dele.
    # Mesma regra de PII que `moderacao.entrada_bloqueada` respeita.
    #
    # Este evento herda o defeito de reemissao de `lead.qualificado`, pela
    # mesma causa: o total nao e monotono desde a TEC-148, entao a borda por
    # faixa e atravessavel nos dois sentidos para o MESMO lead. O forcado nao
    # volta; o derivado volta. Declarado, nao corrigido -- corrigir exige
    # estado persistido de "ja emiti uma vez".
    if (
        recalculo is not None
        and recalculo.anterior is not Temperatura.QUENTE
        and recalculo.temperatura is Temperatura.QUENTE
    ):
        log.info(
            "lead.esquentou",
            channel=message.channel,
            message_id=str(message.id),
            motivos=list(recalculo.gatilhos),
            total=recalculo.total,
        )
        # TEC-174, fix wave (Important 2). Depois do commit, junto de
        # `lead.esquentou` -- mesma condicao, mesma borda, mesmo motivo de
        # nao logar dentro de `registrar_handoff`. `handoff_do_quente` so e
        # None quando esta condicao e falsa, entao aqui ele sempre carrega o
        # registro que o `registrar_handoff` de cima devolveu.
        if handoff_do_quente is not None:
            log.info(
                "handoff.criado" if handoff_do_quente.criado else "handoff.gatilho_adicional",
                channel=message.channel,
                gatilho=Gatilho.LEAD_QUENTE.value,
                etiqueta=ETIQUETA_DE[Gatilho.LEAD_QUENTE],
                prioridade=PRIORIDADE_DE[Gatilho.LEAD_QUENTE].value,
            )
            await _agendar_resumo(agendador, handoff_do_quente)

    desambiguando = deve_desambiguar(
        gerada.confianca, anterior.desambiguado_em if anterior else None
    )
    # Anotado explicitamente: sem isso o mypy infere o tipo de `telemetria` a
    # partir so do primeiro ramo que ve (`PerguntaDeDesambiguacao`) e recusa a
    # atribuicao do segundo. Os dois tipos so precisam ter em comum os campos
    # de telemetria que `record_agent_message` le abaixo.
    texto: str
    telemetria: RespostaDoAgente | PerguntaDeDesambiguacao
    subagente: str
    if desambiguando:
        # A resposta da chamada 1 foi escrita assumindo um palpite que a
        # confianca nao sustenta. Ela e descartada -- paga e nao entregue.
        pergunta = await classificador.desambiguar(contexto)
        texto, telemetria, subagente = pergunta.texto, pergunta, SUBAGENTE_DESAMBIGUADOR
    else:
        texto, telemetria, subagente = gerada.resposta, gerada, SUBAGENTE_CLASSIFICADOR

    # Uma vez por turno: so um texto vem do modelo. No caminho ambiguo a
    # resposta da chamada 1 foi descartada e so a pergunta e entregue. Na
    # apresentacao da TEC-162 saem tres mensagens, mas o unico texto gerado
    # continua sendo esta prosa -- a ficha e dado do banco montado por codigo,
    # e moderar dado nosso seria gastar chamada sobre texto que nao inventamos.
    #
    # Aqui **nao** ha falha aberta. Entregar texto nao moderado e o risco que
    # este subsistema existe para fechar, e o custo recai sobre a reputacao da
    # imobiliaria em publico -- diferente da entrada, onde o custo de falhar
    # aberto recai sobre o contexto do agente. A excecao propaga: a linha vira
    # FAILED com `attempts` e o sweeper retenta.
    try:
        veredito_da_saida = await moderador.moderar(texto, direcao=Direcao.SAIDA)
    except ModeracaoIndisponivel as exc:
        # Loga e **repropaga**. O log existe porque `process_message` vai
        # registrar so `message.failed` -- sem esta linha, "o turno falhou" e
        # "nao deu para moderar a saida" ficam indistinguiveis no log, e o
        # segundo e o unico dos dois que aponta para o moderador.
        log.error(
            "moderacao.indisponivel",
            direcao=Direcao.SAIDA.value,
            message_id=str(message.id),
            reason=str(exc),
        )
        raise
    saida_bloqueada = veredito_da_saida.bloqueado
    if saida_bloqueada:
        # O texto barrado **nao** entra no log: registra-lo criaria, no log,
        # exatamente aquilo que a moderacao impediu de sair.
        log.error(
            "moderacao.saida_bloqueada",
            message_id=str(message.id),
            motivo=veredito_da_saida.motivo,
            subagente=subagente,
            categoria=veredito_da_saida.categoria,
        )
        # Antes da entrega, pelo mesmo precedente de `marcar_bloqueada`: se a
        # auditoria falhar, o turno falha e o sweeper retenta. Um bloqueio de
        # saida entregue e nao auditado e o caso em que o risco da RN-B04
        # aconteceu sem deixar registro.
        await registrar_bloqueio_de_saida(
            session_factory,
            message_id=message.id,
            channel=message.channel,
            conversation_key=message.conversation_key,
            categoria=veredito_da_saida.categoria or CATEGORIA_OUTRO,
        )
        texto = TEXTO_NEUTRO_DE_SAIDA

    # TEC-162, D4. Candidatos sem pergunta e turno de apresentacao. As tres
    # condicoes sao a mesma regra: pergunta adia as fichas. `desambiguando`
    # entra porque `gerada.perguntou` fala da chamada 1, que foi DESCARTADA
    # nesse caminho -- o texto entregue e a pergunta do desambiguador.
    apresentando = bool(gerada.candidatos) and not gerada.perguntou and not desambiguando

    # TEC-161. A ultima coisa que acontece antes de a entrega comecar, e a
    # ordem e a invariante da card: `_apresentar` grava reserva em
    # `outbound_dispatches`, e bloquear depois dela deixaria linha gravada e
    # mensagem entregue.
    #
    # **Nao regenera**, contra a letra da RN-09.4 e com emenda no SRS. Tres
    # razoes, na ordem de peso: a moderacao de saida logo acima ja barra sem
    # regerar e duas politicas para o mesmo problema no mesmo turno seriam uma
    # a mais; uma segunda chamada reexecuta o laco de tool use da TEC-265, ou
    # seja uma busca nova, dentro de um `job_timeout` que o pior caso ja
    # estoura; e depois da TEC-162 descartar a prosa ainda entrega ate tres
    # fichas corretas, porque nenhum campo delas passou pelo modelo.
    # `depois_do_estado or contexto.estado`: `gravar_estado` devolve `None` em
    # todo turno que nao extraiu campo novo e nao registrou recusa (ver o
    # "Deliberadamente NAO cria linha" no docstring dela), o que inclui o
    # turno mais comum de todos -- o lead nao disse nada novo sobre orcamento,
    # so continuou a conversa. Alimentar so `depois_do_estado` cegaria a
    # excecao da faixa exatamente nesses turnos, mesmo com a linha
    # `lead_qualification` ja existindo e ja carregando a faixa: o modelo
    # ecoando "beleza, vou procurar ate 600 mil" -- que o D5 do desenho existe
    # para permitir, e que `montar_contexto` ate instrui o modelo a fazer --
    # seria bloqueado como se tivesse inventado o numero. `contexto.estado` e
    # o mesmo valor que `antes`, la em cima, ja leu para a borda de
    # qualificacao: a linha de antes do turno, que continua valendo quando
    # este turno nao gravou nada novo.
    divergencias = divergencias_de(
        texto,
        candidatos=gerada.candidatos,
        faixa=_faixa_declarada(depois_do_estado or contexto.estado),
    )
    citacao_bloqueada = bool(divergencias)
    if citacao_bloqueada:
        # A prosa barrada **nao** entra no log, pela mesma razao que o texto
        # barrado pela moderacao nao entra: registra-la criaria no log
        # exatamente aquilo que a guarda impediu de sair. Os valores
        # divergentes entram -- sao o que o modelo inventou, e sao o unico
        # dado que torna a linha investigavel.
        log.error(
            "citacao.bloqueada",
            channel=message.channel,
            message_id=str(message.id),
            tipos=[d.tipo for d in divergencias],
            citados=[d.citado for d in divergencias],
            candidatos=len(gerada.candidatos),
            apresentando=apresentando,
        )
        # Apresentando, a prosa vira prefixo vazio e `legenda_de` a omite: o
        # lead recebe a ficha do banco, que e o conteudo que a RN-10.1 exige.
        # Sem ficha para entregar, a prosa era a mensagem inteira, e o
        # substituto e o mesmo texto que o `LacoDeBuscaExcedido` ja usa --
        # ele E a proposta de verificacao com o corretor que a card pede.
        texto = "" if apresentando else TEXTO_DA_BUSCA_INCONCLUSIVA

    # D14. Relaxou e continuou zero tem desfecho nosso, e nao prosa do modelo:
    # e o cenario 2 do Gherkin. `not citacao_bloqueada` porque, se o modelo
    # inventou imovel, a mensagem da TEC-161 e a que importa -- ela fala de um
    # defeito nosso, e este texto fala do catalogo.
    #
    # So no zero POS-relaxamento. O zero de "nada relaxavel" (D5) segue com a
    # prosa do modelo: ali ele ainda pode perguntar algo util que nos nao
    # sabemos perguntar, e cala-lo custaria mais do que padroniza.
    if gerada.relaxou_sem_resultado and not citacao_bloqueada:
        texto = TEXTO_SEM_RESULTADO_APOS_AMPLIAR

    # Depois da moderacao de saida, de proposito: o texto e constante deste
    # repositorio e nao saida de modelo -- moderar dado nosso seria gastar
    # chamada sobre texto que nao inventamos, o mesmo argumento que a TEC-162
    # escreveu para as fichas.
    #
    # Este ponto fica DEPOIS das tres reatribuicoes de `texto` acima, e por
    # isso cobre quatro trilhas, nao uma: a resposta normal, o
    # TEXTO_NEUTRO_DE_SAIDA da moderacao de saida bloqueada, o
    # TEXTO_DA_BUSCA_INCONCLUSIVA da citacao bloqueada da TEC-161 e o
    # TEXTO_SEM_RESULTADO_APOS_AMPLIAR do zero pos-relaxamento da TEC-160. A
    # apresentacao NAO e uma quinta trilha aqui -- e excluida de proposito,
    # tratada em separado dentro do `if apresentando:` abaixo (Task 5).
    #
    # `apresentando` fica de FORA aqui: naquele caminho `texto` vira prefixo de
    # legenda, e `legenda_de` corta o prefixo antes da ficha (D14 da TEC-162).
    # A identificacao seria descartada em silencio. A Task 5 trata dele.
    identificar = not apresentando and await e_conversa_nova(
        session_factory, message, agora=datetime.now(UTC)
    )
    if identificar:
        texto = f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{texto}"

    # Fix de revisao final (Critical 1 e Important 2, TEC-140). So o caminho
    # de texto (o `else:` abaixo) pode marcar as duas True -- `_apresentar` ja
    # tem a forma certa e nao precisa delas --, mas os valores precisam existir
    # para os dois caminhos porque o `if suprimida_apos_entrega:` e o guard de
    # `marcar_perguntados`, mais abaixo, rodam incondicional de qual ramo
    # executou.
    suprimida_apos_entrega = False
    entrega_parcial = False

    try:
        if apresentando:
            if await e_conversa_nova(session_factory, message, agora=datetime.now(UTC)):
                # Mensagem propria, e NAO prefixo da prosa (que e o mecanismo
                # das outras tres trilhas, acima). Na apresentacao a prosa
                # vira prefixo da legenda da PRIMEIRA ficha (D16 da TEC-162),
                # e `legenda_de` corta o prefixo antes de cortar a ficha
                # (D14): "estourado o teto, o que se corta e o PREFIXO, nunca
                # a ficha" -- `_prosa_que_cabe` devolve string vazia quando
                # nao sobra espaco. Se a identificacao viajasse ali dentro,
                # ela sairia truncada ou nao sairia nenhuma, em silencio, no
                # turno mais comum de uma conversa nova: o lead diz o que
                # procura e o agente ja busca e apresenta.
                #
                # A E-02 da TEC-162 separou os tetos da RN-04.2 em ate 2
                # mensagens de TEXTO e ate 3 de APRESENTACAO. TEC-163, Task 10
                # acrescenta uma TERCEIRA trilha de texto propria (o aviso de
                # ajuste, poucas linhas abaixo) -- com identificacao + ajuste +
                # ampliacao, um turno pode ter ate 3 textos mais ate 3 fichas,
                # e o teto de 2 deixa de valer sem emenda. Nao corrigido aqui
                # de proposito: a emenda formal da RN-04.2 e a Task 11 desta
                # card, nao esta.
                await outbound.send(
                    message.id,
                    KIND_DA_RESPOSTA,
                    {
                        "para": message.conversation_key,
                        "de": message.recipient_external_id,
                        "texto": TEXTO_DA_IDENTIFICACAO,
                    },
                )
            if bairros_do_ajuste:
                # TEC-163, Task 10, RN-10.4. Mensagem propria, e NAO prefixo
                # da legenda -- mesmo motivo do aviso de ampliacao logo
                # abaixo: `legenda_de` corta o PREFIXO antes da ficha, e
                # `_prosa_que_cabe` devolve string vazia quando nao sobra
                # espaco. A TEC-139 ja pagou para descobrir isso com a
                # identificacao; um aviso que confirma ter ouvido o lead e
                # some em silencio e pior que nao existir.
                #
                # ANTES do aviso de ampliacao, de proposito -- ordem
                # narrativa da conversa: quem fala (identificacao), o que
                # fizemos com o que o LEAD disse (o ajuste responde a ele),
                # so depois o que tivemos de esticar por CONTA PROPRIA (a
                # ampliacao e iniciativa nossa), e so entao o resultado
                # (fichas).
                #
                # `bairros_do_ajuste` so vem preenchido quando a exclusao
                # nasceu ou mudou NESTE turno (ver o retrato antes/depois no
                # bloco da reacao, acima) -- avisar em toda busca repetiria a
                # mesma frase por todo o tempo em que a exclusao durasse,
                # ensinando o lead a ignorar o aviso.
                #
                # Kind proprio e OBRIGATORIO: `outbound_dispatches` tem
                # UNIQUE (message_id, kind), e a identificacao acima ja usa
                # KIND_DA_RESPOSTA -- reusar colidiria e este aviso seria
                # descartado como reprocessamento.
                await outbound.send(
                    message.id,
                    KIND_DO_FILTRO_AJUSTADO,
                    {
                        "para": message.conversation_key,
                        "de": message.recipient_external_id,
                        "texto": aviso_de_ajuste(bairros_do_ajuste),
                    },
                )
            if gerada.relaxou_e_achou and (gerada.relaxou_preco or gerada.relaxou_bairro):
                # CA-09.3. Mensagem propria, e NAO prefixo da legenda: no
                # caminho de apresentacao `legenda_de` corta o PREFIXO antes
                # da ficha, e `_prosa_que_cabe` devolve string vazia quando
                # nao sobra espaco. A TEC-139 ja pagou para descobrir isso com
                # a identificacao -- "ela sairia truncada ou nao sairia
                # nenhuma, em silencio". Um aviso que some em silencio quebra
                # a CA-09.3 exatamente no turno em que ela existe para valer.
                #
                # A E-02 da TEC-162 separou os tetos em ate 2 mensagens de
                # TEXTO e ate 3 de APRESENTACAO -- e ISTO, sozinho, ainda
                # cabe: identificacao + este aviso sao os 2 textos que a E-02
                # previu. **A proxima trilha que quisesse mensagem propria
                # precisaria de emenda -- e a TEC-163, Task 10 e essa
                # trilha.** O aviso de ajuste (RN-10.4) entra ANTES deste, no
                # mesmo `if apresentando:` (ver acima), e as tres mensagens de
                # texto juntas (identificacao, ajuste, ampliacao) passam do
                # teto de 2. Nao corrigido aqui: a emenda formal da RN-04.2
                # fica para a Task 11 desta card.
                #
                # `relaxou_preco or relaxou_bairro` e a guarda contra o
                # estado impossivel que `aviso_de_ampliacao` recusa
                # (ValueError): se ele ocorrer de qualquer jeito, o turno nao
                # morre por causa de um aviso -- so deixa de mandar um.
                await outbound.send(
                    message.id,
                    KIND_DO_CRITERIO_AMPLIADO,
                    {
                        "para": message.conversation_key,
                        "de": message.recipient_external_id,
                        "texto": aviso_de_ampliacao(gerada.relaxou_preco, gerada.relaxou_bairro),
                    },
                )
            # TEC-163, D17. O score de cada candidato desta busca, lido da
            # PORTA que a fez -- nunca do `tool_result` que o modelo viu (D7
            # da TEC-265, ver `_PortaComScore` em `ferramenta_de_busca.py`).
            # `_apresentar` usa isto para gravar `Recomendacao.score_match`
            # antes de comecar a entrega. Um candidato sem score aqui (nunca
            # deveria acontecer: a porta guarda score de TODO candidato que
            # ela mesma devolveu) fica de fora do dict e `gravar_recomendacoes`
            # decide o resto.
            scores = {
                uuid.UUID(candidato["imovel_id"]): score
                for candidato in gerada.candidatos
                if (score := porta.score_de(uuid.UUID(candidato["imovel_id"]))) is not None
            }
            # `prosa=texto` le o valor ANTES da atribuicao: a chamada e
            # avaliada primeiro, e o `texto` que sai sao as legendas
            # concatenadas (D16).
            texto, quantas, suprimidas = await _apresentar(
                session_factory,
                message=message,
                outbound=outbound,
                candidatos=gerada.candidatos,
                scores=scores,
                criterios=gerada.criterios,
                # TEC-163, fix wave. `criterios` e o que a busca PEDIU (o
                # filtro antes do relaxamento -- o alargado nunca sai de
                # `buscar_com_relaxamento`); sem estes dois, um candidato que
                # so apareceu porque o teto cedeu 10% seria gravado com o
                # criterio que ele nao satisfaz. Sao os mesmos booleanos que
                # `aviso_de_ampliacao` usa logo acima: o lead ouve que o
                # criterio foi ampliado e a linha do banco passa a dizer o
                # mesmo.
                relaxou_preco=gerada.relaxou_preco,
                relaxou_bairro=gerada.relaxou_bairro,
                prosa=texto,
            )
            entregue = quantas > 0
            # Nenhuma ficha entrou e TODAS foram suprimidas pela reserva: e o
            # mesmo caso do `not entregue` do caminho de texto -- reentrega de
            # uma tentativa anterior --, e o desfecho tem de ser o mesmo.
            if not entregue and suprimidas == 0:
                # Duas rotas chegam aqui, e as duas ja logaram em
                # `_apresentar`: ou todas as fichas foram recusadas
                # permanentemente (um `apresentacao.ficha_recusada` por
                # ficha), ou nenhuma ficha existiu -- `imoveis_por_ids`
                # derrubou todos os ids e o loop nunca rodou
                # (`apresentacao.fichas_sumiram_do_catalogo`). A segunda e a
                # que engana: sem aquele log ela seria um turno inteiramente
                # mudo, sem uma linha para quem opera.
                return "sem_resposta"
        else:
            # So o TAMANHO ganha guarda aqui. As outras duas clausulas da RN-04.2
            # continuam vigiadas so pelo gate (`aderencia_ao_tom`, piso de 90%), e
            # o motivo e que fecha-las em runtime custaria mais do que resolvem:
            #
            # - Perguntas: exigiria regenerar a resposta. O argumento contra
            #   isso e emprestado da TEC-161 -- que decidiu sobre a RN-09.4
            #   (citacao de imovel divergente), nao sobre esta clausula --,
            #   mas o motivo arquitetural vale igual aqui: a segunda chamada
            #   reexecuta o laco de tool use dentro de um `job_timeout` que o
            #   pior caso ja estoura. Descartar perguntas do texto muda o que
            #   o agente quis dizer, e a regra existe contra questionario,
            #   nao contra a segunda pergunta (emenda E-01, medida sobre 294
            #   turnos).
            # - Emoji: a RNF-42 fala de COMPREENSAO ("a informacao essencial nunca
            #   depende de emoji"), e o comentario de `evals/metricas.py` registra
            #   que por isso a metrica reporta presenca e quantidade como
            #   diagnostico, sem reprovar. Uma guarda deterministica contaria
            #   figurinhas em vez de checar se a frase sobrevive sem elas.
            #
            # `entregue` fica True se QUALQUER parte entrou. A alternativa --
            # exigir todas -- trataria "a segunda caiu na janela fechada" como
            # turno sem resposta, quando o lead ja recebeu a primeira.
            #
            # A falha da PRIMEIRA parte segue o comportamento de sempre: nada
            # foi capturado ainda, a excecao sobe crua para os `except` deste
            # bloco la embaixo, e o turno termina em "expirado"/"sem_resposta"
            # sem gravar nada -- igual a antes desta card, quando so existia
            # uma mensagem.
            #
            # A falha de uma parte POSTERIOR -- com pelo menos uma ja
            # entregue -- nao pode seguir o mesmo caminho: `EnvioForaDaJanela`
            # e `EnvioRecusado` sao capturadas DENTRO de `executar_turno` (os
            # `except` la embaixo) e viram "expirado"/"sem_resposta" ANTES do
            # recorder gravar. Nao ha retentativa do sweeper para nenhuma das
            # duas -- o estado da linha vira `PROCESSED`, que e terminal
            # (`status.py`). Deixar a excecao subir depois que a parte 1 ja
            # saiu apagaria o registro de conteudo real que o lead recebeu: o
            # log ficaria identico ao de "nada saiu", e a transcricao nao
            # teria nenhuma linha daquele turno para um lead que recebeu
            # metade da resposta.
            #
            # Por isso essas duas excecoes sao capturadas AQUI DENTRO do laco
            # quando `entregue` ja e True, logadas com um evento proprio que
            # diz "parcial" -- distinto do de "nada saiu", para quem le o log
            # conseguir separar os dois casos -- e o turno segue: `entregue`
            # continua True e o fluxo cai no recorder normalmente.
            # `entrega_parcial` reescreve `texto` para so as partes que de
            # fato sairam: gravar o texto inteiro aqui trocaria a mentira
            # "nada saiu" pela mentira "saiu tudo".
            entregue = False
            partes_entregues: list[str] = []
            # strict=False nao e detalhe de estilo: `quebrar_em_mensagens`
            # devolve uma 1-tupla quando o texto cabe numa mensagem so (o
            # caminho comum), e `KINDS_DA_RESPOSTA` tem sempre dois kinds. Com
            # strict=True isso levantaria `ValueError` no caminho de 99% dos
            # turnos. `strict=False` deixa o zip parar no mais curto -- que e
            # exatamente o efeito querido: so tenta o segundo kind quando ha
            # uma segunda parte para ele.
            for kind, parte in zip(KINDS_DA_RESPOSTA, quebrar_em_mensagens(texto), strict=False):
                try:
                    entrou = await outbound.send(
                        message.id,
                        kind,
                        {
                            "para": message.conversation_key,
                            "de": message.recipient_external_id,
                            "texto": parte,
                        },
                    )
                except EnvioRetentavel:
                    # Fix de revisao final (Critical 2, TEC-140), espelhando o
                    # `except EnvioRetentavel` de `_entregar_fichas` (mais
                    # abaixo neste arquivo; ele morava em `_apresentar` ate a
                    # TEC-275 extrair o laco). Antes desta clausula a excecao subia crua
                    # por este `try`, atravessava os `except` la embaixo (que
                    # so pegam `EnvioForaDaJanela`/`EnvioRecusado`) e chegava
                    # ao chamador do mesmo jeito -- entao a clausula NAO muda o
                    # desfecho: a linha ainda vira FAILED e o sweeper ainda
                    # reenfileira. O unico acrescimo e este log, para uma
                    # entrega PARCIAL (a parte 1 ja saida quando o 5xx bateu
                    # nesta) nao ficar invisivel ate a proxima tentativa
                    # reaparecer no mesmo lugar.
                    #
                    # E essa proxima tentativa e o proprio risco que o
                    # comentario no topo do modulo (perto de `KINDS_DA_RESPOSTA`)
                    # documenta: `sweep_stalled` roda o turno inteiro de novo,
                    # com uma chamada NOVA ao classificador. A parte que ja
                    # tem reserva volta a ser suprimida (devolve False, nao
                    # levanta -- e o `if entregue:` abaixo cobre isso na
                    # proxima passada); a parte que falhou aqui sai com o texto
                    # da chamada nova. O lead pode acabar recebendo a primeira
                    # metade deste texto seguida da segunda metade de outro --
                    # este log so torna isso visivel, nao evita.
                    log.error(
                        "turno.entrega_parcial_antes_de_falha_retentavel",
                        channel=message.channel,
                        message_id=str(message.id),
                        kind=kind,
                        partes_entregues=len(partes_entregues),
                    )
                    raise
                except (EnvioForaDaJanela, EnvioRecusado) as exc:
                    if not entregue:
                        # Nada saiu ainda: mesmo desfecho de antes desta
                        # card, a excecao sobe crua.
                        raise
                    entrega_parcial = True
                    log.error(
                        "turno.entrega_parcial_da_resposta",
                        channel=message.channel,
                        message_id=str(message.id),
                        kind=kind,
                        reason=str(exc),
                    )
                    break
                if not entrou:
                    # `send()` devolveu False SEM levantar -- reentrega
                    # suprimida pela reserva, bloqueio da guarda de opt-out ou
                    # bloqueio da guarda de atendimento humano (TEC-179; as
                    # tres causas que o docstring de `OutboundPort` nomeia;
                    # `_bloqueado_por_optout_concorrente` e
                    # `_bloqueado_por_atendimento_humano_concorrente` abaixo
                    # sao quem distingue qual das tres foi).
                    if entregue:
                        # Fix de revisao final (Critical 1, TEC-140). Ja saiu
                        # pelo menos uma parte antes desta: tratar esta parte
                        # do MESMO jeito que a excecao acima -- para de tentar
                        # as proximas e marca a entrega como parcial -- e nao
                        # do jeito de antes desta card, que so olhava para
                        # excecao e deixava `entregue` virar True mesmo com uma
                        # parte suprimida em silencio. Sem isto, o recorder
                        # gravava o texto INTEIRO (incluindo a parte que nunca
                        # saiu) e os desfechos abaixo -- `reentrega_suprimida`,
                        # `bloqueado_por_optout` e `bloqueado_por_atendimento_humano`
                        # (o primeiro de alarme, os outros dois de guarda
                        # funcionando) -- nunca disparavam porque `entregue`
                        # ja estava True.
                        entrega_parcial = True
                        suprimida_apos_entrega = True
                        break
                    # Nada saiu ainda: comportamento de sempre, tenta a
                    # proxima parte. E o caso legitimo da retentativa do
                    # sweeper (comentario do topo do modulo): a parte com
                    # reserva de uma tentativa anterior devolve False aqui, e a
                    # parte sem reserva ainda tem a vez de sair.
                    continue
                partes_entregues.append(parte)
                entregue = True
            if entrega_parcial:
                texto = "\n\n".join(partes_entregues)
    except EnvioForaDaJanela as exc:
        log.warning(
            "outbound.fora_da_janela",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "expirado"
    except EnvioRecusado as exc:
        # `error` e nao `warning`: e o alerta que observa isto. O estado da
        # linha vira PROCESSED porque FAILED faria o sweeper rodar o turno
        # inteiro de novo -- inclusive a chamada paga ao modelo -- para um
        # payload que nunca vai ser aceito.
        log.error(
            "outbound.recusado_permanente",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "sem_resposta"

    if not entregue:
        if await _bloqueado_por_optout_concorrente(session_factory, message):
            # A guarda de `GuardedOutbound.send` (Task 4) barrou ESTE envio
            # porque outro turno da MESMA conversa registrou o opt-out entre
            # a checagem do topo deste turno (`esta_em_optout`, la em cima) e
            # este envio -- os dois turnos correram em paralelo sobre a mesma
            # conversa. A guarda funcionou exatamente como desenhada: nada
            # foi perdido, o lead so nao recebe porque pediu para nao
            # receber. Por isso este desfecho NAO pode se disfarcar de
            # "reentrega_suprimida" -- aquele nome e `error` porque e alarme
            # de DADO SUMIDO (ver o comentario logo abaixo), e aqui nao sumiu
            # nada. `info`, no nivel de uma checagem que funcionou como devia.
            log.info(
                "turno.bloqueado_por_optout_concorrente",
                channel=message.channel,
                message_id=str(message.id),
            )
            return "bloqueado_por_optout"

        if await _bloqueado_por_atendimento_humano_concorrente(session_factory, message):
            # Mesmo raciocinio do bloco de opt-out logo acima, terceira causa:
            # um corretor assumiu a conversa entre a checagem do topo deste
            # turno (a guarda barata, la em cima) e este envio. A guarda da
            # porta de saida barrou exatamente como desenhada -- nada sumiu,
            # o lead so nao recebe porque o atendimento e humano agora.
            log.info(
                "turno.bloqueado_por_atendimento_humano_concorrente",
                channel=message.channel,
                message_id=str(message.id),
            )
            return "bloqueado_por_atendimento_humano"

        # `send()` devolve False sem levantar quando a guarda (Task 3) suprime
        # uma reentrega: ja existe uma reserva em outbound_dispatches para este
        # (message_id, kind), de uma tentativa anterior. `_deliver` nunca foi
        # chamado agora -- entao `texto`, que veio de uma chamada nova ao
        # classificador (a de classificar ou a de desambiguar) ou, no caminho
        # de apresentacao da TEC-162, das legendas que ESTA tentativa montou,
        # pode nao ser o texto que o lead recebeu (ou nenhum texto pode ter
        # saido ainda, se a tentativa anterior tambem foi suprimida). Na
        # apresentacao o `texto` chega aqui vazio, porque nenhuma ficha
        # entrou. Gravar aqui seria o mesmo
        # risco de fala fantasma que a ordem grava-depois-de-entregar existe
        # para evitar, so que entrando por esta porta em vez de uma excecao:
        # exatamente por isso a checagem do retorno, e nao so do "nao
        # levantou", decide se grava.
        # `error`, pelo mesmo criterio do 4xx logo acima: a visibilidade vem
        # do nivel do log, nao do estado da linha, e o estado aqui e PROCESSED
        # -- terminal, o sweeper nunca reenfileira. Este desfecho e pelo menos
        # tao ruim quanto um 4xx: o lead pode nao ter recebido nada em
        # nenhuma das tentativas, e nao ha mais nenhuma. Se so o alerta de
        # `error` acorda alguem, isto tem de estar nele.
        log.error(
            "turno.reentrega_suprimida",
            channel=message.channel,
            message_id=str(message.id),
        )
        return "reentrega_suprimida"

    # Fix de revisao final (Critical 1, TEC-140). `entregue` e True aqui --
    # pelo menos uma parte saiu --, mas `suprimida_apos_entrega` (marcada no
    # laco acima) diz que uma parte POSTERIOR devolveu False sem levantar. Sao
    # as MESMAS tres causas do `if not entregue:` logo acima -- reentrega
    # suprimida pela reserva, a guarda de opt-out barrando um envio
    # concorrente, ou a guarda de atendimento humano barrando pelo mesmo
    # motivo (TEC-179) --, so que com uma parte ja entregue em vez de
    # nenhuma. O desfecho de alarme (`reentrega_suprimida`) ou os de
    # guarda-funcionou (`bloqueado_por_optout`, `bloqueado_por_atendimento_humano`)
    # tem de sobreviver do mesmo jeito: gravar "respondido" aqui esconderia
    # exatamente a corrida que `_bloqueado_por_optout_concorrente` e
    # `_bloqueado_por_atendimento_humano_concorrente` existem para nomear. O
    # recorder ainda roda logo abaixo -- `texto` ja foi cortado para so as
    # partes que sairam -- porque o que saiu e real e precisa ficar na
    # transcricao.
    desfecho_da_supressao_parcial: ResultadoDoTurno | None = None
    if suprimida_apos_entrega:
        if await _bloqueado_por_optout_concorrente(session_factory, message):
            log.info(
                "turno.bloqueado_por_optout_concorrente",
                channel=message.channel,
                message_id=str(message.id),
                entrega_parcial=True,
            )
            desfecho_da_supressao_parcial = "bloqueado_por_optout"
        elif await _bloqueado_por_atendimento_humano_concorrente(session_factory, message):
            log.info(
                "turno.bloqueado_por_atendimento_humano_concorrente",
                channel=message.channel,
                message_id=str(message.id),
                entrega_parcial=True,
            )
            desfecho_da_supressao_parcial = "bloqueado_por_atendimento_humano"
        else:
            log.error(
                "turno.reentrega_suprimida",
                channel=message.channel,
                message_id=str(message.id),
                entrega_parcial=True,
            )
            desfecho_da_supressao_parcial = "reentrega_suprimida"

    if desambiguando and not saida_bloqueada and not citacao_bloqueada:
        # Depois da entrega confirmada, nunca antes: ver `marcar_desambiguacao`.
        # A ordem entre esta gravacao e a da fala do agente nao e carregada --
        # as duas sao pos-entrega, e a guarda do outbound suprime qualquer
        # reentrega se o turno cair entre elas.
        #
        # `not saida_bloqueada` pelo mesmo motivo que o marcador espera a
        # entrega: um bloqueio de saida e indistinguivel de um 5xx da Meta no
        # unico aspecto que o marcador afirma -- a pergunta nao chegou. O que
        # chegou foi `TEXTO_NEUTRO_DE_SAIDA`, que nao pergunta nada. Marcar
        # aqui gastaria a unica pergunta do episodio numa entrega que nunca a
        # fez, e o lead ficaria em INDEFINIDA sem ter sido perguntado. O
        # `log.info` vai junto pela mesma razao: fora daqui ele afirmaria um
        # "desambiguou" que nao aconteceu.
        #
        # `not citacao_bloqueada` (TEC-161) pela mesma razao, terceiro caso: a
        # guarda de citacao substituiu o texto ANTES deste ponto, e no caminho
        # de desambiguacao esse texto era a pergunta do desambiguador. O que
        # chegou ao lead foi `TEXTO_DA_BUSCA_INCONCLUSIVA` (ou a ficha pura),
        # nao a pergunta -- marcar aqui seria o mesmo dano que `saida_bloqueada`
        # evita, so que pela guarda nova em vez da moderacao.
        async with session_factory() as session:
            await marcar_desambiguacao(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
            )
            await session.commit()
        log.info(
            "turno.desambiguou",
            channel=message.channel,
            message_id=str(message.id),
        )

    if not desambiguando and not saida_bloqueada and not citacao_bloqueada and not entrega_parcial:
        # A marca de `perguntou` (TEC-257) e, ao contrario da intencao e da
        # extracao gravadas la em cima, um fato sobre a NOSSA resposta -- e
        # por isso nao pode entrar naquele commit pre-entrega. Ela so pode ser
        # gravada depois da entrega confirmada, e so quando o texto de
        # `gerada` foi de fato o que saiu, pela mesma razao que
        # `marcar_desambiguacao` espera a entrega (ver o bloco acima): no
        # caminho de desambiguacao a resposta da chamada 1 foi descartada --
        # paga e nao entregue -- e o lead recebeu a pergunta do desambiguador,
        # nao a de `gerada`; com a saida bloqueada o lead recebeu
        # `TEXTO_NEUTRO_DE_SAIDA`, que tambem nao pergunta nada; com a
        # citacao bloqueada (TEC-161) o lead recebeu `TEXTO_DA_BUSCA_INCONCLUSIVA`
        # ou a ficha pura -- tambem nao a pergunta de `gerada`; e com a entrega
        # PARCIAL (Important 2 da revisao final da TEC-140) a pergunta de
        # `gerada`, se houve, pode estar inteira, pela metade ou nem ter
        # existido na parte que de fato saiu -- `entrega_parcial` nao diz ONDE
        # dentro do texto a quebra caiu, so que uma parte foi suprimida.
        # Decisao: suprimir a marca tambem aqui, e nao so nos tres casos de
        # cima. O custo de nao marcar quando a pergunta saiu inteira e perguntar
        # de novo depois -- irritante, mas reversivel. O custo de marcar quando
        # a pergunta ficou na parte suprimida e queimar, para sempre e em
        # silencio, a chance de perguntar aquele campo de verdade -- o MESMO
        # dano que os outros tres casos existem para evitar, e a uniao no SQL
        # nunca remove. Entre os dois, o repeticao e o lado barato.
        #
        # `marcar_perguntados`, e NAO `gravar_estado` de novo: regravar
        # `intencao`/`extracao` aqui e idempotente so contra si mesmo. Contra
        # a concorrencia real entre dois turnos da mesma conversa -- a razao
        # pela qual a uniao da marca foi para o SQL -- reescrever as colunas
        # de valor pos-entrega reabriria a corrida que a uniao fechou, so que
        # do lado errado: turno A grava extracao_A em t1, turno B grava
        # extracao_B em t2 > t1, e este commit pos-entrega de A aconteceria
        # em t3 > t2 e sobrescreveria a extracao mais nova de B com a mais
        # velha de A -- "mais novo vence" invertido, em silencio, para as
        # mesmas colunas que a marca foi desenhada para nao arriscar.
        # `marcar_perguntados` faz so o UPDATE da marca, ver o docstring la.
        async with session_factory() as session:
            await marcar_perguntados(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                intencao=gerada.intencao,
                extracao=gerada.extracao,
                perguntou=gerada.perguntou,
            )
            await session.commit()

    recorder = MessageRecorder(session_factory)
    await recorder.record_agent_message(
        conversation_key=message.conversation_key,
        channel=message.channel,
        text=texto,
        model=telemetria.modelo,
        subagent=subagente,
        tokens_in=telemetria.tokens_in,
        tokens_out=telemetria.tokens_out,
        # As duas colunas existem em `message_telemetry` desde a TEC-126 e
        # ficaram SEMPRE NULL: `record_agent_message` as aceitava como
        # parametro e nenhum chamador passava valor. A TEC-251 ligou o cache e
        # pos os contadores no LOG, o que nao alcanca consulta nenhuma -- o
        # painel de custo da TEC-191 continuaria sem custo de cache. Este e o
        # criterio da TEC-231 que faltava.
        cache_write_tokens=telemetria.cache_write,
        cache_read_tokens=telemetria.cache_read,
        latency_ms=telemetria.latency_ms,
        sender_external_id=message.recipient_external_id,
        recipient_external_id=message.conversation_key,
    )
    # `desfecho_da_supressao_parcial` (Critical 1) vence "respondido" quando
    # setado: o recorder acima ja gravou so o que saiu, mas o DESFECHO do
    # turno precisa continuar contando a historia de reentrega-suprimida,
    # opt-out-concorrente ou atendimento-humano-concorrente (TEC-179), e nao
    # a de "respondido" -- ver o comentario onde a variavel e definida.
    return desfecho_da_supressao_parcial or "respondido"


async def _bloqueado_por_optout_concorrente(
    session_factory: async_sessionmaker[AsyncSession], message: Message
) -> bool:
    """Distingue, entre as TRES causas de `outbound.send` devolver False sem
    levantar, a de reentrega suprimida da de opt-out concorrente.

    `OutboundPort.send` documenta que quem le so o retorno NAO consegue
    separar uma reentrega genuinamente suprimida (reserva duplicada em
    `outbound_dispatches`) de um envio que a guarda de opt-out barrou -- ver
    o docstring de `OutboundPort` e `GuardedOutbound.send`. Reconsultar
    `esta_em_optout` aqui, depois do `send()`, e o unico jeito de escolher a
    historia certa para o log: se o lead esta em opt-out agora, a guarda e a
    explicacao mais provavel para o False, e as duas causas nao podem levar
    o mesmo nivel de log nem o mesmo `ResultadoDoTurno` -- uma e alarme de
    dado sumido, a outra e a guarda funcionando como desenhada. A terceira
    causa (atendimento humano concorrente) e quem `_bloqueado_por_atendimento_humano_concorrente`,
    logo abaixo, distingue -- esta funcao nao a cobre, entao um `False` que
    sobra depois desta checagem NAO pode ser assumido como
    `reentrega_suprimida` sem checar a outra tambem.

    Best-effort de proposito: entre o `send()` e esta consulta o estado ainda
    pode mudar (uma reativacao, por exemplo). Isso so muda qual historia o
    log conta -- em nenhum dos dois casos ha texto reenviado ou dado perdido,
    entao um veredito ocasionalmente desatualizado aqui nao cria um risco
    novo de LGPD nem de duplicata.
    """
    async with session_factory() as sessao:
        return await esta_em_optout(
            sessao, channel=message.channel, conversation_key=message.conversation_key
        )


async def _bloqueado_por_atendimento_humano_concorrente(
    session_factory: async_sessionmaker[AsyncSession], message: Message
) -> bool:
    """A terceira causa de `outbound.send` devolver False sem levantar.

    `OutboundPort.send` documenta que o retorno booleano nao distingue
    reentrega suprimida, opt-out concorrente e atendimento humano
    concorrente. Sem esta consulta, um envio barrado porque o corretor
    assumiu no meio do turno seria logado como reentrega suprimida -- alarme
    de dado sumido onde a guarda so fez o trabalho dela.

    Best-effort pelo mesmo argumento de `_bloqueado_por_optout_concorrente`:
    entre o `send()` e esta consulta o estado ainda pode mudar (uma devolucao,
    por exemplo). Isso so muda qual historia o log conta -- em nenhum dos dois
    casos ha texto reenviado ou dado perdido.
    """
    async with session_factory() as sessao:
        return await esta_silenciada(
            sessao, channel=message.channel, conversation_key=message.conversation_key
        )


async def _entregar_texto_fixo(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    recorder_texto: str,
    kind: str = KIND_DA_RESPOSTA,
    subagent: str = SUBAGENTE_MODERACAO,
) -> ResultadoDoTurno:
    """Entrega um texto que nao veio do modelo, grava o que entregou e decide
    se prefixa a identificacao do assistente.

    Bloqueio nunca produz silencio: e a mesma escolha que a TEC-134 e a
    TEC-227 fizeram ao preferir a duplicata a perda, porque a duplicata e
    visivel e recuperavel e o silencio nao. `kind` tem default para preservar
    os chamadores existentes -- o texto de recusa de entrada usa o kind da
    resposta normal. A confirmacao de opt-out (TEC-182) passa o kind proprio,
    que e o unico que atravessa a guarda de opt-out da porta de saida depois
    do registro -- ver `GuardedOutbound.send`. `subagent` anda junto de
    `kind` pelo mesmo motivo: sem o parametro, toda entrega deste caminho --
    inclusive a confirmacao de opt-out, que nao e moderacao nenhuma -- gravava
    `message_telemetry.subagent = "moderacao"`, rotulando errado quem olhar a
    telemetria depois.
    """
    # A identificacao entra AQUI e nao em cada chamador: este e o funil das
    # tres trilhas que passam por `_entregar_texto_fixo` -- recusa da
    # moderacao de entrada, confirmacao de opt-out e laco de busca excedido.
    # (O texto neutro da moderacao de saida e a busca inconclusiva da citacao
    # bloqueada nao chamam esta funcao -- reatribuem `texto` e caem no bloco
    # de entrega compartilhado de `executar_turno`, que tem o ponto de
    # insercao proprio da Task 4.) Espalhada pelos chamadores, a proxima
    # trilha que surgisse sairia sem ela, e em silencio.
    if await e_conversa_nova(session_factory, message, agora=datetime.now(UTC)):
        recorder_texto = f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{recorder_texto}"

    try:
        entregue = await outbound.send(
            message.id,
            kind,
            {
                "para": message.conversation_key,
                "de": message.recipient_external_id,
                "texto": recorder_texto,
            },
        )
    except EnvioForaDaJanela as exc:
        # Separada de `EnvioRecusado`, e com o mesmo nivel e o mesmo desfecho
        # que o caminho principal ja dava a ela: janela de 24h fechada nao e
        # recusa permanente, e o `Literal` de `ResultadoDoTurno` existe para
        # essa distincao nao se perder. Classificar a mesma excecao de dois
        # jeitos conforme o ramo do codigo faria o alerta de `error` acordar
        # alguem por uma janela que so fechou, e faria "expirado" sumir das
        # contagens exatamente nas mensagens bloqueadas.
        log.warning(
            "outbound.fora_da_janela",
            channel=message.channel,
            message_id=str(message.id),
            reason=str(exc),
        )
        return "expirado"
    except EnvioRecusado as exc:
        log.error(
            "moderacao.texto_fixo_nao_entregue",
            message_id=str(message.id),
            reason=type(exc).__name__,
        )
        return "sem_resposta"

    if not entregue:
        # `kind != KIND_DA_CONFIRMACAO_DE_OPTOUT` guarda a chamada seguinte,
        # de proposito -- fix de revisao (Important). Quando ESTE chamador e
        # a propria confirmacao de opt-out, o turno acabou de rodar
        # `registrar_optout` antes de chegar aqui: `esta_em_optout` so pode
        # devolver True, sempre, por construcao -- nao porque a guarda barrou
        # por opt-out desta vez, mas porque o opt-out que o PROPRIO turno
        # gravou ainda esta la. E a guarda pula a checagem de opt-out para
        # este kind especifico (ver `GuardedOutbound.send`), entao um `False`
        # aqui so pode vir de reserva duplicada de verdade. Chamar o helper
        # mesmo assim relataria "bloqueado_por_optout" em `info` e engoliria
        # o "reentrega_suprimida" em `error` -- o alarme de dado sumido que
        # importa exatamente aqui, na confirmacao que apaga o unico rastro
        # visivel do pedido do lead se ela nao chegar.
        if kind != KIND_DA_CONFIRMACAO_DE_OPTOUT and await _bloqueado_por_optout_concorrente(
            session_factory, message
        ):
            # Mesmo raciocinio do bloco principal (ver
            # `turno.bloqueado_por_optout_concorrente` la em cima): a guarda
            # barrou este envio porque outro turno da mesma conversa
            # registrou o opt-out entre a checagem do topo e este envio. Nao
            # e "reentrega_suprimida" -- nada foi perdido.
            log.info(
                "turno.bloqueado_por_optout_concorrente",
                channel=message.channel,
                message_id=str(message.id),
            )
            return "bloqueado_por_optout"

        # Terceiro sitio do recheque (TEC-179) -- o brief da task so nomeava
        # os dois do bloco principal, mas este chamador tem o mesmo problema:
        # sem esta consulta, um corretor que assumiu a conversa ENTRE a
        # checagem do topo e este envio (recusa de entrada ou laco de busca
        # excedido) seria logado como reentrega suprimida -- o mesmo alarme
        # de dado sumido que o bloco principal existe para evitar.
        #
        # `kind != KIND_DA_CONFIRMACAO_DE_OPTOUT` guarda esta checagem tambem,
        # pela MESMA razao da linha equivalente para o opt-out, tres linhas
        # acima -- fix de revisao (Major, rodada 2). A guarda de atendimento
        # humano deixou de barrar TODO kind na emenda que abriu a excecao de
        # `KIND_DA_CONFIRMACAO_DE_OPTOUT` (ver `GuardedOutbound.send`): para
        # esse kind especifico, ela nao pode mais ser a causa de um `False`
        # aqui -- ela deixa passar. Sem esta excecao, a confirmacao de
        # opt-out retentada com a reserva ja existente E a conversa ainda
        # assumida seria atribuida a guarda errada: "bloqueado_por_atendimento_humano"
        # em `info`, quando a causa real e reserva duplicada --
        # "reentrega_suprimida" em `error`, o alarme de dado sumido que
        # importa exatamente aqui (mesmo raciocinio do comentario do opt-out,
        # tres linhas acima, so que para a guarda seguinte).
        if (
            kind != KIND_DA_CONFIRMACAO_DE_OPTOUT
            and await _bloqueado_por_atendimento_humano_concorrente(session_factory, message)
        ):
            log.info(
                "turno.bloqueado_por_atendimento_humano_concorrente",
                channel=message.channel,
                message_id=str(message.id),
            )
            return "bloqueado_por_atendimento_humano"

        # Mesmo raciocinio do bloco principal (ver `turno.reentrega_suprimida`
        # la embaixo): `send()` devolve False sem levantar quando a guarda ja
        # tem uma reserva para este (message_id, kind) de uma tentativa
        # anterior. Gravar aqui seria a mesma fala fantasma que aquele bloco
        # existe para evitar -- so que para o texto fixo do bloqueio.
        log.error(
            "turno.reentrega_suprimida",
            channel=message.channel,
            message_id=str(message.id),
        )
        return "reentrega_suprimida"

    recorder = MessageRecorder(session_factory)
    await recorder.record_agent_message(
        conversation_key=message.conversation_key,
        channel=message.channel,
        text=recorder_texto,
        # Nao houve chamada ao modelo neste caminho: o texto e constante. Ver
        # `MODELO_SEM_CHAMADA` em `app/config.py` -- com "" a telemetria
        # abriria um `telemetry.unknown_model` por entrada bloqueada.
        model=MODELO_SEM_CHAMADA,
        subagent=subagent,
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        sender_external_id=message.recipient_external_id,
        recipient_external_id=message.conversation_key,
    )
    return "respondido"


@dataclass(frozen=True, slots=True)
class ResultadoDaEntrega:
    """O que o laco de entrega de fato conseguiu. TEC-275."""

    legendas: tuple[str, ...]
    entregues: int
    suprimidas: int
    nao_entregues: tuple[uuid.UUID, ...]


async def _entregar_fichas(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    fichas: Sequence[Ficha],
    kinds: Sequence[str],
    apresentado_em: datetime,
    prosa: str | None,
    pular: frozenset[str] = frozenset(),
) -> ResultadoDaEntrega:
    """O laco que fala com a Meta, um por ficha. TEC-275.

    Extraido de `_apresentar` para ter UM laco, e nao dois: a continuacao
    (D4) entrega pelo mesmo caminho. Duas copias de um laco de entrega
    divergem -- o comentario de `KINDS_DA_RESPOSTA`, neste arquivo, registra o
    que isso ja custou.

    **`kinds` e paralelo a `fichas`**, e vem de quem chama porque e quem chama
    que sabe de onde ele veio: na apresentacao e `KINDS_DAS_FICHAS[:n]`; na
    continuacao e o kind PERSISTIDO de cada linha, que nao e reconstruivel
    pela posicao (D9).

    **`prosa` e `None` na continuacao.** A prosa viaja na primeira ficha (D5
    da TEC-162), e uma continuacao so existe se alguma ficha ja saiu -- entao
    a primeira ja saiu, e com ela a prosa.

    **`pular` sao os kinds que ja tem reserva.** A guarda de `send` suprimiria
    esses envios de qualquer jeito, mas pular explicitamente evita usar a
    reserva como controle de fluxo e evita contar como `suprimidas` algo que
    nem foi tentado.
    """
    legendas: list[str] = []
    # Os imoveis deste lote cuja ficha nao chegou ao lead -- recusa permanente
    # ou reserva ja existente. `conciliar_apresentacao` apaga a linha de cada
    # um: `ler_pendentes` tem de devolver exatamente o que ele viu, porque a
    # posicao N daquela lista e o ordinal N da resposta dele (D7).
    nao_entregues: list[uuid.UUID] = []
    entregues = suprimidas = 0

    for posicao, ficha in enumerate(fichas):
        kind = kinds[posicao]
        if kind in pular:
            continue

        # So a primeira leva a prosa (D5); as outras sao ficha pura.
        legenda = legenda_de(ficha, prefixo=prosa if posicao == 0 else None)
        payload: dict[str, Any] = {
            "para": message.conversation_key,
            "de": message.recipient_external_id,
        }
        if ficha.foto is None:
            # D13: sem foto, cai no caminho de texto que ja existe em vez de
            # ganhar um ramo proprio.
            payload["texto"] = legenda
        else:
            payload["tipo"] = "imagem"
            payload["link"] = ficha.foto
            payload["legenda"] = legenda

        try:
            entrou = await outbound.send(message.id, kind, payload)
        except EnvioForaDaJanela:
            # Repropaga, e esta clausula tem de vir ANTES da de baixo:
            # `EnvioForaDaJanela` HERDA de `EnvioRecusado` (port.py), entao um
            # `except EnvioRecusado` sozinho engoliria a janela de 24h
            # fechada: o turno devolveria "sem_resposta" (se todas as tres
            # batessem na janela) ou "respondido" com as fichas restantes (se
            # a janela fechasse no meio) em vez de "expirado", e o alerta que
            # observa janela fechada ficaria cego -- alem de o desfecho passar
            # a mentir sobre por que o lead nao recebeu. Janela fechada torna
            # a apresentacao inteira impossivel; nao e uma ficha ruim entre
            # tres.
            raise
        except EnvioRetentavel:
            # Fix de revisao (aceito do revisor). `EnvioRetentavel` nao herda
            # de `EnvioRecusado` nem de `EnvioForaDaJanela` (port.py) -- as
            # tres sao ramos distintos, entao esta clausula nao disputa MRO
            # com as duas de cima e a ordem entre elas nao muda qual excecao
            # cada uma pega. Propaga sem alterar o desfecho -- FAILED e o
            # sweeper reenfileira, exatamente como sem esta clausula --, e o
            # unico acrescimo e este log: sem ele, uma entrega PARCIAL (uma ou
            # duas fichas ja saidas quando o 5xx bateu nesta) fica invisivel
            # para quem opera ate a proxima tentativa reaparecer no mesmo
            # lugar. `entregues` conta so as que JA passaram por
            # `entregues += 1` abaixo -- a que estourou agora nao entra.
            log.error(
                "apresentacao.entrega_parcial_antes_de_falha_retentavel",
                channel=message.channel,
                message_id=str(message.id),
                kind=kind,
                entregues=entregues,
            )
            raise
        except EnvioRecusado as exc:
            # `error` pelo mesmo criterio do caminho de texto: o estado da
            # linha sera terminal e a visibilidade vem do nivel do log.
            log.error(
                "apresentacao.ficha_recusada",
                channel=message.channel,
                message_id=str(message.id),
                kind=kind,
                reason=str(exc),
            )
            # D8 da TEC-275: apaga AGORA, e nao no fim do laco. A conciliacao
            # la embaixo nao roda se o laco morrer numa ficha seguinte -- e
            # falha permanente MANTEM a reserva, entao a continuacao leria
            # esta recusa como entrega feita.
            await apagar_recomendacao_nao_entregue(
                session_factory,
                channel=message.channel,
                conversation_key=message.conversation_key,
                imovel_id=ficha.id,
                apresentado_em=apresentado_em,
            )
            nao_entregues.append(ficha.id)
            continue

        if not entrou:
            suprimidas += 1
            nao_entregues.append(ficha.id)
            continue

        entregues += 1
        legendas.append(legenda)

    return ResultadoDaEntrega(
        legendas=tuple(legendas),
        entregues=entregues,
        suprimidas=suprimidas,
        nao_entregues=tuple(nao_entregues),
    )


async def _apresentar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    candidatos: list[dict[str, Any]],
    scores: Mapping[uuid.UUID, float],
    criterios: Sequence[str],
    relaxou_preco: bool,
    relaxou_bairro: bool,
    prosa: str,
) -> tuple[str, int, int]:
    """Entrega ate 3 fichas e devolve (texto para gravar, entregues, suprimidas).

    O texto devolvido sao as legendas concatenadas -- o que o lead recebeu, e
    nao a prosa sozinha. Gravar so a prosa faria o turno seguinte reapresentar
    os mesmos imoveis por nao saber que ja os mostrou (D16).

    **Recusa permanente numa ficha nao interrompe as outras**, e a divergencia
    do caminho de texto unico e deliberada: a recusa provavel aqui e a Meta
    rejeitando a URL da midia, e uma foto ruim nao pode apagar dois imoveis
    bons (D10). `EnvioForaDaJanela` propaga, porque nesse caso a apresentacao
    inteira e impossivel e o desfecho e o mesmo de hoje.

    **Custo conhecido, e nao acidente: entrega parcial seguida de falha
    retentavel perde o registro do que ja saiu -- hoje so das fichas que esta
    passada chegou a entregar.** `EnvioRetentavel` e capturado logo abaixo, mas
    so para logar `entregues` e repropagar sem mudar nada -- o desfecho
    continua passando por cima de `record_agent_message`. Se a ficha 1 entregou
    e a 2 tomou um 5xx, a reserva da 2 e liberada e a linha vira FAILED com a
    legenda da ficha 1 nao gravada.

    **O que a varredura faz dali em diante mudou com a TEC-275**, e este
    paragrafo dizia o contrario ate ela: o sweeper NAO roda mais o turno
    inteiro de novo. O desvio no topo de `executar_turno` ve o lote com este
    `message_id` e devolve `_continuar_entrega`, que pula a posicao 1 por
    `pular` -- explicitamente, e nao por supressao da reserva sobrevivente --,
    entrega as fichas 2 e 3 e GRAVA as legendas delas. O buraco encolheu para
    a parte que saiu na passada que morreu: a legenda da ficha 1 continua sem
    ser gravada por nenhuma das duas, porque a passada 1 morreu antes do
    `record_agent_message` e a continuacao so grava o que ela propria
    entregou. E o mesmo dano da D16, menor -- a consequencia pratica e o turno
    seguinte poder reapresentar a ficha 1. O log torna o caso visivel para quem
    opera; nao torna o dado recuperavel -- a lacuna L1 do desenho registra o
    custo por extenso, e a correcao de verdade e a mesma citada abaixo.

    `EnvioForaDaJanela` depois de uma ficha ter entrado abre o mesmo buraco, e
    na continuacao ele e capturado la (desfecho "expirado"), nao aqui.

    Gravar as parciais antes de deixar a excecao sair mudaria o que um turno
    FAILED escreve na linha do tempo, no caminho de entrega que TODA conversa
    usa, e nenhum teste deste repo consegue reproduzir um 5xx no meio da
    apresentacao. A correcao de verdade e persistir o conjunto escolhido --
    a `Recomendacao` da TEC-163. **Isto e o que a linha abaixo faz** -- a
    lacuna L1 do desenho da TEC-162 fecha aqui: o conjunto escolhido
    sobrevive mesmo quando a ficha 2 toma um 5xx, porque ja esta gravado
    antes de a primeira ficha sair.

    **A gravacao acontece depois de `fichas_do_catalogo`, nao antes dela --
    e a ordem importa.** `Recomendacao.imovel_id` tem FK para `imoveis`, e o
    candidato fantasma que o comentario de `encontrados` descreve (D6: o
    imovel saiu do catalogo entre a busca e agora) violaria essa FK se a
    linha fosse tentada para ele. Um candidato assim tambem nunca chega a
    ser apresentado -- nenhuma ficha sai para ele --, entao gravar
    `Recomendacao` so para quem tem `Ficha` de verdade e correto tanto pela
    integridade referencial quanto pelo significado da RN-10.3 ("apresentado"
    exige ter sido apresentado). Isto continua sendo "antes da entrega": o
    laco que fala com a Meta, que e a parte que pode falhar em rede, so
    comeca depois.

    **Gravar antes cobra um preco, e `conciliar_apresentacao` e quem o paga.**
    Ter `Ficha` nao e ter ENTREGUE: o laco abaixo pode ter uma recusada (D10)
    ou encontrar reserva ja feita, e a linha daquele imovel ficaria dizendo
    que ele foi apresentado. Como a lista de pendentes e indexada por ORDINAL
    (D7), uma linha a mais desloca todas as seguintes -- "o segundo" do lead
    cai no imovel errado. Por isso a chamada no fim desta funcao, com o que o
    laco de fato entregou: ela apaga as linhas das fichas que nao sairam e
    fecha como `SEM_RESPOSTA` as pendentes que esta apresentacao supera.
    """
    escolhidos = candidatos[:MAX_IMOVEIS_POR_TURNO]
    ids = [uuid.UUID(c["imovel_id"]) for c in escolhidos]
    precos = {uuid.UUID(c["imovel_id"]): int(c["preco_centavos"]) for c in escolhidos}
    fichas = await fichas_do_catalogo(session_factory, ids=ids, precos=precos)
    encontrados = {ficha.id for ficha in fichas}

    if len(fichas) < len(escolhidos):
        # `imoveis_por_ids` derruba id sem linha, e a D6 chama isso de caminho
        # normal: o candidato veio do indice vetorial e o imovel pode ter saido
        # do catalogo entre a busca e agora. O que NAO e normal e isso passar
        # calado -- quando nenhuma ficha sobra, o loop abaixo nao roda, nenhum
        # `ficha_recusada` sai, e o turno inteiro vira silencio com a prosa ja
        # moderada jogada fora. Sem esta linha ninguem que opera consegue ver
        # isso acontecer.
        #
        # `error` quando sobrou ZERO, porque ai o lead nao recebe nada e nao ha
        # segunda tentativa; `warning` quando sobrou alguma, porque o lead
        # ainda recebe o que restou.
        #
        # `imovel_ids_faltantes` e fix de revisao (Minor): `pedidas` e
        # `encontradas` sao contagem, e quem opera precisa saber QUAL imovel
        # sumiu, nao so quantos. O id nao aparece em nenhuma outra linha deste
        # arquivo -- sem isto ele e irrecuperavel. `Ficha.id` (fix wave, mesma
        # entrega) e o que torna a diferenca calculavel aqui.
        faltantes = [i for i in ids if i not in encontrados]
        registrar = log.error if not fichas else log.warning
        registrar(
            "apresentacao.fichas_sumiram_do_catalogo",
            channel=message.channel,
            message_id=str(message.id),
            pedidas=len(escolhidos),
            encontradas=len(fichas),
            imovel_ids_faltantes=[str(i) for i in faltantes],
        )

    # RN-10.3, e a L1 desta funcao. Gravado ANTES do laco de entrega (a parte
    # que fala com a Meta e pode falhar em rede): o docstring acima registra
    # que uma falha parcial perde o conjunto escolhido e o turno seguinte
    # pode reapresentar os mesmos imoveis. Gravando aqui, o conjunto e
    # recuperavel mesmo quando a segunda ficha toma um 5xx -- que e a
    # correcao que aquele paragrafo prometeu. So os candidatos com `Ficha` de
    # verdade entram (`encontrados` acima): um candidato fantasma nunca foi
    # apresentado e nao pode ganhar linha que violaria a FK para `imoveis`.
    # `agora` num nome, e nao `datetime.now(UTC)` inline: e a marca deste lote,
    # e `conciliar_apresentacao` (no fim desta funcao) usa o MESMO valor para
    # separar as linhas que esta chamada acabou de inserir das que ja estavam
    # na conversa. Com duas leituras do relogio, a de la nao casaria nenhuma
    # linha e as fichas que nao sairam ficariam gravadas como apresentadas.
    agora = datetime.now(UTC)
    await gravar_recomendacoes(
        session_factory,
        channel=message.channel,
        conversation_key=message.conversation_key,
        candidatos=[c for c in escolhidos if uuid.UUID(c["imovel_id"]) in encontrados],
        scores=scores,
        criterios=criterios,
        message_id=message.id,
        kinds=KINDS_DAS_FICHAS[: len(fichas)],
        relaxou_preco=relaxou_preco,
        relaxou_bairro=relaxou_bairro,
        agora=agora,
    )

    entrega = await _entregar_fichas(
        session_factory,
        message=message,
        outbound=outbound,
        fichas=fichas,
        kinds=KINDS_DAS_FICHAS[: len(fichas)],
        apresentado_em=agora,
        prosa=prosa,
    )

    # Depois do laco, e nao antes: so aqui se sabe o que de fato saiu. Fecha as
    # pendentes que esta apresentacao supera e apaga as linhas das fichas que
    # nao chegaram -- as duas coisas que fazem `ler_pendentes` do proximo turno
    # devolver exatamente o que o lead viu, na ordem em que viu. Ver o
    # docstring de `conciliar_apresentacao`.
    #
    # Fora do alcance de `_entregar_fichas` de proposito -- e la, e nao aqui,
    # que fica o `try` do laco desde que a TEC-275 o extraiu. As duas excecoes
    # que ela repropaga (`EnvioForaDaJanela`, `EnvioRetentavel`) terminam o
    # turno sem apresentacao completa, e numa delas o sweeper reprocessa a
    # MESMA mensagem -- conciliar no meio apagaria linha de ficha que a
    # retentativa ainda vai entregar.
    await conciliar_apresentacao(
        session_factory,
        channel=message.channel,
        conversation_key=message.conversation_key,
        agora=agora,
        nao_entregues=entrega.nao_entregues,
        houve_entrega=entrega.entregues > 0,
    )

    return "\n\n".join(entrega.legendas), entrega.entregues, entrega.suprimidas
