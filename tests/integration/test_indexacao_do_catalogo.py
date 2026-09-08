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
from mobia.infra.db import engine_de, get_sessionmaker
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
        # NOT NULL desde a TEC-158 (`0019`). Nenhum chamador sobrescreve
        # `bairro` aqui, entao a dobra fixa acompanha o default acima.
        "bairro_busca": "vila mariana",
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
    # provedor rejeita de forma permanente abortar a passagem inteira -- e a
    # selecao o pega de novo em TODA passagem, porque linha que nunca e
    # gravada nunca sai da ponta mais antiga do `ORDER BY updated_at`. Toda
    # passagem morreria no lote dele entregando so o que por acaso veio antes,
    # com um warning por tick como unico sintoma. O job loga e segue, no molde
    # do `sweep_stalled`.
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
        imoveis = (
            await leitura.scalars(select(Imovel).where(Imovel.id.in_(identificadores)))
        ).all()
    assert len(imoveis) == 3

    # A assercao nao nomeia QUAL linha foi embeddada, e nomear era o defeito da
    # TEC-263. A regra diz que o primeiro lote comita e sobrevive a falha dos
    # seguintes; ela nunca disse qual dos tres imoveis cai nesse lote, e a
    # varredura tambem nao promete: o `ORDER BY updated_at` da selecao e
    # descartado no `select(Imovel).where(id.in_(...))` de `_uma_passagem`, que
    # nao ordena. Afirmar sobre `identificadores[0]` era portanto afirmar sobre
    # a ordem fisica do heap -- que costuma bater com a de insercao para tres
    # linhas novas, e trocava sob carga: 1 failed em 1307 na suite completa,
    # 15/15 em isolamento.
    #
    # Trocar a posicao por carimbos de `updated_at` fixos NAO resolveria, pelo
    # mesmo motivo: o `select` sem `ORDER BY` fica no caminho de qualquer ordem
    # que a selecao tenha escolhido.
    embeddados = [imovel for imovel in imoveis if imovel.embedding is not None]
    assert len(embeddados) == 1

    # O lote que passou gravou as tres colunas de controle, e nao so o vetor.
    unico = embeddados[0]
    assert unico.documento_hash is not None
    assert unico.embedding_atualizado_em is not None

    # E os outros dois continuam pendentes, sem nada parcial gravado.
    for pendente in imoveis:
        if pendente.id == unico.id:
            continue
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


class _EmbedadorEstacionado:
    """Um embedador que PARA dentro de `__call__` ate ser liberado.

    E o que reproduz a geometria real do tick de 30 segundos: enquanto uma
    passagem espera o provedor, ela nao esta usando conexao nenhuma para
    trabalhar -- a do laco de selecao ja foi devolvida ao pool. Um falso que
    responde na hora nunca deixa duas passagens SOBREPOSTAS, e por isso nao
    exercita o lock consultivo.
    """

    def __init__(self, dimensoes: int = 1536) -> None:
        self.dimensoes = dimensoes
        self.entrou = asyncio.Event()
        self.liberar = asyncio.Event()
        self.chamadas: list[list[str]] = []

    async def __call__(self, textos: list[str]) -> list[list[float]]:
        self.chamadas.append(list(textos))
        self.entrou.set()
        await self.liberar.wait()
        return [[0.5] * self.dimensoes for _ in textos]


async def test_a_passagem_sobreposta_nao_pega_o_lock(session: Any) -> None:
    """A segunda passagem devolve 0 SEM chamar o provedor.

    A assercao e sobre a CHAMADA, e nao sobre o desfecho da linha: um lock que
    nao exclui nada tambem deixaria a linha indexada no fim, so que gastando
    duas chamadas -- que e exatamente o desperdicio que a D5 fecha.
    """
    await _imovel(session)
    estacionado = _EmbedadorEstacionado()

    primeira = asyncio.create_task(indexar_catalogo(_ctx(estacionado)))  # type: ignore[arg-type]
    await asyncio.wait_for(estacionado.entrou.wait(), timeout=30)

    segundo = EmbedadorFake()
    assert await indexar_catalogo(_ctx(segundo)) == 0
    assert segundo.chamadas == []

    estacionado.liberar.set()
    assert await primeira == 1


async def test_a_passagem_nao_deixa_lock_pendurado(session: Any) -> None:
    """Depois da passagem, nenhum lock consultivo vivo no banco.

    Lock de sessao vazado dura o que durar a CONEXAO, e a conexao volta para o
    pool -- entao um unlock que nao encontra o lock nao e ruido de log: e a
    varredura desligando a si mesma para sempre, com
    `indexacao_do_catalogo_ja_em_curso` como unico sintoma ate o worker
    reiniciar.
    """
    await _imovel(session)
    fabrica = get_sessionmaker()

    # Mais de uma conexao no pool ANTES da passagem, que e o estado normal de
    # um worker onde `process_message` divide o mesmo pool. Com uma conexao so,
    # o pool devolve sempre a mesma e um lock preso a ela seria solto por
    # acidente -- o vazamento existiria e este teste nao o veria.
    async with fabrica() as uma, fabrica() as outra:
        await uma.execute(text("SELECT 1"))
        await outra.execute(text("SELECT 1"))

    embedador = EmbedadorFake()

    assert await indexar_catalogo(_ctx(embedador)) == 1

    async with fabrica() as leitura:
        vivos = await leitura.scalar(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
        )
    assert vivos == 0


