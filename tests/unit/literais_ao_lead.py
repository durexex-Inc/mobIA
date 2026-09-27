"""As constantes de modulo que o lead recebe, num lugar so.

Nao e arquivo de teste: e a lista que duas guardas leem --
`test_acento_no_texto_ao_lead.py` (TEC-267, o texto ao lead e portugues
acentuado) e `test_promessa_ao_lead.py` (TEC-286, nenhum texto promete contato
que ninguem faz). Ate a TEC-286 a lista morava dentro da primeira; a segunda
precisou dela para outra pergunta, e duas copias da mesma lista seriam duas
coisas para manter em sincronia.

**Entrar nesta lista e o que faz um texto novo ser coberto pelas duas
guardas.** Por isso a lista tem um teste de tamanho logo abaixo: um literal
removido daqui nao reprova nada em lugar nenhum -- as duas guardas passariam,
so que sem checar aquele texto.

**Ela cobre CONSTANTES DE MODULO, e nao todo texto que o lead le.** Os rotulos
da ficha de imovel -- "Condomínio", "Destaque:" e o "/mês" do bloco do
investidor -- sao a mensagem mais visivel do produto e ficam de fora de
proposito: eles nascem de f-strings montados em tempo de execucao dentro de
`_linhas_da_rentabilidade` e `legenda_de` (`apresentacao.py`), nao de
constantes `TEXTO_...` importaveis. "Aluguel estimado: não informado" e
excecao dentro da excecao -- e a constante de modulo `_ALUGUEL_AUSENTE`
(mesmo arquivo), e fica de fora por ser **privada** (`_nome`), nao por nascer
de f-string. Cobrir qualquer um deles aqui exigiria renderizar uma ficha
dentro de um teste desta pasta -- duplicando o que
`tests/unit/test_apresentacao.py` ja faz com snapshots exatos, e criando duas
fontes para a mesma verificacao. Nao e lacuna teorica: uma sabotagem que tirou
o acento de "/mês" em `apresentacao.py` nao fez a guarda de acento falhar (a
string nao esta aqui), e fez o `test_apresentacao.py` falhar, porque e ele que
compara a legenda inteira contra o texto esperado por extenso. Quem cobre os
rotulos da ficha e aquele arquivo, nao estas guardas.
"""

from mobia.domain.agendamento.data_falada import (
    TEXTO_DA_DATA_INEXISTENTE,
    TEXTO_DA_HORA_AMBIGUA,
    TEXTO_DA_NOITE,
    TEXTO_DE_DOIS_DIAS,
    TEXTO_DE_HOJE_OU_DA_PROXIMA,
    TEXTO_DO_DOMINGO,
    TEXTO_DO_FIM_DE_SEMANA,
    TEXTO_DO_PASSADO,
)
from mobia.domain.agendamento.espera import (
    TEXTO_DA_ESPERA_ACEITA,
    TEXTO_DA_LISTA_DE_ESPERA,
    TEXTO_DO_SLOT_LIBERADO,
)
from mobia.domain.agendamento.lembretes import (
    TEXTO_DO_LEMBRETE_DE_2H_DE_REUNIAO,
    TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA,
    TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA_SEM_IMOVEL,
    TEXTO_DO_LEMBRETE_DE_24H_DE_REUNIAO,
    TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA,
    TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA_SEM_IMOVEL,
)
from mobia.domain.agendamento.mensagens import (
    TEXTO_DA_CONFIRMACAO_DE_REUNIAO,
    TEXTO_DA_CONFIRMACAO_DE_VISITA,
    TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL,
    TEXTO_DA_ESCOLHA,
    TEXTO_DA_PRESENCA_CONFIRMADA,
    TEXTO_DA_REMARCACAO,
    TEXTO_DA_RESERVA_VENCIDA,
    TEXTO_DAS_JANELAS,
    TEXTO_DE_OUTRO_HORARIO,
    TEXTO_DO_CANCELAMENTO_FEITO,
    TEXTO_DO_CONFLITO,
)
from mobia.domain.agendamento.remarcacao import TEXTO_DO_CONVITE_DE_REMARCACAO
from mobia.domain.agente.apresentacao import RESSALVA_DE_ESTIMATIVA
from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO
from mobia.domain.agente.turno import (
    SUFIXO_FORA_DA_JANELA,
    TEXTO_DA_BUSCA_INCONCLUSIVA,
    TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
    TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
    TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
    TEXTO_DO_FILTRO_AJUSTADO,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
    TEXTO_SEM_RESULTADO_APOS_AMPLIAR,
)
from mobia.domain.followup.mensagem import CONVITE_PARA_AGENDAR
from mobia.domain.humano.deteccao import (
    TEXTO_DO_PEDIDO_DE_HUMANO,
    TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO,
)
from mobia.domain.moderacao.port import (
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
)
from mobia.domain.notificacao.envio import TEXTO_DA_JANELA_HUMANA
from mobia.domain.optout.deteccao import TEXTO_DA_CONFIRMACAO_DE_OPTOUT
from mobia.domain.titular.deteccao import (
    TEXTO_DA_CONFIRMACAO_DE_ACESSO,
    TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO,
    TEXTO_DA_PERGUNTA_DE_ELIMINACAO,
)
from mobia.workers.jobs.process_message import TEXTO_DO_AVISO_DE_ERRO

