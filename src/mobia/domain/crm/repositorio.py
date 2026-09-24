"""As leituras e as tres marcas da exportacao para CRM. TEC-180.

Nao ha tabela propria: a "fila de reprocessamento" da RN-16.5 e a linha de
`handoffs` com `crm_sincronizado_em` nulo. Ver a emenda E-01 a RN-16.5 e a D5
do desenho.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.handoff.models import Handoff, aad_do_resumo_de_handoff
from mobia.infra.crypto import DecryptionError, decrypt

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EstadoDaExportacao:
    """O que o job precisa saber da linha antes de decidir o que fazer."""

    tentativas: int
    ja_sincronizado: bool
    resumo: str | None
    resumo_fallback: bool


async def carregar_estado(
    session: AsyncSession, *, handoff_id: uuid.UUID
) -> EstadoDaExportacao | None:
    """O estado da exportacao, com o resumo ja decifrado. `None` sem handoff.

    `None` e nao excecao, pela mesma razao que `carregar_dossie` escreve: o job
    pode chegar depois de a linha sumir, e isso nao e erro dele.

    **`DecryptionError` degrada para `resumo=None` em vez de subir.** Molde e
    argumento de `notificacao/envio.py`: sem a guarda, rotacao de chave ou
    restore de outro ambiente fariam o job falhar, retentar, falhar de novo e
    terminar como falha permanente -- um alerta de CRM indisponivel para um
    problema que nao e do CRM. Exportar sem o texto e melhor que nao exportar:
    o CRM ainda recebe a qualificacao, o score e os imoveis.
    """
    handoff = (
        await session.execute(select(Handoff).where(Handoff.id == handoff_id))
    ).scalar_one_or_none()
    if handoff is None:
        return None

    try:
        resumo = decrypt(handoff.resumo, aad_do_resumo_de_handoff(handoff.id))
    except DecryptionError as falha:
        resumo = None
        log.warning(
            "crm.resumo_ilegivel",
            handoff_id=str(handoff_id),
            erro=type(falha).__name__,
        )

    return EstadoDaExportacao(
        tentativas=handoff.crm_tentativas,
        ja_sincronizado=handoff.crm_sincronizado_em is not None,
        resumo=resumo,
        resumo_fallback=handoff.resumo_fallback,
    )


async def marcar_sincronizado(session: AsyncSession, *, handoff_id: uuid.UUID) -> None:
    """Carimba a entrega. **Nao commita** -- mesma disciplina de `gravar_resumo`.

    Limpa `crm_ultimo_erro` junto: uma entrega bem-sucedida depois de duas
    falhas deixaria a coluna apontando um erro que ja nao descreve nada, e
    quem olhasse a linha leria "sincronizado" e "ConnectTimeout" lado a lado.
    Mesma classe de defeito que `gravar_resumo` evita ao gravar
    `resumo_fallback` nos dois sentidos.

    **`crm_tentativas` NAO e zerado.** Ele conta a rodada, e a rodada terminou
    em entrega -- zerar apagaria a evidencia de que esta exportacao custou tres
    tentativas, que e o que alguem quer ver ao investigar um CRM instavel. Quem
    zera e a varredura, ao abrir uma rodada nova.
    """
    await session.execute(
        update(Handoff)
        .where(Handoff.id == handoff_id)
        .values(
            crm_sincronizado_em=datetime.now(UTC),
            crm_ultimo_erro=None,
            atualizado_em=datetime.now(UTC),
        )
    )


async def registrar_falha(session: AsyncSession, *, handoff_id: uuid.UUID, motivo: str) -> int:
    """Soma uma tentativa e grava o motivo. Devolve o total da rodada.

    **O incremento e no banco (`crm_tentativas + 1`), nao em Python.** Ler,
    somar e escrever abriria uma janela em que duas tentativas concorrentes do
    mesmo handoff -- que o `_job_id` derivado torna improvavel, nao impossivel
    -- gravariam o mesmo numero, e a terceira falha nunca chegaria a tres. O
    laco seria eterno e silencioso, que e o modo de falha que esta card existe
    para matar.

    Devolve o valor JA gravado, via `RETURNING`, e nao um calculado aqui: e o
    numero que o job compara com `MAX_TENTATIVAS`, e ele precisa ser o que o
    banco tem.

    `motivo` vem truncado ao tamanho da coluna. Truncar e melhor que estourar:
    um motivo longo e sinal de que alguem violou a garantia que o docstring de
    `FalhaDeExportacao` faz sobre o campo, e perder o fim do texto e desfecho
    mais barato que uma excecao de banco dentro do tratamento de erro.
    """
    resultado = await session.execute(
        text(
            """
            UPDATE handoffs
               SET crm_tentativas = crm_tentativas + 1,
                   crm_ultimo_erro = :motivo,
                   atualizado_em = now()
             WHERE id = :handoff_id
            RETURNING crm_tentativas
            """
        ),
        {"handoff_id": handoff_id, "motivo": motivo[:80]},
    )
    total = resultado.scalar_one_or_none()
    return int(total) if total is not None else 0
