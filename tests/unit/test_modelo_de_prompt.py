"""As regras de uma versao de prompt, sem banco. TEC-199, D2 e D3 do desenho.

O que se trava aqui: o padrao continua byte a byte o de antes, a clausula de
seguranca nao sai do prompt por edicao nenhuma, e a publicacao recusa o que
quebraria a configuracao da TEC-198 ou o orcamento de contexto.
"""

import pytest

from mobia.domain.agente.classificador import (
    MODELO_DO_AGENTE,
    MODELO_DO_INVESTIDOR,
    SISTEMA_DO_AGENTE,
    SISTEMA_DO_INVESTIDOR,
    renderizar,
)
from mobia.domain.agente.delimitacao import CLAUSULA_DO_AGENTE
from mobia.domain.configuracao.vigente import Tom
from mobia.domain.prompts.modelo import (
    AgenteDoPrompt,
    ModeloInvalido,
    diff_entre,
    modelo_padrao,
    teto_de_caracteres,
    validar_modelo,
)


def test_o_padrao_renderizado_e_o_system_de_antes() -> None:
    """Com o padrao, nome nulo e CORDIAL, nada muda para nenhum dos dois."""
    assert renderizar(MODELO_DO_AGENTE, nome=None, tom=Tom.CORDIAL) == SISTEMA_DO_AGENTE
    assert renderizar(MODELO_DO_INVESTIDOR, nome=None, tom=Tom.CORDIAL) == SISTEMA_DO_INVESTIDOR


def test_a_versao_0_e_o_modelo_do_codigo() -> None:
    assert modelo_padrao(AgenteDoPrompt.AGENTE) == MODELO_DO_AGENTE
    assert modelo_padrao(AgenteDoPrompt.INVESTIDOR) == MODELO_DO_INVESTIDOR


@pytest.mark.parametrize("agente", list(AgenteDoPrompt))
def test_os_padroes_passam_na_propria_validacao(agente: AgenteDoPrompt) -> None:
    """Se o padrao nao passasse, reverter para 0 e republica-lo dariam 422."""
    assert validar_modelo(agente, modelo_padrao(agente)) == modelo_padrao(agente)


def test_a_clausula_de_seguranca_fecha_qualquer_versao() -> None:
    """D2: a defesa da TEC-204 nao faz parte do texto editavel."""
    versao = "Voce e {assistente}. Responda {tom}."
    assert renderizar(versao, nome="Ana", tom=Tom.FORMAL).endswith(f" {CLAUSULA_DO_AGENTE}")
    assert CLAUSULA_DO_AGENTE not in MODELO_DO_AGENTE


def test_o_nome_e_o_tom_entram_pelos_marcadores() -> None:
    texto = renderizar("Voce e {assistente}. Responda {tom}.", nome="Ana", tom=Tom.FORMAL)
    assert texto.startswith(
        "Voce e Ana, o assistente virtual. Responda em tom formal e respeitoso."
    )


def test_um_nome_com_marcador_dentro_nao_e_expandido() -> None:
    """O tom e trocado antes do assistente: o nome pode ter chave, a frase do tom nao."""
    texto = renderizar("{assistente} {tom}", nome="{tom}", tom=Tom.CORDIAL)
    assert texto.startswith("{tom}, o assistente virtual em tom de conversa")


def test_chave_literal_no_texto_nao_derruba_a_renderizacao() -> None:
    """`str.replace`, e nao `format`: um JSON de exemplo nao e marcador."""
    texto = renderizar('{assistente} {tom} {"a": 1}', nome=None, tom=Tom.CORDIAL)
    assert '{"a": 1}' in texto


class TestValidacao:
    def test_sem_o_marcador_do_assistente_e_recusado(self) -> None:
        with pytest.raises(ModeloInvalido, match=r"falta o marcador \{assistente\}"):
            validar_modelo(AgenteDoPrompt.AGENTE, "Responda {tom}.")

    def test_sem_o_marcador_do_tom_e_recusado(self) -> None:
        with pytest.raises(ModeloInvalido, match=r"falta o marcador \{tom\}"):
            validar_modelo(AgenteDoPrompt.AGENTE, "Voce e {assistente}.")

    def test_marcador_desconhecido_e_recusado(self) -> None:
        with pytest.raises(ModeloInvalido, match=r"marcador desconhecido: \{nome\}"):
            validar_modelo(AgenteDoPrompt.AGENTE, "Voce e {assistente}, {nome}, {tom}.")

    def test_vazio_e_recusado(self) -> None:
        with pytest.raises(ModeloInvalido, match="vazio"):
            validar_modelo(AgenteDoPrompt.AGENTE, "   ")

    def test_todas_as_violacoes_vem_juntas(self) -> None:
        with pytest.raises(ModeloInvalido) as erro:
            validar_modelo(AgenteDoPrompt.AGENTE, "{x}")
        assert "{assistente}" in str(erro.value)
        assert "{tom}" in str(erro.value)
        assert "{x}" in str(erro.value)

    @pytest.mark.parametrize("agente", list(AgenteDoPrompt))
    def test_o_padrao_mais_um_caractere_e_recusado(self, agente: AgenteDoPrompt) -> None:
        """D3: a folga do orcamento e reservada ao desenvolvimento."""
        with pytest.raises(ModeloInvalido, match="passa 1 caracteres do tamanho do padrao"):
            validar_modelo(agente, modelo_padrao(agente) + "x")

    def test_do_mesmo_tamanho_do_padrao_passa(self) -> None:
        padrao = modelo_padrao(AgenteDoPrompt.AGENTE)
        reescrito = padrao.replace("Nao negocie valor", "Nao discuta valor")
        assert len(reescrito) <= len(padrao)
        assert validar_modelo(AgenteDoPrompt.AGENTE, reescrito) == reescrito

    def test_um_marcador_repetido_conta_a_frase_de_novo(self) -> None:
        """Medido renderizado: `{assistente}` duas vezes custa o nome duas vezes,
        e um texto que caberia pelo tamanho cru passa do teto renderizado."""
        padrao = modelo_padrao(AgenteDoPrompt.AGENTE)
        cru = padrao[: len(padrao) - len(" {assistente}")] + " {assistente}"
        assert len(cru) <= teto_de_caracteres(AgenteDoPrompt.AGENTE)
        with pytest.raises(ModeloInvalido, match="passa"):
            validar_modelo(AgenteDoPrompt.AGENTE, cru)


def test_o_diff_mostra_a_linha_trocada() -> None:
    diff = diff_entre("a\nb\nc", "a\nB\nc", de="agente v3", para="agente v4")
    assert "--- agente v3" in diff
    assert "+++ agente v4" in diff
    assert "-b" in diff.splitlines()
    assert "+B" in diff.splitlines()