async def test_a_troca_de_modelo_reindexa_a_linha_ja_indexada(session: Any) -> None:
    """Mudar o modelo na configuracao nao toca linha nenhuma -- e mesmo assim
    a linha ja indexada tem de ser reindexada.

    Este e o buraco que o hash sozinho nao fecha: o pre-filtro em SQL nao
    consulta hash (D3), entao uma linha com as tres colunas preenchidas e
    `updated_at <= embedding_atualizado_em` nunca viraria candidata e o hash
    novo nunca chegaria a ser comparado. Sem `embedding_modelo` no pre-filtro,
    o catalogo ficaria com vetores de dois espacos incompativeis, e cosseno
    entre eles e ruido -- sem erro e sem sintoma.
    """
    identificador = await _imovel(session)
    embedador = EmbedadorFake()

    assert await indexar_catalogo(_ctx(embedador)) == 1

    async with get_sessionmaker()() as leitura:
        antes = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert antes is not None
    assert antes.embedding_modelo == Settings().embedding_modelo
    hash_antigo = antes.documento_hash

    ctx = _ctx(embedador)
    ctx["settings"] = Settings(embedding_modelo="text-embedding-3-large")

    assert await indexar_catalogo(ctx) == 1
    assert len(embedador.chamadas) == 2

    async with get_sessionmaker()() as leitura:
        depois = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert depois is not None
    assert depois.embedding_modelo == "text-embedding-3-large"
    assert depois.documento_hash != hash_antigo


async def test_a_linha_sem_modelo_gravado_concilia_em_uma_passagem(session: Any) -> None:
    """A linha indexada antes de a `0018` existir nao fica candidata para sempre.

    `embedding_modelo` NULL e `IS DISTINCT FROM` de qualquer modelo
    configurado, entao ela vira candidata -- e o hash bate, porque o texto e o
    modelo nao mudaram. A varredura nao chama a API, so carimba, e a passagem
    SEGUINTE ja nao a encontra. Sem gravar a coluna no ramo do carimbo, esta
    linha seria candidata em toda passagem, para sempre.
    """
    identificador = await _imovel(session)
    embedador = EmbedadorFake()
    assert await indexar_catalogo(_ctx(embedador)) == 1

    async with get_sessionmaker()() as escrita:
        await escrita.execute(
            text("UPDATE imoveis SET embedding_modelo = NULL WHERE id = :id"),
            {"id": identificador},
        )
        await escrita.commit()

    assert await indexar_catalogo(_ctx(embedador)) == 0
    # Nenhuma chamada nova: o hash bate, so o carimbo muda.
    assert len(embedador.chamadas) == 1

    async with get_sessionmaker()() as leitura:
        depois = await leitura.scalar(select(Imovel).where(Imovel.id == identificador))
    assert depois is not None
    assert depois.embedding_modelo == Settings().embedding_modelo

    assert await indexar_catalogo(_ctx(embedador)) == 0
    assert len(embedador.chamadas) == 1


class _ConexaoQueCancelaNoUnlock:
    """Delega tudo a conexao de verdade, menos o `execute` do unlock.

    So o que `_soltar_o_lock` toca. `CancelledError` porque e exatamente o que
    o `job_timeout` de 240s do worker entrega, e o pior caso desenhado da
    passagem e de 200s -- o cancelamento caindo no meio do unlock e
    alcancavel, nao teorico.
    """

    def __init__(self, real: Any) -> None:
        self._real = real

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        raise asyncio.CancelledError()

    async def rollback(self) -> None:
        await self._real.rollback()

    async def invalidate(self) -> None:
        await self._real.invalidate()


async def test_o_cancelamento_no_unlock_ainda_solta_o_lock() -> None:
    """Cancelado no meio do unlock, o lock morre junto com a conexao.

    Invalidar fecha a conexao FISICA em vez de devolve-la ao pool, e o lock e
    da sessao do Postgres: encerrar a sessao o solta. Devolver a conexao ao
    pool ainda segurando o lock desligaria a varredura para sempre.

    E nada escapa do `finally`: uma excecao daqui substituiria a excecao da
    passagem e esconderia o erro de verdade.
    """
    engine = engine_de(get_sessionmaker())

    async with engine.connect() as conexao:
        assert await conexao.scalar(
            text("SELECT pg_try_advisory_lock(:chave)"), {"chave": modulo._CHAVE_DO_LOCK}
        )
        await conexao.rollback()

        await modulo._soltar_o_lock(_ConexaoQueCancelaNoUnlock(conexao))  # type: ignore[arg-type]

    async with engine.connect() as leitura:
        vivos = await leitura.scalar(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
        )
    assert vivos == 0
