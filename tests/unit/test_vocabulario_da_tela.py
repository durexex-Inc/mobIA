"""O que a tela escreve de novo e tem de bater com o backend. TEC-329, TEC-328, TEC-325 e TEC-322.

A correcao da qualificacao oferece `tipoImovel`, `urgencia` e `formaPagamento`
como listas, e as opcoes saem dos mapas de rotulo de `frontend/src/lib/detalhe.ts`.
Nenhuma rota expoe os enums, entao este teste e o que amarra os dois lados: um
valor novo em `agente/schemas.py` sem rotulo na tela, ou um que so a tela tem,
reprova aqui -- e nao no 422 que o corretor veria.

Desde a TEC-328 (D2) vale tambem para a duracao da janela de servico da Meta,
que a tela usa para reabrir a janela quando o lead fala de novo; e desde a
TEC-325 (D4), para as causas do recalculo, a reacao do lead ao imovel e a
categoria do descarte; e desde a TEC-322 (D5), para os filtros da lista de
leads, que moram em `leads.ts`; e desde a TEC-404, para os tipos de evento do
filtro da trilha de auditoria, que moram em `auditoria.ts`.

O arquivo TypeScript e lido como texto. A forma que o teste espera e a de um
objeto literal com chaves sem aspas, uma por linha -- maiusculas nos enums,
minusculas nos canais; se ela mudar, o teste
reprova por nao achar o mapa, e nao passa em silencio.
"""

import re
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

import pytest

from mobia.domain.agente.schemas import (
    CategoriaDescarte,
    FormaPagamento,
    ReacaoLead,
    TipoImovel,
    Urgencia,
)
from mobia.domain.auditoria.vocabulario import Acao
from mobia.domain.context import auditoria
from mobia.domain.context.temperatura import Temperatura
from mobia.domain.conversa.vocabulario import Status
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.outbound.janela import JANELA_DE_SERVICO

_DETALHE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "detalhe.ts"
_LEADS = _DETALHE.with_name("leads.ts")


def _chaves_do_mapa(nome: str, arquivo: Path = _DETALHE) -> set[str]:
    fonte = arquivo.read_text(encoding="utf-8")
    achado = re.search(
        rf"export const {nome}: Record<string, string> = \{{(.*?)\n\}}", fonte, re.DOTALL
    )
    assert achado, f"mapa `{nome}` nao encontrado em {arquivo.name}"
    return set(re.findall(r"^\s*([A-Za-z0-9_]+):", achado.group(1), re.MULTILINE))


@pytest.mark.parametrize(
    ("mapa", "enum"),
    [
        ("TIPOS_DE_IMOVEL", TipoImovel),
        ("URGENCIAS", Urgencia),
        ("FORMAS_DE_PAGAMENTO", FormaPagamento),
        # TEC-325, D4: a reacao do lead e a categoria do descarte.
        ("REACOES", ReacaoLead),
        ("DESCARTES", CategoriaDescarte),
    ],
)
def test_a_lista_da_tela_e_o_enum_do_backend(mapa: str, enum: type[StrEnum]) -> None:
    assert _chaves_do_mapa(mapa) == {membro.value for membro in enum}


_RESPOSTA = _DETALHE.with_name("resposta.ts")


def test_a_janela_da_tela_e_a_do_backend() -> None:
    """TEC-328, D2: a tela reabre a janela com a fala nova do lead, e a duracao e a mesma."""
    fonte = _RESPOSTA.read_text(encoding="utf-8")
    achado = re.search(r"export const JANELA_DE_SERVICO_MS = ([0-9_]+)\n", fonte)
    assert achado, f"`JANELA_DE_SERVICO_MS` nao encontrada em {_RESPOSTA.name}"
    assert timedelta(milliseconds=int(achado.group(1).replace("_", ""))) == JANELA_DE_SERVICO


def test_os_motivos_do_recalculo_sao_as_causas_do_backend() -> None:
    """TEC-325, D4: toda `CAUSA_*` de `context/auditoria.py` tem rotulo na tela, e so elas."""
    causas = {
        valor
        for nome, valor in vars(auditoria).items()
        if nome.startswith("CAUSA_") and isinstance(valor, str)
    }
    assert _chaves_do_mapa("CAUSAS_DO_SCORE") == causas


_AUDITORIA = _DETALHE.with_name("auditoria.ts")


def test_os_tipos_de_evento_da_trilha_sao_as_acoes_do_backend() -> None:
    """TEC-404: `ACOES` de `auditoria.ts` e o filtro da trilha; acao sem rotulo la some dele."""
    assert _chaves_do_mapa("ACOES", _AUDITORIA) == {acao.value for acao in Acao}


@pytest.mark.parametrize(
    ("mapa", "valores"),
    [
        ("TEMPERATURAS", {t.value for t in Temperatura}),
        ("STATUS", {s.value for s in Status}),
        ("CANAIS", {CANAL_WHATSAPP, CANAL_WEB}),
    ],
)
def test_os_filtros_da_lista_sao_os_do_backend(mapa: str, valores: set[str]) -> None:
    """TEC-322, D5: as listas de filtro saem destes mapas; o backend recusa `status` fora deles."""
    assert _chaves_do_mapa(mapa, _LEADS) == valores
