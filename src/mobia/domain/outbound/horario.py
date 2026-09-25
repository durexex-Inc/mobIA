"""O horario em que um envio automatico pode sair. TEC-185, RN-13.3.

Pura de proposito, no molde de `cadencia.py`, `score.py` e `temperatura.py`:
sem I/O, sem banco, sem chamada ao modelo. Quem decide disparar e a
varredura; aqui so se responde "o relogio permite agora?".

**Mora em `outbound/` e nao em `followup/`** porque a regra da card cobre todo
envio automatico -- follow-up, lembrete de agendamento (TEC-171) e
reengajamento (TEC-172). Sob `followup/` a proxima card nao acharia esta
funcao e escreveria a segunda, que e a forma exata do defeito de duas fontes
que a TEC-146 gastou uma card inteira consertando.

**E NAO mora em `GuardedOutbound.send`**, que seria a escolha tentadora: e la
que a guarda de opt-out vive, e o comentario dela diz que quem HERDA daquela
classe "ganha a guarda de graca". Mas aquele caminho carrega a resposta ao
lead -- `executar_turno` envia por ali --, e um lead que escreve as 3h da
manha tem de ser respondido as 3h da manha. A card fala de envio AUTOMATICO,
nao de todo envio; a janela na porta compartilhada silenciaria o produto
treze horas por dia. A guarda pertence aos sitios que ORIGINAM automacao.

**Dois sitios de automacao aplicam esta guarda: `sweep_followups` (TEC-183) e
`sweep_lembretes` (TEC-171) -- e NAO `sweep_stalled`, que tambem e um cron
capaz de causar envio.** A exclusao e deliberada: `sweep_stalled` so
reenfileira `process_message` para uma mensagem INBOUND que o lead ja esta
esperando resposta, nunca origina um contato novo. Gate-lo atrasaria a
resposta a um lead que escreveu as 3h ate as 9h -- exatamente a propriedade
que esta card protege ao NAO tocar `GuardedOutbound.send`. Se um dia
`sweep_stalled` passar a originar envio (e nao so retomar um turno pendente),
a guarda entra la tambem.

**A TEC-171 pagou a consequencia que esta janela cobra, e ela esta declarada
na emenda E-02 da RN-13.3:** com `inicio = 9`, uma visita que comeca as 9h ou
as 10h tem a faixa inteira do lembrete de 2 horas fora desta janela, e esse
lembrete nao sai. Aquela card recusou abrir excecao aqui -- a regra tem dono, e
uma excecao por sitio seria uma segunda opiniao sobre ela.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def horario_permite_envio(*, momento: datetime, inicio: int, fim: int, fuso: ZoneInfo) -> bool:
    """Se um envio automatico pode comecar em `momento`. RN-13.3.

    `inicio` e `fim` sao horas locais no `fuso`, e a janela e inclusiva nas
    duas pontas: `fim=20` autoriza 20:00 e recusa 20:01.

    **A borda inclusiva vem dos criterios de aceite, e os dois primeiros sao a
    mesma borda.** "Um lead QUENTE que parou de responder as 18h ... o
    follow-up e enviado as 20h" cai exatamente em 20:00, porque a primeira
    tentativa do QUENTE e +2h; e "um disparo agendado para exatamente 20h ... a
    mensagem e enviada" diz o mesmo em outras palavras. Uma comparacao
    exclusiva quebraria os dois.

    **Os segundos sao descartados, e isso e o oposto de desleixo.** O cron
    dispara em `minute={0, 5, 10, ...}`, mas `agora` e lido DENTRO do job -- na
    pratica 20:00:00,04. Comparando `time` cheio, esse sweep ficaria FORA da
    janela, e um teste unitario com um `datetime` exato passaria enquanto
    producao falhava o criterio de aceite. Truncando ao minuto, a varredura das
    20:00 entra e a das 20:05 nao.

    **`momento` ingenuo levanta, e a razao e o CI.** `astimezone()` num naive
    nao erra: ele assume o fuso do SISTEMA. A maquina de desenvolvimento deste
    projeto esta em UTC-3 e o runner do GitHub Actions esta em UTC, entao um
    naive daria resultados divergentes nos dois -- e como o `followup_fuso`
    default coincide com o da maquina local, o bug seria invisivel ali e
    apareceria so no CI. Mesma classe de armadilha que o `pythonpath` do
    pyproject.toml documenta, com os papeis trocados.

    Tudo keyword-only: `inicio` e `fim` sao dois `int` adjacentes, e troca-los
    inverte a janela sem levantar, sem erro de tipo e sem o mypy ver. Mesma
    razao dos dois `datetime` de `tentativa_devida` e dos dois flags de
    `temperatura_de`.
    """
    if momento.tzinfo is None:
        raise ValueError(
            "momento sem tzinfo: `astimezone` assumiria o fuso do sistema, que "
            "difere entre esta maquina (UTC-3) e o runner do CI (UTC), e o erro "
            "ficaria invisivel em um dos dois. Passe um datetime aware."
        )
    local = momento.astimezone(fuso)
    minuto_do_dia = local.hour * 60 + local.minute
    return inicio * 60 <= minuto_do_dia <= fim * 60
