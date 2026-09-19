"""O detector que impede a oferta de corretor de aparecer duas vezes (TEC-272).

O teste que carrega esta card e
`test_todo_texto_deterministico_com_corretor_e_reconhecido`: ele **deriva** a
lista dos textos por importacao dos modulos, em vez de transcreve-la. Uma
constante nova que ofereca corretor entra na verificacao sozinha, e se o
detector nao a reconhecer o lead passa a receber a oferta duas vezes -- que e
exatamente o defeito que esta card existe para nao criar.
"""

import mobia.domain.agente.identificacao as ident
import mobia.domain.agente.turno as turno
from mobia.domain.agente.identificacao import (
    TEXTO_DA_OFERTA_DE_CORRETOR,
    ja_oferece_corretor,
)


def _textos_deterministicos_com_corretor() -> dict[str, str]:
    """Toda constante de texto dos dois modulos que menciona corretor.

    Derivada, e nao transcrita: uma lista escrita a mao envelheceria na
    primeira card que acrescentasse trilha, e o envelhecimento seria
    silencioso -- o teste continuaria verde enquanto o lead recebia a oferta
    duplicada.
    """
    achados: dict[str, str] = {}
    for modulo in (ident, turno):
        for nome in dir(modulo):
            if nome.startswith("_"):
                continue
            valor = getattr(modulo, nome)
            if isinstance(valor, str) and "corretor" in valor.lower():
                achados[f"{modulo.__name__}.{nome}"] = valor
    return achados


def test_todo_texto_deterministico_com_corretor_e_reconhecido() -> None:
    """Se um destes nao for reconhecido, aquela trilha passa a duplicar."""
    textos = _textos_deterministicos_com_corretor()

    assert textos, "nenhum texto com corretor encontrado: o derivador quebrou"
    nao_reconhecidos = [nome for nome, valor in textos.items() if not ja_oferece_corretor(valor)]
    assert nao_reconhecidos == []


def test_a_propria_oferta_e_reconhecida() -> None:
    """Sem isto, dois turnos seguidos empilhariam duas ofertas."""
    assert ja_oferece_corretor(TEXTO_DA_OFERTA_DE_CORRETOR) is True


def test_resposta_sem_oferta_nao_e_reconhecida() -> None:
    """O caso que faz o append disparar -- e que a TEC-139 mediu como 1 e 2."""
    assert ja_oferece_corretor("Sim, sou um assistente virtual da imobiliária.") is False
    assert ja_oferece_corretor("Temos três apartamentos de 2 quartos na zona sul.") is False


def test_reconhece_com_e_sem_acento_e_no_plural() -> None:
    """O modelo escreve acentuado e o repo tem literais sem acento.

    Um detector que so casasse uma das formas se calaria na metade dos casos,
    e a metade em que ele se cala e a que duplica.
    """
    assert ja_oferece_corretor("posso te passar para um corretor") is True
    assert ja_oferece_corretor("falo com os corretores da equipe") is True
    assert ja_oferece_corretor("Corretor") is True


def test_texto_vazio_nao_levanta() -> None:
    assert ja_oferece_corretor("") is False
