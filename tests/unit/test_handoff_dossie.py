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
            ImovelApresentado("AP-001", 58_000_000, "venda", "GOSTOU", None),
            ImovelApresentado("AP-002", 59_500_000, "venda", "DESCARTOU", "PRECO"),
            ImovelApresentado("AP-003", 55_000_000, "venda", None, None),
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
            imoveis=(ImovelApresentado("AP-001", 58_000_000, "venda", "GOSTOU", None),),
        )
    )

    assert "nenhum ponto de atencao registrado" in texto


def test_renderizar_sem_primeira_mensagem_nao_inventa_data() -> None:
    """Sem mensagem do lead, primeira_mensagem_em e None -- ver fix wave da
    TEC-175. Renderizar como AUSENTE, nunca como uma data que nao e fato
    sobre mensagem nenhuma (o criado_em do handoff, por exemplo)."""
    texto = renderizar(_dossie(primeira_mensagem_em=None, mensagens_do_lead=0))

    assert "primeira mensagem: nao informado" in texto


def test_renderizar_rotula_o_preco_por_tipo() -> None:
    """RN-15.3: todo numero citado e o do banco. Um imovel de aluguel nao
    pode sair com o preco de venda, e o rotulo e o que prova a distincao."""
    texto = renderizar(
        _dossie(
            imoveis=(
                ImovelApresentado("AP-100", 58_000_000, "venda", "GOSTOU", None),
                ImovelApresentado("AP-200", 320_000, "aluguel", None, None),
            )
        )
    )

    assert "R$ 580.000 (venda)" in texto
    assert "R$ 3.200 (aluguel)" in texto
