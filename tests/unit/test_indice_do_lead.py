"""TEC-203, D2: a chave do lead e o HMAC do valor CRU; o telefone tem indice proprio."""

import re

from mobia.domain.identidade.indice import chave_de, indice_de_telefone


def test_chave_e_hex_de_64_e_deterministica():
    chave = chave_de("whatsapp", "5548999990000")
    assert re.fullmatch(r"[0-9a-f]{64}", chave)
    assert chave == chave_de("whatsapp", "5548999990000")


def test_canal_faz_parte_do_dominio():
    assert chave_de("whatsapp", "abc") != chave_de("web", "abc")


def test_wa_id_com_e_sem_o_nono_digito_sao_conversas_distintas():
    # Espelha a chave de antes da TEC-203, que era o wa_id cru.
    assert chave_de("whatsapp", "554899990000") != chave_de("whatsapp", "5548999990000")


def test_indice_de_telefone_nao_colide_com_chave_do_whatsapp():
    assert indice_de_telefone("5548999990000") != chave_de("whatsapp", "5548999990000")


def test_trocar_a_chave_de_indice_muda_a_chave(monkeypatch):
    from mobia.app.config import Settings
    from mobia.domain.identidade import indice

    antes = chave_de("whatsapp", "5548999990000")
    monkeypatch.setattr(indice, "get_settings", lambda: Settings(lead_indice_chave="outra" * 8))
    assert chave_de("whatsapp", "5548999990000") != antes
