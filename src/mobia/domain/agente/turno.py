import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import MODELO_SEM_CHAMADA, get_settings
from mobia.domain.agendamento.agendador import AgendadorDeAvisosPort
from mobia.domain.agendamento.conversa import (
    KIND_DO_AGENDAMENTO,
    SUBAGENTE_AGENDAMENTO,
)
from mobia.domain.agendamento.conversa import AceitouEspera as EsperaAceita
from mobia.domain.agendamento.conversa import Cancelou as AgendamentoCancelado
from mobia.domain.agendamento.conversa import Confirmou as AgendamentoConfirmado
from mobia.domain.agendamento.conversa import NadaAFazer as NadaAFazerNoAgendamento
from mobia.domain.agendamento.conversa import Ofereceu as AgendamentoOferecido
from mobia.domain.agendamento.conversa import OfereceuEspera as EsperaOferecida
from mobia.domain.agendamento.conversa import Perguntou as AgendamentoPerguntou
from mobia.domain.agendamento.conversa import (
    PresencaConfirmada as AgendamentoPresencaConfirmada,
)
from mobia.domain.agendamento.conversa import Reservou as AgendamentoReservado
from mobia.domain.agendamento.conversa import atender as atender_agendamento
from mobia.domain.agendamento.repositorio import AgendaPostgres
from mobia.domain.agente.apresentacao import Ficha, legenda_de
from mobia.domain.agente.citacao import divergencias_de
from mobia.domain.agente.classificador import (
    ClassificadorPort,
    LacoDeBuscaExcedido,
    ProvedorIndisponivel,
)
from mobia.domain.agente.desambiguacao import deve_desambiguar, intencao_efetiva
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
    texto_com_oferta,
)
from mobia.domain.agente.investidor import RespostaDoInvestidor
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
    zerar_fora_de_escopo,
)
from mobia.domain.agente.schemas import Intencao, PerguntaDeDesambiguacao, RespostaDoAgente
from mobia.domain.atendimento.repositorio import esta_silenciada
from mobia.domain.auditoria.vocabulario import ATOR_AGENTE, ATOR_SISTEMA
from mobia.domain.context.auditoria import CAUSA_MUDANCA_DE_INTENCAO
from mobia.domain.context.gatilhos import gatilhos_de
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import ContextoIrreducivel, montar_contexto
from mobia.domain.context.qualificacao import esta_qualificado, excedeu_o_teto
from mobia.domain.context.repositorio import (
    aplicar_mudanca_de_intencao,
    carimbar_qualificacao,
    contar_perguntas,
    gravar_estado,
    gravar_investidor,
    ler_estado,
    marcar_perguntados,
    perguntas_contaveis,
    registrar_recalculo,
)
from mobia.domain.context.resumo import ContadorPort, ResumidorPort
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.conversa.regras import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA, deve_encerrar
from mobia.domain.conversa.repositorio import (
    encerrar_conversa,
    reabrir_conversa,
    situacao_da_conversa,
)
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento
from mobia.domain.handoff.agendador import AgendadorDeResumoPort
from mobia.domain.handoff.repositorio import (
    HandoffRegistrado,
    registrar_handoff,
    tem_handoff_de_humano_aberto,
)
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho
from mobia.domain.humano.deteccao import (
    KIND_DO_PEDIDO_DE_HUMANO,
    SUBAGENTE_PEDIDO_DE_HUMANO,
    TEXTO_DO_PEDIDO_DE_HUMANO,
    TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO,
    dentro_da_janela_de_atendimento,
    pediu_humano,
)
from mobia.domain.identidade.absorcao import absorver_sessoes_vinculadas
from mobia.domain.messages.bloqueio import (
    moderar_entrada_e_marcar,
    registrar_bloqueio_de_saida,
    veredito_ja_registrado,
)
from mobia.domain.messages.canais import CANAL_WHATSAPP
from mobia.domain.messages.models import Message
from mobia.domain.messages.rajada import ha_fala_pendente_antes
from mobia.domain.messages.recorder import MessageRecorder
from mobia.domain.midia.confirmacao import (
    CONFIRMACOES_DE_MIDIA,
    KIND_DA_CONFIRMACAO_DE_MIDIA,
    SUBAGENTE_MIDIA,
    ja_confirmou_ha_pouco,
)
from mobia.domain.moderacao.port import (
    CATEGORIA_OUTRO,
    KIND_DA_RECUSA_DE_ENTRADA,
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
    Direcao,
    ModeracaoIndisponivel,
    ModeradorPort,
    Veredito,
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
from mobia.domain.outbound.kinds import KIND_DA_RESPOSTA, KINDS_DA_RESPOSTA
from mobia.domain.outbound.port import (
    KINDS_QUE_FURAM_AS_GUARDAS,
    EnvioForaDaJanela,
    EnvioRecusado,
    EnvioRetentavel,
    OutboundPort,
)
from mobia.domain.outbound.repositorio import kinds_reservados, reservado_em
from mobia.domain.titular.deteccao import (
    KIND_DA_CONFIRMACAO_DE_TITULAR,
    KIND_DA_PERGUNTA_DE_ELIMINACAO,
    TEXTO_DA_CONFIRMACAO_DE_ACESSO,
    TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO,
    TEXTO_DA_PERGUNTA_DE_ELIMINACAO,
    e_palavra_de_confirmacao,
    pedido_de_titular,
)
from mobia.domain.titular.repositorio import (
    pergunta_de_eliminacao_pendente,
    registrar_solicitacao,
)
from mobia.domain.titular.vocabulario import OrigemDaSolicitacao, TipoDeSolicitacao
from mobia.infra.crypto import aad_de, decrypt
from mobia.infra.embeddings import embedar_do_turno

log = structlog.get_logger(__name__)

# `KIND_DA_RESPOSTA` e `KINDS_DA_RESPOSTA` mudaram para
# `domain/outbound/kinds.py` na TEC-273: `port.py` passou a precisar deles
# para liberar as reservas irmas, e `domain/outbound` nao pode importar de
# `domain/agente`. Quem importava daqui continua funcionando -- o nome fica no
# namespace deste modulo por causa do import acima.

# TEC-162. Kinds fixos POR POSICAO, e nao derivados do id do imovel: o
# UNIQUE (message_id, kind) de `outbound_dispatches` precisa de um valor que
# a retentativa reproduza. Um kind com o id dentro deixaria de colidir assim
# que a retentativa escolhesse outro imovel, e a idempotencia sumiria
# justamente no caso em que ela importa -- ver a D9 e a L1 do desenho.
KINDS_DAS_FICHAS = ("ficha_1", "ficha_2", "ficha_3")

# RN-10.2: maximo de 3 por turno, mesmo quando a busca devolveu 10.
MAX_IMOVEIS_POR_TURNO = len(KINDS_DAS_FICHAS)

# TEC-265, D4. O lead nunca fica em silencio porque o teto do laco funcionou.
# O aviso do erro irrecuperavel e o kind dele. Nasceram em
# `workers/jobs/process_message.py` (TEC-174), que os usa na quinta falha, e
# vieram para ca na TEC-209 porque o turno passou a usa-los tambem -- quando a
# cadeia do provedor esgota (`_degradar_por_provedor`) -- e `process_message`
# importa este modulo, e nao o contrario. O MESMO kind nos dois caminhos e de
# proposito: se os dois dispararem para a mesma mensagem, a reserva em
# `outbound_dispatches` deixa o lead receber o aviso uma vez so.
#
# String fixa, sem id dentro, pelo mesmo argumento de idempotencia que os KINDs
# deste modulo registram: kind que muda entre retentativas perde a dedup da
# reserva justamente quando ela importa. A coluna e String(32); isto tem 13.
KIND_DO_AVISO_DE_ERRO = "aviso_de_erro"

# Nao promete prazo nem explica a falha: o lead nao tem o que fazer com
# "timeout do provedor", e prometer horario e promessa que o sistema nao tem
# como cumprir -- o turno nao oferece nem reserva horario. E nao promete um
# AVISO que o sistema nao pratica. "Passei sua conversa para" descreve o que
# de fato ocorre (a linha PENDENTE em `handoffs`, que e por onde o time
# humano pega o caso) sem afirmar que alguem do outro lado ja foi avisado.
# E a "mensagem honesta de espera" da RNF-27 (TEC-209, D3).
TEXTO_DO_AVISO_DE_ERRO = (
    "Tive um problema técnico aqui e não consegui seguir. "
    "Passei sua conversa para um corretor assumir."
)

TEXTO_DA_BUSCA_INCONCLUSIVA = (
    "Deixa eu confirmar algumas coisas com um corretor para não te passar "
    "informação errada. Já te retorno com as opções."
)

# Regra 4 da card e cenario 2 do Gherkin. TEC-160, D14.
#
# **Constante nova, e nao reuso de TEXTO_DA_BUSCA_INCONCLUSIVA.** Aquele
# promete "já te retorno com as opções", e aqui nao ha opcao nenhuma para
# retornar -- seria o sistema prometendo o que sabe que nao tem. O laco
# excedido e a citacao bloqueada podem prometer porque nos dois casos os
# imoveis existem e o problema e nosso.
#
# A card manda oferecer "a lista de espera ou o corretor", e poe a lista de
# espera fora de escopo (E5). Este texto entrega a metade disponivel; quando o
# E5 existir, e aqui que se volta.
TEXTO_SEM_RESULTADO_APOS_AMPLIAR = (
    "Procurei também um pouco além do que você pediu e mesmo assim não achei "
    "nada que valha a pena te mostrar agora. Quer que um corretor olhe isso "
    "com você?"
)

# TEC-149, RN-05.5. Substitui a prosa do modelo no turno em que a pergunta
# seguinte passaria do teto -- o caso comum, e nao a regra sem excecao: a
# substituicao so acontece com `not desambiguando` e `not saida_bloqueada`,
# e o encaminhamento por intencao da TEC-137,
# `TEXTO_DA_BUSCA_INCONCLUSIVA`, `TEXTO_SEM_RESULTADO_APOS_AMPLIAR` e a
# despedida do encerramento da TEC-138 ainda podem sobrescrever `texto`
# depois. Ver o `if teto_da_entrega and not
# desambiguando and not saida_bloqueada:` mais abaixo, onde as duas guardas
# e a ordem de precedencia estao escritas por extenso. (`teto_da_entrega`, e
# nao `teto_do_handoff`: desde a TEC-153 sao dois -- um decide o handoff a partir
# da chamada 1, o outro decide esta substituicao a partir do texto ENTREGUE,
# que na virada do investidor nao e o mesmo.)
#
# **Nao promete que alguem foi avisado NEM que alguem vai procurar o lead, e
# isso e deliberado.** Desde a TEC-280 o e-mail entrega, por SMTP, mas aceito
# pelo servidor nao e o mesmo que lido por um corretor, e o whatsapp ao
# corretor (TEC-281) continua so registrando -- o que o sistema garante e a
# fila, e e so a fila que o texto afirma. A TEC-174 escreveu "ja avisei um
# corretor" e teve de reescrever o texto depois, porque nada notificava.
#
# **Ate a TEC-286 esta constante terminava em "Pode deixar que ele entra em
# contato", e escapou de tres revisoes** -- a guarda de teste daquela epoca
# barrava as palavras `avisei`/`avisamos`/`avisado`, e esta frase promete a
# mesma coisa sem usar nenhuma das tres. Quem guarda isto hoje e
# `tests/unit/test_promessa_ao_lead.py`, que barra a frase e roda sobre todo
# literal ao lead.
#
# **O hedge tem condicao de saida, e ela e uma so: a TEC-281.** Quando o
# whatsapp ao corretor entregar, um aviso de fato chega a quem vai atender, e
# o texto pode voltar a ser firme. Enquanto ela estiver aberta, "entra em
# contato" aqui e promessa de terceiro que este sistema nao controla.
#
# A redacao do fecho e a MESMA de TEXTO_DO_ENCAMINHAMENTO_DE_VENDA, de
# proposito: duas redacoes para o mesmo fato seriam duas coisas para manter em
# sincronia, e este arquivo ja usa esse argumento em SUFIXO_FORA_DA_JANELA.
#
# Sem kind proprio, ao contrario de KIND_DO_CRITERIO_AMPLIADO: aquele e
# mensagem ADICIONAL e precisa de kind distinto por causa do
# UNIQUE (message_id, kind). Isto aqui e substituicao, como o
# TEXTO_NEUTRO_DE_SAIDA da moderacao -- nao ha segunda mensagem com que
# colidir.
TEXTO_DO_LIMITE_DE_PERGUNTAS = (
    "Já perguntei bastante e não quero virar interrogatório. "
    "Prefiro passar para um corretor, que vai conseguir te ajudar melhor daqui. "
    "Já coloquei sua conversa na fila deles."
)

# RN-03.4 (TEC-137). Substituem a prosa do modelo quando a intencao e
# VENDER_IMOVEL ou SUPORTE_CONTRATO -- duas conversas que nao sao trabalho de
# SDR e que o `_GATILHO_DA_INTENCAO` ja manda para a fila humana desde a
# TEC-174. O que faltava era o lead saber disso: ate aqui ele recebia a prosa
# do modelo, que podia conter a pergunta de qualificacao de COMPRADOR que a
# regra proibe.
#
# **Dois textos e nao um.** Quem quer vender um imovel e quem tem duvida sobre
# contrato vigente vao para filas diferentes (`venda-imovel` e
# `suporte-contrato` em ETIQUETA_DE), e a segunda pessoa JA e cliente. "Vou
# passar para um corretor que te ajuda a encontrar" serviria mal a ela.
#
# **Nenhum dos dois promete que alguem foi avisado**, pela razao que o
# comentario de TEXTO_DO_LIMITE_DE_PERGUNTAS acima ja registra e que
# `notificacao/envio.py` proibe nominalmente: desde a TEC-280 o e-mail
# entrega, mas aceito pelo servidor nao e o mesmo que lido por um corretor, e
# o whatsapp ainda so registra enquanto a TEC-281 estiver aberta -- nenhum
# dos dois garante que alguem viu ou vai responder. A TEC-174 escreveu
# "ja avisei um corretor" e teve de reescrever; a TEC-143 reintroduziu a frase
# e a revisao final a pegou. `test_textos_do_encaminhamento.py` guarda isso.
#
# Sem kind proprio, como TEXTO_DO_LIMITE_DE_PERGUNTAS: isto e substituicao em
# lugar, nao mensagem adicional, entao nao ha segunda mensagem com que colidir
# na UNIQUE (message_id, kind).
TEXTO_DO_ENCAMINHAMENTO_DE_VENDA = (
    "Que bom que pensou na gente para vender seu imóvel! Isso quem cuida é um "
    "corretor da equipe, não eu — já coloquei sua conversa na fila deles."
)

TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE = (
    "Dúvida de contrato é com a equipe, não comigo — já coloquei sua conversa "
    "na fila deles para te responderem com segurança."
)

# Acrescentado aos dois textos acima quando o pedido chega fora da janela de
# atendimento. As horas vem de `Settings`, e nao de um literal: a regra e do
# repo e nao depende de nenhuma divergencia especifica.
#
# **A divergencia que este comentario registrava foi fechada (TEC-285).** Ate
# ela, o Gherkin da TEC-137 dizia "das 9h as 19h" e a janela real era 9h-18h --
# citar o numero da card faria o texto mentir. A TEC-285 subiu a janela para
# segunda-a-sabado 9h-19h, e os dois numeros passaram a bater.
#
# **Os dias sao literais, e as horas nao.** Ver `_DOMINGO` em
# `domain/humano/deteccao.py`: os dias sao regra em codigo, e mudar a regra e
# mudar este texto junto.
#
# **"pode demorar até", e nao "vem".** O whatsapp ao corretor (TEC-281)
# continua so registrando, e mesmo o e-mail (TEC-280, que ja entrega por
# SMTP) so garante que o servidor aceitou, nao que uma PESSOA abriu a fila e
# respondeu -- marcar hora seria prometer o que o sistema nao controla. Nao e a frase
# banida de "alguem foi avisado" -- e a vizinha dela, e este repo ja recuou
# duas vezes da primeira. A redacao espelha de proposito a irma que a TEC-143
# escreveu ontem para a MESMA situacao, em `domain/humano/deteccao.py`:
# `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO` ja dizia "pode demorar até o
# próximo horário". Duas redacoes para o mesmo fato seriam duas coisas para
# manter em sincronia.
SUFIXO_FORA_DA_JANELA = (
    " O atendimento é de segunda a sábado, das {inicio}h às {fim}h, "
    "então a resposta pode demorar até o próximo horário."
)

# Espelha `_GATILHO_DA_INTENCAO` deliberadamente: as duas intencoes que vao
# para a fila humana sao as mesmas que recebem texto proprio. Sao dois mapas e
# nao um porque respondem perguntas diferentes -- um diz "qual gatilho de
# handoff", o outro "qual texto para o lead" --, e um dicionario de tuplas
# obrigaria todo leitor de um dos lados a entender o outro.
_TEXTO_DO_ENCAMINHAMENTO = {
    Intencao.VENDER_IMOVEL: TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
    Intencao.SUPORTE_CONTRATO: TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
}

# RN-03.5 (TEC-138). Substitui a prosa do modelo na TERCEIRA mensagem fora de
# escopo seguida, e e a ultima coisa que o lead ouve antes dos 30 dias de
# silencio da D1 -- **exceto quando a moderacao de saida barra o turno**, caso
# em que quem sai e `TEXTO_NEUTRO_DE_SAIDA` e a conversa fecha atras dele
# assim mesmo (fix da revisao final, Important 2; ver as duas guardas la
# embaixo).
#
# **Nao promete que alguem foi avisado**, pela razao que o comentario de
# TEXTO_DO_LIMITE_DE_PERGUNTAS acima ja registra e que `notificacao/envio.py`
# proibe nominalmente. Aqui a razao e ainda mais direta que nas outras
# trilhas -- nesta nao ha corretor nenhum: a conversa nao vai para fila, ela
# para.
#
# **Diz que a porta continua aberta E diz QUANDO, e o "quando" nao e enfeite**
# (ruling R8 da revisao). A primeira versao deste texto terminava em "é só me
# chamar de novo", que se le como AGORA -- e a guarda do topo cala tambem a
# mensagem dentro do escopo, entao o lead que aceitasse o convite no dia
# seguinte nao receberia nada. Era prosa de produto prometendo o que o sistema
# nao faz, a mesma medida que a TEC-137 aplicou ao sufixo de fora do horario.
# A redacao de hoje adia o convite para depois da janela, que e quando ele
# passa a ser verdade.
#
# O numero sai de `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA` e nao de um literal,
# pelo mesmo motivo que `SUFIXO_FORA_DA_JANELA` formata as horas a partir de
# `Settings`: o texto tem de continuar verdadeiro se alguem mexer na janela, e
# um "30" escrito a mao aqui viraria mentira em silencio. A MESMA constante
# que `situacao_da_conversa` usa para medir a janela -- nao ha como as duas
# divergirem.
#
# Continua **sem prometer que alguem foi avisado** e sem mencionar corretor:
# nesta trilha nao ha fila nem pessoa alguma para procurar o lead, e "volto a
# responder" fala do agente, que e quem de fato volta.
#
# Sem kind proprio, como TEXTO_DO_LIMITE_DE_PERGUNTAS: e substituicao em
# lugar, nao mensagem adicional, entao nao ha segunda mensagem com que colidir
# na UNIQUE (message_id, kind).
TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO = (
    "Acho que não vou conseguir ajudar com isso — aqui eu falo de imóveis. "
    f"Vou parar por aqui: volto a responder daqui a {DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA} dias, "
    "e aí é só me chamar se precisar procurar, alugar ou anunciar um imóvel."
)

# RN-09.3 / CA-09.3, e a regra "avisado ... e EM QUE" da card. TEC-160, D11.
#
# Tres variantes e nao uma constante: quando so o preco foi relaxado (o lead
# nao deu regiao), dizer "incluí bairros vizinhos" e informacao falsa sobre o
# que o sistema fez -- num aviso cujo proposito inteiro e ser explicito.
#
# Nenhum numero, de proposito: o teto ampliado e conta nossa, e nao fato do
# banco. Os nomes dos bairros tambem ficam de fora, e essa e a escolha mais
# discutivel -- nome de bairro E fato do catalogo. Ficam fora porque a lista e
# variavel (a Trindade amplia para tres, o Itacorubi para quatro) e uma
# mensagem que cresce com o grau do no e uma mensagem cujo pior caso ninguem
# mediu. O lead ve o bairro na ficha, que e onde ele importa.
_ABERTURA_DA_AMPLIACAO = "Não achei nada exatamente no que você pediu, então "

TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO = (
    f"{_ABERTURA_DA_AMPLIACAO}ampliei um pouco a busca: valor um pouco acima e "
    "bairros vizinhos. Veja se algum destes serve."
)
TEXTO_DO_CRITERIO_AMPLIADO_PRECO = (
    f"{_ABERTURA_DA_AMPLIACAO}ampliei um pouco o valor. Veja se algum destes serve."
)
TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO = (
    f"{_ABERTURA_DA_AMPLIACAO}incluí bairros vizinhos. Veja se algum destes serve."
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
# que so passou a existir na TEC-174. O lead segue recebendo resposta neste
# turno -- desde a TEC-137 o texto fixo de `_TEXTO_DO_ENCAMINHAMENTO`, nao
# mais a prosa do modelo -- e isso nao e a mesma coisa que ser silenciado:
# silenciar e a RN-16.4, que e a TEC-179, e esta card nao faz isso.
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
    doc do modulo (acima) existe para evitar: dizer "incluí bairros vizinhos"
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

TEXTO_DO_FILTRO_AJUSTADO = "Tirei {bairros} da busca, que você já descartou."


def aviso_de_ajuste(bairros: Sequence[str]) -> str:
    """O aviso da RN-10.4, com os NOMES dos bairros que saem da busca. D15.

    **Diverge de proposito de `aviso_de_ampliacao` (D11 da TEC-160), que NAO
    nomeia bairro nenhum.** La os bairros incluidos sao escolha NOSSA (a
    tabela de adjacencia), e calar o nome evita uma mensagem cujo tamanho
    cresce com o grau do no, sem teto medido. Aqui os bairros sao os que o
    LEAD rejeitou -- duas ou tres vezes, nunca a arvore de adjacencia inteira
    --, e nomea-los e a propria confirmacao de que ele foi ouvido: "Tirei o
    Campeche da busca, que você descartou" faz um trabalho que "ajustei o
    filtro" nao faz.

    `bairros` chega na forma dobrada (`recomendacao.bairros_a_excluir`,
    minuscula e sem acento -- ver `texto.dobrar`); `.title()` basta para virar
    nome legivel, e o dobrado ja garante ASCII -- nao ha acento para perder
    na volta.

    **A moldura tem acento e o nome nao** (TEC-267, L2): o lead le "Tirei
    Aclimacao da busca, que você já descartou". Restaurar a forma de exibicao
    exigiria carrega-la ao lado da chave dobrada por toda a cadeia de
    recomendacao, ou consultar o catalogo aqui dentro -- as duas
    desproporcionais, e a segunda errada. Lacuna declarada, nao esquecimento.

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
SUBAGENTE_INVESTIDOR = "investidor"
SUBAGENTE_MODERACAO = "moderacao"
SUBAGENTE_OPTOUT = "optout"
SUBAGENTE_TITULAR = "titular"

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
    # A TEC-143 acrescentou este. Nao reuse "atendimento_humano": aquele e o
    # turno que nao fez nada porque um corretor JA tinha assumido; este e o
    # turno em que o LEAD pediu e o handoff acabou de nascer. Duas historias
    # com donos diferentes -- mesmo criterio que o comentario acima aplica aos
    # tres do opt-out.
    "pedido_de_humano",
    # A TEC-138 (RN-03.5) acrescentou este: o turno que nao fez nada porque a
    # conversa esta ENCERRADA por escopo e a janela de 30 dias ainda corre.
    #
    # Nao reuse "silenciado" nem "atendimento_humano", pelo mesmo criterio que
    # os comentarios acima aplicam entre si: aquele ja significa opt-out e este
    # significa que um corretor assumiu. Somar o terceiro aos dois tornaria
    # impossivel saber, no log, se o agente calou por pedido do lead, por
    # decisao de uma pessoa ou por politica automatica de escopo -- tres
    # historias com donos diferentes, e so a ultima e nossa para revisar.
    #
    # E nao ha valor irmao de "bloqueado_por_..." aqui: esta politica nao tem
    # guarda na porta de saida. O encerramento e a substituicao acontecem no
    # MESMO turno, entao nao existe a corrida que os outros dois nomeiam.
    "fora_de_escopo",
    # A TEC-132 (revisao final, I2) acrescentou este: a midia sem texto cujo
    # turno nao mandou nada porque a ultima fala do agente ja foi a
    # confirmacao de midia, ha menos de `JANELA_DA_CONFIRMACAO_DE_MIDIA`.
    # Nao reuse "silenciado" nem "reentrega_suprimida": nao houve pedido de
    # silencio, e nada foi perdido -- o lead ja recebeu a confirmacao que
    # cobre esta midia.
    "midia_ja_confirmada",
    # A TEC-371 acrescentou os dois abaixo, separados pelo mesmo criterio que
    # os comentarios acima aplicam entre si.
    #
    # "agendamento_oferecido" e o turno que respondeu sobre horario -- ofertou
    # janelas, reservou a escolhida, avisou que o horario caiu ou que a
    # reserva venceu. Nao reuse "respondido": aquele significa que o MODELO
    # respondeu, e este turno nao chegou a chama-lo; somar os dois tornaria
    # impossivel medir quanto da conversa o agendamento atende sozinho.
    #
    # "agendamento_confirmado" e o turno que gravou o agendamento e nao mandou
    # texto nenhum, porque quem manda a confirmacao e o job da RN-12.1 (D6).
    # Nao reuse "sem_resposta": aquele e ausencia de coisa a dizer, e aqui a
    # coisa a dizer existe e sai por outro caminho -- se um dia o job parar de
    # sair, e este contador que denuncia o silencio.
    "agendamento_oferecido",
    "agendamento_confirmado",
    # A TEC-372 acrescentou os dois abaixo, pelo mesmo criterio.
    #
    # "presenca_confirmada" e o turno em que o lead respondeu ao lembrete
    # dizendo que vai. Nao reuse "agendamento_confirmado": aquele e a
    # visita nascendo, e este e o lead prometendo aparecer numa que ja
    # existia -- duas historias, e so a segunda diz algo sobre no-show.
    #
    # "agendamento_cancelado" e a visita caindo por pedido do lead. Nao
    # reuse "opt_out" nem "silenciado": ninguem pediu silencio, e o
    # agente respondeu normalmente.
    "presenca_confirmada",
    "agendamento_cancelado",
    # A TEC-169 acrescentou os dois abaixo, pelo mesmo criterio.
    #
    # "espera_oferecida" e o turno que bateu numa semana sem horario livre e
    # ofereceu a fila. Nao reuse "agendamento_oferecido": aquele significa que
    # houve horario a oferecer, e este e o oposto -- somar os dois apagaria
    # exatamente o numero que justifica a RN-11.5 existir, que e quantos leads
    # pedem visita e nao encontram vaga.
    #
    # "espera_aceita" e o lead entrando na fila, com o handoff aberto na mesma
    # transacao. Nao reuse "espera_oferecida": a distancia entre os dois e a
    # taxa de aceite da oferta, e ela e o que diz se o texto da D5 funciona.
    "espera_oferecida",
    "espera_aceita",
    # A TEC-209 acrescentou este: a cadeia da chamada principal esgotou -- o
    # primario com as retentativas e o secundario --, e o turno entregou a
    # espera honesta com handoff na mesma passada. Nao reuse "sem_resposta":
    # aquele e o envio que falhou; este e o modelo que nao respondeu, e e o
    # numero que diz quanto tempo o provedor esteve fora.
    "provedor_indisponivel",
    # A TEC-207 acrescentou este: o turno que registrou um pedido de titular
    # (acesso, ou eliminacao ja confirmada, D3) e confirmou. Nao reuse
    # "opt_out", mesmo quando a eliminacao grava opt-out junto: quantos
    # pedidos de titular chegam pelo WhatsApp e um numero que o produto quer
    # ler no log separado de quantos leads so pediram para sair, e soma-los o
    # apagaria.
    "pedido_de_titular",
    # E este, da revisao final da mesma card (C2): o primeiro passo da
    # eliminacao, em que o turno so perguntou se o lead quer mesmo apagar e
    # nao registrou nada. Nao reuse "pedido_de_titular": a distancia entre os
    # dois e quantas perguntas nao viraram pedido -- as correcoes de cadastro
    # que os dois passos existem para nao transformar em eliminacao.
    "confirmacao_de_titular_pedida",
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
    except Exception as falha:
        # `motivo` alem do traceback: desde a TEC-293 o traceback leva pilha e
        # tipo, nunca a mensagem, e aqui a mensagem e o diagnostico -- numa
        # queda do Redis o que se quer ler e `Error 111 connecting to
        # localhost:6379`. O texto e seguro neste ponto porque a unica coisa
        # que esta chamada passa adiante e `registro.id`, um UUID gerado por
        # este projeto: nao ha entrada externa para a excecao ecoar. Mesmo
        # argumento da D3 da TEC-292.
        log.warning(
            "resumo_handoff.nao_agendado",
            handoff_id=str(registro.id),
            motivo=str(falha),
            exc_info=True,
        )


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

    **Le o estado de qualificacao so para escolher a FORMA da ficha (TEC-154,
    D7)** -- se a trilha e a do investidor, a ficha sai com os indicadores de
    rentabilidade; senao, sai sem. A leitura nunca muda O QUE e entregue: o
    lote, os ids e os precos ja vieram fixados pela passada anterior.
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

    # TEC-154, D7. Esta funcao roda ANTES de `montar_contexto` e por isso nao
    # tem `contexto.estado` nem `ja_e_investidor` -- e a mesma cegueira que o
    # comentario de `record_agent_message`, mais abaixo, declara para a
    # telemetria. Ali a consequencia so aparece para quem opera; aqui
    # apareceria para o LEAD, que receberia a ficha 1 com yield e as fichas 2
    # e 3 sem. Uma consulta fecha isso.
    #
    # **Custo declarado: o estado lido e o de AGORA, nao o do instante da
    # apresentacao original.** Na maioria dos casos os dois coincidem, mas nao
    # pelo motivo que este comentario chegou a afirmar (que o turno que
    # moveria a intencao e o mesmo que esta sendo continuado): o turno
    # continuado GRAVA o estado antes de apresentar (`gravar_estado`, por
    # volta da linha 1173, roda antes de `_apresentar`, por volta da 1889, no
    # mesmo turno) -- ele e justamente o turno capaz de produzir a
    # divergencia, e nao o que a impede.
    #
    # A borda real e estreita: um turno de investidor (`ja_e_investidor` ja
    # travado desde o inicio do turno) em que o subagente devolve uma
    # `intencao` definida e NAO-INVESTIMENTO -- o schema aceita qualquer
    # membro do enum -- e que TAMBEM apresenta. A ficha 1 sai com o bloco
    # (decidido por `ja_e_investidor`, ja travado, nao pela `intencao` nova),
    # o estado grava a intencao nova antes do commit, e as fichas 2 e 3 desta
    # mesma apresentacao, entregues por uma continuacao que rele o estado ja
    # trocado, saem sem bloco. Exige a virada de intencao MAIS uma entrega
    # parcial no mesmo turno.
    #
    # **A direcao inversa (ficha 1 sem bloco, fichas 2 e 3 com) e
    # inalcancavel.** `gravar_intencao` sobrescreve `conversation_intent` a
    # cada turno com a MESMA `gerada.intencao` que `gravar_estado` grava no
    # estado, entao `anterior.intencao == INVESTIMENTO` (o `anterior` lido
    # logo abaixo) implica `ja_e_investidor` no turno seguinte. Para a
    # continuacao reler INVESTIMENTO, este turno teria de gravar
    # `gerada.intencao == INVESTIMENTO` -- e nesse caso `virou_investidor` (ou
    # `ja_e_investidor`, se ja fosse) ja forca o bloco na propria ficha 1, o
    # que fecha exatamente a direcao inversa. A alternativa exata para fechar
    # a borda estreita que sobra -- gravar a trilha na linha de
    # `recomendacoes` -- custa coluna, migration e mais uma tabela no
    # TRUNCATE de todo teste que toca banco.
    async with session_factory() as session:
        estado = await ler_estado(session, message.channel, message.conversation_key)
    # Contra `.value` porque a coluna e str, e nao o enum -- mesma comparacao
    # que `ja_e_investidor` faz em `executar_turno`.
    investidor = estado is not None and estado.intencao == Intencao.INVESTIMENTO.value

    fichas = await fichas_do_catalogo(
        session_factory, ids=ids, precos=precos, com_rentabilidade=investidor
    )
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
            # estas fichas saem da busca da passada anterior. Um rotulo proprio
            # partiria a MESMA apresentacao em dois valores de `subagent` para
            # quem le a telemetria depois.
            #
            # **Mas este rotulo nao distingue as duas buscas que podem te-las
            # produzido, e desde a TEC-153 sao duas.** A trilha do investidor
            # tambem busca e apresenta, entao a passada anterior pode ter sido
            # um turno do subagente investidor -- e esta continuacao grava
            # `classificador` do mesmo jeito.
            #
            # **Desde a TEC-154 esta funcao TEM um sinal, e "nao ha como saber
            # daqui" deixou de ser verdade.** `investidor`, calculado acima, e
            # a mesma leitura e o mesmo custo ja declarados ali -- o estado e
            # o de AGORA, nao o do instante da apresentacao original, e por
            # isso e uma aproximacao da trilha da passada anterior, nao uma
            # leitura exata dela. Esta card deliberadamente NAO o usou para
            # este rotulo: trocar `subagent` e mudanca de comportamento de
            # telemetria, fora do escopo da TEC-154 (que e sobre a ficha), e
            # entraria sem teste que a prendesse. A consequencia segue real e
            # declarada, nao corrigida: a telemetria subconta as continuacoes
            # da trilha do investidor, jogando-as no balde do classificador.
            # Fechar isto agora e um caminho curto -- `SUBAGENTE_INVESTIDOR if
            # investidor else SUBAGENTE_CLASSIFICADOR` aqui embaixo -- e nao
            # mais uma consulta que esta funcao nao faz.
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


class _ModeracaoDoTurno:
    """Garante que a fala de entrada seja moderada UMA vez, por onde quer que
    o turno saia.

    Privada de `turno.py` e nao de `domain/messages/`: ela carrega estado de um
    turno -- o veredito memorizado e o `_resolvida` --, e nao tem sentido fora
    dele. A operacao compartilhada e `moderar_entrada_e_marcar`; aqui mora so a
    memoria de ja ter chamado.

    **O problema que ela resolve** (TEC-297): o corpo do turno
    (`_executar_turno`) tinha cinco returns antes da linha que chama a
    moderacao, e a fala que dispara qualquer um deles nunca era moderada.
    Chamar a moderacao antes de cada um seria um sitio a lembrar por return
    -- e a D4 do desenho desta card registra as duas vezes em que uma lista
    escrita a mao ja envelheceu errado neste fluxo. Um ramo novo nasce coberto
    pelo invulucro e nasceria furado por uma lista. Foi o que aconteceu com o
    sexto, a confirmacao de midia da TEC-132 -- que, sem corpo, nem tem fala a
    moderar.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        moderador: ModeradorPort,
        message: Message,
        corpo: str | None,
    ) -> None:
        self._session_factory = session_factory
        self._moderador = moderador
        self._message = message
        self._corpo = corpo
        self._resolvida = False
        self._veredito: Veredito | None = None

    async def resolver(self) -> Veredito | None:
        """Modera e marca, na primeira chamada. Depois, devolve o memorizado.

        Sem corpo nao ha o que moderar -- audio, imagem e documento passam por
        aqui e nao pagam nada --, e a fala fica resolvida como se tivesse sido
        liberada: `None`. A checagem esta aqui, e nao so no `if corpo` que o
        turno sempre teve, porque quem chega pelo fecho do invulucro nao passa
        por aquele `if`.
        """
        if self._resolvida:
            return self._veredito
        self._resolvida = True
        if not self._corpo:
            return None
        # TEC-298, D5. Uma passada anterior pode ja ter julgado esta fala: o
        # carimbo de `bloqueada_em` e o veredito persistido do caso bloqueado.
        # Sem esta consulta, toda retentativa de turno bloqueado paga a
        # moderacao de novo e grava uma segunda linha de auditoria para a
        # MESMA recusa. Custa um SELECT por chave primaria contra uma chamada
        # de rede paga.
        ja_registrado = await veredito_ja_registrado(
            self._session_factory, message_id=self._message.id
        )
        if ja_registrado is not None:
            self._veredito = ja_registrado
            return self._veredito
        self._veredito = await moderar_entrada_e_marcar(
            self._session_factory,
            self._moderador,
            message_id=self._message.id,
            channel=self._message.channel,
            conversation_key=self._message.conversation_key,
            corpo=self._corpo,
        )
        return self._veredito

    async def resolver_no_fim(self) -> None:
        """O caminho SEM excecao em voo: resolve e deixa a falha da marca subir.

        Propagar aqui preserva o contrato de `messages/bloqueio.py` -- o turno
        vira FAILED, o sweeper retenta e a marca sai depois. Ver a D5 do
        desenho.

        O invulucro escolhe entre esta e `resolver_engolindo` pelo bloco em que
        esta, e nao consultando estado global: `sys.exc_info()` enxerga a
        excecao em tratamento em QUALQUER ponto da pilha da task, entao um
        chamador futuro que fizesse `except X: await executar_turno(...)` faria
        esta falha ser engolida sem que ninguem tivesse decidido isso.
        """
        await self.resolver()

    async def resolver_engolindo(self) -> None:
        """O caminho COM excecao do turno em voo: resolve, e loga se falhar.

        **A excecao ao contrato de `messages/bloqueio.py`, e ela mora aqui.**
        Aquele modulo propaga de proposito: marca que falha em silencio deixa a
        fala bloqueada elegivel para o contexto e para o resumo, e o desfecho
        seguro e o turno falhar para o sweeper retentar. Mas com a excecao do
        turno em voo, propagar daqui a SUBSTITUIRIA -- e `process_message` grava
        em `messages.last_error` o nome da classe do que subir (via
        `_detalhe_para_a_coluna`). Quem for diagnosticar leria a falha da marca
        no lugar da causa real.

        Engolir nao desfaz o contrato: a excecao original segue subindo, a linha
        vira FAILED do mesmo jeito e o sweeper reenfileira a mensagem inteira
        enquanto ela tiver tentativa (`sweep_max_attempts`) -- a marca sai na
        retentativa. O que se perde e o detalhe da falha da marca em
        `last_error`, e e por isso que se loga.
        """
        try:
            await self.resolver()
        except Exception as exc:
            # `Exception` e nao `BaseException`, ao contrario do `except` do
            # invulucro: aqui o que se engole e a falha DESTA marca, e engolir
            # um `CancelledError` levantado por ela suprimiria o cancelamento
            # da task -- o `process_message` tem clausula propria para ele
            # justamente porque perde-lo quebra o desligamento limpo.
            log.error(
                "moderacao.marca_falhou",
                message_id=str(self._message.id),
                reason=type(exc).__name__,
            )


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
    agendador_de_avisos: AgendadorDeAvisosPort,
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

    A trilha do investidor (TEC-153, RN-07.1) tem uma segunda chamada
    parecida, e uma diferenca que importa: ela acontece **uma vez por
    virada**, e nao em todo turno. Dali em diante a intencao ja esta no
    estado que montou o prompt, o subagente do investidor e escolhido antes
    da chamada unica e nao ha chamada extra nenhuma. Quando o turno e ambiguo
    e investidor ao mesmo tempo, a desambiguacao vence -- sem intencao
    confiavel nao ha trilha a escolher.

    Por VIRADA, e nao por lead: `campos_a_gravar` deixa COMPRA sobrescrever a
    intencao gravada, entao um lead que sai da trilha e volta paga a segunda
    chamada outra vez.

    A marca de `perguntou` da TEC-257 segue a mesma regra, pelo mesmo motivo:
    e um fato sobre a nossa resposta, nao sobre a fala do lead, entao so entra
    depois da entrega confirmada e so quando `gerada` foi de fato o texto
    entregue -- nunca no caminho de desambiguacao nem na virada do investidor
    (nos dois a chamada 1 foi descartada) nem com a saida bloqueada (o texto
    neutro nao pergunta nada). Diferente do marcador de desambiguacao, esta
    marca e permanente e a uniao no SQL nunca remove: marcar de mais aqui perde
    a chance de perguntar aquele campo para sempre e em silencio, nao so ate o
    proximo episodio.
    """
    # Decifra uma vez so, aqui no involucro: e o unico `decrypt` deste modulo,
    # e o mesmo `corpo` vai para a moderacao de entrada e para
    # `_executar_turno` logo abaixo -- os dois julgam o mesmo texto.
    corpo = decrypt(message.text_body, aad_de(message.id, "text_body"))
    # TEC-297: a moderacao de entrada nasce aqui e e garantida pelos dois
    # fechos abaixo -- um por caminho de saida --, e nao pela linha em que o
    # corpo do turno a chama. Sete returns saem antes dessa linha (cinco na
    # TEC-297, mais a confirmacao de midia da TEC-132 e o pedido de titular da
    # TEC-207), e sem os fechos a fala que os dispara nao seria moderada.
    moderacao = _ModeracaoDoTurno(session_factory, moderador, message, corpo)
    try:
        resultado = await _executar_turno(
            session_factory,
            message=message,
            classificador=classificador,
            resumidor=resumidor,
            contador=contador,
            outbound=outbound,
            moderador=moderador,
            agendador=agendador,
            agendador_de_avisos=agendador_de_avisos,
            corpo=corpo,
            moderacao=moderacao,
        )
    except BaseException:
        # `BaseException` e nao `Exception` de proposito: um `CancelledError`
        # tambem tem de passar por aqui, senao o turno cancelado perde a marca
        # por um caminho que a D5 nao previu. `raise` logo abaixo o devolve
        # intacto.
        await moderacao.resolver_engolindo()
        raise
    # Sem excecao em voo a falha da marca PROPAGA, e e o lugar em que ela deve
    # propagar: e a decisao do bloco em que estamos, nao uma consulta a estado
    # global. Nao e `finally` porque `finally` nao distingue os dois casos.
    await moderacao.resolver_no_fim()
    return resultado


async def _executar_turno(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    classificador: ClassificadorPort,
    resumidor: ResumidorPort,
    contador: ContadorPort,
    outbound: OutboundPort,
    moderador: ModeradorPort,
    agendador: AgendadorDeResumoPort,
    agendador_de_avisos: AgendadorDeAvisosPort,
    corpo: str | None,
    moderacao: _ModeracaoDoTurno,
) -> ResultadoDoTurno:
    """O corpo do turno. Contrato e desfechos: ver `executar_turno`.

    Existe separada so para que o `try` do invulucro nao reindente as ~2.700
    linhas deste corpo (TEC-297, D9). Nao chame direto: sem o fecho do
    invulucro a fala dos returns antecipados volta a nao ser moderada.
    """
    # `bool(...)` por fora, e nao `bool(corpo) and ...`: so a forma curta-
    # circuitada estreita `corpo` de `str | None` para `str` dentro da chamada.
    pedido_de_optout = bool(corpo and pediu_optout(corpo))

    # Ao lado do opt-out, e pela mesma razao que o `not pedido_de_optout` da
    # guarda de silencio existe -- fix de revisao final (Critical 2). So o
    # CALCULO subiu para ca; o bloco que age sobre ele continua la embaixo,
    # depois do opt-out, porque a ordem da D4 do desenho nao mudou. Mesma forma
    # de `bool()` por fora, pelo mesmo motivo de estreitamento de tipo.
    pedido_de_humano = bool(corpo and pediu_humano(corpo))

    # TEC-207, D3. Calculado aqui, ao lado dos outros dois pedidos do lead, pelo
    # mesmo motivo: funcao pura sobre o texto decifrado, sem consulta. O bloco
    # que age sobre ele vem logo abaixo, antes de todas as guardas.
    tipo_de_titular = pedido_de_titular(corpo) if corpo else None

    # Ao lado do opt-out de proposito: mesmo insumo (o texto decifrado), mesmo
    # ponto do fluxo, e nenhuma consulta. Na regra, a fala bloqueada pela
    # moderacao nao chega ao gancho -- `_executar_turno` retorna por
    # `_entregar_texto_fixo` antes do bloco transacional --, entao um turno que
    # o resto do produto trata como nao-dito nao forca QUENTE, e isso sai de
    # graca. **A D4 da TEC-295 tirou o "sempre" dessa frase:** havendo pergunta
    # pendente, o bloco de bloqueio cai para fora e o turno segue (ver o
    # `if not tem_pendencia` mais abaixo). Esta linha roda antes de qualquer
    # moderacao, entao nessa continuacao os gatilhos calculados sobre a fala
    # bloqueada deixam de estar garantidamente fora do gancho.
    #
    # `if corpo else ()` e nao `bool(corpo) and ...` porque a saida e uma
    # tupla, nao um bool: so a forma condicional estreita `corpo` de
    # `str | None` para `str` E preserva o tipo de retorno.
    gatilhos = gatilhos_de(corpo) if corpo else ()

    # O pedido de titular (TEC-207, D3) vem ANTES de todas as guardas abaixo,
    # e cada uma delas o engoliria por um motivo diferente:
    #
    # - **Antes do portao de silencio por opt-out**: quem ja pediu para sair
    #   continua podendo exercer o direito de acesso e de eliminacao -- o
    #   opt-out e sobre receber mensagem, nao sobre abrir mao da LGPD. Depois
    #   do portao, o pedido de quem ja optou fecharia em "silenciado", sem
    #   registro nenhum e sem o prazo de 15 dias comecar a contar.
    # - **Antes da guarda de atendimento humano e da de encerramento por
    #   escopo**: um corretor ter assumido a conversa, ou a politica de escopo
    #   te-la calado, nao suspende direito do titular.
    # - **Antes da moderacao de entrada**, que tem `return` proprio: pelo
    #   mesmo CRITICAL que o bloco de opt-out, mais abaixo, descreve -- um
    #   pedido com um xingamento junto seria recusado e nunca registrado. A
    #   moderacao continua acontecendo, no fecho de `executar_turno`, depois
    #   do registro (TEC-297).
    #
    # Sem LLM, como o opt-out: uma decisao de LGPD nao depende de provedor.
    #
    # **A eliminacao e em dois passos** (C2 da revisao final, decisao do
    # Eduardo -- ver `_CONFIRMACOES_DE_ELIMINACAO` em `titular/deteccao.py`).
    # O pedido (`tipo_de_titular is ELIMINACAO`) nao registra nada: so manda
    # `TEXTO_DA_PERGUNTA_DE_ELIMINACAO`. Quem registra e a mensagem seguinte,
    # se ela for a palavra de confirmacao E a ultima coisa que o agente mandou
    # ao lead tiver sido a pergunta, ha menos de 24 horas
    # (`pergunta_de_eliminacao_pendente`). Fora disso "apagar" e so uma
    # palavra e o turno segue normal. O acesso continua em um passo.
    #
    # **A eliminacao confirmada grava opt-out junto** (D3): quem pede para
    # apagar os dados nao quer follow-up enquanto o pedido espera, e o texto
    # que confirma promete isso ("até lá não vou mais te enviar mensagens").
    # `or pedido_de_optout` porque este bloco devolve antes do bloco de
    # opt-out: sem ele, "pare de mandar mensagem e quero meus dados" registraria
    # o acesso e PERDERIA o opt-out em silencio -- o defeito de LGPD que o
    # comentario da guarda de atendimento humano descreve, entrando por outra
    # porta. A confirmacao nesse caso e a do pedido de titular so; o opt-out
    # fica registrado e o portao o aplica do proximo turno em diante. O mesmo
    # vale para a PERGUNTA de eliminacao: "pare de mandar mensagem e apaguem
    # meus dados" grava o opt-out agora e pergunta -- a pergunta fura a guarda
    # de opt-out, e o "apagar" seguinte tambem, porque este bloco vem antes do
    # portao.
    #
    # A ordem das escritas segue o bloco de opt-out: tudo gravado ANTES da
    # entrega, porque entrega que falha deixa o lead sem confirmacao (ruim e
    # conforme), e registro que falta deixa o pedido sem prazo nem trilha. A
    # solicitacao vai primeiro e commita sozinha; `registrar_optout` abre a
    # propria transacao. Numa retentativa sobre a mesma mensagem as duas sao
    # seguras: `registrar_solicitacao` e idempotente por (lead, tipo), e o
    # opt-out so e gravado se o lead ainda nao esta nele (a tabela e
    # append-only, e o segundo evento seria ruido na trilha). A retentativa do
    # "apagar" continua se reconhecendo como confirmacao porque
    # `pergunta_de_eliminacao_pendente` ignora as reservas da propria mensagem.
    #
    # A confirmacao sai com `KIND_DA_CONFIRMACAO_DE_TITULAR` e a pergunta com
    # `KIND_DA_PERGUNTA_DE_ELIMINACAO`, os dois em `KINDS_QUE_FURAM_AS_GUARDAS`
    # (`outbound/port.py`): sem isso, o opt-out que a propria eliminacao
    # acabou de gravar barraria a confirmacao dela, e o de quem ja optou
    # barraria a pergunta.
    confirmou_eliminacao = False
    if corpo and e_palavra_de_confirmacao(corpo):
        async with session_factory() as sessao_da_confirmacao:
            confirmou_eliminacao = await pergunta_de_eliminacao_pendente(
                sessao_da_confirmacao,
                channel=message.channel,
                conversation_key=message.conversation_key,
                antes_da_mensagem=message.id,
            )
    # O que o bloco registra: o acesso, na hora; a eliminacao, so confirmada.
    # `pedido_de_titular` nunca devolve nada para a palavra solta ("apagar"
    # nao fala de dados), entao os dois ramos nao colidem.
    tipo_a_registrar: TipoDeSolicitacao | None = (
        TipoDeSolicitacao.ELIMINACAO
        if confirmou_eliminacao
        else TipoDeSolicitacao.ACESSO
        if tipo_de_titular is TipoDeSolicitacao.ACESSO
        else None
    )
    pergunta_de_eliminacao = tipo_de_titular is TipoDeSolicitacao.ELIMINACAO
    if tipo_a_registrar is not None or pergunta_de_eliminacao:
        async with session_factory() as sessao_do_titular:
            if tipo_a_registrar is not None:
                await registrar_solicitacao(
                    sessao_do_titular,
                    channel=message.channel,
                    conversation_key=message.conversation_key,
                    tipo=tipo_a_registrar,
                    origem=OrigemDaSolicitacao.WHATSAPP,
                    ator=ATOR_SISTEMA,
                )
                await sessao_do_titular.commit()
            ja_em_optout = await esta_em_optout(
                sessao_do_titular,
                channel=message.channel,
                conversation_key=message.conversation_key,
            )
        quer_silencio = tipo_a_registrar is TipoDeSolicitacao.ELIMINACAO or pedido_de_optout
        if quer_silencio and not ja_em_optout:
            await registrar_optout(
                session_factory,
                channel=message.channel,
                conversation_key=message.conversation_key,
                message_id=message.id,
            )
            # A mesma escrituracao do bloco de opt-out (TEC-130, D6), na mesma
            # ordem: opt-out primeiro, encerramento depois.
            await _encerrar_por_optout(session_factory, message)
        if tipo_a_registrar is None:
            log.info(
                "turno.confirmacao_de_titular_pedida",
                channel=message.channel,
                message_id=str(message.id),
            )
            texto_do_titular = TEXTO_DA_PERGUNTA_DE_ELIMINACAO
            kind_do_titular = KIND_DA_PERGUNTA_DE_ELIMINACAO
            desfecho_de_sucesso: ResultadoDoTurno = "confirmacao_de_titular_pedida"
        else:
            log.info(
                "turno.pedido_de_titular",
                channel=message.channel,
                message_id=str(message.id),
                tipo=str(tipo_a_registrar),
            )
            texto_do_titular = (
                TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO
                if tipo_a_registrar is TipoDeSolicitacao.ELIMINACAO
                else TEXTO_DA_CONFIRMACAO_DE_ACESSO
            )
            kind_do_titular = KIND_DA_CONFIRMACAO_DE_TITULAR
            desfecho_de_sucesso = "pedido_de_titular"
        desfecho_do_titular = await _entregar_texto_fixo(
            session_factory,
            message=message,
            outbound=outbound,
            recorder_texto=texto_do_titular,
            kind=kind_do_titular,
            subagent=SUBAGENTE_TITULAR,
        )
        # Mesmo contrato do bloco de opt-out: os desfechos de nao-entrega sao
        # sobre o ENVIO, e o pedido ja esta gravado (na pergunta, nao havia o
        # que gravar) -- passam como estao.
        return desfecho_de_sucesso if desfecho_do_titular == "respondido" else desfecho_do_titular

    # Antes de tudo, exceto o pedido de titular logo acima: quem ja pediu
    # silencio nao recebe resposta. **Paga a moderacao, desde a TEC-297** --
    # este `return` e um dos cinco que saiam
    # antes dela, e a fala que o dispara entrava no contexto, no resumo, no
    # score e na ancora de follow-up sem nunca ter sido julgada. A chamada
    # acontece no fecho do involucro, depois deste return, entao ela nao
    # atrasa o silencio. Fica FORA do `if corpo:` de proposito: o
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
    # proprio pedido e o unico envio permitido depois do registro -- ao lado,
    # desde a TEC-207, da confirmacao do pedido de titular e da pergunta de
    # eliminacao), e o gatilho e sempre uma fala do lead pedindo exatamente
    # isso.
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
    # nao paga chamada ao classificador (desde a TEC-297 a moderacao roda de
    # qualquer jeito, no fecho do involucro). A guarda autoritativa e a da
    # porta de saida (`outbound/port.py`); esta so evita o trabalho.
    #
    # `tem_handoff_de_humano_aberto` (TEC-143) e a SEGUNDA fonte de silencio,
    # ao lado de `esta_silenciada`. Sao perguntas diferentes -- "um corretor
    # assumiu" contra "o lead pediu e tem handoff na fila" --, e o docstring
    # daquela funcao e explicito: e dali que vem o silencio da TEC-143, nao de
    # `esta_silenciada`. No PRIMEIRO turno em que o lead pede humano nao ha
    # handoff ainda (o bloco novo, mais abaixo, e quem cria), entao esta
    # checagem so passa a valer do SEGUNDO turno em diante -- e o resultado
    # continua "atendimento_humano" nos dois casos, porque para o lead o
    # efeito e o mesmo (o agente calou).
    #
    # **`not pedido_de_humano` condiciona SO a fonte de handoff, e nao a guarda
    # inteira** -- fix de revisao final (Critical 2), e a forma estreita e
    # deliberada. Sem ele o aviso da transferencia se perdia PARA SEMPRE numa
    # falha retentavel: `_entregar_texto_fixo` nao captura `EnvioRetentavel`,
    # entao a excecao sobe, `process_message` marca a linha FAILED e o sweeper
    # reenfileira a MESMA mensagem -- e no turno 2
    # `tem_handoff_de_humano_aberto` ja devolve True (o turno 1 commita o
    # handoff ANTES de entregar), esta guarda disparava, o turno fechava em
    # "atendimento_humano" e o lead nunca era avisado de nada. E exatamente o
    # defeito que o comentario da guarda de opt-out, logo acima, descreve para
    # a confirmacao de opt-out: o repo ja pagou por ele uma vez e esta card o
    # reintroduziu uma guarda abaixo, pela fonte de silencio nova.
    #
    # O custo aceito e o mesmo que a guarda de opt-out declara:
    # `registrar_handoff` e idempotente (acumula o gatilho na linha aberta em
    # vez de criar outra, e `_agendar_resumo` sai cedo quando `not criado`),
    # entao um lead que repete o pedido so recebe o aviso de novo.
    #
    # **`esta_silenciada` continua valendo, e a versao ampla desta condicao
    # (`if not pedido_de_optout and not pedido_de_humano:`) foi recusada por
    # isso.** So a fonte de handoff causava o Critical 2; `esta_silenciada`
    # responde outra pergunta -- um corretor ASSUMIU esta conversa (TEC-179,
    # RN-16.4) -- e nao tem nada a ver com a falha retentavel. Pulando-a, um
    # lead cuja conversa ja esta sendo atendida por gente de verdade e que
    # pedisse humano caia no bloco abaixo e, quando nao houvesse handoff
    # aberto (o corretor que assume por conta propria, sem handoff nenhum),
    # nascia um handoff NOVO com `criado=True` -- e desde o fix da esteira
    # (Critical 1) isso agenda resumo e notificacao para uma conversa que ja
    # tem dono. Ruido operacional que chega a um corretor. Conversa assumida
    # nao gera handoff nem notificacao nova: ela devolve "atendimento_humano"
    # aqui, como sempre devolveu.
    if not pedido_de_optout:
        async with session_factory() as sessao:
            se_calar = await esta_silenciada(
                sessao, channel=message.channel, conversation_key=message.conversation_key
            ) or (
                not pedido_de_humano
                and await tem_handoff_de_humano_aberto(
                    sessao, channel=message.channel, conversation_key=message.conversation_key
                )
            )
            if se_calar:
                log.info(
                    "turno.atendimento_humano",
                    channel=message.channel,
                    message_id=str(message.id),
                )
                return "atendimento_humano"

    # A guarda do encerramento por escopo (TEC-138, RN-03.5). A conversa
    # encerrada POR FORA DE ESCOPO cala o agente enquanto a janela de 30 dias
    # corre.
    #
    # **"Por fora de escopo" e a metade que o motivo carrega, e ela nao e
    # detalhe** (fix da revisao final, Important 1). Quem decide e
    # `situacao.silencia_o_agente`, que exige
    # `MotivoDoEncerramento.FORA_DE_ESCOPO` -- e nao `dentro_da_janela`
    # sozinho, que so fala do tempo. Calar 30 dias e politica DESTA regra, nao
    # propriedade do `status`: a Emenda E-02 da RN-02.3 que esta card escreveu
    # manda a TEC-130 acrescentar `INATIVIDADE` ao vocabulario e o escritor que
    # fecha por inatividade, e uma guarda cega ao motivo faria disso 30 dias de
    # silencio em toda conversa inativa -- o oposto do reengajamento que a
    # RN-02.3 existe para ter. A razao por extenso esta na docstring de
    # `silencia_o_agente` (`domain/conversa/repositorio.py`).
    #
    # **Perde para as duas guardas de cima, e a ordem e a razao.** Opt-out e
    # direito do lead (LGPD); silencio de atendimento humano e decisao de uma
    # PESSOA sobre esta conversa. As duas vencem politica automatica nossa, e
    # inverter nao seria so trocar um rotulo no log: um lead que digitasse
    # "parar" numa conversa encerrada sairia por aqui sem o opt-out
    # registrado, que e o mesmo defeito de LGPD que o comentario da guarda
    # acima ja descreve para o caso dela. Dai o `if not pedido_de_optout:`,
    # identico ao das duas.
    #
    # **Ganha de tudo o que vem abaixo pelo motivo oposto**: daqui para baixo
    # o caminho leva a montagem de contexto e ao classificador -- as duas
    # caras --, e economiza-las e o que esta guarda faz. Descer um degrau
    # que seja a transformaria em silencio CARO, que e o oposto do que a
    # card pede. A politica sozinha nao precisava estar aqui em cima: o
    # silencio funcionaria igual la embaixo, so que pago.
    #
    # **A moderacao de entrada saiu dessa conta na TEC-297, e a saida foi
    # deliberada.** A guarda passou a pagar uma moderacao (US$ 0,00057
    # medidos, roda em Haiku) porque, sem a marca, a fala entra no contexto e
    # no resumo quando a conversa reabre depois dos 30 dias. A chamada
    # acontece no fecho do involucro de `executar_turno`, depois deste
    # `return`, entao ela nao atrasa o silencio. A D8 do desenho da TEC-297
    # registra o que isso encolhe da reducao de superficie que a D7 da
    # TEC-138 tinha oferecido a TEC-204.
    #
    # **E ela nao morde o turno que encerra.** O encerramento so e gravado
    # DEPOIS da entrega confirmada (ver o bloco pos-entrega la embaixo), entao
    # na terceira mensagem fora de escopo esta guarda ainda ve a conversa
    # aberta e deixa passar. Quem cala e o turno SEGUINTE.
    #
    # **O pedido de humano e a excecao, e ele nao cala** (fix da revisao,
    # Important 1). A versao anterior desta guarda calava tambem quem pedisse
    # atendente, e justificava com um custo que NAO existe: o bloco da TEC-143
    # (`if pedido_de_humano:`) fica logo abaixo e devolve antes da linha da
    # moderacao de entrada, antes de `montar_contexto` e antes da chamada ao
    # classificador -- e a D5 do desenho enumera essa ordem. **Desde a
    # TEC-297 a moderacao acontece de qualquer jeito**, no fecho do
    # involucro de `executar_turno`: devolver antes da linha nao poupa mais
    # a chamada, so adia ela para depois do return. O preco real da excecao
    # e um `INSERT` idempotente, um resumo agendado, um envio de texto fixo
    # e uma moderacao (roda em Haiku): zero chamadas ao classificador, que e
    # o que esta guarda existe para poupar. Calar custava o oposto -- o lead
    # que escreve "quero falar com um atendente" nao seria atendido, nenhum
    # handoff nasceria e ninguem ficaria sabendo que ele pediu, por ate 30
    # dias. Isso inverteria o "decisao de pessoa vence politica automatica" das
    # duas guardas de cima justamente no caso em que a pessoa que pede e o
    # lead. A forma -- `not pedido_de_humano` sobre o silencio, e nao sobre o
    # bloco inteiro -- e a mesma que a guarda imediatamente acima usa para a
    # fonte de handoff dela.
    if not pedido_de_optout:
        async with session_factory() as sessao:
            situacao = await situacao_da_conversa(
                sessao,
                channel=message.channel,
                conversation_key=message.conversation_key,
                agora=datetime.now(UTC),
            )
            if situacao.silencia_o_agente and not pedido_de_humano:
                # Sem o texto da mensagem, pela mesma razao que a prosa
                # bloqueada da TEC-161 nao entra no log: o canal registra que
                # a politica agiu, nao o que o lead escreveu.
                log.info(
                    "turno.fora_de_escopo",
                    channel=message.channel,
                    message_id=str(message.id),
                )
                return "fora_de_escopo"

            # A REABERTURA mora aqui, e o gatilho dela e a mensagem do lead.
            # **Desde a TEC-130 existe uma varredura diaria**
            # (`sweep_conversas_inativas`) que fecha por INATIVIDADE, mas ela
            # so ESCREVE o encerramento -- nao reabre nada e nao decide
            # contexto. Entre a passagem dela e a mensagem do lead a linha
            # fica dizendo ENCERRADA, e `situacao_da_conversa` ja conta a
            # verdade nesse meio tempo. Chegando aqui o turno SEGUE, e nao
            # devolve.
            #
            # Condicionada a `marcada_como_encerrada` (fix da revisao, Minor
            # 7). A versao anterior chamava `reabrir_conversa`
            # incondicionalmente, argumentando que separar "nao ha linha" de
            # "ha linha vencida" custaria um SELECT a mais -- nao custa: a
            # leitura acima ja trouxe as colunas, e so devolvia uma delas.
            # Incondicional, toda conversa ja reaberta pagava um `UPDATE` e um
            # commit em TODO turno, para sempre, reescrevendo os mesmos tres
            # valores que ja estavam la.
            #
            # **Cobre tres entradas, nao uma.** A janela vencida e a comum; a
            # segunda e o pedido de humano dentro da janela, que acabou de
            # passar pela excecao acima. Reabrir nesse caso e deliberado: o
            # lead voltou com um pedido que nao e fora de escopo, e sem a
            # reabertura ele ficaria mudo para o agente pelo resto da janela
            # mesmo depois de o corretor ter resolvido o handoff. A terceira
            # nasceu do fix da revisao final (Important 1) e ainda nao tem
            # produtor: um encerramento de OUTRO motivo, dentro da janela --
            # `silencia_o_agente` nao o cala, e o turno cai aqui. Reabrir e o
            # certo tambem ali, e e o que a propria RN-02.3 pede ("nova
            # mensagem apos encerramento abre nova conversa"). **Quem
            # acrescentar um motivo e quiser outro tratamento muda ESTA linha
            # de proposito** -- ela nao olha o motivo.
            #
            # Sem log: `reabrir_conversa` nao diz se mexeu em alguma linha, e
            # um `conversa.reaberta` que nao pode afirmar isso mentiria.
            if situacao.marcada_como_encerrada:
                await reabrir_conversa(
                    sessao, channel=message.channel, conversation_key=message.conversation_key
                )
                await sessao.commit()

    if pedido_de_optout:
        # ANTES da moderacao de entrada, de proposito -- fix de revisao
        # (Critical): o bloco de moderacao logo abaixo tem `return` proprio.
        # Se este bloco rodasse depois dele, uma mensagem que e AO MESMO
        # TEMPO um pedido de opt-out e algo que a moderacao reprova (ex.:
        # "pare de mandar mensagem" seguido de um xingamento) nunca chegaria
        # aqui: a moderacao bloquearia e devolveria antes, o opt-out nunca
        # seria registrado, e continuariamos mandando mensagem (a recusa de
        # entrada) para quem pediu para sair -- a violacao que a D5 existe
        # para evitar, entrando por outra porta. Checar opt-out primeiro ja
        # nao poupa a chamada de moderacao -- desde a TEC-297 ela roda de
        # qualquer jeito, no fecho do involucro, depois do desfecho "opt_out"
        # que este bloco produz mais abaixo. O que a ordem preserva e o
        # registro do opt-out nao depender do veredito da moderacao, que e o
        # que o docstring de
        # `test_pedido_de_optout_grava_confirma_e_nao_paga_o_modelo`
        # (`tests/integration/test_turno_optout.py`) diz hoje.
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
        # **Escrituracao, nao silencio** (TEC-130, D6). Quem cala e
        # `esta_em_optout`, no portao la em cima; `MotivoDoEncerramento.OPTOUT`
        # nao entra em `silencia_o_agente`, de proposito. Isto aqui existe
        # para a conversa ter data e motivo, que e o que a RN-02.3 pede.
        #
        # **Sao duas transacoes, e a ordem importa.** `registrar_optout` abre
        # e commita a propria sessao; `encerrar_conversa` recebe a sessao e
        # deixa o commit para quem chama -- nao ha como junta-las sem mudar a
        # assinatura de uma das duas. O opt-out vai primeiro pelo mesmo
        # argumento que o comentario acima usa para grava-lo antes da
        # entrega: morrer entre as duas deixa o lead em opt-out com a conversa
        # ainda ATIVA -- registro de menos, nunca mensagem a mais. A varredura
        # diaria fecha essa conversa por INATIVIDADE 30 dias depois, com o
        # motivo menos preciso; e o custo aceito.
        #
        # **`conversa.encerrada` passa a significar TODO encerramento**, e nao
        # so o da RN-03.5 (fix da revisao final). O evento ja existia com campo
        # `motivo`, e emiti-lo em dois dos tres caminhos fazia o `motivo`
        # prometer uma distincao que o conjunto de linhas nao entregava: quem
        # paginasse por ele veria o funil sem os encerramentos por opt-out e
        # sem os da varredura (`encerrar_inativas` emite o terceiro).
        #
        # `_encerrar_por_optout` o emite depois do commit e sem texto do lead,
        # pelas mesmas duas razoes do bloco da RN-03.5 mais abaixo. Sem
        # `seguidas`: aqui nao ha contagem que tenha decidido nada -- o que
        # decidiu foi o pedido do lead, e o `message_id` e a alca que leva ate
        # ele. Desde a TEC-207 o bloco do pedido de titular, la em cima, chama
        # a mesma funcao quando grava opt-out.
        await _encerrar_por_optout(session_factory, message)
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
        # dentro, nos dois `if kind not in KINDS_QUE_FURAM_AS_GUARDAS`). Esses
        # desfechos sao sobre o ENVIO da confirmacao, e o opt-out ja esta
        # gravado -- entao eles passam adiante como estao, e so o caminho de
        # sucesso vira "opt_out".
        return "opt_out" if desfecho_da_confirmacao == "respondido" else desfecho_da_confirmacao

    # ORDEM: depois do opt-out, antes do classificador.
    #
    # Depois do opt-out porque opt-out e direito do lead e vence tudo -- uma
    # mensagem que pede humano E pede saida grava a saida. O comentario da
    # guarda de atendimento humano, algumas linhas acima, registra o Critical
    # em que uma guarda incondicional engoliu exatamente esse registro.
    #
    # Antes do classificador porque um pedido de humano nao precisa de modelo
    # para ser atendido, e a card pede handoff em ate 5 segundos. Pulando a
    # chamada, o prazo vira consequencia da arquitetura em vez de aposta na
    # latencia do provedor -- e nao ha chamada paga para falhar justamente
    # quando o lead ja esta irritado.
    #
    # **E antes da moderacao de entrada, com a consequencia declarada.** A D4
    # do desenho fixou esta ordem pela mesma razao de LGPD que o bloco de
    # opt-out acima registra: o bloco de moderacao logo abaixo tem `return`
    # proprio, e rodar depois dele faria uma mensagem que e AO MESMO TEMPO
    # pedido de humano e algo que a moderacao reprova nunca chegar aqui -- o
    # lead irritado que xinga e pede uma pessoa na mesma frase ficaria preso no
    # robo, que e exatamente a dor da card. O preco dessa ordem era declarado
    # aqui e a TEC-297 o tirou: ate ela, uma mensagem que a moderacao
    # reprovaria e que contivesse um termo da lista criava handoff, RECEBIA o
    # aviso e saia por este `return` sem nunca ter sido moderada. Agora ela e
    # moderada de qualquer jeito -- no fecho de `executar_turno`, depois do
    # handoff e depois do aviso --, entao a fala nao escapa mais da marca nem
    # da auditoria. A ordem que este bloco descreve nao mudou: o handoff e o
    # aviso continuam nao esperando por chamada paga nenhuma, e inverte-la
    # continua sendo decisao e nao acidente -- e o que os testes de
    # `tests/integration/test_pedido_de_humano.py` travam.
    if pedido_de_humano:
        async with session_factory() as sessao:
            handoff_do_pedido = await registrar_handoff(
                sessao,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=Gatilho.PEDIDO_DE_HUMANO,
                ator=ATOR_AGENTE,
            )
            # `registrar_handoff` NAO commita -- a docstring dela diz que o
            # commit e de quem chama, para o handoff poder entrar na mesma
            # transacao de um recalculo. Aqui nao ha nada para juntar, entao o
            # commit e imediato: o lead nao pode receber o aviso de que a
            # conversa esta indo para um corretor sem a linha existir.
            await sessao.commit()

        # Fix de revisao final (Critical 1). Depois do commit, no molde exato
        # dos outros CINCO sitios de `registrar_handoff` (os quatro daqui e o
        # de `workers/jobs/process_message.py`) -- este bloco nasceu sem as
        # duas linhas, e a falta da segunda quebrava a esteira inteira: sem
        # `_agendar_resumo` nao ha `gerar_resumo`, sem ele nao ha
        # `enqueue_job(NOTIFICAR_JOB)`, sem ele nao ha `sla_limite_em`, e
        # `escalar_vencidos` nunca via este handoff. Quem o pegava era a rede
        # de recuperacao da TEC-279 (`handoff/recuperacao.py`), 10 a 15 minutos
        # depois e logando `handoff.recuperado_sem_prazo` em warning -- a rede
        # de seguranca virando o caminho normal do unico gatilho `ALTA` da
        # RN-16.1, e o alarme dela virando ruido permanente.
        #
        # `_agendar_resumo` ja sai cedo quando `not registro.criado`, entao a
        # acumulacao de gatilho num handoff que ja existia nao reagenda nada e
        # nao precisa de condicao extra aqui.
        log.info(
            "handoff.criado" if handoff_do_pedido.criado else "handoff.gatilho_adicional",
            channel=message.channel,
            gatilho=Gatilho.PEDIDO_DE_HUMANO.value,
            etiqueta=ETIQUETA_DE[Gatilho.PEDIDO_DE_HUMANO],
            prioridade=PRIORIDADE_DE[Gatilho.PEDIDO_DE_HUMANO].value,
        )
        await _agendar_resumo(agendador, handoff_do_pedido)

        settings = get_settings()
        # Nome proprio (`texto_do_aviso`, nao `texto`) pelo mesmo motivo do
        # `desfecho_do_aviso` abaixo: mypy infere um tipo unico por nome de
        # variavel na funcao inteira, e `texto` ja e outra coisa la embaixo.
        texto_do_aviso = (
            TEXTO_DO_PEDIDO_DE_HUMANO
            if dentro_da_janela_de_atendimento(datetime.now(UTC))
            else TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO.format(
                inicio=settings.atendimento_horario_inicio,
                fim=settings.atendimento_horario_fim,
            )
        )
        log.info(
            "turno.pedido_de_humano",
            channel=message.channel,
            message_id=str(message.id),
        )
        # Nome distinto de `entregue` pelo mesmo motivo que o bloco do opt-out
        # explica: o mypy infere um tipo unico por nome de variavel na funcao
        # inteira, e este e o `ResultadoDoTurno` de `_entregar_texto_fixo`.
        #
        # `kind=KIND_DO_PEDIDO_DE_HUMANO` atravessa a guarda de atendimento
        # humano em `GuardedOutbound.send` sem escotilha nenhuma -- CONFERIDO
        # rodando, nao so lendo. Aquela guarda consulta
        # `esta_silenciada_por_mensagem`, que le `AtendimentoHumano`
        # (corretor ASSUMIU, `atendimento/repositorio.py`); o
        # `registrar_handoff` acima grava em `Handoff` (a fila, RN-16.1), uma
        # tabela diferente. Um corretor assumido ANTES deste turno ja teria
        # barrado na guarda de silencio do topo (`tem_handoff_de_humano_aberto`/
        # `esta_silenciada`, algumas linhas acima) -- nem `registrar_handoff`
        # nem este envio chegam a rodar, e nenhum handoff nasce. O aviso do
        # PRIMEIRO pedido so seria barrado por um corretor que assumiu a
        # conversa entre a checagem do topo deste turno e este envio -- nesse
        # caso o bloqueio e correto (ha gente cuidando de verdade) e o
        # desfecho vira "bloqueado_por_atendimento_humano" abaixo, nao
        # "pedido_de_humano". O mesmo vale para o recheque em
        # `_entregar_texto_fixo` (`_bloqueado_por_atendimento_humano_concorrente`):
        # ele tambem le `AtendimentoHumano`, nao `Handoff`, entao o handoff que
        # este bloco acabou de registrar nao o faz disparar.
        desfecho_do_aviso = await _entregar_texto_fixo(
            session_factory,
            message=message,
            outbound=outbound,
            recorder_texto=texto_do_aviso,
            kind=KIND_DO_PEDIDO_DE_HUMANO,
            subagent=SUBAGENTE_PEDIDO_DE_HUMANO,
        )
        # O handoff JA esta gravado e o resumo ja foi agendado: a transferencia
        # acontece mesmo que o aviso nao saia. O que NAO e verdade -- e a
        # versao anterior deste comentario afirmava -- e que o lead fique
        # sabendo. Nas saidas TERMINAIS de `_entregar_texto_fixo` (janela de
        # 24h fechada, recusa permanente da Meta, reentrega suprimida, bloqueio
        # por opt-out ou por atendimento humano concorrente) o desfecho do
        # envio passa adiante como esta e o lead fica transferido e em
        # silencio, sem nunca ter sido avisado -- nao e o que a card promete, e
        # e aceito pelo mesmo criterio da D5 do opt-out: o registro vale mais
        # que o aviso, e nenhuma dessas saidas tem retentativa.
        #
        # A falha RETENTAVEL nao e nenhuma delas: ela sobe como excecao daqui,
        # a linha vira FAILED, o sweeper reenfileira a mesma mensagem, e o
        # `not pedido_de_humano` da guarda de silencio la em cima e o que faz o
        # aviso ser reentregue no turno seguinte em vez de se perder.
        return "pedido_de_humano" if desfecho_do_aviso == "respondido" else desfecho_do_aviso

    # TEC-132, D4. Midia sem nenhum texto do lead na rajada: resposta fixa,
    # sem modelo. Aqui, e nao antes, porque as guardas de opt-out, atendimento
    # humano e conversa encerrada ja rodaram -- quem pediu silencio nao recebe
    # "recebi sua imagem". E antes da moderacao e do classificador porque nao
    # ha texto a moderar nem o que perguntar ao modelo: um texto fixo e a unica
    # forma de GARANTIR que nada se afirma sobre o conteudo.
    #
    # "Na rajada" e nao "nesta mensagem": com "quero esse" + foto o debounce
    # roda o turno na foto, e responder fixo ali deixaria o "quero esse" sem
    # resposta. Havendo texto pendente, o turno segue normal e o modelo ve a
    # midia marcada (`_MARCADOR_DE_MIDIA`, em `context/montagem.py`).
    #
    # E um return a mais antes da linha da moderacao, e nao fura a TEC-297:
    # so dispara com `corpo is None`, e sem corpo nao ha fala a moderar
    # (`_ModeracaoDoTurno.resolver` devolve `None` sem chamar nada).
    #
    # **A checagem de kinds reservados e o que torna isto seguro numa
    # retentativa** -- mesma classe da TEC-298, D1. Com "quero esse" + foto, a
    # passada 1 ve o texto pendente, roda o turno normal, entrega a resposta
    # e grava a fala OUTBOUND; se o worker morre antes de PROCESSED, a passada
    # 2 encontra essa fala como a ultima do agente, o "quero esse" deixa de
    # estar pendente, e sem esta checagem o turno mandaria "Recebi sua
    # imagem!" depois de o agente ja ter respondido. Qualquer kind reservado
    # que NAO seja o da confirmacao prova que uma passada anterior tomou o
    # caminho normal, e entao o turno segue normal de novo (e termina em
    # `reentrega_suprimida`, como terminava antes desta card). So a propria
    # confirmacao reservada mantem o caminho fixo: a reserva dela suprime a
    # duplicata. Aqui nao serve o `teto_do_agente` da recusa: a fala que
    # envenena a fronteira nao e desta trilha, e o teto dependeria de saber
    # qual kind do turno normal saiu primeiro.
    #
    # **E a confirmacao nao se repete em sequencia** (I2 da revisao final):
    # fotos que atravessam mais de uma janela de debounce rodam um turno cada,
    # e sem isto o lead recebia o mesmo texto fixo duas ou tres vezes
    # seguidas. Se a ultima fala do agente foi a propria confirmacao, ha menos
    # de `JANELA_DA_CONFIRMACAO_DE_MIDIA`, o turno fecha em silencio -- e
    # "nao ha texto pendente desde entao" ja e o `not ha_texto_pendente`, cuja
    # fronteira e essa mesma ultima fala. Vem DEPOIS da regra de kinds
    # reservados, que continua decidindo a retentativa; e so quando esta
    # mensagem ainda nao tem a confirmacao reservada: tendo, a ultima fala
    # pode ser a dela mesma, e quem responde e a supressao de
    # `_entregar_texto_fixo`, com o desfecho de sempre.
    confirmacao = CONFIRMACOES_DE_MIDIA.get(message.content_type)
    if confirmacao is not None and corpo is None:
        reservados_antes = await kinds_reservados(session_factory, message_id=message.id)
        ja_seguiu_o_turno_normal = bool(reservados_antes - {KIND_DA_CONFIRMACAO_DE_MIDIA})
        ha_texto_pendente = False
        if not ja_seguiu_o_turno_normal:
            async with session_factory() as sessao_da_rajada:
                ha_texto_pendente = await ha_fala_pendente_antes(
                    sessao_da_rajada, message, com_texto=True
                )
        if not ja_seguiu_o_turno_normal and not ha_texto_pendente:
            if KIND_DA_CONFIRMACAO_DE_MIDIA not in reservados_antes:
                async with session_factory() as sessao_da_confirmacao:
                    ja_confirmada = await ja_confirmou_ha_pouco(sessao_da_confirmacao, message)
                if ja_confirmada:
                    log.info("turno.midia_ja_confirmada", message_id=str(message.id))
                    return "midia_ja_confirmada"
            return await _entregar_texto_fixo(
                session_factory,
                message=message,
                outbound=outbound,
                recorder_texto=confirmacao,
                kind=KIND_DA_CONFIRMACAO_DE_MIDIA,
                subagent=SUBAGENTE_MIDIA,
            )

    if corpo:
        veredito = await moderacao.resolver()
        if veredito is not None and veredito.bloqueado:
            # A marca vem ANTES da entrega, e a ordem e o ponto (TEC-236).
            # `_entregar_texto_fixo` tem cinco saidas que nao entregam
            # nada -- janela fechada, recusa permanente da Meta, reentrega
            # suprimida, bloqueio por opt-out concorrente (TEC-182),
            # bloqueio por atendimento humano concorrente (TEC-179) --, e
            # a maioria delas fecha a linha em PROCESSED, que e terminal.
            # Desde a TEC-298, "reentrega suprimida" so fecha a linha
            # quando `not tem_pendencia`: com pendencia, o guard abaixo
            # deixa o turno continuar em vez de retornar aqui -- ela saiu
            # do grupo que sempre fechava e entrou no que fecha condicional.
            # Marcar depois deixaria a fala bloqueada sem marca exatamente
            # nos casos em que ninguem mais volta nesta linha, e ela
            # entraria no contexto do proximo turno -- e e por isso que
            # `moderar_entrada_e_marcar` marca por dentro, antes de devolver.
            #
            # TEC-295, D4, ruling R5. `tem_pendencia` tem de ser calculado
            # ANTES de `_entregar_texto_fixo` -- nao e so ordem de codigo,
            # e a pergunta certa. `_entregar_texto_fixo` grava a recusa como
            # fala OUTBOUND do agente (`recorder.record_agent_message`), e
            # `ha_fala_pendente_antes` define "pendente" como "INBOUND mais
            # nova que a ULTIMA fala OUTBOUND do agente". Calculado DEPOIS,
            # a propria recusa (que nao responde a pergunta pendente
            # nenhuma) viraria essa ultima fala e apagaria a pendencia da
            # pergunta legitima -- o booleano sairia sempre falso, e a
            # continuacao que esta task existe para habilitar nunca
            # rodaria. Calculado ANTES, a pergunta e a certa: "havia fala
            # pendente no estado que existia antes desta recusa?" --
            # resistir a "simplificar" isto de volta para perto do uso e o
            # ponto deste comentario.
            #
            # **A ordem esta certa e nao era suficiente (TEC-298).** Ela
            # protege a PRIMEIRA passada. A seguinte encontra a recusa ja
            # gravada antes mesmo de o turno comecar, e para essa nenhuma
            # ordem de codigo ajuda -- quem resolve e o teto logo abaixo.
            #
            # TEC-298, D1. O teto vem da reserva da recusa, e so existe numa
            # RETENTATIVA: se a reserva ja esta la, uma passada anterior ja
            # entregou a recusa e a linha OUTBOUND dela ja esta em `messages`,
            # envenenando a fronteira. Na primeira passada isto e `None` e a
            # conta e exatamente a de antes desta card.
            teto_da_recusa = await reservado_em(
                session_factory, message_id=message.id, kind=KIND_DA_RECUSA_DE_ENTRADA
            )
            async with session_factory() as sessao_da_pendencia:
                tem_pendencia = await ha_fala_pendente_antes(
                    sessao_da_pendencia, message, teto_do_agente=teto_da_recusa
                )
            # TEC-295, ruling R6. Kind proprio -- nao o default `reply` de
            # `_entregar_texto_fixo` --, porque a resposta que a continuacao
            # abaixo pode entregar tambem usa `reply` (a primeira parte de
            # `KINDS_DA_RESPOSTA`). Com o mesmo kind, a segunda entrega
            # colidiria com a UNIQUE (message_id, kind) de
            # `outbound_dispatches` e seria suprimida em silencio como
            # reentrega -- exatamente o defeito que a D4 existe para evitar,
            # so que na entrega em vez de na deteccao de pendencia.
            desfecho_da_recusa = await _entregar_texto_fixo(
                session_factory,
                message=message,
                outbound=outbound,
                recorder_texto=TEXTO_DA_RECUSA_DE_ENTRADA,
                kind=KIND_DA_RECUSA_DE_ENTRADA,
            )
            # TEC-295, D4. Ate aqui o turno retornava, e com o debounce isso
            # passou a matar pergunta legitima: numa rajada, a pergunta que
            # veio antes do xingamento fecha "agrupado" sem resposta, e
            # `PROCESSED` e terminal -- nada a reenfileira.
            #
            # O guard e sobre ESTA passada nao ter entregue a recusa, e
            # nao sobre o lead nunca ter recebido nada. `"respondido"` e
            # o unico desfecho em que a entrega aconteceu agora. Dos
            # outros quatro -- janela fechada, recusa permanente da Meta,
            # opt-out concorrente, atendimento humano concorrente --, os
            # dois ultimos tambem significam que o lead nao pode receber
            # nada NESTE MOMENTO (esta silenciado ou com humano), entao a
            # continuacao fica de fora pelo mesmo motivo que a recusa
            # fica.
            #
            # Ja `"reentrega_suprimida"` quer dizer o CONTRARIO de "nao
            # chegou": a reserva em `outbound_dispatches` ja existe porque
            # uma tentativa ANTERIOR entregou a recusa. Desde a TEC-298 ele
            # SEGUE para a continuacao, e e isso que faz a rota de
            # recuperacao da D4 sobreviver ao reprocessamento -- ate ela, o
            # turno fechava aqui e a pergunta pendente se perdia, porque
            # `PROCESSED` e terminal e nada reenfileira so a resposta que
            # ficou faltando.
            if desfecho_da_recusa not in ("respondido", "reentrega_suprimida"):
                return desfecho_da_recusa
            if not tem_pendencia:
                # Fala reprovada isolada: continuar faria o agente responder
                # ao historico anterior, que e o engajamento que a TEC-233
                # recusou de proposito.
                return desfecho_da_recusa
            # TEC-298, revisao final: composicao D1+D3. `teto_da_recusa` e o
            # `created_at` da RESERVA da recusa, e uma passada de resposta
            # bem-sucedida acontece DEPOIS dela -- entao numa TERCEIRA passada
            # (recusa entregue, resposta entregue, e so ENTAO o turno morre) o
            # teto esconde tambem a resposta que a passada anterior ja deu, e
            # `tem_pendencia` volta a True sobre uma pergunta que ja foi
            # respondida. Sem esta guarda aconteceriam duas coisas: (a) a
            # continuacao pagaria o modelo de novo para responder ao que ja
            # foi respondido, e o `send` de KIND_DA_RESPOSTA seria suprimido
            # pela reserva existente -- reabrindo, pelo kind da RESPOSTA, o
            # mesmo alarme falso que a D4 acabou de fechar pelo kind da
            # RECUSA (`turno.recusa_ja_reservada` acima); e (b) pior que o
            # alarme, se a geracao nova quebrar em duas mensagens onde a
            # anterior coube numa, `reply` e suprimido e `reply_2` sai
            # sozinho -- a metade orfa de uma resposta nova, a "costura" que
            # `domain/outbound/kinds.py` documenta como corrupcao silenciosa.
            # Reserva de KIND_DA_RESPOSTA e o mesmo sinal que fecha os dois:
            # uma passada anterior ja chegou a responder, entao nao ha
            # pendencia nenhuma para esta continuar.
            reservados_da_resposta = await kinds_reservados(session_factory, message_id=message.id)
            if KIND_DA_RESPOSTA in reservados_da_resposta:
                return desfecho_da_recusa
            # Cai para fora do bloco e segue o turno. O contexto que
            # `montar_contexto` monta a seguir NAO inclui esta fala: o
            # `moderacao.resolver()` do topo deste bloco ja carimbou a linha
            # (ele chama `moderar_entrada_e_marcar`, que chama
            # `marcar_bloqueada`), e `literais_apos` filtra por
            # `bloqueada_em IS NULL`. Ha um uso de `corpo` daqui para baixo,
            # em `texto_com_oferta(corpo, texto)`, e ele nao expoe a fala
            # bloqueada: devolve o texto intacto a menos que
            # `perguntou_se_e_robo(corpo_do_lead)` seja verdadeiro, e nesse
            # caso o efeito e so a oferta de corretor ser anexada quando a
            # mensagem bloqueada tambem perguntava se o agente e um robo.
            log.info(
                "moderacao.recusa_com_resposta_pendente",
                message_id=str(message.id),
            )

    # TEC-275, D4. Antes de montar contexto de proposito: a continuacao nao
    # precisa de contexto, nao chama o classificador e nao chama `reagir` --
    # e e justamente por nao chamar `reagir` que ela nao fecha como NEUTRO as
    # pendentes da passada anterior.
    #
    # Tres ramos, e o do meio tem DUAS entradas -- so a primeira foi desenhada.
    #
    # (a) Nada saiu: a ficha que falhou foi a PRIMEIRA, entao nem as fichas nem
    # a prosa chegaram ao lead -- a prosa viaja junto com a ficha 1 e nao esta
    # persistida em lugar nenhum se nao chegou a sair. Continuar uma entrega em
    # que nada saiu nao e continuar; e recomecar.
    #
    # (b) Algo saiu, mas a linha da ficha que saiu nao pertence a ESTE lote.
    # `gravar_recomendacoes` usa `ON CONFLICT DO NOTHING` e nada exclui da
    # busca um imovel ja apresentado nesta conversa (nao ha anti-join contra
    # `recomendacoes` em `ferramenta_de_busca.py` nem em `catalogo/busca.py`, e
    # o docstring de `gravar_recomendacoes` chama a reapresentacao de
    # legitima). Um imovel repetido colide e a linha dele fica INTOCADA, com o
    # `message_id`, o `kind` e o `apresentado_em` da mensagem ANTERIOR. Se a
    # ficha que saiu foi justamente a dele, a reserva existe mas o kind dela
    # nao esta neste lote, a intersecao abaixo da vazia, e uma entrega PARCIAL
    # cai aqui: o turno inteiro roda de novo para um lead que ja recebeu uma
    # ficha. Nao e regressao -- a `main` fazia o mesmo --, e o conserto mexe na
    # semantica do UNIQUE e de `reacao_lead`, entao e card propria. Ver a L4 do
    # desenho, que registra tambem o que a reapresentacao ja custava antes.
    #
    # Em ambas as entradas as linhas orfas tem de ser APAGADAS, nao ignoradas:
    # o `ON CONFLICT DO NOTHING` da passada nova preservaria o carimbo velho, e
    # o UNIQUE por conversa impediria a linha nova de nascer.
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

    # TEC-371, D9. O agendamento pela conversa entra AQUI, e a posicao e
    # decisao, nao acaso. Tres coisas ficam garantidas pela ordem:
    #
    #   - ABAIXO das guardas de opt-out, de atendimento humano e de
    #     encerramento por escopo: todas vencem o agendamento, e um lead
    #     silenciado que escreve "quero marcar visita" continua silenciado.
    #   - ABAIXO da moderacao de entrada: fala recusada nao marca visita.
    #   - ACIMA de `montar_contexto` e da chamada ao modelo: o caminho de
    #     agendamento nao paga token nenhum, e continua funcionando com o
    #     provedor fora do ar. E a razao que `agendamento/deteccao.py` declara
    #     para ser deterministico.
    #
    # Le o estado com `ler_estado` direto, e nao pelo contexto: `criterio_de`
    # precisa so da qualificacao, e montar contexto inteiro -- resumo,
    # historico, ancora -- para um caminho que nao chama o modelo seria pagar
    # o caro para nao usar.
    #
    # **A funcao nao foi partida nesta card, e isto e um bloco e nao uma
    # trilha.** `_executar_turno` tem ~2837 linhas e 75,9% do ruido da
    # listagem de comentarios; partir a funcao e trabalho de outra natureza --
    # a ordem dos efeitos colaterais dela e o contrato, e um diff que mistura
    # a refatoracao com a primeira ligacao do agendamento a conversa nao e
    # revisavel nem em metade. O que esta card faz pelo problema e nao
    # agrava-lo: o que entra aqui e uma chamada e um retorno.
    if corpo:
        agenda_do_agendamento = AgendaPostgres(session_factory)
        async with session_factory() as sessao_do_agendamento:
            desfecho_do_agendamento = await atender_agendamento(
                sessao_do_agendamento,
                channel=message.channel,
                conversation_key=message.conversation_key,
                texto=corpo,
                estado=await ler_estado(
                    sessao_do_agendamento, message.channel, message.conversation_key
                ),
                agora=datetime.now(UTC),
                agenda=agenda_do_agendamento,
                visitas=agenda_do_agendamento,
            )
            if not isinstance(desfecho_do_agendamento, NadaAFazerNoAgendamento):
                # O commit acontece DENTRO do `async with`, e o enfileiramento
                # depois dele: a card exige essa ordem, e o motivo e que um
                # job consumido antes do commit nao encontra a linha.
                await sessao_do_agendamento.commit()
        if isinstance(desfecho_do_agendamento, AgendamentoConfirmado):
            await agendador_de_avisos.confirmacao(desfecho_do_agendamento.agendamento_id)
            # Sem texto de proposito (D6): quem manda a confirmacao ao lead e
            # o job da RN-12.1, ja com data, hora, endereco e nome do
            # corretor. Uma mensagem nossa aqui seria a segunda dizendo a
            # mesma coisa, com menos dados.
            log.info(
                "turno.agendamento_confirmado",
                channel=message.channel,
                message_id=str(message.id),
                agendamento_id=str(desfecho_do_agendamento.agendamento_id),
            )
            return "agendamento_confirmado"
        if isinstance(desfecho_do_agendamento, AgendamentoCancelado):
            # TEC-372. O aviso ao corretor e job pela mesma razao que o da
            # confirmacao: manter uma chamada SMTP dentro do turno poria a
            # latencia do lead na mao do servidor de e-mail. Depois do
            # commit, como o outro.
            await agendador_de_avisos.cancelamento(desfecho_do_agendamento.agendamento_id)
            log.info(
                "turno.agendamento_cancelado",
                channel=message.channel,
                message_id=str(message.id),
                agendamento_id=str(desfecho_do_agendamento.agendamento_id),
            )
        if isinstance(
            desfecho_do_agendamento,
            AgendamentoOferecido
            | AgendamentoReservado
            | AgendamentoPerguntou
            | AgendamentoPresencaConfirmada
            | AgendamentoCancelado
            | EsperaOferecida
            | EsperaAceita,
        ):
            entrega_do_agendamento = await _entregar_texto_fixo(
                session_factory,
                message=message,
                outbound=outbound,
                recorder_texto=desfecho_do_agendamento.texto,
                kind=KIND_DO_AGENDAMENTO,
                subagent=SUBAGENTE_AGENDAMENTO,
            )
            # So o desfecho FELIZ vira o valor proprio. "reentrega_suprimida",
            # "expirado" e "sem_resposta" continuam com o nome que ja tinham:
            # sao fatos sobre a porta de saida, nao sobre o agendamento, e
            # renomea-los aqui os tiraria das contagens que ja existem.
            if entrega_do_agendamento == "respondido":
                # Tres desfechos felizes e tres valores, pelo criterio que
                # todo o `Literal` segue: presenca confirmada e cancelamento
                # sao fatos diferentes de uma oferta de horario, e soma-los
                # tornaria impossivel medir quantas visitas a conversa
                # derruba.
                if isinstance(desfecho_do_agendamento, AgendamentoCancelado):
                    return "agendamento_cancelado"
                if isinstance(desfecho_do_agendamento, AgendamentoPresencaConfirmada):
                    return "presenca_confirmada"
                # TEC-169. Os dois da lista de espera, separados um do outro e
                # de "agendamento_oferecido" pelo criterio que o `Literal`
                # declara: a oferta e o aceite medem coisas diferentes, e
                # nenhuma delas e uma oferta de horario.
                if isinstance(desfecho_do_agendamento, EsperaAceita):
                    return "espera_aceita"
                if isinstance(desfecho_do_agendamento, EsperaOferecida):
                    return "espera_oferecida"
                return "agendamento_oferecido"
            return entrega_do_agendamento

    # A fronteira de historico da TEC-130 (D4) nao entra por aqui: quem decide
    # dobrar a conversa anterior inteira e `montar_contexto`, olhando para os
    # proprios literais -- ver `_fronteira_do_silencio`, em
    # `context/montagem.py`. Passar um predicado sobre `message` daqui e o que
    # a rodada final de revisao derrubou: numa rajada a mensagem que carrega o
    # turno e a MAIS NOVA do lote, e ela enxerga a irma de segundos atras, de
    # modo que `e_conversa_nova` devolvia False exatamente na reabertura em
    # que a dobra tinha de acontecer.
    #
    # TEC-129, D4: os `pares_vinculados` absorvidos abaixo entram nos literais
    # que `_fronteira_do_silencio` olha -- o silencio entre a ultima fala web e
    # a primeira do WhatsApp pode ser o ultimo intervalo e disparar a dobra ja
    # no primeiro turno do WhatsApp. A dobra continua escrevendo so no resumo
    # do par do WhatsApp (nunca no par web).
    #
    # TEC-129, D4. So no WhatsApp, que e o lado autenticado: a Meta garante o
    # numero, o site nao garante nada (D1). O turno web NUNCA passa por aqui.
    # Se passasse, o que aconteceria nao e o agente web conhecer o WhatsApp --
    # o estado que ele le continua sendo o do par web -- e sim a absorcao
    # procurar um telefone para a chave da sessao: se achasse um, criaria uma
    # linha `whatsapp` fantasma com essa chave e poria na janela do turno web
    # as falas de OUTRAS sessoes vinculadas a esse numero, de outra pessoa.
    # Desde a TEC-203 a chave e um HMAC sem identidade no canal WhatsApp e a
    # revelacao falharia, mas o gate nao depende disso. A funcao recusa o canal por
    # conta propria tambem (`channel=`); o gate aqui e o que evita ate a
    # chamada. Roda antes de `montar_contexto` porque e la que o estado e lido:
    # preenchido aqui, ele ja chega completo.
    #
    # `except Exception` amplo, no molde da captura de reacao logo abaixo: a
    # absorcao e enriquecimento, e o lead que falha nela perde o historico do
    # site NESTE turno, nao o atendimento. O turno seguinte tenta de novo --
    # a absorcao e idempotente.
    pares_vinculados: tuple[tuple[str, str], ...] = ()
    if message.channel == CANAL_WHATSAPP:
        try:
            pares_vinculados = await absorver_sessoes_vinculadas(
                session_factory,
                channel=message.channel,
                conversation_key=message.conversation_key,
            )
        except Exception:
            log.exception(
                "turno.absorcao_falhou",
                channel=message.channel,
                message_id=str(message.id),
            )
            pares_vinculados = ()
        if pares_vinculados:
            log.info(
                "turno.sessoes_absorvidas",
                channel=message.channel,
                message_id=str(message.id),
                sessoes=len(pares_vinculados),
            )
    try:
        contexto = await montar_contexto(
            session_factory,
            channel=message.channel,
            conversation_key=message.conversation_key,
            resumidor=resumidor,
            contador=contador,
            pares_vinculados=pares_vinculados,
            # O instante da fala a que o turno responde, e nao o relogio: o
            # que o site disse depois dela nao entra (ver `literais_apos`).
            ate_das_vinculadas=message.created_at,
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
        # sem resultado), uma excecao no meio do turno, uma desambiguacao que
        # adia as fichas, ou (desde a TEC-137) o encaminhamento por intencao,
        # que exclui `apresentando` para nao devolver ficha de catalogo a quem
        # esta indo para a fila humana. Quando isso acontece, o aviso nao fica
        # adiado para o proximo turno: ele se PERDE para sempre. O `bairros_antes_da_
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
            # `embedar_do_turno` e nao `embedar`: teto de 10s e sem
            # retentativa, contra os 50s com retentativa da indexacao. Esta
            # busca divide o `job_timeout` com cinco chamadas pagas (TEC-228).
            embedador=embedar_do_turno,
            channel=message.channel,
            conversation_key=message.conversation_key,
        ),
    )
    # TEC-153, RN-07.1. Do SEGUNDO turno do investidor em diante nao ha
    # chamada extra: a intencao anterior ja esta no estado, que `montar_contexto`
    # leu antes desta linha, entao o prompt e o schema do investidor sao
    # escolhidos aqui e a chamada continua sendo uma so.
    #
    # `contexto.estado.intencao` e a coluna (str), e nao o enum -- por isso a
    # comparacao e contra `.value`.
    ja_e_investidor = (
        contexto.estado is not None and contexto.estado.intencao == Intencao.INVESTIMENTO.value
    )
    # As duas irmas tem assinatura identica (`ClassificadorPort` declara as
    # duas assim, e o comentario de la diz por que): a escolha cabe num unico
    # ponto de chamada, e nao em dois blocos que teriam de ser mantidos em
    # sincronia. A anotacao existe porque o mypy nao une sozinho dois
    # callables que so diferem no tipo de retorno.
    chamada: Callable[..., Awaitable[RespostaDoAgente | RespostaDoInvestidor]] = (
        classificador.qualificar_investidor if ja_e_investidor else classificador.classificar
    )
    try:
        gerada = await chamada(
            contexto,
            # A porta e montada aqui porque e aqui que existe `session_factory`.
            # O classificador recebe um callable pronto e nao sabe o que e uma
            # sessao -- D3 do desenho.
            #
            # `embedador=embedar_do_turno` liga a busca do turno ao provedor de
            # verdade -- o MESMO provedor que `indexar_catalogo` usa para o
            # catalogo, com o mesmo modelo e as mesmas dimensoes, so que com o
            # teto e as tentativas do turno (TEC-228). Fossem clientes de
            # modelos diferentes, o vetor da consulta nao viveria no mesmo
            # espaco dos vetores indexados e a similaridade seria ruido.
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
            # TEC-153. Quem estourou o laco foi a chamada que `ja_e_investidor`
            # escolheu, e o rotulo tem de dizer qual trilha o turno era -- do
            # contrario o custo e as falhas da trilha do investidor apareceriam
            # no balde do classificador. Mesma regra do `else` do ramo, abaixo.
            subagent=SUBAGENTE_INVESTIDOR if ja_e_investidor else SUBAGENTE_CLASSIFICADOR,
        )
    except ProvedorIndisponivel:
        # TEC-209, D3. A cadeia ja retentou o primario e tentou o secundario:
        # nao propaga, pelo argumento do `LacoDeBuscaExcedido` acima -- o
        # sweeper refaria a cadeia inteira para chegar ao mesmo lugar, e o
        # lead ficaria em silencio ate a quinta falha. Espera honesta com
        # handoff, agora.
        log.warning("turno.provedor_indisponivel", channel=message.channel)
        return await _degradar_por_provedor(
            session_factory,
            message=message,
            outbound=outbound,
            agendador=agendador,
            subagent=SUBAGENTE_INVESTIDOR if ja_e_investidor else SUBAGENTE_CLASSIFICADOR,
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
    # TEC-149, RN-05.5. Depois da geracao, porque depende de `gerada.perguntou`;
    # antes do bloco transacional, porque e ele quem registra o handoff.
    #
    # **O nome diz o escopo, e o par tem de ser lido junto** (TEC-153). Desde a
    # virada do investidor sao DOIS tetos, e os nomes sao simetricos de
    # proposito -- `teto_do_handoff` e `teto_da_entrega` -- para ninguem ter de
    # ler comentario para escolher entre dois nomes parecidos que guardam
    # decisoes diferentes:
    #
    # - `teto_do_handoff` (este): "o turno QUIS perguntar demais". Le a chamada
    #   1, que e a unica que existe aqui -- a do investidor depende de
    #   `gerada.intencao` e so acontece depois. Registra o handoff.
    # - `teto_da_entrega` (la embaixo): "o texto ENTREGUE contem pergunta que
    #   passa do teto". Le `resposta_do_turno`. Substitui o texto e trava a
    #   marca pos-entrega.
    #
    # Nos caminhos que nao sao a virada os dois valem o mesmo. Na virada eles
    # divergem, e o comentario do `if teto_da_entrega:` la embaixo explica o
    # que fecha o buraco quando a divergencia cai para o lado de haver texto do
    # teto sem handoff -- que seria prometer corretor e nao registrar nenhum.
    # Registrar o handoff a partir da chamada 1 e conservador e ja tinha
    # precedente declarado: o comentario do `if teto_do_handoff:` abaixo diz
    # por que ele nasce mesmo nos turnos em que o texto do teto nao sai.
    teto_do_handoff = excedeu_o_teto(
        contexto.estado.perguntas_feitas if contexto.estado is not None else 0,
        len(perguntas_contaveis(gerada.perguntou)),
        # TEC-198, D4: o teto vigente, do mesmo retrato que o turno inteiro usa.
        teto=contexto.configuracao.teto_de_perguntas,
    )
    # TEC-174, fix wave (Important 2). Os tres ficam None quando a condicao que
    # os preenche nao roda -- e viram o `HandoffRegistrado` de `registrar_handoff`
    # quando roda. `registrar_handoff` nao loga mais (ver o comentario de la);
    # quem loga e este modulo, e so DEPOIS do commit abaixo.
    handoff_do_quente: HandoffRegistrado | None = None
    handoff_da_intencao: HandoffRegistrado | None = None
    handoff_do_teto: HandoffRegistrado | None = None
    async with session_factory() as session:
        anterior = await ler_intencao(session, message.channel, message.conversation_key)
        # TEC-138, RN-03.5. O retorno e `fora_de_escopo_seguidas`
        # pos-incremento -- o numero que este mesmo statement acabou de
        # gravar. Zero em toda intencao que nao seja FORA_DE_ESCOPO (o `else`
        # de `gravar_intencao`), e por isso `deve_encerrar` abaixo nao precisa
        # reperguntar qual foi a intencao deste turno: voltar ao assunto ja
        # zerou a contagem aqui dentro.
        #
        # **O contador conta a intencao EFETIVA, e a coluna continua crua**
        # (fix da revisao final, Important 3, ruling R11). `gerada.intencao` vai
        # inteiro para a coluna, porque e do par (palpite, confianca) que a
        # TEC-210 precisa; o que decide o encerramento passa por
        # `intencao_efetiva`, que abaixo de `LIMIAR_DE_DESAMBIGUACAO` devolve
        # `INDEFINIDA`. A razao e a convencao do repo, escrita na docstring
        # daquela funcao: o palpite de baixa confianca e "operacionalmente
        # `INDEFINIDA`", e a TEC-136 e a TEC-137 ja leem por ela. Esta card era
        # a unica a decidir sobre o valor cru -- e o que ela decide sao 30 dias
        # de silencio. O caso e alcancavel: duas mensagens fora de escopo
        # confiantes e uma terceira de baixa confianca, que e tambem o turno em
        # que `desambiguando` la embaixo quer PERGUNTAR -- contando o cru, a
        # despedida substituiria justamente a pergunta que resolveria a
        # ambiguidade.
        fora_de_escopo_seguidas = await gravar_intencao(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            confianca=gerada.confianca,
            modelo=gerada.modelo,
            fora_de_escopo_efetivo=(
                intencao_efetiva(gerada.intencao, gerada.confianca) is Intencao.FORA_DE_ESCOPO
            ),
        )
        # RN-03.5. A terceira mensagem fora de escopo seguida encerra -- mas
        # aqui so se DECIDE. **A gravacao mora depois da entrega confirmada**,
        # no bloco `if encerrando ...` la embaixo, junto dos outros dois
        # registros pos-entrega. O nome fica aqui porque e aqui que existe a
        # contagem que decide, e porque a substituicao do texto e o
        # `apresentando` la embaixo dependem dele antes de a entrega comecar.
        #
        # **Por que a gravacao nao entra neste commit** (fix da revisao,
        # Important 2). Encerrar antes de entregar repetia, por uma terceira
        # porta, o defeito que este repo ja pagou duas vezes -- a confirmacao
        # de opt-out que "se perdia PARA SEMPRE" e o Critical 2 da TEC-143: o
        # envio levanta `EnvioRetentavel` (5xx da Meta), a excecao sobe, a
        # linha vira FAILED, o sweeper reenfileira a MESMA mensagem -- e no
        # turno 2 a guarda do topo ja lia ENCERRADA, devolvia "fora_de_escopo"
        # e a despedida nunca saia. Conversa encerrada, lead calado por 30
        # dias, sem nunca ter ouvido por que.
        #
        # A ordem inversa e barata aqui, e e essa a diferenca em relacao ao
        # opt-out: la o registro vale mais que o aviso porque nao registrar e
        # violacao de LGPD. Aqui, nao encerrar quando a entrega falha custa
        # UMA mensagem fora de escopo a mais -- a proxima sobe a contagem para
        # 4 e `deve_encerrar` encerra do mesmo jeito, porque ele usa `>=` e nao
        # `==` justamente para tolerar contagem acima do teto.
        #
        # **O que continua indivisivel e o par encerramento+zero**, que e o
        # que sustenta a docstring de `reabrir_conversa`: os dois vao juntos na
        # transacao curta de la embaixo, ou nenhum dos dois vai.
        #
        # **O zero e o que faz a maquina se fechar sozinha.** Durante a janela
        # a guarda do topo devolve ANTES de `gravar_intencao`, entao o contador
        # nao anda; vencida a janela a guarda reabre e segue, e a contagem
        # recomeca do zero. Sem ele o lead que volta depois dos 30 dias iria de
        # 3 para 4 e seria encerrado na PRIMEIRA mensagem, sem nenhuma das tres
        # tentativas que a regra lhe da.
        #
        # **O zero nao e a prova de que ninguem mais escreve o contador**, e a
        # folga esta declarada: dois turnos concorrentes da MESMA conversa,
        # ambos fora de escopo, podem ter passado a guarda do topo antes do
        # encerramento. O segundo espera o cadeado de linha que
        # `gravar_intencao` tomou, le o zero e grava 1 -- conversa encerrada
        # com contador em 1. O dano e limitado e conhecido: passada a janela, o
        # lead tem duas tentativas em vez de tres. E a mesma corrida que o
        # `>=` de `deve_encerrar` ja admite existir, e o conserto dela seria
        # serializar o turno inteiro por conversa, caro demais para uma
        # tentativa a menos.
        encerrando = deve_encerrar(fora_de_escopo_seguidas)
        # TEC-136, RN-03.3. **Antes de `gravar_estado`, e a ordem e o desenho.**
        # Esta chamada anula a faixa de preco quando a banda de plausibilidade
        # muda; o upsert de `gravar_estado` vem depois e escreve por cima o
        # numero novo quando o lead o disse no MESMO turno ("na verdade quero
        # comprar, ate 800 mil"). Invertidas, o descarte apagaria justamente o
        # numero que o lead acabou de dar.
        #
        # **E antes de `registrar_recalculo` pela outra metade da razao.**
        # Aquele toma o mesmo `SELECT ... FOR UPDATE` de `lead_qualification`;
        # tomar o cadeado aqui primeiro preserva a ordem de aquisicao, que e o
        # que sustenta o "nao cria deadlock novo" da docstring de
        # `aplicar_mudanca_de_intencao`. As duas metades estao escritas la por
        # extenso -- quem for mover esta linha leia aquela docstring antes.
        mudanca = await aplicar_mudanca_de_intencao(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
        )
        depois_do_estado = await gravar_estado(
            session,
            channel=message.channel,
            conversation_key=message.conversation_key,
            intencao=gerada.intencao,
            extracao=gerada.extracao,
            recusou=gerada.recusou,
        )
        # TEC-190, D3. O carimbo entra AQUI, dentro da transacao, e nao junto
        # do `log.info("lead.qualificado", ...)` la embaixo. Os dois marcam a
        # mesma travessia e a posicao de cada um segue do que ele e: o log
        # existe para quem le o log, e sai depois do commit porque "logar uma
        # transicao que o rollback desfez e mentir para quem le o log"; a
        # coluna e DADO, e se a transacao volta atras a qualificacao nao
        # aconteceu e o carimbo tem de voltar junto.
        #
        # Nao introduz ordem de lock nova: `gravar_estado`, uma linha acima,
        # ja deixou esta transacao com a linha de `lead_qualification` na
        # mao. Ver os comentarios acima de `aplicar_mudanca_de_intencao`
        # sobre a ordem de aquisicao ser carga e nao acaso.
        if depois_do_estado is not None and esta_qualificado(
            depois_do_estado, _recusados_de(depois_do_estado)
        ):
            await carimbar_qualificacao(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                quando=datetime.now(UTC),
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
            # TEC-136. A troca de intencao pode nao mexer em nenhum dos cinco
            # fatores, e a tupla vazia de `causas_do_recalculo` seria o sinal
            # de nao gravar -- a mudanca sumiria da trilha. Informada aqui, ela
            # e razao propria para a linha existir; a docstring de
            # `registrar_recalculo` explica por que a uniao vem antes da guarda.
            causas_externas=(CAUSA_MUDANCA_DE_INTENCAO,) if mudanca is not None else (),
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
                ator=ATOR_AGENTE,
            )

        if (gatilho_da_intencao := _GATILHO_DA_INTENCAO.get(gerada.intencao)) is not None:
            handoff_da_intencao = await registrar_handoff(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=gatilho_da_intencao,
                ator=ATOR_AGENTE,
            )

        if teto_do_handoff:
            # Registrado aqui mesmo nos turnos em que o texto do teto NAO vai
            # sair. Das guardas da substituicao la embaixo, `saida_bloqueada`
            # de fato nao existe ainda neste ponto -- depende da chamada de
            # moderacao de saida, que so roda depois. O mesmo vale, desde a
            # TEC-153, para o proprio `teto_da_entrega`: ele le a resposta
            # ENTREGUE, e na virada do investidor ela so existe depois do ramo,
            # bem abaixo deste bloco. `desambiguando` e
            # diferente: ele depende de `anterior`, que este mesmo bloco ja leu
            # (`ler_intencao`, logo acima), entao dar hoisting nele seria
            # possivel. A escolha e nao fazer isso -- `desambiguando` mora perto
            # de onde e usado, e duplicar a leitura de `anterior` aqui so para
            # antecipar uma guarda economizaria uma variavel as custas de dois
            # lugares para manter em sincronia. A assimetria e deliberada e nao
            # um esquecimento: o handoff nasce, o lead recebe o texto no proximo
            # turno que qualificar, e `registrar_handoff` e idempotente --
            # nenhum handoff duplicado aparece. Nao mova isto para baixo para
            # emparelhar as condicoes.
            handoff_do_teto = await registrar_handoff(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                gatilho=Gatilho.LIMITE_DE_PERGUNTAS,
                ator=ATOR_AGENTE,
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

    # TEC-149, RN-05.5. Depois do commit acima, pelo mesmo motivo dos outros
    # dois: logar um handoff que o rollback desfez e mentir para quem le o
    # log. `registrar_handoff` nao loga -- quem loga e este modulo.
    if handoff_do_teto is not None:
        log.info(
            "handoff.criado" if handoff_do_teto.criado else "handoff.gatilho_adicional",
            channel=message.channel,
            gatilho=Gatilho.LIMITE_DE_PERGUNTAS.value,
            etiqueta=ETIQUETA_DE[Gatilho.LIMITE_DE_PERGUNTAS],
            prioridade=PRIORIDADE_DE[Gatilho.LIMITE_DE_PERGUNTAS].value,
        )
        await _agendar_resumo(agendador, handoff_do_teto)

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
    # a borda e cruzada de novo, para o MESMO lead. O evento reemite.
    #
    # **O LOG continua reemitindo, e a METRICA nao (TEC-190).** A card dona da
    # RN-17.1 criou o estado persistido que este comentario declarou faltar:
    # `qualificado_em`, carimbado mais acima dentro da transacao, com guarda
    # `IS NULL` no proprio UPDATE. A ida-e-volta descrita acima faz este `if`
    # disparar duas vezes e o carimbo NAO se mover. Quem conta lead
    # qualificado le a coluna, nao este log.
    if not antes and esta_qualificado(depois_do_estado, _recusados_de(depois_do_estado)):
        log.info(
            "lead.qualificado",
            channel=message.channel,
            message_id=str(message.id),
        )

    # A borda, e nao o estado: um lead que continua QUENTE nao reemite, senao
    # a RN-06.5 viraria um ping por mensagem. `recalculo.anterior` sai da
    # coluna `temperatura`, e nao da trilha de auditoria -- a trilha tem
    # retencao de 12 meses (RNF-18), entao um lead cujo ultimo registro fosse
    # expurgado voltaria a parecer nunca-calculado e reemitiria como se
    # tivesse acabado de esquentar. Ate a TEC-136 este argumento vinha com uma
    # segunda perna, "a trilha grava so quando o score muda", que deixou de
    # ser verdade quando `causas_externas` passou a gravar linha com os cinco
    # fatores parados; ela nao faz falta, e a retencao sozinha ja fecha o
    # caso. (`anterior`, sem prefixo, e OUTRA variavel nesta funcao -- a linha
    # de intencao que `ler_intencao` devolveu, la em cima; nao confundir as
    # duas.)
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
    # TEC-153. A virada: a intencao passou a ser INVESTIMENTO NESTE turno e
    # nao era antes. So aqui ha segunda chamada -- nos turnos seguintes
    # `ja_e_investidor`, la em cima, ja escolheu o prompt certo para a chamada
    # unica. `anterior` e a linha que `ler_intencao` devolveu dentro do bloco
    # transacional acima, a mesma leitura que `desambiguando` usa.
    #
    # **`not ja_e_investidor` nao e redundante com o resto da expressao.** As
    # duas condicoes leem FONTES DIFERENTES do mesmo fato: `ja_e_investidor`
    # le `lead_qualification.intencao` (o estado que montou o prompt) e
    # `anterior` le `conversation_intent` (o que o classificador disse no
    # turno passado). Elas divergem por desenho, nao por bug: `gravar_intencao`
    # grava INDEFINIDA em `conversation_intent`, e `campos_a_gravar` NAO deixa
    # INDEFINIDA sobrescrever a coluna do estado (TEC-147). Um investidor que
    # mande um "obrigado" no meio da conversa deixa `conversation_intent` em
    # INDEFINIDA e a coluna em INVESTIMENTO -- e no turno seguinte a chamada
    # unica ja seria a do investidor e ESTA expressao, sem a guarda, pediria
    # uma segunda. Duas chamadas do investidor no mesmo turno, a primeira paga
    # e jogada fora, num turno que a RN-07.1 promete ser de chamada unica.
    virou_investidor = (
        not ja_e_investidor
        and gerada.intencao is Intencao.INVESTIMENTO
        and (anterior is None or anterior.intencao is not Intencao.INVESTIMENTO)
    )
    # Anotado explicitamente: sem isso o mypy infere o tipo de `telemetria` a
    # partir so do primeiro ramo que ve (`PerguntaDeDesambiguacao`) e recusa a
    # atribuicao dos outros. Os tres tipos so precisam ter em comum os campos
    # de telemetria que `record_agent_message` le abaixo.
    texto: str
    telemetria: RespostaDoAgente | PerguntaDeDesambiguacao | RespostaDoInvestidor
    subagente: str
    # TEC-153. A resposta de modelo de que as decisoes ABAIXO dependem: a que
    # de fato foi entregue, e nao a que foi paga. Em todo caminho menos a
    # virada ela E `gerada` -- inclusive no turno seguinte do investidor, em
    # que `ja_e_investidor` ja fez de `gerada` a resposta do subagente.
    #
    # Existe porque na virada `gerada` foi descartada, e daqui para baixo TUDO
    # o que o turno decide sobre busca e sobre pergunta lia dela: a
    # substituicao pelo texto do teto, a guarda de citacao, `apresentando`, as
    # fichas que saem, os criterios gravados e os avisos de ampliacao. Ou o
    # bloco inteiro le a mesma resposta, ou o turno mistura duas -- fichas de
    # uma busca com a prosa de outra.
    #
    # A pior era a citacao: comparar a prosa do INVESTIDOR contra os
    # candidatos da busca GENERICA bloqueia como alucinacao um imovel que a
    # busca do investidor de fato achou, e o lead recebe o texto de fallback
    # no lugar da resposta certa -- o falso positivo que a doc de `citacao.py`
    # diz nao poder ter.
    #
    # A desambiguacao continua excluida por `not desambiguando` nas mesmas
    # condicoes, e nao migra para ca: `PerguntaDeDesambiguacao` nao tem
    # candidato nem `perguntou` nenhum, entao excluir o CAMINHO e a resposta
    # certa la. O investidor busca e apresenta como a trilha padrao -- excluir
    # o caminho dele calaria uma capacidade que o desenho lhe da; o que ele
    # precisa e que estas linhas leiam a resposta CERTA.
    resposta_do_turno: RespostaDoAgente | RespostaDoInvestidor = gerada
    if desambiguando:
        # A resposta da chamada 1 foi escrita assumindo um palpite que a
        # confianca nao sustenta. Ela e descartada -- paga e nao entregue.
        pergunta = await classificador.desambiguar(contexto)
        texto, telemetria, subagente = pergunta.texto, pergunta, SUBAGENTE_DESAMBIGUADOR
    elif virou_investidor:
        # **A ORDEM DOS RAMOS E A PRECEDENCIA, e nao acidente de escrita.** Com
        # o turno ambiguo E investidor ao mesmo tempo, desambigua: sem intencao
        # confiavel nao ha trilha a escolher (D1), e chamar o subagente do
        # investidor sobre um palpite que a confianca nao sustenta gastaria a
        # chamada e ainda erraria a trilha. Nao reordene estes dois ramos.
        #
        # A resposta da chamada 1 foi escrita pelo prompt generico: ela
        # pergunta metragem e quartos, que e exatamente o que a RN-07.1 existe
        # para evitar. Descartada -- paga e nao entregue --, como no ramo da
        # desambiguacao e pelo mesmo motivo estrutural: o prompt precisa de um
        # fato que so a primeira chamada produz.
        try:
            do_investidor = await classificador.qualificar_investidor(contexto, porta=porta)
        except ProvedorIndisponivel:
            # TEC-209, D3. A virada divide o prazo com a chamada 1, entao
            # pode esgotar mesmo com a chamada 1 tendo respondido. Mesma
            # espera com handoff do ramo de cima -- a resposta da chamada 1
            # nao serve, pela razao escrita logo acima.
            log.warning("turno.provedor_indisponivel", channel=message.channel)
            return await _degradar_por_provedor(
                session_factory,
                message=message,
                outbound=outbound,
                agendador=agendador,
                subagent=SUBAGENTE_INVESTIDOR,
            )
        texto, telemetria, subagente = (
            do_investidor.resposta,
            do_investidor,
            SUBAGENTE_INVESTIDOR,
        )
        # O unico caminho em que `resposta_do_turno` deixa de ser `gerada`.
        resposta_do_turno = do_investidor
    else:
        texto, telemetria, subagente = (
            gerada.resposta,
            gerada,
            # TEC-153. O rotulo diz qual PROMPT gerou o texto, e nao qual ramo
            # rodou: do segundo turno do investidor em diante e este `else` que
            # entrega a resposta do subagente, porque `ja_e_investidor` escolheu
            # o prompt dele la em cima. Rotular esses turnos de "classificador"
            # faria a telemetria mostrar a trilha do investidor acontecendo
            # so nas viradas, e quem lesse o painel nao teria
            # como saber o que a trilha custa nem quantos turnos ela atende.
            SUBAGENTE_INVESTIDOR if ja_e_investidor else SUBAGENTE_CLASSIFICADOR,
        )

    # **A resposta de modelo acima ainda esta de pe?** (TEC-272, revisao
    # final.) Seis blocos abaixo TROCAM `texto` por constante deste
    # repositorio, e cada um deles marca esta flag. Nos tres ramos acima a
    # resposta e do modelo -- inclusive a pergunta do desambiguador e a prosa
    # do subagente do investidor, que sao texto gerado e nao substituicao --,
    # entao ela nasce False.
    #
    # Quem le isto e o append da oferta de corretor, la embaixo: a precondicao
    # do CA-04.1 e o agente CONFIRMAR ser assistente virtual, e uma resposta
    # substituida por texto nosso nao confirma nada. Ver o comentario de la
    # para o que acontecia sem esta guarda.
    #
    # A flag e o mecanismo, e nao uma lista de trilhas, de proposito: a proxima
    # substituicao deterministica marca-a junto com as outras seis, e o append
    # continua certo sem que ninguem se lembre dele.
    #
    # **O que ela afirma e PROCEDENCIA, e isso e um proxy direcional -- lacuna
    # declarada, nao conserto pendente.** "Substituido => nao confirmou" vale
    # sempre; a reciproca nao. Os ramos `desambiguando` e `virou_investidor`
    # entregam texto do modelo, entao a flag nasce False e o append roda --
    # so que `SISTEMA_DA_DESAMBIGUACAO` manda "Escreva uma unica pergunta" e
    # "Devolva apenas o texto da pergunta", e pergunta nenhuma confirma ser
    # assistente virtual. E pre-existente ao conserto de Important 1 e o dano e
    # baixo: a oferta gruda numa pergunta aberta, sem contradizer nada do que o
    # turno acabou de dizer -- diferente das tres trilhas deterministicas, em
    # que ela contradizia. Esta declarada nas "Lacunas declaradas" do desenho.
    texto_substituido = False

    if isinstance(telemetria, RespostaDoInvestidor):
        # Transacao propria, e nao o bloco transacional la de cima: os campos
        # do investidor so existem depois da chamada que os produz, e aquele
        # bloco ja commitou. Antes da entrega, e nao depois, porque sao fato
        # sobre a fala do LEAD -- perde-los numa falha de entrega apagaria o
        # que ele acabou de responder. E a mesma razao pela qual `recusou`
        # entra no commit pre-entrega e `perguntou` nao.
        #
        # O `isinstance` cobre os DOIS caminhos do investidor: o ramo da
        # virada logo acima e o turno seguinte, em que `ja_e_investidor` fez
        # de `gerada` -- e portanto de `telemetria`, pelo `else` -- a propria
        # resposta do investidor.
        async with session_factory() as session:
            await gravar_investidor(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                investidor=telemetria.investidor,
            )
            await session.commit()

    # Uma vez por turno: so um texto vem do modelo. No caminho ambiguo a
    # resposta da chamada 1 foi descartada e so a pergunta e entregue; na
    # virada do investidor (TEC-153) o descarte e o mesmo e quem e moderado e
    # a prosa do subagente -- em qualquer dos tres caminhos `texto` ja e o
    # unico texto candidato a sair, e e por isso que esta chamada nao precisa
    # saber qual deles rodou. Na
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
        texto_substituido = True

    # TEC-153. A outra metade da pergunta que `teto_do_handoff` fazia sozinho, e
    # agora sobre a resposta ENTREGUE: o texto que vai sair contem pergunta que
    # passa do teto? Em todo caminho menos a virada este valor e igual ao de
    # cima, porque `resposta_do_turno is gerada`. Na virada eles divergem nos
    # dois sentidos: a chamada 1 pode ter perguntado e o subagente nao (e
    # substituir calaria uma resposta que nao pergunta nada), ou o contrario
    # (e nao substituir entregaria a nona pergunta que a RN-05.5 proibe).
    teto_da_entrega = excedeu_o_teto(
        contexto.estado.perguntas_feitas if contexto.estado is not None else 0,
        len(perguntas_contaveis(resposta_do_turno.perguntou)),
        # TEC-198, D4: o teto vigente, do mesmo retrato que o turno inteiro usa.
        teto=contexto.configuracao.teto_de_perguntas,
    )
    if teto_da_entrega and not desambiguando and not saida_bloqueada:
        # A prosa do modelo nao sai: ela contem a pergunta que o teto proibe,
        # e nao da para entregar meia pergunta -- a prosa e um texto so.
        # Substituicao em lugar, como a moderacao de saida faz logo acima.
        #
        # `not desambiguando`: a RN-05.5 limita pergunta de QUALIFICACAO, e
        # nesse caminho quem sai e a pergunta do desambiguador --
        # `resposta_do_turno.perguntou` fala da chamada 1, que foi DESCARTADA,
        # pela mesma razao que `apresentando` logo abaixo a exclui. (A virada
        # do investidor nao precisa de exclusao equivalente: la
        # `resposta_do_turno` ja E a resposta entregue.) Sem isto, um
        # lead que bateu o teto nunca mais poderia ser desambiguado: toda
        # mensagem vaga receberia o texto do corretor em lugar da pergunta
        # que teria resolvido a intencao.
        #
        # `not saida_bloqueada`: `TEXTO_NEUTRO_DE_SAIDA` e a resposta
        # declarada da politica de moderacao de saida, e sobrepor a nossa a
        # ela tornaria impossivel saber depois qual das duas agiu. O teto nao
        # se perde: a guarda pos-entrega ja exclui `saida_bloqueada`, entao
        # nada foi contado, e o teto dispara normalmente no proximo turno sem
        # bloqueio.
        #
        # E NAO e a ultima palavra sobre `texto`: o encaminhamento por
        # intencao da TEC-137, a citacao bloqueada da TEC-161, o zero
        # pos-relaxamento da TEC-160 e a despedida do encerramento da TEC-138
        # reatribuem depois daqui e vencem. Esta certo assim -- politica mais
        # especifica ganha --, e as quatro substituem por constante NOSSA,
        # entao a pergunta que o teto suprimiu nao vaza por nenhuma delas.
        texto = TEXTO_DO_LIMITE_DE_PERGUNTAS
        texto_substituido = True

        if not teto_do_handoff:
            # **O texto promete corretor; sem isto, na virada, nao haveria
            # corretor nenhum para prometer.** Os dois tetos divergem so na
            # virada do investidor, e este e o sentido que machuca: a chamada 1
            # nao perguntou nada, entao `teto_do_handoff` foi False e o bloco
            # transacional la em cima nao registrou handoff; o subagente
            # perguntou e passou do teto, entao `teto_da_entrega` e True e o
            # lead recebe "prefiro passar para um corretor... já coloquei sua
            # conversa na fila deles" -- com linha nenhuma em `handoffs` para
            # alguem agir. Desde a TEC-286 o texto afirma a FILA em vez do
            # contato, o que torna este caso pior e nao melhor: a frase passou
            # a descrever uma linha de banco que, sem isto, nao existiria.
            #
            # E a falha da TEC-174 de novo, e pior: la o texto prometia um
            # aviso que nao existia; aqui nao existe nem o registro. O
            # comentario de `TEXTO_DO_LIMITE_DE_PERGUNTAS`, no topo deste
            # modulo, guarda essa historia. O handoff de intencao nao cobre o
            # turno: INVESTIMENTO nao esta em `_GATILHO_DA_INTENCAO`. O de
            # LEAD_QUENTE pode cobrir -- se o recalculo esquentou o lead neste
            # mesmo turno, ja existe linha em `handoffs` para alguem agir --,
            # mas isso e coincidencia e nao garantia: o teto nao sabe nada da
            # temperatura. Quando os dois acontecem no mesmo turno,
            # `registrar_handoff` e idempotente e esta chamada so acrescenta
            # LIMITE_DE_PERGUNTAS aos `gatilhos_adicionais` do registro que ja
            # existe.
            #
            # A contagem nao sobe (a guarda pos-entrega exclui
            # `teto_da_entrega`), entao sem esta linha o handoff so apareceria
            # num turno futuro em que o investidor perguntasse de novo -- uma
            # mitigacao que depende do modelo repetir o comportamento, o que
            # nao e garantia nenhuma.
            #
            # Transacao curta propria, como a de `gravar_investidor` logo
            # acima, e pelo mesmo motivo: o fato so existe depois do ramo, e o
            # bloco transacional de la em cima ja commitou. `registrar_handoff`
            # e idempotente, entao um retry do sweeper nao duplica.
            #
            # `not teto_do_handoff` e nao incondicional: com os dois True o
            # handoff ja nasceu no bloco transacional, com `_agendar_resumo`
            # junto -- repetir aqui so gastaria uma transacao para o mesmo
            # `gatilho_adicional`.
            async with session_factory() as session:
                handoff_da_entrega = await registrar_handoff(
                    session,
                    channel=message.channel,
                    conversation_key=message.conversation_key,
                    gatilho=Gatilho.LIMITE_DE_PERGUNTAS,
                    ator=ATOR_AGENTE,
                )
                await session.commit()
            log.info(
                "handoff.criado" if handoff_da_entrega.criado else "handoff.gatilho_adicional",
                channel=message.channel,
                gatilho=Gatilho.LIMITE_DE_PERGUNTAS.value,
                etiqueta=ETIQUETA_DE[Gatilho.LIMITE_DE_PERGUNTAS],
                prioridade=PRIORIDADE_DE[Gatilho.LIMITE_DE_PERGUNTAS].value,
            )
            await _agendar_resumo(agendador, handoff_da_entrega)

    # RN-03.4 (TEC-137). Precedencia ACIMA do teto de perguntas -- e por isso
    # este bloco vem DEPOIS dele, nao antes: neste trecho quem atribui `texto`
    # por ultimo e quem vence, e o bloco do teto acima atribui
    # `TEXTO_DO_LIMITE_DE_PERGUNTAS`. Quem vai para a fila de venda nao precisa
    # ouvir "Já perguntei bastante": o teto e sobre qualificacao, que estas duas
    # intencoes nao recebem.
    #
    # **Tres blocos abaixo reatribuem depois daqui, e so um deles alcanca o
    # lead encaminhado -- a diferenca esta medida, nao suposta.** O terceiro e
    # a despedida do encerramento (TEC-138), e ele nao alcanca por construcao:
    # `encerrando` exige que a contagem de fora de escopo tenha chegado ao
    # teto, e qualquer intencao EFETIVA que nao seja FORA_DE_ESCOPO zera essa
    # contagem em `gravar_intencao` -- entao ele e `encaminhou` sao mutuamente
    # exclusivos, e nao concorrentes. A efetiva so reforca a exclusao: um
    # VENDER_IMOVEL de baixa confianca vira INDEFINIDA e zera do mesmo jeito.
    # Dos outros dois: a citacao
    # bloqueada da TEC-161 roda sobre o `texto` JA substituido, e para os nossos
    # dois literais (com e sem o sufixo) `divergencias_de` devolve vazio: nenhum
    # deles carrega valor citavel. `valores_em` exige marca de dinheiro (`R$`,
    # "reais", palavra de magnitude), entao "9h" e "18h" nao sao preco, e
    # `_CODIGO` quer `[A-Z]{2,3}-\d{3,6}`. Ela vence por estrutura e e
    # inalcancavel na pratica. Ja o zero pos-relaxamento da TEC-160 le apenas
    # `resposta_do_turno.relaxou_sem_resultado` e nunca olha para o texto: ele
    # ALCANCA, e um lead de venda cujo turno relaxou e continuou sem resultado
    # recebe `TEXTO_SEM_RESULTADO_APOS_AMPLIAR` no lugar do encaminhamento.
    # Aceito e declarado (R5 da revisao final, e as lacunas declaradas do
    # desenho), nao esquecido: e raro e o lead ainda recebe resposta.
    #
    # O teto continua rodando primeiro, e o `gatilho_adicional`
    # LIMITE_DE_PERGUNTAS que ele registra no handoff que ja existe fica --
    # `registrar_handoff` e idempotente, e o gatilho a mais nao mente sobre
    # nada: a pergunta de fato foi suprimida. So o TEXTO e que e nosso.
    #
    # As mesmas duas guardas do bloco do teto (`not desambiguando` e
    # `not saida_bloqueada`), pelas mesmas razoes que o comentario dele escreve
    # por extenso -- ver la, e nao aqui: duas copias de uma razao so sao duas
    # coisas para manter em sincronia.
    #
    # Le `gerada.intencao` e nao `gatilho_da_intencao`, que tambem estaria em
    # escopo aqui (o walrus la em cima liga o nome no escopo da FUNCAO, nao no
    # do `async with`). A razao nao e alcance, e o que cada mapa responde:
    # `_GATILHO_DA_INTENCAO` responde "qual gatilho de handoff" e
    # `_TEXTO_DO_ENCAMINHAMENTO` responde "qual texto para o lead". Sao dois
    # objetos com o mesmo conjunto de CHAVES, e e por isso que os dois lados
    # disparam juntos -- o comentario do mapa, no topo do modulo, escreve por
    # extenso por que nao sao um so.
    #
    # Consequencia da D2 do desenho: isto roda em TODO turno com a intencao,
    # nao so no primeiro. O lead que insiste recebe a mesma frase de novo --
    # aceito, porque a alternativa devolveria ao modelo a palavra no segundo
    # turno, com ela a pergunta de qualificacao que a regra proibe.
    #
    # A condicao vira um nome porque a guarda pos-entrega la embaixo precisa
    # dela: esta e mais uma trilha em que o texto de `gerada` NAO foi o que
    # saiu, e marcar ou contar a pergunta suprimida queimaria o campo e o
    # orcamento do lead por uma pergunta que ele nunca viu.
    encaminhou = (
        gerada.intencao in _TEXTO_DO_ENCAMINHAMENTO and not desambiguando and not saida_bloqueada
    )
    if encaminhou:
        texto = _TEXTO_DO_ENCAMINHAMENTO[gerada.intencao]
        texto_substituido = True
        if not dentro_da_janela_de_atendimento(datetime.now(UTC)):
            settings_do_turno = get_settings()
            texto += SUFIXO_FORA_DA_JANELA.format(
                inicio=settings_do_turno.atendimento_horario_inicio,
                fim=settings_do_turno.atendimento_horario_fim,
            )

    # TEC-162, D4. Candidatos sem pergunta e turno de apresentacao. As tres
    # primeiras condicoes sao a mesma regra: pergunta adia as fichas.
    # `desambiguando` entra porque `resposta_do_turno.perguntou` fala da
    # chamada 1, que foi DESCARTADA nesse caminho -- o texto entregue e a
    # pergunta do desambiguador, e `PerguntaDeDesambiguacao` nao tem candidato
    # nenhum para apresentar. A virada do investidor nao entra: ela tem a sua
    # propria busca e as suas proprias fichas, e `resposta_do_turno` ja aponta
    # para elas.
    #
    # **`not encaminhou` (R6 da revisao final da TEC-137) e de outra natureza,
    # e por isso vale dizer por que.** As reatribuicoes de `texto` acima sao
    # todas do mesmo idioma -- quem atribui por ultimo vence --, e por isso
    # toda analise de precedencia desta branch passou reto por aqui:
    # `apresentando` NAO reatribui `texto`, ele o REAPROVEITA como prefixo de
    # legenda da primeira ficha (D16 da TEC-162). Nao ha ordem que resolva
    # isso, so exclusao.
    #
    # O que a exclusao impede: `tool_choice` e `auto` (`classificador.py`) e o
    # enum de `operacao` da ferramenta de busca tem "VENDA", entao nada impede
    # o modelo de buscar no mesmo turno em que classifica `VENDER_IMOVEL`. Com
    # candidato e sem pergunta, o proprietario recebia ate tres fichas do
    # catalogo de VENDA, e o encaminhamento ia junto truncado -- ou sumia, que
    # e o que `prosa_que_cabe` faz quando a ficha nao deixa espaco nem para a
    # reticencia. E o defeito da propria card numa forma mais forte: o dono
    # tratado como comprador, agora com o catalogo na mao.
    #
    # Destrava `identificar` (logo abaixo, que le `not apresentando`) nestes
    # turnos: o vendedor de primeiro contato passa a receber identificacao e
    # encaminhamento como UMA mensagem. Pretendido, e coberto por
    # `test_o_primeiro_contato_de_venda_com_candidatos_tambem_se_identifica`.
    #
    # **`not encerrando` (TEC-138) e da mesma natureza que o `not encaminhou`**
    # que o paragrafo acima explica, e entra pelo mesmo motivo: `apresentando`
    # nao REATRIBUI `texto`, ele o reaproveita como prefixo da legenda da
    # primeira ficha -- entao nenhuma ordem de substituicao resolve, so
    # exclusao. Sem isto, o lead da terceira mensagem fora de escopo receberia
    # a despedida colada (ou truncada) numa legenda, com ate tres fichas do
    # catalogo atras dela, e so depois os 30 dias de silencio. **Aqui
    # `encerrando` exclui sozinho**, e nao ha `not saida_bloqueada` ao lado que
    # cubra a folga: no turno que encerra com a saida bloqueada, o texto seria
    # o neutro da moderacao, e prefixar fichas do catalogo a ele antes de calar
    # por 30 dias e o mesmo absurdo. `tool_choice` e
    # `auto`, entao nada impede o modelo de buscar no mesmo turno em que
    # classifica FORA_DE_ESCOPO.
    apresentando = (
        bool(resposta_do_turno.candidatos)
        and not resposta_do_turno.perguntou
        and not desambiguando
        and not encaminhou
        and not encerrando
    )

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
        candidatos=resposta_do_turno.candidatos,
        faixa=_faixa_declarada(depois_do_estado or contexto.estado),
    )
    # TEC-136, fix wave. **A prosa deste turno foi gerada contra o prompt de
    # ANTES do descarte, e por isso a faixa de depois nao basta para julga-la.**
    # Num turno que descartou o orcamento, `depois_do_estado` existe e a faixa
    # dele e `(None, None)` -- que `_na_faixa` le como AUSENCIA de declaracao, e
    # nao como faixa aberta. Sozinha, ela transforma em divergencia todo valor
    # da prosa, inclusive o que o proprio prompt mostrou ao modelo (o comentario
    # acima registra que `montar_contexto` ate instrui o modelo a ecoa-lo).
    # Quem paga e o turno titular do Gherkin: "voce procurava aluguel ate
    # R$ 2.500, para compra qual seu orcamento?" vira `TEXTO_DA_BUSCA_INCONCLUSIVA`
    # e um ERROR de `citacao.bloqueada` num canal reservado a invencao do modelo.
    #
    # **Segunda passada, e nao troca de faixa.** Trocar por `contexto.estado`
    # seria mais curto e estaria errado no outro caso da mesma card: o lead que
    # diz "na verdade quero comprar, ate 800 mil" descarta E declara no mesmo
    # turno, e ai e a faixa NOVA que sustenta o eco -- ela nao esta em
    # `contexto.estado`. O que se quer e a uniao ("o lead declarou este valor
    # antes OU depois desta fala"), e uma tupla `(min, max)` unica nao a
    # expressa quando as duas faixas tem pontas abertas diferentes. Duas
    # passadas com a intersecao das divergencias dizem exatamente isso.
    #
    # Roda so quando ha divergencia E houve descarte: o turno comum paga uma
    # chamada, como antes.
    if divergencias and mudanca is not None and mudanca.faixa_descartada:
        sob_a_faixa_de_antes = divergencias_de(
            texto,
            candidatos=resposta_do_turno.candidatos,
            faixa=_faixa_declarada(contexto.estado),
        )
        # As divergencias de codigo nao dependem da faixa, entao saem identicas
        # das duas passadas e a intersecao as preserva -- so as de preco que a
        # faixa de antes sustenta e que caem.
        divergencias = tuple(d for d in divergencias if d in sob_a_faixa_de_antes)
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
            candidatos=len(resposta_do_turno.candidatos),
            apresentando=apresentando,
        )
        # Apresentando, a prosa vira prefixo vazio e `legenda_de` a omite: o
        # lead recebe a ficha do banco, que e o conteudo que a RN-10.1 exige.
        # Sem ficha para entregar, a prosa era a mensagem inteira, e o
        # substituto e o mesmo texto que o `LacoDeBuscaExcedido` ja usa --
        # ele E a proposta de verificacao com o corretor que a card pede.
        texto = "" if apresentando else TEXTO_DA_BUSCA_INCONCLUSIVA
        texto_substituido = True

    # D14. Relaxou e continuou zero tem desfecho nosso, e nao prosa do modelo:
    # e o cenario 2 do Gherkin. `not citacao_bloqueada` porque, se o modelo
    # inventou imovel, a mensagem da TEC-161 e a que importa -- ela fala de um
    # defeito nosso, e este texto fala do catalogo.
    #
    # So no zero POS-relaxamento. O zero de "nada relaxavel" (D5) segue com a
    # prosa do modelo: ali ele ainda pode perguntar algo util que nos nao
    # sabemos perguntar, e cala-lo custaria mais do que padroniza.
    if resposta_do_turno.relaxou_sem_resultado and not citacao_bloqueada:
        texto = TEXTO_SEM_RESULTADO_APOS_AMPLIAR
        texto_substituido = True

    # RN-03.5 (TEC-138). A despedida, e ela e a ULTIMA das substituicoes de
    # proposito -- quem atribui `texto` por ultimo neste trecho e quem vence.
    #
    # **Vence as tres que podem estar acima dela porque todas prometem um
    # depois que esta conversa nao tem.** Entregue esta mensagem, a conversa
    # sera encerrada (bloco pos-entrega, la embaixo) e a guarda do topo vai
    # calar o agente pelos proximos 30 dias:
    # `TEXTO_DO_LIMITE_DE_PERGUNTAS` diz "já coloquei sua conversa na fila
    # deles", `TEXTO_DA_BUSCA_INCONCLUSIVA` diz "já te retorno com as
    # opções" e `TEXTO_SEM_RESULTADO_APOS_AMPLIAR` pergunta "Quer que um
    # corretor olhe isso com você?" -- as duas primeiras viram promessa que
    # ninguem cumpre e a terceira, pergunta cuja resposta o agente vai
    # ignorar. A despedida nao promete nem pergunta nada, e e a unica das
    # quatro que continua verdadeira depois do encerramento.
    #
    # **A primeira continua na lista mesmo depois da TEC-286, que tirou dela
    # a promessa de contato.** Dizer "coloquei na fila" e verdade no turno em
    # que e dito, mas com a conversa encerrada atras da despedida o lead fica
    # com uma fila em que nao pode mais falar -- e um depois, como os outros
    # dois. O que a TEC-286 trocou foi quem promete: antes era um corretor
    # que ninguem avisou; agora e uma fila que o silencio de 30 dias fecha.
    #
    # O handoff que o teto porventura tenha registrado FICA --
    # `registrar_handoff` ja rodou no bloco transacional, e uma pessoa
    # continua podendo procurar o lead. So o TEXTO e nosso, e o silencio da
    # guarda e do AGENTE, nao da empresa.
    #
    # **Com o encaminhamento da TEC-137 nao ha ordem a decidir: os dois sao
    # mutuamente exclusivos.** `encaminhou` exige `gerada.intencao` em
    # VENDER_IMOVEL ou SUPORTE_CONTRATO, e `encerrando` exige que a contagem
    # tenha chegado ao teto -- o que so acontece com FORA_DE_ESCOPO efetivo,
    # porque qualquer outra intencao zera o contador no `else` de
    # `gravar_intencao`. Uma intencao so por turno, entao as duas condicoes
    # nunca sao verdadeiras juntas.
    #
    # `not saida_bloqueada` pela razao que o comentario do teto de perguntas
    # escreve por extenso -- ver la, e nao aqui: `TEXTO_NEUTRO_DE_SAIDA` e a
    # resposta declarada da moderacao de saida, e sobrepor a nossa a ela
    # tornaria impossivel saber depois qual das duas agiu.
    #
    # **O ENCERRAMENTO, ao contrario do texto, acontece do mesmo jeito** (fix
    # da revisao final, Important 2). Esta guarda e so sobre o TEXTO: o bloco
    # pos-entrega la embaixo ja nao repete `not saida_bloqueada`, entao com a
    # saida bloqueada a conversa fecha atras do texto neutro e o turno seguinte
    # ja e silencio barato. O comentario de la carrega a razao e o preco.
    #
    # **O preco, dito aqui porque e aqui que ele nasce: neste caminho o lead
    # nao ouve a despedida.** Ele recebe o texto neutro da moderacao, a
    # conversa fecha, e ele so descobre pelo silencio dos 30 dias. E o lado
    # ruim de uma escolha entre dois ruins -- o outro era deixar um sondador
    # com chamadas pagas sem limite --, e nao um esquecimento.
    #
    # `desambiguando` NAO entra na guarda, ao contrario do teto e do
    # encaminhamento, e a assimetria e deliberada: naqueles dois a conversa
    # continua e vale mais perguntar; aqui ela ACABOU. Entregar a pergunta do
    # desambiguador e calar por 30 dias seria perguntar e ignorar a resposta
    # -- pior que a incoerencia que o `not desambiguando` deles evita. Os dois
    # marcadores pos-entrega excluem `encerrando` por causa disto; ver la.
    if encerrando and not saida_bloqueada:
        texto = TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO
        texto_substituido = True

    # Depois da moderacao de saida, de proposito: o texto e constante deste
    # repositorio e nao saida de modelo -- moderar dado nosso seria gastar
    # chamada sobre texto que nao inventamos, o mesmo argumento que a TEC-162
    # escreveu para as fichas.
    #
    # Este ponto fica DEPOIS das seis reatribuicoes de `texto` acima, e por
    # isso cobre sete trilhas, nao uma: a resposta normal, o
    # TEXTO_NEUTRO_DE_SAIDA da moderacao de saida bloqueada, o
    # TEXTO_DO_LIMITE_DE_PERGUNTAS do teto de perguntas da TEC-149, o
    # TEXTO_DO_ENCAMINHAMENTO_DE_VENDA/TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE do
    # encaminhamento por intencao da TEC-137, o TEXTO_DA_BUSCA_INCONCLUSIVA da
    # citacao bloqueada da TEC-161, o TEXTO_SEM_RESULTADO_APOS_AMPLIAR do zero
    # pos-relaxamento da TEC-160 e o TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO do
    # encerramento por escopo da TEC-138. A apresentacao NAO e uma oitava
    # trilha aqui -- e excluida de proposito, tratada em separado dentro do
    # `if apresentando:` abaixo (Task 5).
    #
    # Na trilha do encerramento a identificacao ainda pode se concatenar: o
    # lead que sumiu por mais de 30 dias e volta com a TERCEIRA fala fora de
    # escopo recebe `TEXTO_DA_IDENTIFICACAO` -- "Oi! Sou o assistente virtual
    # da imobiliária. Posso te ajudar a encontrar um imóvel, e a qualquer
    # momento te passo para um corretor." -- seguido da despedida.
    #
    # **Isso NAO tem o precedente da TEC-137** (fix da revisao, Important 5), e
    # a versao anterior deste comentario dizia que tinha. La o encaminhamento
    # de fato registra handoff, entao "te passo para um corretor" continua
    # verdade na mensagem composta. Aqui nao ha fila nenhuma: o lead le uma
    # oferta de corretor colada a uma despedida, e nada foi enfileirado. O
    # composto e raro (exige janela de 30 dias vencida E contagem ja em 2) e
    # fica DECLARADO, nao consertado: ou a identificacao passa a se calar
    # quando o turno encerra, ou ela ganha variante propria -- as duas sao
    # decisao de produto, e estao no comentario da card.
    #
    # `apresentando` fica de FORA aqui: naquele caminho `texto` vira prefixo de
    # legenda, e `legenda_de` corta o prefixo antes da ficha (D14 da TEC-162).
    # A identificacao seria descartada em silencio. A Task 5 trata dele.
    identificar = not apresentando and await e_conversa_nova(
        session_factory, message, agora=datetime.now(UTC)
    )
    if identificar:
        texto = f"{TEXTO_DA_IDENTIFICACAO}{SEPARADOR_DA_IDENTIFICACAO}{texto}"

    # CA-04.1: ao confirmar ser assistente virtual, oferecer corretor. A guarda
    # inteira vive em `identificacao.texto_com_oferta` -- inclusive a razao de
    # ela olhar o texto ja montado e nao a resposta crua do modelo.
    #
    # Aqui, e nao depois de `quebrar_em_mensagens`: aquele corte aplica os 600
    # caracteres da RN-04.2, e anexar depois dele estouraria o teto em silencio.
    #
    # `apresentando` fica de FORA pelo mesmo motivo do `identificar` acima, mas
    # por um mecanismo pior. `texto_com_oferta` anexa a oferta no FINAL, e no
    # caminho de apresentacao este mesmo `texto` vira `prosa` de `_apresentar`
    # -> `_entregar_fichas` -> `legenda_de`, que chama `prosa_que_cabe(prefixo,
    # len(corpo))` (`apresentacao.py`) -- e essa funcao corta o prefixo A
    # PARTIR DO FIM quando ele nao cabe no teto da legenda. A oferta, por
    # morar no fim, e exatamente o trecho que cai primeiro, e o corte e mudo:
    # sem log, sem erro. Mesmo quando cabe, colar a oferta de corretor como
    # prefixo de legenda de ficha e formato que esta card nunca discutiu --
    # decisao de produto do desenho da TEC-162, nao desta.
    #
    # Lead que pergunta se e robo no MESMO turno em que recebe fichas ("voce e
    # um robo? quero um apto de 2 quartos na zona sul") fica sem a oferta.
    # Falso negativo, devolve o comportamento de hoje -- o lado barato da
    # assimetria declarada em `ja_oferece_corretor`.
    # `test_a_oferta_nao_entra_ao_apresentar_e_e_lacuna_declarada`
    # (`tests/integration/test_apresentacao_no_turno.py`) trava a lacuna.
    #
    # **`texto_substituido` fica de fora porque a PRECONDICAO do CA-04.1 e a
    # confirmacao, e nao a pergunta do lead** (fix da revisao final,
    # Important 1). O criterio de aceite diz "AO CONFIRMAR ser assistente
    # virtual, oferece": quando uma das seis substituicoes deterministicas
    # rodou, a resposta do modelo nao saiu -- o agente nao confirmou nada, e
    # nao ha confirmacao a que anexar a oferta. Perguntar "o texto ainda e do
    # modelo?" fecha as tres trilhas de uma vez, e e por isso que esta e a
    # formulacao certa: as outras trilhas deterministicas ja dizem "corretor",
    # entao `ja_oferece_corretor` sozinho ja as calava, e as unicas em que o
    # append disparava sobre uma substituicao eram estas tres.
    #
    # As tres, com o que o lead recebia antes desta guarda:
    #
    # - `TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE` -- "ja coloquei sua conversa na
    #   fila deles" seguido de uma oferta de corretor, contradizendo o
    #   roteamento que a frase anterior acabou de anunciar. Que o
    #   encaminhamento de SUPORTE nao fale em corretor (so o de venda) e
    #   decisao registrada no desenho da TEC-272, nao omissao.
    # - `TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO` -- e verbatim o defeito que o
    #   comentario do `identificar`, logo acima, ja declara para a
    #   identificacao ("o lead le uma oferta de corretor colada a uma
    #   despedida, e nada foi enfileirado"), e mais alcancavel que ele: aquele
    #   exige janela de 30 dias vencida E contagem ja em 2, este exige so
    #   `encerrando` mais a pergunta.
    # - `TEXTO_NEUTRO_DE_SAIDA` -- "Tive um problema para montar a resposta
    #   agora." seguido da oferta, num turno em que o agente nao respondeu
    #   coisa nenhuma.
    if not apresentando and not texto_substituido:
        texto = texto_com_oferta(corpo, texto)

    # Fix de revisao final (Critical 1 e Important 2, TEC-140). So o caminho
    # de texto (o `else:` abaixo) pode marcar as duas True -- `_apresentar` ja
    # tem a forma certa e nao precisa delas --, mas os valores precisam existir
    # para os dois caminhos porque o `if suprimida_apos_entrega:` e o guard de
    # `marcar_perguntados`, mais abaixo, rodam incondicional de qual ramo
    # executou.
    suprimida_apos_entrega = False
    entrega_parcial = False
    # O `kind` cuja supressao setou `suprimida_apos_entrega`, so para o log
    # que o bloco `if suprimida_apos_entrega:` emite mais abaixo -- ver la.
    # `None` nunca chega a ser lido: so e consultado dentro daquele `if`, que
    # so roda quando `suprimida_apos_entrega` e True, e as duas unicas
    # atribuicoes ficam juntas com as de `suprimida_apos_entrega = True`.
    kind_suprimido: str | None = None

    try:
        if apresentando:
            if await e_conversa_nova(session_factory, message, agora=datetime.now(UTC)):
                # Mensagem propria, e NAO prefixo da prosa (que e o mecanismo
                # das outras tres trilhas, acima). Na apresentacao a prosa
                # vira prefixo da legenda da PRIMEIRA ficha (D16 da TEC-162),
                # e `legenda_de` corta o prefixo antes de cortar a ficha
                # (D14): "estourado o teto, o que se corta e o PREFIXO, nunca
                # a ficha" -- `prosa_que_cabe` devolve string vazia quando
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
                # `prosa_que_cabe` devolve string vazia quando nao sobra
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
            if resposta_do_turno.relaxou_e_achou and (
                resposta_do_turno.relaxou_preco or resposta_do_turno.relaxou_bairro
            ):
                # CA-09.3. Mensagem propria, e NAO prefixo da legenda: no
                # caminho de apresentacao `legenda_de` corta o PREFIXO antes
                # da ficha, e `prosa_que_cabe` devolve string vazia quando
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
                        "texto": aviso_de_ampliacao(
                            resposta_do_turno.relaxou_preco, resposta_do_turno.relaxou_bairro
                        ),
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
                for candidato in resposta_do_turno.candidatos
                if (score := porta.score_de(uuid.UUID(candidato["imovel_id"]))) is not None
            }
            # `prosa=texto` le o valor ANTES da atribuicao: a chamada e
            # avaliada primeiro, e o `texto` que sai sao as legendas
            # concatenadas (D16).
            texto, quantas, suprimidas = await _apresentar(
                session_factory,
                message=message,
                outbound=outbound,
                candidatos=resposta_do_turno.candidatos,
                scores=scores,
                criterios=resposta_do_turno.criterios,
                # TEC-163, fix wave. `criterios` e o que a busca PEDIU (o
                # filtro antes do relaxamento -- o alargado nunca sai de
                # `buscar_com_relaxamento`); sem estes dois, um candidato que
                # so apareceu porque o teto cedeu 10% seria gravado com o
                # criterio que ele nao satisfaz. Sao os mesmos booleanos que
                # `aviso_de_ampliacao` usa logo acima: o lead ouve que o
                # criterio foi ampliado e a linha do banco passa a dizer o
                # mesmo.
                relaxou_preco=resposta_do_turno.relaxou_preco,
                relaxou_bairro=resposta_do_turno.relaxou_bairro,
                prosa=texto,
                # TEC-154, D9. O gatilho e a TRILHA, nunca `perfil_investidor`:
                # a Emenda E-01 da RN-07.2 fixa que perfil ausente e NULL e nao
                # MISTO, e proibiu esta card de tratar os dois como um so. Um
                # Ricardo que ainda nao respondeu horizonte e investidor do
                # mesmo jeito, e a ficha dele leva os numeros.
                #
                # As duas variaveis, e nao so `ja_e_investidor`: no turno da
                # VIRADA a intencao ainda nao esta no estado que
                # `montar_contexto` leu, e sem `virou_investidor` a primeira
                # apresentacao do investidor sairia sem bloco -- justo a que
                # ele esperava.
                investidor=ja_e_investidor or virou_investidor,
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
                    # nesta) nao ficar invisivel para quem opera.
                    #
                    # O que essa proxima tentativa faz mudou na TEC-273, e
                    # este paragrafo dizia o contrario ate ela: `sweep_stalled`
                    # continua rodando o turno inteiro de novo, com uma chamada
                    # NOVA ao classificador, mas a parte ja entregue NAO tem
                    # mais reserva quando ele chega. `GuardedOutbound.send`
                    # libera as reservas do GRUPO de `kind` -- as duas de
                    # `KINDS_DA_RESPOSTA` -- antes de deixar esta excecao
                    # subir; ver `_liberar` e o comentario de `KINDS_DA_RESPOSTA`
                    # em `domain/outbound/kinds.py`, que registra o que a
                    # liberacao por kind unico custava. A retentativa entrega
                    # as duas partes da geracao nova: o lead le a parte 1 duas
                    # vezes -- duplicata visivel, o lado que TEC-134/TEC-227 ja
                    # escolheram -- em vez da primeira metade deste texto
                    # costurada na segunda metade de outro.
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
                        kind_suprimido = kind
                        break
                    # Ate a TEC-273 isto fazia `continue` liso, sem marcar
                    # nada, e o comentario chamava o caso de "a retentativa
                    # legitima do sweeper": a parte com reserva de uma
                    # tentativa anterior devolvia False aqui, e a parte sem
                    # reserva ainda tinha a vez de sair.
                    #
                    # A TEC-273 libera as reservas do GRUPO inteiro, mas so
                    # quando a falha e RETENTAVEL -- `except (EnvioRetentavel,
                    # asyncio.CancelledError)` em `GuardedOutbound.send`
                    # (`port.py`). Qualquer OUTRA morte do turno depois do
                    # `send()` -- queda do worker, `job_timeout`, excecao no
                    # recorder -- nao passa por ali, a reserva fica viva, e o
                    # reprocessamento cai exatamente aqui com uma reserva SAUDAVEL
                    # de uma entrega que ja aconteceu de verdade: caminho
                    # normal, nao anomalia (`tests/features/test_reprocessamento_apos_falha.py`
                    # documenta esse caso). Fix de revisao (Important 2): uma
                    # versao anterior deste comentario dizia que aquela
                    # retentativa "deixou de existir" e chamava isto de
                    # anomalia sem ressalva -- falso para qualquer morte do
                    # turno que nao seja uma das duas excecoes acima. Uma
                    # reserva de verdade PRESA (o delete da liberacao falhando
                    # por deadlock ou conexao caida, que `port.py` ja antecipa
                    # e loga como `outbound.liberacao_falhou`) e so UMA das
                    # causas possiveis -- a MESMA guarda de opt-out ou de
                    # atendimento humano que bloqueou a parte anterior
                    # (`if entregue:` logo acima cobre o caso simetrico) e
                    # outra.
                    #
                    # `continue`, e nao `break`: a proxima parte ainda pode
                    # sair de verdade, e reter o quanto foi entregue (visivel,
                    # recuperavel) e melhor que ficar em silencio total --
                    # o mesmo criterio de TEC-134/TEC-227 que ja rege este
                    # arquivo. `entrega_parcial` reescreve `texto` mais abaixo
                    # para so as partes que de fato sairam, entao a parte
                    # suprimida nunca chega no recorder.
                    #
                    # `suprimida_apos_entrega = True`, e nao False: o NOME diz
                    # "apos entrega" pensando na ORDEM cronologica, mas o que a
                    # variavel de fato controla, la embaixo, e se o desfecho
                    # final pode virar "respondido" quando pelo menos uma
                    # parte saiu -- e aqui, se uma parte POSTERIOR sair, e
                    # exatamente essa a duvida (reserva presa vs guarda) que
                    # nao pode ficar disfarcada de "respondido". Sem isto,
                    # exatamente o defeito que o comentario do `if entregue:`
                    # acima descreve se repetiria aqui, so que com a ordem das
                    # partes invertida. Se NENHUMA parte posterior sair,
                    # `entregue` continua False e este valor nem chega a ser
                    # lido -- quem decide o desfecho e o bloco `if not
                    # entregue:` abaixo, inalterado.
                    #
                    # Sem log aqui, de proposito (fix de revisao, Important 1):
                    # uma versao anterior deste fix logava `error` NESTE ponto,
                    # e disparava tambem quando NENHUMA parte saia em turno
                    # nenhum -- o caso de supressao TOTAL, que e exatamente o
                    # que `if not entregue:` abaixo ja cobre com
                    # `turno.reentrega_suprimida`.
                    # `test_reentrega_suprimida_nao_grava_fala_fantasma`
                    # (`test_turno.py`) tem um unico kind, reserva plantada, e
                    # ZERO partes saem -- e ainda assim aquele log incondicional
                    # disparava ali, afirmando "entrega parcial" num turno sem
                    # entrega nenhuma. O alarme certo so pode nascer depois do
                    # laco, quando `entregue` e sabidamente True -- ver o
                    # bloco `if suprimida_apos_entrega:` mais abaixo, que e
                    # onde `turno.entrega_parcial_da_resposta` agora mora.
                    # `kind_suprimido` guarda so o dado que aquele log precisa
                    # e que so existe aqui dentro do laco.
                    entrega_parcial = True
                    suprimida_apos_entrega = True
                    kind_suprimido = kind
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

    # Fix de revisao final (Critical 1, TEC-140; texto corrigido na TEC-273,
    # cenario 2 do Gherkin). `entregue` e True aqui -- pelo menos uma parte
    # saiu --, e `suprimida_apos_entrega` (marcada no laco acima) diz que
    # ALGUMA parte devolveu False sem levantar -- nao necessariamente
    # POSTERIOR a que entrou. Ate a TEC-273 a flag so nascia no ramo `if
    # entregue:` do laco, com uma parte ja entregue quando a suprimida
    # apareceu -- dai o nome. A D4 da TEC-273 passou a setar a MESMA flag
    # tambem no ramo `not entregue` (reserva presa achada na PRIMEIRA parte do
    # laco, ZERO partes entregues naquele instante) quando uma parte seguinte
    # sai depois -- o nome continua pensando na ordem cronologica, mas o que
    # ele de fato controla e so isto: alguma parte foi suprimida sem
    # levantar, com ou sem parte entregue ANTES dela. Sao as MESMAS tres
    # causas do `if not entregue:` logo acima -- reentrega
    # suprimida pela reserva, a guarda de opt-out barrando um envio
    # concorrente, ou a guarda de atendimento humano barrando pelo mesmo
    # motivo (TEC-179) --, so que com pelo menos uma parte entregue no laco,
    # em vez de nenhuma. O desfecho de alarme (`reentrega_suprimida`) ou os de
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
            # TEC-273, cenario 2 do Gherkin: "um log distingue este caso de
            # 'nada saiu'". `turno.entrega_parcial_da_resposta` e esse log --
            # deliberadamente NAO emitido la dentro do laco (fix de revisao,
            # Important 1): so aqui, depois do laco inteiro, `entregue` e
            # sabidamente True (este `if` inteiro so roda quando e), entao so
            # aqui da para afirmar "parcial" sem risco de mentir para o caso
            # de supressao TOTAL (zero partes), que e o que `if not entregue:`
            # acima ja cobre com `turno.reentrega_suprimida` sozinho.
            # `kind_suprimido` sempre esta preenchido quando chegamos aqui: as
            # duas atribuicoes de `suprimida_apos_entrega = True`, no laco
            # acima, guardam o `kind` junto na mesma linha.
            log.error(
                "turno.entrega_parcial_da_resposta",
                channel=message.channel,
                message_id=str(message.id),
                kind=kind_suprimido,
                reason="reserva presa ou reprocessamento apos morte do turno: "
                "nem opt-out nem atendimento humano concorrente explicam a "
                "supressao",
            )
            log.error(
                "turno.reentrega_suprimida",
                channel=message.channel,
                message_id=str(message.id),
                entrega_parcial=True,
            )
            desfecho_da_supressao_parcial = "reentrega_suprimida"

    if (
        desambiguando
        and not saida_bloqueada
        and not citacao_bloqueada
        and not entrega_parcial
        and not encerrando
    ):
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
        #
        # `not entrega_parcial` (TEC-273), quarta causa, mesmo argumento que
        # `marcar_perguntados` mais abaixo ja escreve para a marca dele:
        # `entrega_parcial` nao diz ONDE dentro do texto a quebra caiu, entao
        # a pergunta do desambiguador -- que atravessa o MESMO laco de
        # `KINDS_DA_RESPOSTA` que a resposta normal -- pode ter saido inteira,
        # pela metade, ou nem ter existido na parte que o lead recebeu.
        # Marcar aqui gastaria, para sempre e em silencio, a unica pergunta do
        # episodio numa entrega que talvez nunca a tenha feito -- o MESMO dano
        # que `saida_bloqueada` e `citacao_bloqueada` evitam acima, so que
        # pela guarda de formato em vez da moderacao ou da citacao. Esta
        # guarda tinha tres condicoes ate a TEC-273.
        #
        # `not encerrando` (TEC-138), quinta causa e o mesmo dano pela quinta
        # porta: a despedida da RN-03.5 substituiu o texto ANTES deste ponto,
        # e no caminho de desambiguacao esse texto era a pergunta do
        # desambiguador. O que chegou ao lead foi
        # `TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO`, que nao pergunta nada -- ou,
        # no turno que encerra com a saida bloqueada, o texto neutro da
        # moderacao, que tambem nao pergunta; ali quem ja exclui este bloco e o
        # `not saida_bloqueada` logo acima. E a
        # marca nao se resolveria sozinha: `gravar_intencao` so limpa
        # `desambiguado_em` quando a confianca sustenta a classificacao, e
        # neste caminho ela nao sustenta -- a marca atravessaria os 30 dias e
        # o lead voltaria sem a pergunta a que tinha direito.
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

    if (
        not desambiguando
        and not virou_investidor
        and not saida_bloqueada
        and not citacao_bloqueada
        and not entrega_parcial
        and not teto_da_entrega
        and not encaminhou
        and not encerrando
    ):
        # A marca de `perguntou` (TEC-257) e, ao contrario da intencao e da
        # extracao gravadas la em cima, um fato sobre a NOSSA resposta -- e
        # por isso nao pode entrar naquele commit pre-entrega. Ela so pode ser
        # gravada depois da entrega confirmada, e so quando o texto de
        # `gerada` foi de fato o que saiu, pela mesma razao que
        # `marcar_desambiguacao` espera a entrega (ver o bloco acima): no
        # caminho de desambiguacao a resposta da chamada 1 foi descartada --
        # paga e nao entregue -- e o lead recebeu a pergunta do desambiguador,
        # nao a de `gerada`; na VIRADA do investidor (TEC-153) a chamada 1 foi
        # descartada pelo mesmo motivo estrutural e o lead recebeu a prosa do
        # subagente, entao `gerada.perguntou` descreve um texto que ninguem
        # leu -- marca-lo queimaria para sempre a chance de perguntar aquele
        # campo, que e exatamente o dano que esta guarda existe para evitar
        # (repare que o TURNO SEGUINTE do investidor nao entra aqui: la
        # `ja_e_investidor` fez de `gerada` a propria resposta entregue, e a
        # marca vale normalmente).
        #
        # **A guarda e uma so, e leva `contar_perguntas` junto -- inclusive na
        # virada, onde a pergunta ENTREGUE foi a do subagente.** Isso e
        # declarado, e nao esquecido: e a L5 do desenho. O teto efetivo do
        # investidor e 8 mais o turno da virada, no maximo duas perguntas por
        # virada. Contar `do_investidor.perguntou` aqui seria contar o
        # `perguntou` de uma resposta cujos campos irmaos (`intencao`,
        # `extracao`, que `marcar_perguntados` tambem recebe) foram todos
        # descartados. O comportamento tem teste:
        # `test_a_virada_nao_marca_a_pergunta_da_chamada_descartada`.
        #
        # Com a saida bloqueada o lead recebeu
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
        # `not encaminhou` (TEC-137) pela mesma razao das anteriores: o lead
        # recebeu `TEXTO_DO_ENCAMINHAMENTO_DE_VENDA` ou o de suporte, que
        # tambem nao perguntam nada. Aqui o dano e o menos obvio de todos, e
        # por isso vale dizer por extenso: a intencao e POR TURNO e o contador
        # e COMPARTILHADO entre elas, entao "esses leads nunca sao qualificados
        # mesmo" nao fecha o caso. O lead que fala de venda hoje e volta como
        # COMPRA amanha chegaria com o campo marcado -- a uniao no SQL nunca
        # remove -- e com `perguntas_feitas` ja gasto; depois de turnos
        # suficientes o teto da TEC-149 dispara "Já perguntei bastante" contra
        # quem nao foi perguntado de nada.
        #
        # `not encerrando` (TEC-138) pela mesma razao, e com o mesmo dano
        # diferido: o lead recebeu `TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO`, que
        # nao pergunta nada (ou o texto neutro da moderacao, no turno que
        # encerra com a saida bloqueada -- caso que o `not saida_bloqueada`
        # acima ja exclui). O encerramento nao e o fim do lead -- passados os
        # 30 dias a conversa reabre e a MESMA linha de `lead_qualification`
        # continua la, com o campo marcado e o orcamento de perguntas gasto
        # por uma pergunta que ninguem leu.
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
        #
        # `not teto_da_entrega` pela mesma razao das outras: o texto de
        # `gerada` nao foi o que saiu. A pergunta foi SUPRIMIDA, nao feita --
        # marcar ou contar aqui gastaria orcamento do lead por uma pergunta
        # que ele nunca viu, e o proximo turno ja nasceria acima do teto. E
        # `teto_da_entrega`, e nao `teto_do_handoff`: a pergunta que importa aqui
        # e sobre o texto ENTREGUE, e e so ele que o lead pode ter lido. Nos
        # caminhos que chegam ate aqui os dois valem o mesmo, porque
        # `resposta_do_turno is gerada`.
        #
        # **E este bloco continua lendo `gerada`, de proposito.** A guarda
        # `not virou_investidor` la em cima ja exclui o unico caminho em que
        # `gerada` difere de `resposta_do_turno`; e `marcar_perguntados` recebe
        # tambem `intencao` e `extracao`, que foram as de `gerada` no commit
        # pre-entrega -- misturar aqui o `perguntou` de uma chamada com a
        # extracao de outra decidiria a marca sobre um estado que nunca
        # existiu.
        async with session_factory() as session:
            await marcar_perguntados(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                intencao=gerada.intencao,
                extracao=gerada.extracao,
                perguntou=gerada.perguntou,
            )
            await contar_perguntas(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                perguntou=gerada.perguntou,
            )
            await session.commit()

    # RN-03.5 (TEC-138). O encerramento, e ele e pos-entrega pelo mesmo
    # criterio dos dois blocos acima: **so depois de o lead ter recebido a
    # despedida**. O comentario de `encerrando`, no bloco transacional, escreve
    # por extenso por que a ordem inversa reintroduzia o defeito da entrega
    # retentavel -- conversa fechada e lead calado por 30 dias sem nunca ter
    # ouvido o porque.
    #
    # As duas condicoes dizem "alguma coisa nossa chegou inteira ao lead":
    # `encerrando` e a decisao da contagem; `not entrega_parcial` pela mesma
    # razao que os dois blocos acima o excluem -- ele nao diz ONDE a quebra
    # caiu, entao o texto pode ter saido pela metade. `entregue` e sabidamente
    # True aqui: o `if not entregue:` la em cima ja devolveu em todos os outros
    # casos.
    #
    # **A saida bloqueada NAO adia mais o encerramento** (fix da revisao final,
    # Important 2, ruling R9). Ate aqui este bloco exigia tambem
    # `not saida_bloqueada`, e justificava com "nao encerrar num destes turnos
    # nao perde a regra, so a adia". So adia se algum turno seguinte vier
    # desbloqueado -- e nada garante isso. Bloqueando sempre, `encerrando`
    # ficava True para sempre, a despedida nunca substituia nada, a conversa
    # nunca fechava e cada mensagem seguia pagando classificador e moderacao,
    # sem teto. Isso falsifica o dividendo que a D7 declara -- "tres chamadas
    # pagas por conversa a cada 30 dias, contra ilimitado hoje" --, e
    # justamente no perfil de abuso que o proprio desenho nomeia
    # (`borda-injecao-02`, uma prompt injection), que e o mais provavel de
    # reprovar na moderacao de saida turno apos turno.
    #
    # **Fechar atras do texto neutro esta certo, e o turno nao fica mudo.** O
    # lead recebeu `TEXTO_NEUTRO_DE_SAIDA`, que e a resposta declarada da
    # politica de moderacao -- nao e silencio, e sim outra resposta nossa. O
    # preco da escolha esta dito onde ele aparece: **neste caminho o lead nao
    # ouve a despedida**, porque a substituicao la em cima continua cedendo o
    # texto a moderacao (ver o `if encerrando and not saida_bloqueada:`, que
    # guarda a razao). Ele fica sem saber que a conversa parou, e so descobre
    # pelo silencio. O outro lado da balanca era dar a um sondador chamadas
    # pagas sem limite, e este bloco escolhe o primeiro.
    #
    # **Transacao curta propria**, como a do `registrar_handoff` da entrega e a
    # de `gravar_investidor`, e pelo mesmo motivo: o bloco transacional la de
    # cima ja commitou. Os DOIS statements ficam nela juntos -- e essa
    # indivisibilidade, e nao a de cima, que sustenta a docstring de
    # `reabrir_conversa`.
    if encerrando and not entrega_parcial:
        async with session_factory() as session:
            await encerrar_conversa(
                session,
                channel=message.channel,
                conversation_key=message.conversation_key,
                motivo=str(MotivoDoEncerramento.FORA_DE_ESCOPO),
                agora=datetime.now(UTC),
            )
            await zerar_fora_de_escopo(
                session, channel=message.channel, conversation_key=message.conversation_key
            )
            await session.commit()
        # Depois do commit, pelo mesmo motivo dos logs de handoff: logar um
        # encerramento que o rollback desfez e mentir para quem le o log.
        #
        # **Sem o texto das mensagens** (D7), pela mesma razao que a prosa
        # bloqueada da TEC-161 nao entra no log: o que torna a linha
        # investigavel e a contagem e o motivo, e o conteudo das tres falas do
        # lead nao acrescenta nada que justifique guarda-lo fora de `messages`.
        # A contagem e a de ANTES do zero -- e o numero que decidiu, e depois
        # dele a coluna nao o guarda mais em lugar nenhum.
        log.info(
            "conversa.encerrada",
            channel=message.channel,
            message_id=str(message.id),
            motivo=str(MotivoDoEncerramento.FORA_DE_ESCOPO),
            seguidas=fora_de_escopo_seguidas,
        )

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


async def _degradar_por_provedor(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    message: Message,
    outbound: OutboundPort,
    agendador: AgendadorDeResumoPort,
    subagent: str,
) -> ResultadoDoTurno:
    """A espera honesta com handoff, quando o provedor nao respondeu. TEC-209, D3.

    **Na mesma passada, e nao na quinta falha.** Antes, a excecao subia para
    `process_message`, que marcava FAILED; o aviso e o handoff so saiam
    quando `attempts` chegava a `sweep_max_attempts`, com uma passada do
    sweeper a cada 30 s entre as falhas -- minutos de silencio para o lead.
    A cadeia do classificador ja retentou e ja tentou o secundario:
    reprocessar repagaria tudo para chegar ao mesmo lugar.

    **Handoff primeiro, aviso depois**, pela razao de
    `process_message._encaminhar_por_erro`: o corretor ser avisado nao pode
    depender de o lead ter sido. O gatilho e o `ERRO_DO_AGENTE` de la -- para
    quem atende, provedor fora e agente quebrado sao o mesmo caso -- e o
    ator e o SISTEMA, como la.
    """
    async with session_factory() as sessao:
        registro = await registrar_handoff(
            sessao,
            channel=message.channel,
            conversation_key=message.conversation_key,
            gatilho=Gatilho.ERRO_DO_AGENTE,
            ator=ATOR_SISTEMA,
        )
        await sessao.commit()
    log.info(
        "handoff.criado" if registro.criado else "handoff.gatilho_adicional",
        channel=message.channel,
        gatilho=Gatilho.ERRO_DO_AGENTE.value,
        etiqueta=ETIQUETA_DE[Gatilho.ERRO_DO_AGENTE],
        prioridade=PRIORIDADE_DE[Gatilho.ERRO_DO_AGENTE].value,
    )
    await _agendar_resumo(agendador, registro)

    entrega = await _entregar_texto_fixo(
        session_factory,
        message=message,
        outbound=outbound,
        recorder_texto=TEXTO_DO_AVISO_DE_ERRO,
        kind=KIND_DO_AVISO_DE_ERRO,
        subagent=subagent,
    )
    # O desfecho do envio so substitui o do turno quando o envio nao saiu:
    # "expirado" e "sem_resposta" dizem mais que "provedor_indisponivel" sobre
    # o que o lead de fato recebeu.
    return "provedor_indisponivel" if entrega == "respondido" else entrega


async def _encerrar_por_optout(
    session_factory: async_sessionmaker[AsyncSession], message: Message
) -> None:
    """Fecha a conversa com `MotivoDoEncerramento.OPTOUT` e emite o evento.

    Escrituracao, nao silencio (TEC-130, D6): o porque, a ordem das duas
    transacoes e o significado de `conversa.encerrada` estao comentados no
    bloco `if pedido_de_optout:` de `_executar_turno`, o primeiro chamador.
    Extraida quando o pedido de titular (TEC-207) passou a gravar opt-out
    tambem -- sem ela, o opt-out que ele grava deixava a conversa ATIVA,
    sem data nem motivo, ao contrario do que o bloco de opt-out faz.
    """
    async with session_factory() as sessao_do_encerramento:
        await encerrar_conversa(
            sessao_do_encerramento,
            channel=message.channel,
            conversation_key=message.conversation_key,
            motivo=str(MotivoDoEncerramento.OPTOUT),
            agora=datetime.now(UTC),
        )
        await sessao_do_encerramento.commit()
    log.info(
        "conversa.encerrada",
        channel=message.channel,
        message_id=str(message.id),
        motivo=str(MotivoDoEncerramento.OPTOUT),
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
    visivel e recuperavel e o silencio nao. `kind` tem default
    (`KIND_DA_RESPOSTA`) para preservar o chamador que nao precisa de kind
    proprio -- hoje so o texto da busca inconclusiva (`LacoDeBuscaExcedido`,
    mais abaixo) usa o default. Os outros seis chamadores passam kind
    proprio: a confirmacao de opt-out (TEC-182), o bloco do pedido de
    titular (TEC-207: `KIND_DA_CONFIRMACAO_DE_TITULAR` na confirmacao e
    `KIND_DA_PERGUNTA_DE_ELIMINACAO` na pergunta do primeiro passo da
    eliminacao, as duas com `SUBAGENTE_TITULAR`), o aviso de pedido de humano,
    a confirmacao de midia sem texto (TEC-132, D4:
    `KIND_DA_CONFIRMACAO_DE_MIDIA`, com `SUBAGENTE_MIDIA`), a recusa de
    entrada -- desde a TEC-295, ruling R6 --, que usa
    `KIND_DA_RECUSA_DE_ENTRADA` para nao colidir com o `kind` da resposta que
    a continuacao da D4 pode entregar depois dela na mesma mensagem, e o
    agendamento pela conversa (TEC-371: `KIND_DO_AGENDAMENTO`, com
    `SUBAGENTE_AGENDAMENTO`). O da
    opt-out e os dois do pedido de titular sao os unicos que atravessam as guardas
    de opt-out e de atendimento humano da porta de saida -- ver
    `KINDS_QUE_FURAM_AS_GUARDAS` e `GuardedOutbound.send`. `subagent` anda junto
    de `kind` pelo mesmo motivo: sem o parametro, toda entrega deste caminho
    -- inclusive a confirmacao de opt-out, que nao e moderacao nenhuma --
    gravava `message_telemetry.subagent = "moderacao"`, rotulando errado
    quem olhar a telemetria depois.
    """
    # A identificacao entra AQUI e nao em cada chamador: este e o funil das
    # trilhas que passam por `_entregar_texto_fixo` -- recusa da moderacao de
    # entrada, confirmacao de opt-out, confirmacao do pedido de titular e
    # pergunta de eliminacao (TEC-207), aviso de pedido de humano, confirmacao
    # de midia sem texto (TEC-132), agendamento pela conversa (TEC-371) e laco
    # de busca excedido.
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
        # `kind not in KINDS_QUE_FURAM_AS_GUARDAS` guarda a chamada seguinte,
        # de proposito -- fix de revisao (Important). Quando ESTE chamador e
        # a propria confirmacao de opt-out, o turno acabou de rodar
        # `registrar_optout` antes de chegar aqui: `esta_em_optout` so pode
        # devolver True, sempre, por construcao -- nao porque a guarda barrou
        # por opt-out desta vez, mas porque o opt-out que o PROPRIO turno
        # gravou ainda esta la. O mesmo vale para a confirmacao do pedido de
        # eliminacao (TEC-207), que tambem grava opt-out antes de confirmar;
        # e mesmo no pedido de acesso e na pergunta de eliminacao, sem opt-out
        # gravado pelo turno, o argumento abaixo basta. A guarda pula a
        # checagem de opt-out para os kinds desse conjunto (ver
        # `GuardedOutbound.send`), entao um `False` aqui so pode vir de
        # reserva duplicada de verdade. Chamar o helper mesmo assim
        # relataria "bloqueado_por_optout" em `info` e engoliria o
        # "reentrega_suprimida" em `error` -- o alarme de dado sumido que
        # importa exatamente aqui, na confirmacao que apaga o unico rastro
        # visivel do pedido do lead se ela nao chegar.
        if kind not in KINDS_QUE_FURAM_AS_GUARDAS and await _bloqueado_por_optout_concorrente(
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
        # `kind not in KINDS_QUE_FURAM_AS_GUARDAS` guarda esta checagem
        # tambem, pela MESMA razao da linha equivalente para o opt-out, acima
        # -- fix de revisao (Major, rodada 2). A guarda de atendimento humano
        # deixou de barrar TODO kind na emenda que abriu a excecao de
        # `KIND_DA_CONFIRMACAO_DE_OPTOUT` (ver `GuardedOutbound.send`), e a
        # TEC-207 somou a confirmacao do pedido de titular e a pergunta de
        # eliminacao ao mesmo conjunto:
        # para esses kinds, ela nao pode mais ser a causa de um `False` aqui
        # -- ela deixa passar. Sem esta excecao, a confirmacao de
        # opt-out retentada com a reserva ja existente E a conversa ainda
        # assumida seria atribuida a guarda errada: "bloqueado_por_atendimento_humano"
        # em `info`, quando a causa real e reserva duplicada --
        # "reentrega_suprimida" em `error`, o alarme de dado sumido que
        # importa exatamente aqui (mesmo raciocinio do comentario do opt-out,
        # acima, so que para a guarda seguinte).
        if (
            kind not in KINDS_QUE_FURAM_AS_GUARDAS
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
        #
        # **A recusa de entrada e a excecao, e ela e o caminho ESPERADO desde a
        # TEC-298 (D4).** Quando a reserva dela sobrevive, o turno continua para
        # responder a pergunta pendente -- a supressao aqui e o mecanismo que
        # impede a recusa de sair duas vezes, nao um acidente. `error` e o
        # alarme de dado sumido, e dispara-lo sobre algo que a passada anterior
        # entregou e alarme falso.
        #
        # `warning` e nao `info`: a reserva sobrevivente e evidencia forte de
        # entrega, NAO e prova. Ela tambem sobrevive se o worker morreu entre o
        # commit da reserva e o `_deliver`, ou se o proprio `_liberar` falhou
        # (que tem alarme proprio, `outbound.liberacao_falhou`). Nessas duas
        # rotas a recusa de fato nao chegou, e `info` as esconderia. E a mesma
        # ressalva que `kinds_reservados` ja documenta: presenca significa
        # "encerrado", nao "entregue".
        if kind == KIND_DA_RECUSA_DE_ENTRADA:
            log.warning(
                "turno.recusa_ja_reservada",
                channel=message.channel,
                message_id=str(message.id),
            )
        else:
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
    divergem -- o comentario de `KINDS_DA_RESPOSTA`, em
    `domain/outbound/kinds.py` desde a TEC-273, registra o que isso ja custou.

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

    **O que "de qualquer jeito" nao cobre e a consequencia para a LINHA.**
    Reserva significa "encerrado", nao "entregue" (ver `kinds_reservados`), e
    ela pode ficar presa sem que a ficha tenha saido: `port.py` antecipa a
    liberacao do `EnvioRetentavel` FALHAR -- deadlock, conexao caida -- e um
    kill entre o commit da reserva e o `_deliver` da no mesmo. Nesse estado,
    chamar `send` devolveria False, o imovel entraria em `nao_entregues` e a
    conciliacao o tiraria da lista de pendentes -- era o que a passada seguinte
    fazia antes desta card, rodando o turno inteiro. Pulando, a linha
    sobrevive: `ler_pendentes` devolve tres onde o lead viu duas, e o ordinal
    dele desloca, que e o defeito-alvo desta card. A troca continua sendo a
    certa -- o caso e raro e o contrario reenviaria ficha ja vista a cada
    retentativa --, mas esta frase existe para ele nao ficar escrito como
    impossivel.
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
    investidor: bool,
) -> tuple[str, int, int]:
    """Entrega ate 3 fichas e devolve (texto para gravar, entregues, suprimidas).

    **`investidor` liga o bloco da RN-07.3 e nada mais.** Ele decide a forma
    da ficha, nunca quais imoveis entram nela: a busca e a escolha sao as
    mesmas das duas trilhas.

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
    fichas = await fichas_do_catalogo(
        session_factory, ids=ids, precos=precos, com_rentabilidade=investidor
    )
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
