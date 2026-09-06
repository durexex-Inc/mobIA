"""O parser do arquivo de catalogo: o que vira registro e o que vira rejeicao.

TEC-156, RN-08.1 e RN-08.5. Estrito no conteudo, tolerante so na forma --
codificacao e delimitador. Ver D5, D6 e D7 do desenho.
"""

import json
from decimal import Decimal

import pytest

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel, Zona
from mobia.domain.catalogo.parser import ArquivoInvalido, parsear
from mobia.domain.catalogo.schemas import RegistroImovel, Rejeicao

CABECALHO = (
    "codigo,titulo,descricao,tipo,operacao,preco_venda,preco_aluguel,condominio,"
    "iptu_mensal,bairro,cidade,uf,zona,latitude,longitude,area_util_m2,quartos,"
    "suites,banheiros,vagas,caracteristicas,fotos,status"
)

LINHA_BOA = (
    "AP-1042,Apartamento com varanda,Vista para o mar e varanda gourmet,"
    "APARTAMENTO,VENDA,580000.00,,850.00,320.00,Centro,Florianopolis,SC,CENTRO,"
    "-27.595377,-48.548050,74,2,1,2,1,varanda gourmet|pet friendly,"
    "https://ex.com/1.jpg|https://ex.com/2.jpg,DISPONIVEL"
)


def _csv(*linhas: str) -> bytes:
    return ("\n".join((CABECALHO, *linhas)) + "\n").encode("utf-8")


def _so(resultado):
    itens = list(resultado)
    assert len(itens) == 1, itens
    return itens[0]


def test_linha_completa_vira_registro():
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert isinstance(r, RegistroImovel)
    assert r.codigo == "AP-1042"
    assert r.tipo is TipoImovel.APARTAMENTO
    assert r.operacao is Operacao.VENDA
    assert r.zona is Zona.CENTRO
    assert r.status is StatusImovel.DISPONIVEL
    assert r.area_util_m2 == 74


def test_preco_em_reais_vira_centavos():
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert r.preco_venda == 58_000_000
    assert r.condominio == 85_000
    assert r.iptu_mensal == 32_000
    assert r.preco_aluguel is None


def test_latitude_e_longitude_sao_decimal_e_nao_float():
    # Coordenada em float acumula erro na ida e volta ao Numeric(9,6).
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert r.latitude == Decimal("-27.595377")
    assert isinstance(r.longitude, Decimal)


def test_arrays_separados_por_barra_vertical():
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert r.caracteristicas == ("varanda gourmet", "pet friendly")
    assert len(r.fotos) == 2


def test_array_vazio_vira_tupla_vazia_e_nao_none():
    linha = LINHA_BOA.replace("varanda gourmet|pet friendly", "")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert r.caracteristicas == ()


def test_a_primeira_linha_de_dados_e_a_linha_2():
    # Numeracao fisica do arquivo: o cabecalho e 1. O numero tem que bater com
    # o que o editor mostra quando o admin for corrigir.
    linha_ruim = LINHA_BOA.replace("APARTAMENTO", "apto")
    r = _so(parsear(_csv(linha_ruim), nome_arquivo="base.csv"))
    assert r.linha == 2


def test_enum_em_minuscula_e_rejeicao_e_nao_normalizacao():
    linha = LINHA_BOA.replace("APARTAMENTO", "apartamento")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "tipo" in r.motivo


def test_uma_rejeicao_por_linha_com_todos_os_motivos():
    linha = LINHA_BOA.replace("APARTAMENTO", "apto").replace(",74,2,", ",74,dois,")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "tipo" in r.motivo
    assert "quartos" in r.motivo
    assert r.motivo.count(";") == 1


def test_sem_nenhum_preco_e_rejeicao():
    linha = LINHA_BOA.replace(",580000.00,,", ",,,")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "preco" in r.motivo


def test_preco_abaixo_da_faixa_e_rejeitado():
    # Quem digitou "580000" achando que eram centavos grava R$ 5.800 sem
    # sintoma nenhum. A guarda existe para esse erro. Ver D6.
    linha = LINHA_BOA.replace("580000.00", "500.00")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "implausivel" in r.motivo


def test_preco_acima_da_faixa_e_rejeitado():
    linha = LINHA_BOA.replace("580000.00", "900000000.00")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "implausivel" in r.motivo


def test_bom_do_excel_nao_derruba_o_cabecalho():
    # Sem utf-8-sig a primeira coluna vira "﻿codigo" (BOM colado no nome) e TODA linha e
    # rejeitada por "codigo ausente" -- 500 rejeicoes com motivo enganoso.
    conteudo = b"\xef\xbb\xbf" + _csv(LINHA_BOA)
    r = _so(parsear(conteudo, nome_arquivo="base.csv"))
    assert isinstance(r, RegistroImovel)
    assert r.codigo == "AP-1042"


def test_delimitador_ponto_e_virgula_do_excel_pt_br():
    conteudo = CABECALHO.replace(",", ";") + "\n" + LINHA_BOA.replace(",", ";") + "\n"
    r = _so(parsear(conteudo.encode("utf-8"), nome_arquivo="base.csv"))
    assert isinstance(r, RegistroImovel)
    assert r.codigo == "AP-1042"


def test_codigo_repetido_no_mesmo_arquivo_e_rejeitado_na_segunda():
    itens = list(parsear(_csv(LINHA_BOA, LINHA_BOA), nome_arquivo="base.csv"))
    assert isinstance(itens[0], RegistroImovel)
    assert isinstance(itens[1], Rejeicao)
    assert "linha 2" in itens[1].motivo


def test_coluna_obrigatoria_ausente_no_cabecalho_derruba_o_arquivo():
    # Isto NAO e rejeicao de linha: sem a coluna, toda linha estaria errada
    # pelo mesmo motivo, e o admin precisa saber que o arquivo esta errado.
    cabecalho_torto = CABECALHO.replace("codigo,", "")
    with pytest.raises(ArquivoInvalido, match="codigo"):
        list(parsear((cabecalho_torto + "\n").encode("utf-8"), nome_arquivo="base.csv"))


def test_json_lista_de_objetos():
    dados = [
        {
            "codigo": "CA-7",
            "titulo": "Casa no centro",
            "descricao": "Casa com quintal",
            "tipo": "CASA",
            "operacao": "VENDA",
            "preco_venda": "750000.00",
            "bairro": "Centro",
            "cidade": "Florianopolis",
            "uf": "SC",
            "area_util_m2": "120",
            "quartos": "3",
            "suites": "1",
            "banheiros": "2",
            "vagas": "2",
            "status": "DISPONIVEL",
        }
    ]
    r = _so(parsear(json.dumps(dados).encode("utf-8"), nome_arquivo="base.json"))
    assert isinstance(r, RegistroImovel)
    assert r.preco_venda == 75_000_000
    # No JSON a "linha" e o indice 1-based do elemento: nao ha linha fisica.
    assert r.linha == 1


def test_json_malformado_derruba_o_arquivo():
    with pytest.raises(ArquivoInvalido):
        list(parsear(b"{nao e json", nome_arquivo="base.json"))


def test_extensao_desconhecida_derruba_o_arquivo():
    with pytest.raises(ArquivoInvalido, match="extensao"):
        list(parsear(b"qualquer coisa", nome_arquivo="base.xlsx"))
