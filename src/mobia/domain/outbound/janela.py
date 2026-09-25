"""A janela de servico da Meta: ate quando cabe mensagem livre. RN-13.6.

Pura de proposito, no molde de `horario.py`: sem I/O, sem banco, sem chamada
ao modelo. Quem decide disparar e a varredura; aqui so se responde "ainda cabe
texto livre nesta conversa?".

**Mora em `outbound/` e nao em `followup/`, pelo argumento que `horario.py` ja
escreveu sobre si mesmo.** A regra e do CANAL -- e a mesma janela que
`outbound/whatsapp.py` nomeia pelo codigo 131047, la como gatilho da recusa e
aqui como duracao --, e vale para todo envio automatico: follow-up (TEC-183),
lembrete de agendamento (TEC-171) e o que vier depois. Ela nasceu sob
`followup/template.py` na TEC-186 e mudou de lar na TEC-171, que foi a
primeira card a precisar dela de fora do follow-up: sob `followup/` a proxima
card nao acharia esta funcao e escreveria a segunda, que e a forma exata do
defeito de duas fontes que a TEC-146 gastou uma card inteira consertando.

**O CATALOGO de templates nao veio junto.** `TEMPLATES` e
`escolher_template` continuam em `followup/template.py`, e o lembrete tem o
proprio (`domain/agendamento/lembretes.py`): as categorias de la sao contextos
de reengajamento, escolhidos do par `(ficha, queda)` que um lembrete nao tem.
O que e do canal e a janela; o que e do produto e o texto que cabe nela.
"""

from datetime import datetime, timedelta

# A Meta so aceita mensagem livre dentro de 24h da ultima fala do lead; fora
# disso, so template aprovado. E a mesma janela que `outbound/whatsapp.py`
# nomeia pelo codigo 131047 -- la ela e o gatilho da recusa, aqui e a duracao.
JANELA_DE_SERVICO = timedelta(hours=24)


def dentro_da_janela(*, ancora_em: datetime, agora: datetime) -> bool:
    """True quando ainda cabe mensagem livre. TEC-186, RN-13.6.

    **A borda e estrita (`<`).** Aos 24h exatos a janela ja fechou -- e a regra
    da Meta, e o cenario 4 do Gherkin cai exatamente nesse limite. Um `<=` aqui
    deixaria passar um envio livre que a Meta recusaria.

    **`ancora_em`, e nao a ultima mensagem da conversa.** A ancora e a ultima
    fala do LEAD (`candidatos_a_followup`), entao uma resposta do agente no
    meio nao move a janela -- e o cenario 4 do Gherkin exige exatamente isso.
    No lembrete de agendamento (TEC-171) a ancora e a mesma coisa pela mesma
    razao, e e dela que sai o `recipient_external_id` do envio.

    Tudo keyword-only: `ancora_em` e `agora` sao dois `datetime` adjacentes, e
    trocar a ordem devolveria o resultado errado em silencio, sem erro de tipo
    -- mesma razao de `tentativa_devida` (`followup/cadencia.py`).
    """
    return agora - ancora_em < JANELA_DE_SERVICO
