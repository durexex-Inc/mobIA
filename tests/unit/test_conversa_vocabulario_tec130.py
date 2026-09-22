"""Os dois motivos que a TEC-130 acrescenta, e o silencio que eles NAO herdam."""

from mobia.domain.conversa.regras import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
from mobia.domain.conversa.repositorio import SituacaoDaConversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento


def test_a_janela_de_silencio_mora_nas_regras_da_conversa() -> None:
    """A constante saiu de `agente/identificacao.py` e vive no modulo puro.

    Ela e compartilhada por tres leitores -- a identificacao de conversa nova,
    a janela de `situacao_da_conversa` e a varredura de inativas -- e morar no
    modulo de um deles fazia os outros dois importarem de `agente/`.
    """
    assert DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA == 30


def test_identificacao_reexporta_a_mesma_constante() -> None:
    """Nao ha duas definicoes de silencio no sistema, so um reexport."""
    from mobia.domain.agente.identificacao import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA as da_ident

    assert da_ident is DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA


def test_os_dois_motivos_novos_existem() -> None:
    assert MotivoDoEncerramento.INATIVIDADE == "INATIVIDADE"
    assert MotivoDoEncerramento.OPTOUT == "OPTOUT"


def test_nenhum_motivo_novo_cala_o_agente() -> None:
    """**O ponto inteiro da RN-02.3.**

    Calar por 30 dias e politica do FORA_DE_ESCOPO (RN-03.5). Um motivo novo
    que herdasse o silencio destruiria o reengajamento que esta card existe
    para ter: o lead que volta depois de 30 dias parados ficaria mais 30 sem
    resposta.
    """
    for motivo in (MotivoDoEncerramento.INATIVIDADE, MotivoDoEncerramento.OPTOUT):
        situacao = SituacaoDaConversa(
            marcada_como_encerrada=True,
            dentro_da_janela=True,
            motivo_do_encerramento=str(motivo),
        )
        assert situacao.silencia_o_agente is False


def test_fora_de_escopo_continua_calando() -> None:
    """A contraprova do teste acima: a propriedade nao foi neutralizada."""
    situacao = SituacaoDaConversa(
        marcada_como_encerrada=True,
        dentro_da_janela=True,
        motivo_do_encerramento=str(MotivoDoEncerramento.FORA_DE_ESCOPO),
    )
    assert situacao.silencia_o_agente is True
