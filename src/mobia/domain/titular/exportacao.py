"""O JSON que `GET /leads/{lead_id}/dados-pessoais` devolve. TEC-207, D4.

Reusa os seis blocos de `leads/detalhe.py::ler_detalhe` e acrescenta os dois
que so o titular ve: o consentimento e a transcricao INTEIRA, paginada com
`ve_retidas=True` -- quem pede os proprios dados ve tambem a fala que a
moderacao reteve, ao contrario da tela do corretor.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.consentimento.models import Consentimento
from mobia.domain.identidade.indice import telefones_de
from mobia.domain.leads.detalhe import DetalheDoLead, ler_detalhe
from mobia.domain.leads.transcricao import (
    LIMITE_MAXIMO_DA_TRANSCRICAO,
    CursorDaTranscricao,
    pagina_da_transcricao,
)


def _escalar(valor: object) -> object:
    """Mesma conversao de `api/routes/leads.py::_escalar` -- `Decimal` e
    instante nao tem representacao direta em JSON."""
    if isinstance(valor, Decimal):
        return float(valor)
    isoformat = getattr(valor, "isoformat", None)
    return isoformat() if isoformat is not None else valor


async def _telefone_revelado(session: AsyncSession, par: tuple[str, str]) -> str | None:
    """Com o `+`, como `leads/repositorio.py::valor_revelado` -- quem exporta
    os proprios dados os recebe prontos para discar, e nao em digitos crus."""
    telefone = (await telefones_de(session, [par]))[par]
    return f"+{telefone}" if telefone else None


async def _consentimentos(session: AsyncSession, par: tuple[str, str]) -> list[dict[str, object]]:
    linhas = (
        (
            await session.execute(
                select(Consentimento)
                .where(Consentimento.channel == par[0], Consentimento.conversation_key == par[1])
                .order_by(Consentimento.created_at, Consentimento.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "marketing": linha.marketing,
            "textoExibido": linha.texto_exibido,
            "registradoEm": linha.created_at.isoformat(),
        }
        for linha in linhas
    ]


async def _transcricao_inteira(
    session: AsyncSession, par: tuple[str, str]
) -> list[dict[str, object]]:
    """Todas as falas, da mais antiga a mais recente -- pagina ate o cursor
    acabar. `ve_retidas=True`: o titular ve a propria fala retida pela
    moderacao, ao contrario da tela do corretor (`api/routes/leads.py::mensagens`).
    """
    falas: list[dict[str, object]] = []
    cursor: CursorDaTranscricao | None = None
    while True:
        pagina, anterior = await pagina_da_transcricao(
            session,
            par=par,
            limite=LIMITE_MAXIMO_DA_TRANSCRICAO,
            cursor=cursor,
            ve_retidas=True,
        )
        # Cada pagina ja vem em ordem cronologica; a pagina anterior (mais
        # antiga) entra ANTES da acumulada, porque a paginacao anda para tras.
        pagina_json: list[dict[str, object]] = [
            {
                "autor": fala.autor,
                "tipo": fala.tipo,
                "conteudo": fala.conteudo,
                "em": fala.em.isoformat(),
            }
            for fala in pagina
        ]
        falas = pagina_json + falas
        if anterior is None:
            break
        cursor = anterior
    return falas


def _blocos(lido: DetalheDoLead) -> dict[str, object]:
    """Qualificacao, score, agendamentos, recomendacoes e followups -- os
    cinco blocos de `ler_detalhe` que nao sao o telefone nem o resumo, no
    mesmo camelCase de `api/routes/leads.py::_detalhe_como_json`. O resumo
    fica de fora: e derivado da transcricao, e a transcricao ja sai inteira."""
    return {
        "qualificacao": (
            {chave: _escalar(valor) for chave, valor in lido.qualificacao.items()}
            if lido.qualificacao is not None
            else None
        ),
        "score": lido.score,
        "agendamentos": [
            {
                "id": str(a.id),
                "tipo": a.tipo,
                "inicio": a.inicio.isoformat(),
                "fim": a.fim.isoformat(),
                "status": a.status,
                "imovelId": str(a.imovel_id) if a.imovel_id else None,
            }
            for a in lido.agendamentos
        ],
        "recomendacoes": [
            {
                "imovelId": str(r.imovel_id),
                "codigo": r.codigo,
                "titulo": r.titulo,
                "bairro": r.bairro,
                "scoreMatch": float(r.score_match),
                "motivoMatch": r.motivo_match,
                "reacao": r.reacao,
                "motivoDescarte": r.motivo_descarte,
                "apresentadoEm": r.apresentado_em.isoformat(),
            }
            for r in lido.recomendacoes
        ],
        "followups": [
            {
                "tentativa": f.tentativa,
                "temperatura": f.temperatura,
                "disparadoEm": f.disparado_em.isoformat(),
            }
            for f in lido.followups
        ],
    }


async def exportar(
    session: AsyncSession, *, lead_id: uuid.UUID, par: tuple[str, str]
) -> dict[str, object] | None:
    """O corpo de `GET /leads/{lead_id}/dados-pessoais`, ou `None`.

    `None` quando `ler_detalhe` devolve `None` -- o par existe em
    `referencias_de_lead` (quem chama ja confirmou com `par_de`), mas nao tem
    mensagem nenhuma. Nao deveria acontecer, nem depois de uma eliminacao: a
    anonimizacao apaga o apelido na mesma transacao em que troca o par, entao
    o lead eliminado ja e 404 em `par_de`, e a retencao mantem as linhas de
    `messages`. Ver a docstring de `ler_detalhe`.
    """
    lido = await ler_detalhe(session, lead_id=lead_id, par=par)
    if lido is None:
        return None

    return {
        "exportadoEm": datetime.now(UTC).isoformat(),
        "canal": par[0],
        "telefone": await _telefone_revelado(session, par),
        **_blocos(lido),
        "consentimentos": await _consentimentos(session, par),
        "transcricao": await _transcricao_inteira(session, par),
    }
