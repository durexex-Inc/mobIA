"""A gravacao dos campos do investidor, sem banco. TEC-153.

O que se trava aqui e a RELEITURA das colunas de vocabulario: o perfil e
derivado do estado ja mesclado, entao `gravar_investidor` precisa converter
de volta o que a coluna guarda. Um duble captura o `UPDATE` que ela montaria,
como em `test_estado_marcado.py` -- o SQL compilado diz o que seria gravado
sem precisar de Postgres de pe.
"""

import logging
from typing import Any

from sqlalchemy.dialects import postgresql

from mobia.domain.agente.investidor import (
    ExtracaoDoInvestidor,
    Horizonte,
    RetornoEsperadoTipo,
)
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import gravar_investidor

CANAL = "whatsapp"
CONVERSA = "c-1"


class _SessaoComLinha:
    """Duble minimo: devolve a linha que `gravar_investidor` rele e guarda o
    `UPDATE` que ela mandaria executar. Nao herda de `AsyncSession` -- so
    precisa dos dois metodos que a funcao chama, e nao abre conexao nenhuma.
    """

    def __init__(self, linha: LeadQualification) -> None:
        self.linha = linha
        self.statement: Any = None

    async def scalar(self, statement: Any) -> LeadQualification:
        return self.linha

    async def execute(self, statement: Any) -> None:
        self.statement = statement


def _sql_de(sessao: _SessaoComLinha) -> str:
    assert sessao.statement is not None, "nenhum UPDATE foi montado"
    return str(sessao.statement.compile(dialect=postgresql.dialect()))


async def test_o_perfil_sai_do_estado_mesclado_e_nao_so_deste_turno() -> None:
    """Horizonte pode ter vindo num turno e o tipo de retorno noutro."""
    linha = LeadQualification(
        channel=CANAL, conversation_key=CONVERSA, horizonte=Horizonte.LONGO.value
    )
    sessao = _SessaoComLinha(linha)

    await gravar_investidor(
        sessao,  # type: ignore[arg-type]
        channel=CANAL,
        conversation_key=CONVERSA,
        investidor=ExtracaoDoInvestidor(retorno_esperado_tipo=RetornoEsperadoTipo.ALUGUEL),
    )

    assert "perfil_investidor" in _sql_de(sessao)


async def test_valor_fora_do_enum_na_coluna_nao_derruba_o_turno(caplog) -> None:
    """Uma card futura que encolha um vocabulario sem migrar os dados nao pode
    transformar isso em falha de turno.

    O construtor cru (`Horizonte(linha.horizonte)`) levantaria `ValueError`
    dentro da transacao PRE-entrega: a mensagem voltaria para a fila e o lead
    nao receberia resposta nenhuma. Com a leitura tolerante o perfil so deixa
    de ser derivado -- fica como esta ate o lead responder de novo --, e o
    resto do turno grava normalmente.

    Hoje nada escreve valor assim: so `gravar_investidor` toca estas colunas,
    e sempre a partir do enum. E defesa para o dia seguinte, com log para ela
    nao ser silenciosa.
    """
    linha = LeadQualification(
        channel=CANAL,
        conversation_key=CONVERSA,
        horizonte="ETERNO",
        retorno_esperado_tipo=RetornoEsperadoTipo.ALUGUEL.value,
    )
    sessao = _SessaoComLinha(linha)

    with caplog.at_level(logging.WARNING):
        await gravar_investidor(
            sessao,  # type: ignore[arg-type]
            channel=CANAL,
            conversation_key=CONVERSA,
            investidor=ExtracaoDoInvestidor(ja_investe_em_imoveis=True),
        )

    sql = _sql_de(sessao)
    assert "ja_investe_em_imoveis" in sql
    assert "perfil_investidor" not in sql, (
        "sem horizonte valido nao ha perfil a derivar -- e `None` nao apaga o que havia"
    )
    assert "estado.vocabulario_fora_do_enum" in caplog.text
    assert "ETERNO" in caplog.text, "descobrir QUAL valor sumiu do vocabulario e o ponto do alerta"
