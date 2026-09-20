"""Nenhum texto ao lead promete um contato que ninguem faz. TEC-286.

Puro: nao toca banco nem modelo. O que se testa aqui e o CONTEUDO dos
literais, e a pergunta e uma so -- este texto afirma que um corretor foi
avisado, ou que vai procurar o lead?

**A promessa e falsa hoje, e o motivo mudou de forma desde que a primeira
versao desta guarda foi escrita.** Desde a TEC-280 o e-mail ao corretor
entrega, por SMTP; mas aceito pelo servidor nao e o mesmo que lido por uma
pessoa, e o WhatsApp ao corretor continua so registrando enquanto nao houver
template aprovado pela Meta (TEC-281). O que o sistema garante e que o
handoff existe numa fila -- e e so isso que o texto pode afirmar.
"""

import pytest

from tests.unit.literais_ao_lead import LITERAIS_AO_LEAD

# As formas que este repo de fato escreveu, mais as vizinhas obvias delas.
#
# **Por que frase e nao palavra.** Ate a TEC-286 a guarda equivalente barrava
# tres palavras -- `avisei`, `avisamos`, `avisado` -- e foi por isso que a
# promessa passou pela quarta vez: `TEXTO_DO_LIMITE_DE_PERGUNTAS` dizia "Pode
# deixar que ele entra em contato", que promete a mesma coisa sem usar
# nenhuma das tres. A guarda pegava o vocabulario de tres ocorrencias
# passadas, e nao o que elas tinham em comum. O historico: a TEC-174 escreveu
# "ja avisei um corretor" e teve de reescrever o texto inteiro; a TEC-143
# reintroduziu a frase e a revisao final a pegou antes do merge; a TEC-149
# escreveu a versao que esta card removeu, e ela sobreviveu a todas as tres.
#
# **Erra de menos, nunca de mais**, como a guarda de acento ao lado. Uma frase
# que falte aqui deixa de pegar um caso; nenhuma das que estao aqui reprova
# texto correto. Nao ha como provar por analise de texto que uma prosa nao
# promete nada -- o que da para prender e a forma que ja escorregou.
#
# **Substring, e nao fronteira de palavra.** O vizinho de acento usa `\b`
# porque la as agulhas sao palavras soltas, que colam em outras ("mes" em
# "mesmo"). Aqui sao frases de duas ou tres palavras: "entra em contato" nao
# aparece por acidente dentro de outra coisa, e a fronteira nao acrescentaria
# nada.
PROMESSAS_BANIDAS = (
    "avisei",
    "avisamos",
    "avisado",
    "entra em contato",
    "entrar em contato",
    "entrará em contato",
    "entram em contato",
    "vai te procurar",
    "vai te ligar",
    "vai te chamar",
)


@pytest.mark.parametrize("texto", LITERAIS_AO_LEAD)
def test_nenhum_literal_ao_lead_promete_contato(texto: str) -> None:
    """A promessa que o sistema nao cumpre, barrada em todo texto fixo.

    `notificacao/envio.py` proibe a promessa por escrito e nomeia o
    precedente. O que esta guarda acrescenta e alcance: ela roda sobre
    `LITERAIS_AO_LEAD` inteira, entao um texto novo entra sob a proibicao no
    momento em que entra na lista -- sem que ninguem se lembre desta card.

    O texto PODE dizer que a conversa foi para a fila de um corretor: isso e
    verdade, o handoff e criado. O que ele nao pode e afirmar que alguem viu o
    aviso ou que vai procurar o lead.
    """
    minusculo = texto.lower()
    achadas = [promessa for promessa in PROMESSAS_BANIDAS if promessa in minusculo]
    assert not achadas, f"{achadas} em {texto!r}"


def test_a_lista_de_promessas_nao_encolheu_sem_querer() -> None:
    """Guarda da guarda, pela razao do vizinho de acento.

    Uma frase removida da tupla acima faz a guarda passar sem checa-la, e
    nenhum teste denuncia. O numero cresce quando alguem achar uma quinta
    forma de prometer -- nunca encolhe sem que a promessa tenha virado
    verdade, e nesse dia a card que a tornou verdadeira e que apaga a linha.
    """
    assert len(PROMESSAS_BANIDAS) == 10