LITERAIS_AO_LEAD = (
    TEXTO_DA_IDENTIFICACAO,
    TEXTO_DA_BUSCA_INCONCLUSIVA,
    TEXTO_SEM_RESULTADO_APOS_AMPLIAR,
    TEXTO_DO_LIMITE_DE_PERGUNTAS,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO_E_BAIRRO,
    TEXTO_DO_CRITERIO_AMPLIADO_PRECO,
    TEXTO_DO_CRITERIO_AMPLIADO_BAIRRO,
    TEXTO_DO_FILTRO_AJUSTADO,
    CONVITE_PARA_AGENDAR,
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
    TEXTO_DA_JANELA_HUMANA,
    TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
    TEXTO_DO_AVISO_DE_ERRO,
    RESSALVA_DE_ESTIMATIVA,
    TEXTO_DO_PEDIDO_DE_HUMANO,
    TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO,
    SUFIXO_FORA_DA_JANELA,
    TEXTO_DO_ENCAMINHAMENTO_DE_VENDA,
    TEXTO_DO_ENCAMINHAMENTO_DE_SUPORTE,
    TEXTO_DO_FIM_DE_SEMANA,
    TEXTO_DO_DOMINGO,
    TEXTO_DE_HOJE_OU_DA_PROXIMA,
    TEXTO_DA_HORA_AMBIGUA,
    TEXTO_DO_PASSADO,
    TEXTO_DE_DOIS_DIAS,
    TEXTO_DA_NOITE,
    TEXTO_DA_DATA_INEXISTENTE,
    TEXTO_DA_CONFIRMACAO_DE_VISITA,
    TEXTO_DA_CONFIRMACAO_DE_VISITA_SEM_IMOVEL,
    TEXTO_DA_CONFIRMACAO_DE_REUNIAO,
    TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA,
    TEXTO_DO_LEMBRETE_DE_24H_DE_VISITA_SEM_IMOVEL,
    TEXTO_DO_LEMBRETE_DE_24H_DE_REUNIAO,
    TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA,
    TEXTO_DO_LEMBRETE_DE_2H_DE_VISITA_SEM_IMOVEL,
    TEXTO_DO_LEMBRETE_DE_2H_DE_REUNIAO,
    TEXTO_DO_CONVITE_DE_REMARCACAO,
    # TEC-371. Os cinco da conversa que marca a visita.
    TEXTO_DAS_JANELAS,
    TEXTO_DA_ESCOLHA,
    TEXTO_DO_CONFLITO,
    TEXTO_DA_RESERVA_VENCIDA,
    TEXTO_DE_OUTRO_HORARIO,
    # TEC-372. Os tres da resposta ao lembrete.
    TEXTO_DA_PRESENCA_CONFIRMADA,
    TEXTO_DO_CANCELAMENTO_FEITO,
    TEXTO_DA_REMARCACAO,
    # TEC-169. Os tres da lista de espera.
    TEXTO_DA_LISTA_DE_ESPERA,
    TEXTO_DA_ESPERA_ACEITA,
    TEXTO_DO_SLOT_LIBERADO,
    # TEC-207. Os dois da confirmacao de pedido de titular, e a pergunta que
    # abre o segundo passo da eliminacao (revisao final, C2).
    TEXTO_DA_CONFIRMACAO_DE_ELIMINACAO,
    TEXTO_DA_CONFIRMACAO_DE_ACESSO,
    TEXTO_DA_PERGUNTA_DE_ELIMINACAO,
)
