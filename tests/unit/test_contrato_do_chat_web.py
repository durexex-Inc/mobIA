"""O que o chat web manda por texto tem de casar com o que o servidor reconhece.

TEC-353, D2 e D3. O menu do chat manda frases prontas -- o pedido de corretor
e o telefone do campo com mascara --, e o servidor as reconhece por guardas
deterministicas sobre o texto: `pediu_humano` (TEC-143) e `extrair_telefone`
(TEC-129). Nada liga os dois lados alem deste teste: quem mexer na lista de
termos ou na regex ve o chat quebrar aqui, e nao em producao.

As frases sao COPIAS das constantes do frontend, e cada uma diz de onde veio.
"""

import pytest

from mobia.domain.humano.deteccao import pediu_humano
from mobia.domain.identidade.telefone import extrair_telefone

# `PEDIDO_DE_CORRETOR`, em `frontend/src/components/Conversa.tsx`.
PEDIDO_DE_CORRETOR = "Quero falar com uma pessoa da equipe de corretores."


def test_o_pedido_de_corretor_do_menu_dispara_a_guarda_de_humano() -> None:
    assert pediu_humano(PEDIDO_DE_CORRETOR)


# As duas formas que `telefoneParaEnvio`, em `frontend/src/lib/telefone.ts`,
# produz: celular e fixo.
@pytest.mark.parametrize(
    ("enviado", "canonico"),
    [("+55 48 99999-0021", "5548999990021"), ("+55 48 3333-0021", "554833330021")],
)
def test_o_telefone_do_campo_com_mascara_vincula(enviado: str, canonico: str) -> None:
    assert extrair_telefone(enviado) == canonico
