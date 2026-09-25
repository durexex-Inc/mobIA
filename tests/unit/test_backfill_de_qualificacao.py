"""O limiar de completude que a migration 0055 copiou. TEC-367.

Nao toca banco: le o ARQUIVO da migration com `ast`, como
`test_auditoria_vocabulario.py` e `test_uma_cabeca_de_migration.py` fazem, e
pela mesma razao -- importar a migration rodaria o `from alembic import op`
fora de um contexto de migracao.

**Este arquivo existe porque o `20` e uma copia.** A migration nao importa
`mobia.*` de proposito (migration aplicada nao muda quando o codigo muda), e
o preco dessa escolha e uma segunda fonte para o mesmo numero. Sem esta
guarda, mudar `PONTOS_POR_CAMPO_OBRIGATORIO` ou acrescentar um quinto campo
obrigatorio deixaria a migration certa sobre o passado e a prosa dela errada
sobre o presente -- e ninguem notaria.
"""

import ast
import pathlib

from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import (
    CAMPOS_OBRIGATORIOS,
    campos_obrigatorios_preenchidos,
    esta_qualificado,
)
from mobia.domain.context.score import PONTOS_POR_CAMPO_OBRIGATORIO

MIGRACAO = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0055_backfill_de_qualificado_em.py"
)


def _constante_da_migracao(nome: str) -> int:
    arvore = ast.parse(MIGRACAO.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(
            isinstance(alvo, ast.Name) and alvo.id == nome for alvo in no.targets
        ):
            valor = ast.literal_eval(no.value)
            assert isinstance(valor, int)
            return valor
    raise AssertionError(f"{nome} nao encontrado na 0055")


def test_o_limiar_copiado_bate_com_o_codigo() -> None:
    """O `20` da migration e `len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO`.

    Divergir nao quebra o que a migration ja aplicou -- e essa e justamente a
    razao de ela nao importar do codigo. O que divergir quebra e a prosa dela,
    que afirma qual condicao o numero representa.
    """
    esperado = len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO
    assert _constante_da_migracao("COMPLETUDE_DE_QUALIFICADO") == esperado


def _estado(**campos: object) -> LeadQualification:
    """Um `LeadQualification` solto, sem banco. Nao e adicionado a sessao nenhuma."""
    return LeadQualification(channel="whatsapp", conversation_key="5511900000000", **campos)


_QUATRO_CAMPOS = {
    "intencao": "COMPRA",
    "faixa_preco_max_centavos": 80_000_000,
    "regiao": "pinheiros",
    "urgencia": "ATE_30_DIAS",
}


def test_completude_cheia_e_a_mesma_condicao_de_esta_qualificado() -> None:
    """A equivalencia de que o backfill inteiro depende.

    Se um dia `esta_qualificado` ganhar um criterio que
    `campos_obrigatorios_preenchidos` nao veja -- ou o contrario --, a
    migration passa a datar a coisa errada. As duas funcoes leem hoje os
    mesmos `CAMPOS_OBRIGATORIOS` com o mesmo `_preenchido`, e este teste e o
    que denuncia quando deixarem de ler.
    """
    completo = _estado(**_QUATRO_CAMPOS)
    limiar = len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO

    assert esta_qualificado(completo) is True
    assert campos_obrigatorios_preenchidos(completo) * PONTOS_POR_CAMPO_OBRIGATORIO == limiar


def test_com_um_campo_a_menos_nenhuma_das_duas_vale() -> None:
    """A outra ponta da equivalencia: tres campos nao datam nada."""
    parcial = _estado(**{k: v for k, v in _QUATRO_CAMPOS.items() if k != "urgencia"})
    limiar = len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO

    assert esta_qualificado(parcial) is False
    assert campos_obrigatorios_preenchidos(parcial) * PONTOS_POR_CAMPO_OBRIGATORIO < limiar


def test_campo_recusado_derruba_as_duas_juntas() -> None:
    """Recusa e o caso em que as duas funcoes poderiam divergir e nao divergem.

    `campos_obrigatorios_preenchidos` desconta recusado mesmo com valor na
    coluna, e `esta_qualificado` tambem. Se so uma delas descontasse, um lead
    que recusou falar de orcamento seria datado pelo backfill como
    qualificado.
    """
    completo = _estado(**_QUATRO_CAMPOS)
    recusados = frozenset({"faixa_preco_max"})
    limiar = len(CAMPOS_OBRIGATORIOS) * PONTOS_POR_CAMPO_OBRIGATORIO

    assert esta_qualificado(completo, recusados) is False
    assert campos_obrigatorios_preenchidos(completo, recusados) * PONTOS_POR_CAMPO_OBRIGATORIO < (
        limiar
    )
