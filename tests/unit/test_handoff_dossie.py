from datetime import UTC, datetime

from mobia.domain.handoff.dossie import Dossie, ImovelApresentado, reais, renderizar

QUANDO = datetime(2026, 9, 12, 14, 30, tzinfo=UTC)


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
        "score_fatores": (("completude", 25), ("urgencia", 20)),
        "score_causas": ("CAMPOS_OBRIGATORIOS",),
        "temperatura": "QUENTE",
        "temperatura_forcada_motivos": (),
        "imoveis": (
            ImovelApresentado("AP-001", 58_000_000, "GOSTOU", None),
            ImovelApresentado("AP-002", 59_500_000, "DESCARTOU", "PRECO"),
            ImovelApresentado("AP-003", 55_000_000, None, None),
        ),
        "campos_recusados": ("renda",),
        "perguntados_sem_resposta": ("prazo",),
        "gatilho": "LEAD_QUENTE",
        "etiqueta": "lead-quente",
        "prioridade": "NORMAL",
        "criado_em": QUANDO,
    }
    return Dossie(**(base | trocas))  # type: ignore[arg-type]


def test_reais_formata_centavos_em_moeda_brasileira() -> None:
    assert reais(60_000_000) == "R$ 600.000"
    assert reais(0) == "R$ 0"
    assert reais(None) == "nao informado"


def test_renderizar_cita_os_numeros_do_banco() -> None:
    texto = renderizar(_dossie())

    assert "72" in texto
    assert "R$ 600.000" in texto
    assert "3 imoveis apresentados" in texto


def test_renderizar_nao_inventa_quando_o_campo_e_nulo() -> None:
    texto = renderizar(_dossie(regiao=None, quartos=None, score_total=None))

    assert "nao informado" in texto
    # O numero que nao existe nao pode aparecer inventado como zero.
    assert "score 0" not in texto


def test_renderizar_lista_os_pontos_de_atencao_estruturados() -> None:
    texto = renderizar(_dossie())

    assert "renda" in texto
    assert "prazo" in texto
    assert "PRECO" in texto


def test_renderizar_sem_pontos_de_atencao_diz_que_nao_ha() -> None:
    texto = renderizar(
        _dossie(
            campos_recusados=(),
            perguntados_sem_resposta=(),
            imoveis=(ImovelApresentado("AP-001", 58_000_000, "GOSTOU", None),),
        )
    )

    assert "nenhum ponto de atencao registrado" in texto
