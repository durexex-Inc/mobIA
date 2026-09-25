"""O cursor e a validacao do filtro da lista de leads. TEC-192.

Sem banco: o que se verifica aqui e a FORMA do cursor e o que a borda recusa --
as duas coisas que decidem antes de qualquer SQL rodar. Os cenarios contra
banco estao em `tests/integration/test_lista_de_leads.py`.
"""

import uuid

import pytest

from mobia.domain.leads.consulta import (
    LIMITE_MAXIMO,
    Cursor,
    FiltroInvalido,
    RecorteDoPapel,
    decodificar_cursor,
    montar_filtro,
)


class TestCursor:
    def test_ida_e_volta_preserva_os_tres_campos(self) -> None:
        cursor = Cursor(score=42, channel="whatsapp", conversation_key="5548999")

        assert decodificar_cursor(cursor.codificar()) == cursor

    def test_score_nulo_sobrevive(self) -> None:
        """Lead sem pontuacao entra na lista (D4), entao a pagina pode terminar
        num deles -- e `None` tem de voltar `None`, e nunca zero."""
        cursor = Cursor(score=None, channel="web", conversation_key="sessao-1")

        assert decodificar_cursor(cursor.codificar()).score is None

    @pytest.mark.parametrize(
        "texto",
        [
            "nao-e-base64!!",
            "",
            "eyJ4IjoxfQ==",  # base64 e JSON validos, chaves erradas
            "Zm9v",  # base64 valido, JSON invalido
        ],
    )
    def test_cursor_invalido_e_recusado(self, texto: str) -> None:
        """**Recusa, e nao volta para a primeira pagina.**

        Voltar em silencio faria a tela mostrar o comeco da lista como se fosse
        a continuacao dela, e o defeito apareceria so como "a rolagem pulou
        para o topo sozinha".
        """
        with pytest.raises(FiltroInvalido):
            decodificar_cursor(texto)


class TestFiltro:
    @pytest.mark.parametrize("limite", [0, -1, LIMITE_MAXIMO + 1])
    def test_limite_fora_da_faixa_e_recusado(self, limite: int) -> None:
        with pytest.raises(FiltroInvalido):
            montar_filtro(limite=limite)

    def test_status_desconhecido_e_recusado(self) -> None:
        """`QUALIFICADO` esta no exemplo do SRS e nao existe neste sistema (D8).

        Recusar e nao devolver vazio: lista vazia se leria como "nao ha lead
        qualificado", que e afirmacao sobre o negocio.
        """
        with pytest.raises(FiltroInvalido):
            montar_filtro(status="QUALIFICADO")

    def test_busca_so_de_espacos_vira_ausencia(self) -> None:
        """Sem isto, a busca filtraria por `%   %` e a base pareceria vazia."""
        assert montar_filtro(busca="   ").busca is None


class TestRecorteDoPapel:
    def test_corretor_sem_vinculo_nao_ve_nada(self) -> None:
        """Fail-closed, e e a asserta que separa esta classe de um `uuid | None`.

        Com o vinculo nulo colapsado em "sem recorte", um CORRETOR de cadastro
        incompleto veria a base inteira -- foi o defeito da primeira
        implementacao desta card.
        """
        assert RecorteDoPapel(e_corretor=True, corretor_id=None).nao_ve_nada

    def test_quem_nao_e_corretor_nao_tem_recorte(self) -> None:
        assert not RecorteDoPapel().nao_ve_nada
        assert not RecorteDoPapel(e_corretor=False, corretor_id=uuid.uuid4()).nao_ve_nada

    def test_corretor_com_vinculo_tem_recorte_e_nao_e_vazio(self) -> None:
        recorte = RecorteDoPapel(e_corretor=True, corretor_id=uuid.uuid4())

        assert not recorte.nao_ve_nada
