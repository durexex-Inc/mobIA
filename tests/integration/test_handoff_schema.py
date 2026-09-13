"""O schema de `handoffs`: o que so o Postgres prova."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.repositorio import registrar_handoff
from mobia.domain.handoff.vocabulario import Gatilho

CANAL = "whatsapp"
CONVERSA = "5511911112222"


def _linha(status: str = "PENDENTE", conversa: str = CONVERSA) -> Handoff:
    return Handoff(
        id=uuid.uuid4(),
        channel=CANAL,
        conversation_key=conversa,
        gatilho="LEAD_QUENTE",
        etiqueta="lead-quente",
        prioridade="NORMAL",
        status=status,
        criado_em=datetime.now(UTC),
        atualizado_em=datetime.now(UTC),
    )


async def test_a_tabela_aceita_uma_linha_pendente(session: AsyncSession) -> None:
    session.add(_linha())
    await session.commit()
    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 1


async def test_dois_pendentes_na_mesma_conversa_sao_recusados_pelo_banco(
    session: AsyncSession,
) -> None:
    """O UNIQUE parcial e a garantia da deduplicacao, nao a consulta.

    Sem ele, dois turnos concorrentes do mesmo lead criam dois handoffs -- e a
    concorrencia e prevista, nao hipotetica: `turno.py` declara que
    `lead.esquentou` reemite para o MESMO lead desde a TEC-148.
    """
    session.add(_linha())
    await session.commit()
    session.add(_linha())
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_um_concluido_nao_bloqueia_um_pendente_novo(session: AsyncSession) -> None:
    """O indice so olha para PENDENTE.

    Um lead atendido meses atras que volta merece handoff novo -- por isso o
    `postgresql_where`, e nao um UNIQUE simples sobre o par.
    """
    session.add(_linha(status="CONCLUIDO"))
    await session.commit()
    session.add(_linha())
    await session.commit()
    total = await session.scalar(text("SELECT count(*) FROM handoffs"))
    assert total == 2


async def test_gatilhos_adicionais_nasce_vazio_e_nao_nulo(session: AsyncSession) -> None:
    """`array_append` sobre NULL funciona, mas o default vazio evita a duvida."""
    linha = _linha()
    session.add(linha)
    await session.commit()
    valor = await session.scalar(
        text("SELECT gatilhos_adicionais FROM handoffs WHERE id = :i"), {"i": linha.id}
    )
    assert valor == []


async def test_a_coluna_do_resumo_nasce_nulavel_e_binaria(session: AsyncSession) -> None:
    """Nulavel por construcao: a geracao e assincrona (D1 do desenho).

    Todo handoff existe por alguns segundos sem resumo, e NULL e o nome desse
    intervalo -- e tambem o estado em que ele fica quando a geracao falha, que
    e o que a TEC-176 vai ler.
    """
    linhas = (
        await session.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'handoffs' "
                "AND column_name IN ('resumo', 'resumo_gerado_em', 'resumo_modelo')"
            )
        )
    ).all()

    por_nome = {linha[0]: (linha[1], linha[2]) for linha in linhas}
    assert por_nome["resumo"] == ("bytea", "YES")
    assert por_nome["resumo_gerado_em"] == ("timestamp with time zone", "YES")
    assert por_nome["resumo_modelo"] == ("character varying", "YES")


async def test_o_resumo_recusa_texto_claro(session: AsyncSession) -> None:
    """Mesma guarda de `Message` e de `ConversationSummary`.

    O driver embute o argumento recusado na propria mensagem de excecao, antes
    de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log.
    """
    with pytest.raises(TypeError, match="apenas bytes cifrados"):
        Handoff(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key="5511911112222",
            gatilho="LEAD_QUENTE",
            etiqueta="lead-quente",
            prioridade="NORMAL",
            status="PENDENTE",
            resumo="texto em claro",
        )


async def test_as_colunas_da_notificacao_nascem_com_o_default_certo(
    session: AsyncSession,
) -> None:
    """`notificado_em` nulo e `aviso_manual_pendente` falso: ninguem tentou ainda.

    O default de `aviso_manual_pendente` e FALSO e nao verdadeiro, e a
    distincao importa: verdadeiro significaria que todo handoff nasce pedindo
    intervencao humana, e o dashboard da E8 mostraria a fila inteira como
    problema. O estado "ainda nao tentei" e falso com `notificado_em` nulo.
    """
    registro = await registrar_handoff(
        session,
        channel="whatsapp",
        conversation_key="5511911112222",
        gatilho=Gatilho.LEAD_QUENTE,
    )
    await session.commit()

    linha = (await session.execute(select(Handoff).where(Handoff.id == registro.id))).scalar_one()
    assert linha.notificado_em is None
    assert linha.aviso_manual_pendente is False
