"""O formato que um consumidor externo passa a depender. TEC-180.

Estes testes existem por uma razao diferente da dos vizinhos: nao protegem uma
regra de negocio, protegem um CONTRATO com quem esta fora deste repositorio.
Quem mudar um nome de campo aqui quebra um CRM que nao tem como avisar -- e por
isso o teste da versao e tao importante quanto o dos valores.
"""

import uuid
from datetime import UTC, datetime

from mobia.domain.crm.payload import VERSAO_DO_PAYLOAD, montar
from mobia.domain.handoff.dossie import Dossie, ImovelApresentado

QUANDO = datetime(2026, 9, 24, 14, 30, tzinfo=UTC)
HANDOFF = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _dossie(**trocas: object) -> Dossie:
    base: dict[str, object] = {
        "canal": "whatsapp",
        "conversa": "5511911112222",
        "primeira_mensagem_em": QUANDO,
        "mensagens_do_lead": 12,
        "intencao": "COMPRAR",
        "faixa_min_centavos": None,
        "faixa_max_centavos": 60_000_000,
        "regiao": "Pinheiros",
        "tipo_imovel": "APARTAMENTO",
        "quartos": 2,
        "vagas": 1,
        "urgencia": "ATE_3_MESES",
        "forma_pagamento": "FINANCIAMENTO",
        "tem_imovel_para_vender": False,
        "score_total": 72,
        "score_fatores": (("completude", 25),),
        "score_causas": ("CAMPOS_OBRIGATORIOS",),
        "temperatura": "QUENTE",
        "temperatura_forcada_motivos": (),
        "imoveis": (
            ImovelApresentado("AP-001", 58_000_000, "venda", "GOSTOU", None),
            ImovelApresentado("AP-002", 59_500_000, "venda", "DESCARTOU", "PRECO"),
        ),
        "campos_recusados": ("renda",),
        "perguntados_sem_resposta": ("prazo",),
        "gatilho": "LEAD_QUENTE",
        "etiqueta": "lead-quente",
        "prioridade": "NORMAL",
        "criado_em": QUANDO,
    }
    return Dossie(**(base | trocas))  # type: ignore[arg-type]


def _payload(**trocas: object) -> dict[str, object]:
    argumentos: dict[str, object] = {
        "handoff_id": HANDOFF,
        "dossie": _dossie(),
        "resumo": "Lead quente procurando apartamento em Pinheiros.",
        "resumo_fallback": False,
    }
    return montar(**(argumentos | trocas))  # type: ignore[arg-type]


def test_o_payload_leva_o_numero_da_versao_do_formato() -> None:
    """Primeiro cenario do Gherkin: "um JSON com numero de versao do formato"."""
    assert _payload()["versao"] == VERSAO_DO_PAYLOAD


def test_o_payload_leva_os_dados_do_lead_a_qualificacao_e_o_resumo() -> None:
    """As tres partes que o primeiro cenario do Gherkin nomeia."""
    payload = _payload()

    assert payload["lead"] == {
        "canal": "whatsapp",
        "conversa": "5511911112222",
        "primeira_mensagem_em": QUANDO.isoformat(),
        "mensagens_do_lead": 12,
    }
    qualificacao = payload["qualificacao"]
    assert isinstance(qualificacao, dict)
    assert qualificacao["intencao"] == "COMPRAR"
    assert qualificacao["score_total"] == 72
    assert qualificacao["temperatura"] == "QUENTE"
    assert payload["resumo"] == "Lead quente procurando apartamento em Pinheiros."


def test_o_preco_vai_em_centavos_e_nao_na_prosa_de_reais() -> None:
    """O leitor e um programa.

    `reais()` devolve "R$ 600.000", que obrigaria o CRM a fazer parsing de
    moeda em portugues para comparar dois numeros. Ele existe para o corretor
    ler, e este teste e o que impede alguem de reusa-lo aqui por parecer mais
    apresentavel.
    """
    payload = _payload()

    qualificacao = payload["qualificacao"]
    assert isinstance(qualificacao, dict)
    assert qualificacao["faixa_max_centavos"] == 60_000_000

    imoveis = payload["imoveis_apresentados"]
    assert isinstance(imoveis, list)
    assert imoveis[0]["preco_centavos"] == 58_000_000
    # O rotulo vai junto do numero: um imovel pode ter preco de venda E de
    # aluguel, e o numero sozinho nao diz qual e.
    assert imoveis[0]["tipo_de_preco"] == "venda"


def test_o_resumo_ausente_vai_como_nulo_e_a_exportacao_continua_valida() -> None:
    """D10: o handoff sem resumo e exportado do mesmo jeito.

    O consumidor precisa conseguir distinguir "sem texto" de "texto vazio", e
    e por isso que o campo vai como `null` em vez de string vazia.
    """
    payload = _payload(resumo=None)

    assert payload["resumo"] is None
    assert payload["qualificacao"] is not None


def test_o_payload_diz_quando_o_resumo_veio_do_template() -> None:
    """`resumo_fallback` muda o que o texto E (RN-15.4), e o texto nao o diz.

    Sem este campo, quem pontuasse a qualidade do lead no CRM trataria um
    resumo montado deterministicamente como se um modelo o tivesse redigido.
    """
    assert _payload(resumo_fallback=True)["resumo_fallback"] is True
    assert _payload(resumo_fallback=False)["resumo_fallback"] is False


def test_o_payload_nao_leva_nome_do_lead() -> None:
    """Nenhuma tabela deste sistema guarda um -- emenda E-02 da RN-15.1.

    O teste existe para que quem acrescentar nome ao sistema um dia passe
    aqui e decida conscientemente se ele vai para fora.
    """
    assert "nome" not in str(_payload())


def test_a_reacao_e_o_motivo_de_descarte_acompanham_cada_imovel() -> None:
    imoveis = _payload()["imoveis_apresentados"]

    assert isinstance(imoveis, list)
    assert imoveis[0]["reacao"] == "GOSTOU"
    assert imoveis[0]["motivo_descarte"] is None
    assert imoveis[1]["reacao"] == "DESCARTOU"
    assert imoveis[1]["motivo_descarte"] == "PRECO"


def test_handoff_sem_primeira_mensagem_nao_estoura() -> None:
    """`isoformat_ou_none` existe por isto, e o payload precisa herdar a guarda."""
    payload = _payload(dossie=_dossie(primeira_mensagem_em=None))

    lead = payload["lead"]
    assert isinstance(lead, dict)
    assert lead["primeira_mensagem_em"] is None
