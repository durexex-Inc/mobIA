"""A varredura da indexacao vetorial.

Basename distinto de tudo em `tests/unit/`.
"""

import asyncio
import uuid
from typing import Any

import pytest
from conftest import EmbedadorFake
from sqlalchemy import select, text

from mobia.app.config import Settings
from mobia.domain.catalogo.models import Imovel
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs import indexar_catalogo as modulo
from mobia.workers.jobs.indexar_catalogo import indexar_catalogo


async def _imovel(session: Any, codigo: str = "AP-001", **sobrescritas: object) -> uuid.UUID:
    identificador = uuid.uuid4()
    campos: dict[str, object] = {
        "id": identificador,
        "codigo": codigo,
        "titulo": "Apartamento na Vila Mariana",
        "descricao": "Sala ampla com varanda.",
        "tipo": "APARTAMENTO",
        "operacao": "VENDA",
        "preco_venda": 74900000,
        "bairro": "Vila Mariana",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "area_util_m2": 78,
        "quartos": 3,
        "suites": 1,
        "banheiros": 2,
        "vagas": 2,
        "caracteristicas": ["varanda"],
        "fotos": [],
        "status": "DISPONIVEL",
    }
    campos.update(sobrescritas)
    session.add(Imovel(**campos))
    await session.commit()
    return identificador


def _ctx(embedador: EmbedadorFake) -> dict[str, Any]:
    return {"session_factory": get_sessionmaker(), "embedador": embedador}


