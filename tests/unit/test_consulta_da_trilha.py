"""O cursor e a validacao do filtro da trilha de auditoria. TEC-206, D8.

Sem banco, no molde de `test_cursor_da_lista_de_leads.py`. Os cenarios contra
banco estao em `tests/integration/test_rota_de_auditoria.py`.
"""

import uuid
from datetime import UTC, datetime

import pytest

from mobia.domain.auditoria.consulta import CursorDaTrilha, decodificar_cursor, montar_filtro
from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.leads.consulta import LIMITE_MAXIMO, FiltroInvalido

CHAVE = "chave-de-teste"
AGORA = datetime(2026, 9, 25, 12, 0, 0, 123456, tzinfo=UTC)


class TestCursor:
    def test_ida_e_volta_preserva_os_microssegundos(self) -> None:
        cursor = CursorDaTrilha(criado_em=AGORA, id=uuid.uuid4())

        assert decodificar_cursor(cursor.codificar()) == cursor

    @pytest.mark.parametrize(
        "texto",
        [
            "nao-e-base64!!",
            "",
            # {"x":1}: base64 e JSON validos, chaves erradas
            "eyJ4IjoxfQ==",
            # {"t": "...+00:00", "i": "x"}: data boa, uuid invalido
            "eyJ0IjoiMjAyNi0wOS0yNVQxMjowMDowMCswMDowMCIsImkiOiJ4In0=",
            # [1,2]: JSON que nao e objeto
            "WzEsMl0=",
            # {"t": "2026-09-25T12:00:00", "i": uuid valido}: sem fuso
            "eyJ0IjoiMjAyNi0wOS0yNVQxMjowMDowMCIsImkiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDAifQ==",
            # nao-ASCII: `encode("ascii")` levanta antes do base64
            "cursor-com-acentuação",
        ],
    )
    def test_cursor_invalido_e_recusado(self, texto: str) -> None:
        with pytest.raises(FiltroInvalido, match="cursor"):
            decodificar_cursor(texto)


class TestFiltro:
    def test_o_lead_vira_lead_ref_e_o_telefone_nao_fica(self) -> None:
        filtro = montar_filtro(
            channel="whatsapp", conversation_key="5511911112222", chave_do_lead=CHAVE
        )

        assert filtro.lead_ref == lead_ref("whatsapp", "5511911112222", chave=CHAVE)
        assert "5511911112222" not in repr(filtro)

    @pytest.mark.parametrize(
        ("channel", "conversation_key"), [("whatsapp", None), (None, "5511911112222")]
    )
    def test_lead_pela_metade_e_recusado(
        self, channel: str | None, conversation_key: str | None
    ) -> None:
        """Review Focus 5: metade do par nao pode virar "sem filtro"."""
        with pytest.raises(FiltroInvalido, match="juntos"):
            montar_filtro(channel=channel, conversation_key=conversation_key, chave_do_lead=CHAVE)

    def test_acao_fora_do_vocabulario_e_recusada(self) -> None:
        with pytest.raises(FiltroInvalido, match="APAGOU"):
            montar_filtro(acoes=("HANDOFF_CRIADO", "APAGOU"), chave_do_lead=CHAVE)

    @pytest.mark.parametrize("limite", [0, LIMITE_MAXIMO + 1])
    def test_limite_fora_da_faixa(self, limite: int) -> None:
        with pytest.raises(FiltroInvalido, match="limite"):
            montar_filtro(limite=limite, chave_do_lead=CHAVE)

    def test_data_sem_fuso_e_recusada(self) -> None:
        with pytest.raises(FiltroInvalido, match="fuso"):
            montar_filtro(de=datetime(2026, 9, 1), chave_do_lead=CHAVE)

    def test_intervalo_vazio_ou_invertido_e_recusado(self) -> None:
        with pytest.raises(FiltroInvalido, match="anterior"):
            montar_filtro(de=AGORA, ate=AGORA, chave_do_lead=CHAVE)

    def test_sem_filtro_nenhum_passa(self) -> None:
        filtro = montar_filtro(chave_do_lead=CHAVE)

        assert filtro.lead_ref is None
        assert filtro.acoes == ()
