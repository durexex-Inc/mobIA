"""O cursor e a validacao do filtro da lista de leads. TEC-192, e a segunda
ordem da TEC-321 (`TestCursorDaUltimaInteracao` e o `ordenar` do filtro).

Sem banco: o que se verifica aqui e a FORMA do cursor e o que a borda recusa --
as duas coisas que decidem antes de qualquer SQL rodar. Os cenarios contra
banco estao em `tests/integration/test_lista_de_leads.py`.
"""

import base64
import json
import uuid
from datetime import UTC, datetime

import pytest

from mobia.domain.leads.consulta import (
    LIMITE_MAXIMO,
    Cursor,
    FiltroInvalido,
    Ordem,
    RecorteDoPapel,
    decodificar_cursor,
    montar_filtro,
)


class TestCursor:
    def test_ida_e_volta_preserva_os_dois_campos(self) -> None:
        cursor = Cursor(score=42, lead_id=uuid.uuid4())

        assert decodificar_cursor(cursor.codificar()) == cursor

    def test_score_nulo_sobrevive(self) -> None:
        """Lead sem pontuacao entra na lista (D4), entao a pagina pode terminar
        num deles -- e `None` tem de voltar `None`, e nunca zero."""
        cursor = Cursor(score=None, lead_id=uuid.uuid4())

        assert decodificar_cursor(cursor.codificar()).score is None

    def test_o_cursor_nao_carrega_o_par_do_lead(self) -> None:
        """TEC-195, D3: o que trafega aqui deixou de ser dado pessoal.

        `codificar` e base64, que qualquer um decodifica. Enquanto o par
        viajava aqui, `proximoCursor` entregava o telefone do lead a quem nao
        pode le-lo -- por um campo em que ninguem olhava.
        """
        telefone = "5548999990021"
        cursor = Cursor(score=42, lead_id=uuid.uuid4())

        cru = base64.urlsafe_b64decode(cursor.codificar().encode("ascii")).decode("utf-8")

        assert telefone not in cru
        assert "whatsapp" not in cru
        assert str(cursor.lead_id) in cru

    def test_cursor_do_formato_anterior_e_recusado(self) -> None:
        """O `{"s","c","k"}` de antes da TEC-195 nao volta como primeira pagina.

        `KeyError` na chave que sumiu -- e o caso que `decodificar_cursor` ja
        nomeava como "cursor de uma VERSAO anterior deste formato".
        """
        antigo = base64.urlsafe_b64encode(
            json.dumps({"s": 42, "c": "whatsapp", "k": "5548999990021"}).encode("utf-8")
        ).decode("ascii")

        with pytest.raises(FiltroInvalido):
            decodificar_cursor(antigo)

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


class TestCursorDaUltimaInteracao:
    """A segunda ordem da lista (TEC-321, D4): o cursor carrega a ordem."""

    def test_ida_e_volta_preserva_o_instante_e_a_ordem(self) -> None:
        cursor = Cursor(
            score=None,
            lead_id=uuid.uuid4(),
            ordem=Ordem.ULTIMA_INTERACAO,
            ultima_interacao_em=datetime(2026, 9, 26, 14, 3, 7, 123456, tzinfo=UTC),
        )

        assert decodificar_cursor(cursor.codificar()) == cursor

    def test_o_cursor_de_score_mantem_a_forma_de_antes(self) -> None:
        """Nenhum cursor em uso passa a ser recusado: a forma `{"s","l"}` e a
        mesma da TEC-195, e decodifica como ordem por score."""
        lead_id = uuid.uuid4()
        de_antes = base64.urlsafe_b64encode(
            json.dumps({"s": 42, "l": str(lead_id)}, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")

        assert Cursor(score=42, lead_id=lead_id).codificar() == de_antes
        assert decodificar_cursor(de_antes).ordem is Ordem.SCORE

    def test_cursor_da_ultima_interacao_sem_instante_e_recusado(self) -> None:
        corpo = json.dumps({"o": "u", "l": str(uuid.uuid4())}).encode("utf-8")

        with pytest.raises(FiltroInvalido):
            decodificar_cursor(base64.urlsafe_b64encode(corpo).decode("ascii"))


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

    def test_a_ordem_padrao_e_por_score(self) -> None:
        assert montar_filtro().ordem is Ordem.SCORE

    def test_ordem_pelo_nome_do_srs(self) -> None:
        assert montar_filtro(ordenar="ultima_interacao_desc").ordem is Ordem.ULTIMA_INTERACAO

    def test_ordem_desconhecida_e_recusada(self) -> None:
        """Cair na ordem padrao em silencio devolveria uma lista que quem pediu
        leria como a ordem que pediu."""
        with pytest.raises(FiltroInvalido):
            montar_filtro(ordenar="nome_asc")

    def test_cursor_de_uma_ordem_e_recusado_na_outra(self) -> None:
        """Continuar a lista por score a partir de um instante daria uma pagina
        plausivel e errada. TEC-321, D4."""
        de_score = Cursor(score=42, lead_id=uuid.uuid4()).codificar()

        with pytest.raises(FiltroInvalido):
            montar_filtro(ordenar="ultima_interacao_desc", cursor=de_score)

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