async def test_imovel_novo_e_indexado(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()

    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 1
    assert len(embedador.chamadas) == 1

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None
    assert imovel.documento_hash is not None
    assert imovel.embedding_atualizado_em is not None


async def test_a_segunda_passagem_nao_reindexa_nada(session: Any) -> None:
    await _imovel(session)
    embedador = EmbedadorFake()

    await indexar_catalogo(_ctx(embedador))
    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 0
    # Uma chamada na primeira passagem, nenhuma na segunda.
    assert len(embedador.chamadas) == 1


async def test_o_teto_por_passagem_limita(session: Any) -> None:
    for numero in range(5):
        await _imovel(session, codigo=f"AP-{numero:03d}")
    embedador = EmbedadorFake()

    indexados = await indexar_catalogo(_ctx(embedador), limite=3)

    assert indexados == 3


async def test_mudanca_de_preco_nao_faz_chamada_nenhuma(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()
    await indexar_catalogo(_ctx(embedador))
    assert len(embedador.chamadas) == 1

    async with get_sessionmaker()() as escrita:
        await escrita.execute(
            text(
                "UPDATE imoveis SET preco_venda = 69900000, updated_at = clock_timestamp() "
                " WHERE id = :id"
            ),
            {"id": identificador},
        )
        await escrita.commit()

    indexados = await indexar_catalogo(_ctx(embedador))

    # A assercao e sobre CHAMADAS, e nao sobre o vetor: um vetor igual nao
    # provaria nada, porque uma implementacao errada tambem o devolveria.
    assert indexados == 0
    assert len(embedador.chamadas) == 1


async def test_mudanca_de_descricao_gera_vetor_e_hash_novos(session: Any) -> None:
    identificador = await _imovel(session)
    embedador = EmbedadorFake()
    await indexar_catalogo(_ctx(embedador))

    async with get_sessionmaker()() as leitura:
        antes = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert antes is not None
    hash_antigo = antes.documento_hash

    async with get_sessionmaker()() as escrita:
        await escrita.execute(
            text(
                "UPDATE imoveis SET descricao = 'Reformado em 2026.', "
                "       updated_at = clock_timestamp() "
                " WHERE id = :id"
            ),
            {"id": identificador},
        )
        await escrita.commit()

    indexados = await indexar_catalogo(_ctx(embedador))

    assert indexados == 1
    assert len(embedador.chamadas) == 2

    async with get_sessionmaker()() as leitura:
        depois = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert depois is not None
    assert depois.documento_hash != hash_antigo


async def test_imovel_vendido_tambem_e_indexado(session: Any) -> None:
    # D9: a RN-08.4 tira o nao disponivel dos RESULTADOS da busca, mas o
    # corte por status e da busca, nao da indexacao. Filtrar aqui criaria o
    # caso em que reativar um imovel o deixa sem vetor.
    identificador = await _imovel(session, status="VENDIDO")
    embedador = EmbedadorFake()

    assert await indexar_catalogo(_ctx(embedador)) == 1

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None


async def test_falha_do_provedor_deixa_a_linha_pendente(session: Any) -> None:
    identificador = await _imovel(session)

    # NAO levanta, e isso e deliberado. Relevantar faria um documento que o
    # provedor rejeita de forma permanente abortar a passagem inteira -- e com
    # `ORDER BY updated_at` ele cai no lote 1 de TODA passagem, entao nada mais
    # no catalogo seria indexado nunca, com um warning por tick como unico
    # sintoma. O job loga e segue, no molde do `sweep_stalled`.
    assert await indexar_catalogo(_ctx(EmbedadorFake(falhar=True))) == 0

    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    # A linha so e gravada em caso de sucesso: falha deixa o candidato como
    # estava, e a retomada nao depende do retry do ARQ -- o cron roda de novo.
    assert imovel.embedding is None
    assert imovel.documento_hash is None

    embedador = EmbedadorFake()
    assert await indexar_catalogo(_ctx(embedador)) == 1


async def test_a_falha_num_lote_preserva_o_commit_do_lote_anterior(session: Any) -> None:
    identificadores = [await _imovel(session, codigo=f"AP-{numero:03d}") for numero in range(3)]
    embedador = EmbedadorFake(falhar_a_partir_da_chamada=2)

    ctx = _ctx(embedador)
    # `indexacao_tamanho_do_lote = 1` e o que exercita a SEGUNDA iteracao do
    # laco de lotes. Com o default de 50, tres pendentes cabem num lote so e o
    # "comita por lote" nunca chega a ser exercido -- e ele e toda a
    # justificativa de teto (100) e lote (50) serem dois numeros diferentes.
    ctx["settings"] = Settings(indexacao_tamanho_do_lote=1)

    indexados = await indexar_catalogo(ctx)

    assert indexados == 1
    # Tres tentativas, e nao duas: a passagem nao aborta no primeiro erro, ela
    # loga e segue para o lote seguinte.
    assert len(embedador.chamadas) == 3

    async with get_sessionmaker()() as leitura:
        por_id = {
            imovel.id: imovel
            for imovel in (
                await leitura.scalars(select(Imovel).where(Imovel.id.in_(identificadores)))
            ).all()
        }

    # O primeiro lote comitou e sobreviveu a falha dos seguintes.
    primeiro = por_id[identificadores[0]]
    assert primeiro.embedding is not None
    assert primeiro.documento_hash is not None
    assert primeiro.embedding_atualizado_em is not None

    # E os outros dois continuam pendentes, sem nada parcial gravado.
    for identificador in identificadores[1:]:
        pendente = por_id[identificador]
        assert pendente.embedding is None
        assert pendente.documento_hash is None
        assert pendente.embedding_atualizado_em is None


class _LogEspiao:
    def __init__(self) -> None:
        self.avisos: list[str] = []

    def warning(self, evento: str, **_: object) -> None:
        self.avisos.append(evento)

    def info(self, evento: str, **_: object) -> None:
        pass


async def test_sem_chave_a_varredura_avisa_uma_vez_e_nao_indexa(
    session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D10, a metade "aviso unico em desenvolvimento".

    Sem esta guarda a chave ausente vira um warning por LOTE a cada passagem,
    para sempre: nenhuma linha e indexada, entao o retorno da passagem ociosa
    nunca dispara. Na cadencia de 30 segundos isso e ruido continuo no log --
    e o segundo aviso ja e um a mais do que a D10 permite.
    """
    await _imovel(session)
    espiao = _LogEspiao()
    monkeypatch.setattr(modulo, "log", espiao)
    monkeypatch.setattr(modulo, "_AVISOU_DA_CHAVE_AUSENTE", False)

    # Sem `ctx["embedador"]`: a guarda pergunta ao embedador DE VERDADE, que e
    # quem exige a chave. Nenhuma chamada de rede acontece -- o ponto do teste
    # e que a passagem sai antes de qualquer coisa.
    ctx: dict[str, Any] = {
        "session_factory": get_sessionmaker(),
        "settings": Settings(openai_api_key=None),
    }

    assert await indexar_catalogo(ctx) == 0
    assert await indexar_catalogo(ctx) == 0
    assert await indexar_catalogo(ctx) == 0

    assert espiao.avisos == ["indexacao_do_catalogo_sem_chave"]

    async with get_sessionmaker()() as leitura:
        pendente = await leitura.scalar(select(Imovel))
    assert pendente is not None
    assert pendente.embedding is None


async def test_varreduras_concorrentes_deixam_a_linha_indexada_uma_vez(
    session: Any,
) -> None:
    identificador = await _imovel(session)
    primeiro = EmbedadorFake()
    segundo = EmbedadorFake()

    await asyncio.gather(
        indexar_catalogo(_ctx(primeiro)),
        indexar_catalogo(_ctx(segundo)),
    )

    # A assercao e sobre o DESFECHO, e nao sobre QUAL das duas indexou.
    #
    # `pg_try_advisory_lock` faz a varredura excluir a si mesma: a segunda a
    # chegar nao pega o lock e devolve 0 na hora, sem tocar o banco. Antes
    # disso as duas podiam gastar uma chamada em duplicidade -- desperdicio
    # idempotente, nao incorrecao, mas desperdicio pago justamente quando o
    # provedor esta lento.
    #
    # Nao se afirma AQUI qual das duas venceu, nem em qual `EmbedadorFake` a
    # chamada caiu: isso depende de qual corrotina o laco de eventos despacha
    # primeiro, e afirmar sobre ela seria flake sob carga.
    async with get_sessionmaker()() as leitura:
        imovel = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert imovel is not None
    assert imovel.embedding is not None
    assert imovel.documento_hash is not None
    assert imovel.embedding_atualizado_em is not None

    # E a linha nao fica candidata depois: a proxima passagem nao chama nada.
    terceiro = EmbedadorFake()
    assert await indexar_catalogo(_ctx(terceiro)) == 0
    assert terceiro.chamadas == []
