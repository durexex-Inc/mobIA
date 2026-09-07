"""O documento embeddado: quais campos entram, e quando o hash muda.

Funcao pura, sem banco. O criterio de aceite da card -- "o texto embeddado
nao contem preco nem numero de quartos" -- virou os dois primeiros testes.
"""

import uuid

from mobia.domain.catalogo.documento import documento_de, hash_do_documento
from mobia.domain.catalogo.models import Imovel


def _imovel(**sobrescritas: object) -> Imovel:
    campos: dict[str, object] = {
        "id": uuid.uuid4(),
        "codigo": "AP-001",
        "titulo": "Apartamento reformado na Vila Mariana",
        "descricao": "Sala ampla com varanda gourmet e sol da manha.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 74900000,
        "preco_aluguel": None,
        "condominio": 89000,
        "iptu_mensal": 31000,
        "bairro": "Vila Mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "zona": "SUL",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        # Texto sem digito de proposito: o teste abaixo afirma a ausencia dos
        # VALORES numericos, e digito solto dentro de texto livre legitimo
        # tornaria a assercao insustentavel.
        "caracteristicas": ["varanda gourmet", "portaria full time"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    return Imovel(**campos)


def test_nenhum_valor_numerico_do_imovel_aparece_no_documento() -> None:
    documento = documento_de(_imovel())

    # Os valores como o banco os guarda, e como um humano os leria.
    for proibido in ("74900000", "749000", "89000", "890", "31000", "310"):
        assert proibido not in documento, f"{proibido!r} vazou para o documento"

    # Nenhum algarismo, o que so vale porque o fixture usa texto sem digito:
    # e a forma mais forte de afirmar que area, quartos, suites, banheiros e
    # vagas nao entraram.
    assert not any(caractere.isdigit() for caractere in documento)


def test_o_documento_e_exatamente_os_seis_campos_nesta_ordem() -> None:
    # Igualdade exata, e nao `in`: e o que pega um campo novo entrando no
    # documento sem que ninguem decida que ele deve entrar.
    assert documento_de(_imovel()) == "\n".join(
        [
            "Apartamento reformado na Vila Mariana",
            "Sala ampla com varanda gourmet e sol da manha.",
            "APARTAMENTO",
            "Vila Mariana",
            "Sao Paulo",
            "varanda gourmet",
            "portaria full time",
        ]
    )


def test_os_quatro_textuais_de_filtro_ficam_fora() -> None:
    documento = documento_de(_imovel())

    # Dimensoes de filtro por igualdade, resolvidas no WHERE da RN-09.1.
    # Pedir ao vetor que entenda "para alugar" e o mesmo erro que pedir que
    # entenda "ate 600 mil".
    assert "VENDA" not in documento
    assert "DISPONIVEL" not in documento
    assert "SUL" not in documento
    assert "SP" not in documento


def test_os_seis_campos_que_entram_estao_no_documento() -> None:
    documento = documento_de(_imovel())

    assert "Apartamento reformado na Vila Mariana" in documento
    assert "Sala ampla com varanda gourmet" in documento
    assert "APARTAMENTO" in documento
    assert "Vila Mariana" in documento
    assert "Sao Paulo" in documento
    assert "portaria full time" in documento


def test_o_hash_nao_muda_quando_so_o_preco_muda() -> None:
    antes = hash_do_documento(documento_de(_imovel(preco_venda=74900000)))
    depois = hash_do_documento(documento_de(_imovel(preco_venda=69900000)))

    assert antes == depois


def test_o_hash_muda_quando_a_descricao_muda() -> None:
    antes = hash_do_documento(documento_de(_imovel()))
    depois = hash_do_documento(documento_de(_imovel(descricao="Reformado em 2026.")))

    assert antes != depois


def test_o_hash_e_sha256_em_hexadecimal() -> None:
    valor = hash_do_documento("qualquer texto")

    assert len(valor) == 64
    assert set(valor) <= set("0123456789abcdef")
