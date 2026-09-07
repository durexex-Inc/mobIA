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


def test_uf_mais_longa_que_a_coluna_e_rejeicao_de_linha():
    """ "Sao Paulo" no lugar de "SP" nao pode derrubar o lote inteiro.

    Sem esta checagem o registro atravessava o parser, entrava num INSERT de
    500 linhas e o Postgres derrubava o lote com StringDataRightTruncation:
    zero imoveis gravados, FALHOU sem numero de linha e sem nome de campo, por
    um typo numa celula. O parser e a unica camada que sabe a linha.
    """
    linha = LINHA_BOA.replace(",SC,CENTRO,", ",Sao Paulo,CENTRO,")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "uf" in r.motivo
    assert r.linha == 2


def test_codigo_titulo_bairro_e_cidade_respeitam_o_tamanho_da_coluna():
    casos = {
        "codigo": ("AP-1042", "A" * 21),
        "titulo": ("Apartamento com varanda", "T" * 161),
        "bairro": ("Centro", "B" * 121),
        "cidade": ("Florianopolis", "C" * 121),
    }
    for campo, (original, longo) in casos.items():
        linha = LINHA_BOA.replace(original, longo)
        r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
        assert isinstance(r, Rejeicao), campo
        assert campo in r.motivo, (campo, r.motivo)


def test_o_limite_de_texto_vem_da_coluna_e_nao_de_constante_copiada():
    # Guarda contra descolamento: se `titulo` virar String(200), um 160
    # escrito no parser passaria a recusar linha boa sem nenhum gate acusar.
    from mobia.domain.catalogo.models import Imovel
    from mobia.domain.catalogo.parser import _limite_de_texto

    for campo in ("codigo", "titulo", "bairro", "cidade", "uf"):
        assert _limite_de_texto(campo) == Imovel.__table__.c[campo].type.length
    # Text nao tem teto, e nao um teto grande: a checagem tem de sair de cena.
    assert _limite_de_texto("descricao") is None


def test_quartos_fora_do_smallint_e_rejeicao_de_linha():
    # `99999` nao e "muito quarto": e overflow de SMALLINT, que derruba o
    # INSERT do lote de 500 do mesmo jeito que o `uf` longo.
    linha = LINHA_BOA.replace(",74,2,1,2,1,", ",74,99999,1,2,1,")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "quartos" in r.motivo


def test_area_util_fora_do_integer_e_rejeicao_de_linha():
    linha = LINHA_BOA.replace(",74,2,1,2,1,", ",99999999999,2,1,2,1,")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "area_util_m2" in r.motivo


def test_latitude_fora_da_faixa_geografica_e_rejeicao_de_linha():
    # Numeric(9, 6) aceita tres digitos inteiros; "1234.5" estoura a coluna.
    linha = LINHA_BOA.replace("-27.595377", "1234.5")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "latitude" in r.motivo


def test_longitude_fora_da_faixa_geografica_e_rejeicao_de_linha():
    linha = LINHA_BOA.replace("-48.548050", "-200.0")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "longitude" in r.motivo


def test_latitude_nan_e_rejeicao_e_nao_um_decimal_valido():
    """`Decimal("NaN")` parseia, o `numeric` do Postgres o aceita, e envenena o diff.

    Gravado, `NaN != NaN` faz o diff campo a campo de `_mudou` acusar a linha
    como alterada em TODA reimportacao: um UPDATE inutil por importacao, e
    `updated_at` bumpado numa linha que nao mudou -- exatamente o que o
    comentario da coluna diz que nao pode acontecer.
    """
    for texto in ("NaN", "nan", "-NaN", "sNaN"):
        linha = LINHA_BOA.replace("-27.595377", texto)
        r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
        assert isinstance(r, Rejeicao), texto
        assert "latitude" in r.motivo


def test_coordenada_infinita_e_rejeicao():
    for texto in ("Infinity", "-Infinity"):
        linha = LINHA_BOA.replace("-48.548050", texto)
        r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
        assert isinstance(r, Rejeicao), texto
        assert "longitude" in r.motivo


def test_preco_nao_finito_e_rejeicao():
    for texto in ("NaN", "Infinity"):
        linha = LINHA_BOA.replace("580000.00", texto)
        r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
        assert isinstance(r, Rejeicao), texto
        assert "preco_venda" in r.motivo


def test_condominio_que_nao_cabe_no_bigint_e_rejeicao_de_linha():
    # O limite fisico da coluna vale mesmo sem guarda de plausibilidade: a
    # ausencia de faixa em condominio (D6) nao e licenca para estourar BIGINT.
    linha = LINHA_BOA.replace(",850.00,", ",1e30,")
    r = _so(parsear(_csv(linha), nome_arquivo="base.csv"))
    assert isinstance(r, Rejeicao)
    assert "condominio" in r.motivo


def test_condominio_e_iptu_nao_tem_guarda_de_faixa():
    """R$ 850 de condominio e R$ 320 de IPTU passam, e isso e decisao D6.

    A faixa [R$ 1.000, R$ 500.000.000] de `preco_venda`/`preco_aluguel` NAO se
    aplica a esses dois campos: sao cobrancas mensais, tipicamente na casa das
    centenas de reais, e o piso de R$ 1.000 rejeitaria a maioria dos imoveis
    legitimos. Os dois valores deste teste ficam abaixo do piso de proposito.

    Este teste existe porque a excecao inverte o que o plano original dizia e
    hoje so esta protegida por acidente: uma limpeza de "consistencia" que
    acrescentasse `checar_faixa=True` as quatro chamadas de `preco` produziria
    uma falha sobre centavos, confusa o bastante para ser "corrigida" mexendo
    na expectativa. A lacuna declarada 7 do desenho e a contrapartida aceita.
    """
    r = _so(parsear(_csv(LINHA_BOA), nome_arquivo="base.csv"))
    assert isinstance(r, RegistroImovel)
    assert r.condominio == 85_000
    assert r.iptu_mensal == 32_000
    # E o mesmo valor, no campo com guarda, seria recusado:
    linha = LINHA_BOA.replace("580000.00", "850.00")
    assert isinstance(_so(parsear(_csv(linha), nome_arquivo="base.csv")), Rejeicao)


def test_descricao_com_quebra_de_linha_nao_desloca_a_numeracao():
    """A numeracao conta linha fisica, e nao registro.

    Uma `descricao` entre aspas com quebra de linha faz o primeiro registro
    ocupar as linhas 2 e 3. Com `enumerate` sobre registros o registro
    seguinte seria chamado de linha 3, e todo numero dali para frente
    apontaria para a linha errada no editor de quem for corrigir.
    """
    com_quebra = LINHA_BOA.replace(
        "Vista para o mar e varanda gourmet",
        '"Vista para o mar\ne varanda gourmet"',
    )
    ruim = LINHA_BOA.replace("AP-1042", "AP-2").replace("APARTAMENTO", "apto")
    itens = list(parsear(_csv(com_quebra, ruim), nome_arquivo="base.csv"))

    assert isinstance(itens[0], RegistroImovel)
    assert itens[0].descricao == "Vista para o mar\ne varanda gourmet"
    assert itens[0].linha == 3  # o registro termina na linha 3
    assert isinstance(itens[1], Rejeicao)
    assert itens[1].linha == 4  # e nao 3, que e onde `enumerate` o poria
