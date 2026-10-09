"""Os pedidos de interesse do portal, como o painel os le. TEC-404.

D4 da spec: cada pedido aponta para o handoff mais recente do mesmo lead
criado ate o momento do pedido -- o que nasceu junto com ele ou o que ja estava
aberto. D8: lista mascarada, por `criado_em` decrescente, keyset por
(`criado_em`, `id`), sem total. O recorte do CORRETOR vem da claim do JWT
(`RecorteDoPapel`), nunca da query.
"""

import base64
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Row, Select, and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.catalogo.models import Imovel
from mobia.domain.corretores.models import Corretor
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import ACEITAVEIS
from mobia.domain.identidade.indice import telefones_de
from mobia.domain.leads.consulta import RecorteDoPapel
from mobia.domain.leads.mascara import mascarar_email, mascarar_telefone
from mobia.domain.leads.repositorio import referencias_para
from mobia.domain.portal.interesse import SolicitacaoDeInteresse, aad_do_email_de_interesse
from mobia.infra.crypto import decrypt


class Estado(StrEnum):
    PENDENTES = "pendentes"
    TODOS = "todos"


class CursorInvalido(ValueError):
    pass


@dataclass(frozen=True)
class CursorDePedidos:
    criado_em: datetime
    id: uuid.UUID

    def codificar(self) -> str:
        """base64 de um JSON, opaco como o cursor de `leads/consulta.py`."""
        corpo = json.dumps({"c": self.criado_em.isoformat(), "i": str(self.id)})
        return base64.urlsafe_b64encode(corpo.encode("utf-8")).decode("ascii")


def decodificar_cursor(texto: str) -> CursorDePedidos:
    """Recusa, e nao volta para a primeira pagina -- mesma regra de
    `leads/consulta.py::decodificar_cursor`.

    **Data sem fuso tambem e recusada.** `codificar` sempre escreve o fuso,
    porque `criado_em` e `timestamptz`; uma data ingenua so chega aqui montada a
    mao, e o banco a leria no fuso da sessao -- a pagina seguinte pularia ou
    repetiria linhas sem erro nenhum.
    """
    try:
        corpo = json.loads(base64.urlsafe_b64decode(texto.encode("ascii")))
        cursor = CursorDePedidos(
            criado_em=datetime.fromisoformat(corpo["c"]), id=uuid.UUID(corpo["i"])
        )
    except (ValueError, KeyError, TypeError) as erro:
        raise CursorInvalido("cursor invalido") from erro
    if cursor.criado_em.tzinfo is None:
        raise CursorInvalido("cursor invalido")
    return cursor


@dataclass(frozen=True)
class Atendimento:
    id: uuid.UUID
    status: str
    corretor_id: uuid.UUID | None
    corretor_nome: str | None
    notificado_em: datetime | None
    sem_corretor: bool


@dataclass(frozen=True)
class PedidoDaLista:
    id: uuid.UUID
    criado_em: datetime
    imovel_id: uuid.UUID
    imovel_codigo: str
    imovel_titulo: str
    nome: str | None
    telefone_mascarado: str | None
    email_mascarado: str | None
    lead_id: uuid.UUID
    channel: str
    conversation_key: str
    atendimento: Atendimento | None


# O handoff de cada pedido (D4), como LATERAL: correlacionado com a linha de
# `SolicitacaoDeInteresse` da consulta de fora. So as colunas que o item usa.
# O `id` desempata dois handoffs do mesmo lead no mesmo instante -- sem ele o
# Postgres escolheria qualquer um, e o mesmo pedido poderia apontar para
# atendimentos diferentes entre duas leituras.
_HANDOFF = (
    select(
        Handoff.id,
        Handoff.status,
        Handoff.corretor_id,
        Handoff.notificado_em,
        Handoff.aviso_manual_pendente,
    )
    .where(
        Handoff.channel == SolicitacaoDeInteresse.channel,
        Handoff.conversation_key == SolicitacaoDeInteresse.conversation_key,
        Handoff.criado_em <= SolicitacaoDeInteresse.criado_em,
    )
    .order_by(Handoff.criado_em.desc(), Handoff.id.desc())
    .limit(1)
    .lateral("atendimento")
)


def _consulta() -> Select[
    SolicitacaoDeInteresse,
    str,
    str,
    uuid.UUID | None,
    str | None,
    uuid.UUID | None,
    datetime | None,
    bool | None,
    str | None,
]:
    """Pedido, imovel, handoff (D4) e nome do corretor, numa ida so.

    `LEFT JOIN ... ON true` no lateral: pedido sem handoff nenhum continua na
    lista de `todos`, com as colunas do lateral nulas. O portal de hoje cria os
    dois na mesma transacao, mas nada no schema liga uma tabela a outra, e um
    pedido nao deve sumir da tela por falta do atendimento. Por isso todas elas sao opcionais
    no tipo, mesmo as que sao `NOT NULL` em `handoffs`.
    """
    return (
        select(
            SolicitacaoDeInteresse,
            Imovel.codigo,
            Imovel.titulo,
            _HANDOFF.c.id,
            _HANDOFF.c.status,
            _HANDOFF.c.corretor_id,
            _HANDOFF.c.notificado_em,
            _HANDOFF.c.aviso_manual_pendente,
            Corretor.nome,
        )
        .join(Imovel, Imovel.id == SolicitacaoDeInteresse.imovel_id)
        .outerjoin(_HANDOFF, true())
        .outerjoin(Corretor, Corretor.id == _HANDOFF.c.corretor_id)
    )


