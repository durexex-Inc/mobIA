"""O vocabulario da trilha do investidor. TEC-153, RN-05.2 e RN-07.2.

**Modulo proprio, e nao `schemas.py`.** Aquele arquivo define o schema
estrito da chamada principal, e o schema compilado e uma das quatro parcelas
do orcamento de prompt medido contra o teto fixo -- seis campos que a maioria
dos leads nunca preenche nao podem custar tokens a todos eles. O vocabulario
do investidor pertence a OUTRA chamada, e fica fora daquele schema de
proposito. Ver a D2 do desenho.

Sem I/O, como `handoff/vocabulario.py` e `corretores/vocabulario.py`: e o que
deixa a regra ser testada em `tests/unit/`, sem Postgres de pe.
"""

import dataclasses
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from mobia.domain.agente.schemas import Extracao, Intencao


class Horizonte(StrEnum):
    """As faixas da RN-05.2. Faixas, nao datas -- o que importa e o prazo em
    que o dinheiro sai, nao a data em que o lead pensou nisso."""

    CURTO = "CURTO"
    MEDIO = "MEDIO"
    LONGO = "LONGO"


class RetornoEsperadoTipo(StrEnum):
    """O que o investidor espera COMO retorno, nao QUANTO.

    Este e o campo que a RN-07.2 pressupoe sem nomear. `retorno_esperado_pct`
    nao separa renda de valorizacao: 8% ao ano descreve os dois. Ver a Emenda
    E-01 da RN-07.2.
    """

    ALUGUEL = "ALUGUEL"
    REVENDA = "REVENDA"
    AMBOS = "AMBOS"


class ToleranciaReforma(StrEnum):
    NENHUMA = "NENHUMA"
    LEVE = "LEVE"
    PESADA = "PESADA"


class PerfilInvestidor(StrEnum):
    """Os tres da RN-07.2. Derivado por `perfil_de`, nunca informado pelo lead."""

    RENDA = "RENDA"
    VALORIZACAO = "VALORIZACAO"
    MISTO = "MISTO"


@dataclass(frozen=True, slots=True)
class ExtracaoDoInvestidor:
    """O que a chamada do subagente investidor devolve sobre a fala do lead.

    Frozen como `Extracao`, e todo campo nulavel: qualificacao e progressiva,
    e campo ausente e o estado normal, nao defeito.

    **`ticket_expressao` e `str`, nao `int`.** O modelo devolve o que o lead
    falou ("uns 800 mil") e quem normaliza e `ticket_de`, em `dinheiro.py` --
    o mesmo desenho que `faixa_preco_expressao` ja usa em `Extracao`. Pedir
    centavos ao modelo seria delegar a ele uma conversao que o codigo faz
    melhor e que precisa ser a mesma da trilha padrao.
    """

    ticket_expressao: str | None = None
    retorno_esperado_pct: Decimal | None = None
    retorno_esperado_tipo: RetornoEsperadoTipo | None = None
    horizonte: Horizonte | None = None
    tolerancia_reforma: ToleranciaReforma | None = None
    ja_investe_em_imoveis: bool | None = None


# Derivado do dataclass, nunca escrito a mao: uma segunda lista de nomes
# divergiria em silencio, que e o defeito que a TEC-146 gastou uma card
# inteira consertando. Quem le isto e `_nome_contavel` (em
# `context/repositorio.py`), para que a trilha do investidor conte no teto da
# RN-05.5 (TEC-149) -- e nao `_marca_de`, que e o vocabulario da MARCA e
# ignora estes nomes de proposito: campo de investidor nunca sai de
# `Extracao.preenchidos()`, entao marca-lo seria marcar de mais, para sempre.
# Quem mudar de novo quem le esta constante move esta frase junto: ela ja
# esteve errada tres vezes, e nenhuma delas apareceu no diff -- o que muda e
# o CONSUMIDOR, noutro arquivo, e `scripts/comentarios_tocados.py` nao tem
# como ver isso daqui.
CAMPOS_DO_INVESTIDOR: frozenset[str] = frozenset(
    campo.name for campo in dataclasses.fields(ExtracaoDoInvestidor)
)


@dataclass(frozen=True)
class RespostaDoInvestidor:
    """O que a chamada do subagente investidor devolve num turno.

    **Mesmo envelope de `RespostaDoAgente` (em `schemas.py`), mais
    `investidor`.** A chamada do investidor e uma chamada de modelo como
    qualquer outra: `turno.py` e `MessageRecorder.record_agent_message` leem
    o mesmo conjunto de campos de telemetria e de conteudo dela que leem da
    resposta da trilha padrao, e um campo que faltasse aqui so quebraria o
    turno no ramo do investidor -- o pior tipo de falha para achar, porque a
    trilha padrao continuaria passando em todo teste que nao a exercita.

    Os campos ate `extracao` sao literalmente os de `RespostaDoAgente`, na
    mesma ordem; `investidor` entra logo depois de `extracao` porque os dois
    sao "o que este turno extraiu" e os dois sao obrigatorios -- um dataclass
    nao aceita campo sem default depois de um campo com default, e todo o
    resto abaixo (`perguntou` em diante) ja carrega default em
    `RespostaDoAgente`. Dali para baixo a ordem e a mesma do original.

    Duplicar em vez de derivar de uma base comum foi decisao deliberada desta
    tarefa, nao trade-off resolvido por engenho local: a TEC-153 registrou a
    duplicacao e deixou para uma tarefa futura decidir se compensa extrair
    uma base -- ver o relatorio da Task 2.
    """

    intencao: Intencao
    confianca: Decimal
    resposta: str
    modelo: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    extracao: Extracao
    investidor: ExtracaoDoInvestidor

    perguntou: tuple[str, ...] = ()
    recusou: tuple[str, ...] = ()
    cache_write: int = 0
    cache_read: int = 0
    candidatos: list[dict[str, Any]] = field(default_factory=list)
    criterios: list[str] = field(default_factory=list)
    relaxou_e_achou: bool = False
    relaxou_sem_resultado: bool = False
    relaxou_preco: bool = False
    relaxou_bairro: bool = False