async def listar_pedidos(
    session: AsyncSession,
    *,
    estado: Estado,
    limite: int,
    cursor: CursorDePedidos | None,
    recorte: RecorteDoPapel,
) -> tuple[list[PedidoDaLista], CursorDePedidos | None]:
    """A pagina pedida e o cursor da proxima. Pede `limite + 1` para saber se ha mais.

    Nao commita: `referencias_para` cria apelidos, e quem chama decide a
    transacao.
    """
    if recorte.nao_ve_nada:
        return [], None

    consulta = _consulta().order_by(
        SolicitacaoDeInteresse.criado_em.desc(), SolicitacaoDeInteresse.id.desc()
    )
    if estado is Estado.PENDENTES:
        # "Pendente" na tela (D8) e PENDENTE ou ESCALADO: o mesmo conjunto de
        # `ACEITAVEIS`, o que ainda espera alguem assumir. `IN` com coluna nula
        # e nulo, nao verdadeiro: o pedido sem handoff sai daqui sem condicao
        # propria -- nao ha atendimento esperando nele.
        consulta = consulta.where(_HANDOFF.c.status.in_(ACEITAVEIS))
    if recorte.e_corretor:
        consulta = consulta.where(_HANDOFF.c.corretor_id == recorte.corretor_id)
    if cursor is not None:
        # Espelho exato do `ORDER BY` acima: estritamente depois de
        # (`criado_em`, `id`) na ordem decrescente dos dois.
        consulta = consulta.where(
            or_(
                SolicitacaoDeInteresse.criado_em < cursor.criado_em,
                and_(
                    SolicitacaoDeInteresse.criado_em == cursor.criado_em,
                    SolicitacaoDeInteresse.id < cursor.id,
                ),
            )
        )

    linhas = (await session.execute(consulta.limit(limite + 1))).all()
    visiveis = linhas[:limite]
    pares = [(linha[0].channel, linha[0].conversation_key) for linha in visiveis]
    apelidos = await referencias_para(session, pares)
    telefones = await telefones_de(session, pares)

    pagina = [_montar(linha, apelidos, telefones) for linha in visiveis]
    proximo = (
        CursorDePedidos(criado_em=pagina[-1].criado_em, id=pagina[-1].id)
        if len(linhas) > limite and pagina
        else None
    )
    return pagina, proximo


def _montar(
    linha: Row[
        SolicitacaoDeInteresse,
        str,
        str,
        uuid.UUID | None,
        str | None,
        uuid.UUID | None,
        datetime | None,
        bool | None,
        str | None,
    ],
    apelidos: Mapping[tuple[str, str], uuid.UUID],
    telefones: Mapping[tuple[str, str], str | None],
) -> PedidoDaLista:
    (
        pedido,
        codigo,
        titulo,
        handoff_id,
        handoff_status,
        corretor_id,
        notificado_em,
        aviso_manual_pendente,
        corretor_nome,
    ) = linha
    par = (pedido.channel, pedido.conversation_key)
    email = decrypt(pedido.email_cifrado, aad_do_email_de_interesse(pedido.id))
    telefone = telefones.get(par)
    # `id` e `status` sao `NOT NULL` em `handoffs`: so saem nulos juntos, quando o
    # lateral nao achou handoff. Testar os dois e o que o tipo pede, nao um
    # terceiro caso.
    atendimento = (
        None
        if handoff_id is None or handoff_status is None
        else Atendimento(
            id=handoff_id,
            status=handoff_status,
            corretor_id=corretor_id,
            corretor_nome=corretor_nome,
            notificado_em=notificado_em,
            sem_corretor=bool(aviso_manual_pendente),
        )
    )
    return PedidoDaLista(
        id=pedido.id,
        criado_em=pedido.criado_em,
        imovel_id=pedido.imovel_id,
        imovel_codigo=codigo,
        imovel_titulo=titulo,
        nome=pedido.nome,
        telefone_mascarado=mascarar_telefone(telefone) if telefone is not None else None,
        email_mascarado=mascarar_email(email) if email is not None else None,
        lead_id=apelidos[par],
        channel=pedido.channel,
        conversation_key=pedido.conversation_key,
        atendimento=atendimento,
    )


async def atendimento_do_pedido(
    session: AsyncSession, solicitacao_id: uuid.UUID
) -> tuple[SolicitacaoDeInteresse, Handoff | None] | None:
    """O pedido e o handoff dele (D4), pela mesma consulta da lista. `None` se o
    pedido nao existe.

    O handoff volta como entidade, por um `session.get` a partir do id do
    lateral: quem chama (a revelacao, D5) precisa do `corretor_id` para decidir
    o dono, e a entidade evita uma segunda copia da regra do D4.
    """
    linha = (
        await session.execute(_consulta().where(SolicitacaoDeInteresse.id == solicitacao_id))
    ).first()
    if linha is None:
        return None
    pedido, handoff_id = linha[0], linha[3]
    handoff = await session.get(Handoff, handoff_id) if handoff_id is not None else None
    return pedido, handoff
