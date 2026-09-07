"""A varredura que mantem o vetor do catalogo atualizado.

TEC-157, RN-08.2 e RN-08.3. Molde da `sweep_stalled`: SQL cru para a
selecao, teto por passagem, `FOR UPDATE SKIP LOCKED`.

**A pendencia e derivada do estado da linha, e nao avisada por quem escreve.**
Esta e a decisao central da card (D2 do desenho), e a alternativa recusada
era usar o gancho que a TEC-156 preservou -- a importacao sabe quais campos
mudaram, logo ela enfileira. Foi recusada por tres motivos, todos ja pagos
por este repo: o caminho de corrida do `ON CONFLICT` nao passa por `_mudou`,
entao uma linha atualizada por ali nunca seria reindexada e nao haveria
sintoma; os imoveis ja importados exigiriam backfill proprio; e
enfileiramento que falha nao retoma -- o bug que a TEC-156 corrigiu no
endpoint e a lacuna que a TEC-261 existe para fechar.

**A regra "falha de embedding nao bloqueia o atendimento" sai da topologia,
nao de um `try/except`.** Este job e um cron separado: nao existe caminho em
que `process_message` chame o provedor de embedding. Isso e mais forte que
capturar excecao -- e e por isso que esta escrito aqui. Um refactor futuro
que chame o embedding de dentro do turno violaria a RN da card sem que teste
nenhum reclamasse.

**Mas o argumento da topologia cobre CORRECAO, nao CAPACIDADE.** Os dois jobs
dividem o mesmo pool do worker ARQ: `process_message` nao chama o provedor de
embedding, e mesmo assim disputa vaga com quem chama. O lock consultivo
abaixo e o que cobre a segunda metade.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy import select, text, update

from mobia.app.config import Settings, get_settings
from mobia.domain.catalogo.documento import documento_de, hash_do_documento
from mobia.domain.catalogo.models import Imovel
from mobia.infra.embeddings import embedar as embedar_de_verdade
from mobia.infra.embeddings import motivo_do_provedor

log = structlog.get_logger(__name__)

# Chave do lock consultivo desta varredura. O espaco de
# `pg_advisory_lock(bigint)` e GLOBAL no banco -- nao ha namespace por tabela
# nem por aplicacao --, entao numero redondo escolhido a dedo (1, 42) e
# exatamente o que colide com o proximo job a fazer o mesmo. Esta veio do nome
# do job, e e reproduzivel:
#
#     python -c "import hashlib; print(int.from_bytes(
#         hashlib.sha256(b'mobia.indexar_catalogo').digest()[:8],
#         'big', signed=True))"
_CHAVE_DO_LOCK = -6845322960407244279

# Lock de SESSAO, e nao de transacao (`pg_try_advisory_xact_lock`): ele precisa
# sobreviver ao rollback que solta os locks de linha e atravessar as sessoes de
# escrita do laco de lotes. Um lock de transacao aqui significaria manter uma
# transacao aberta durante todo o I/O de rede, que e justamente o que o
# rollback antes do laco existe para evitar. O preco de escolher o de sessao e
# ter de solta-lo a mao -- por isso o `finally`.
_TOMAR_O_LOCK = text("SELECT pg_try_advisory_lock(:chave)")
_SOLTAR_O_LOCK = text("SELECT pg_advisory_unlock(:chave)")

# Modulo, e nao `Settings`: o aviso e uma vez por PROCESSO, e o que o torna
# unico e o estado que sobrevive entre passagens do cron.
_AVISOU_DA_CHAVE_AUSENTE = False

# O `embedding_atualizado_em IS NULL` esta explicito de proposito: sem ele,
# `updated_at > NULL` da NULL e imovel recem-inserido nunca seria candidato.
#
# Nenhum nome de campo do documento aparece aqui, e isso e o ponto da D3: a
# definicao do documento mora em `documento.py` e a comparacao exata e feita
# em Python. Um `md5` de colunas concatenadas nesta consulta duplicaria a
# lista de campos, e a divergencia se manifestaria como vetor velho e mudo.
#
# `clock_timestamp()` vai no SELECT, nao e lido do relogio da aplicacao: o
# carimbo gravado em `embedding_atualizado_em` precisa estar no MESMO relogio
# que `updated_at` (gravado em `repositorio.py` via `func.clock_timestamp()`),
# senao a comparacao `updated_at > embedding_atualizado_em` compara relogios
# diferentes e deixa de ser invariante. Lido na mesma instrucao que seleciona
# e trava as linhas, o valor nunca pode ser mais tarde que o instante em que
# o documento foi lido -- nem mesmo se um importador bloqueado no FOR UPDATE
# gravar `updated_at` no instante em que o rollback abaixo solta o lock.
_SELECIONAR_PENDENTES = text(
    """
    SELECT id, clock_timestamp() AS lido_em
      FROM imoveis
     WHERE embedding IS NULL
        OR documento_hash IS NULL
        OR embedding_atualizado_em IS NULL
        OR updated_at > embedding_atualizado_em
     ORDER BY updated_at
     LIMIT :limite
       FOR UPDATE SKIP LOCKED
    """
)


async def indexar_catalogo(ctx: dict[str, Any], limite: int | None = None) -> int:
    """Indexa uma passagem de candidatos. Devolve quantos foram embeddados.

    O retorno conta EMBEDDADOS, nao candidatos: uma linha cujo hash bate e
    candidata, e carimbada, e nao entra na conta -- porque nada foi gerado
    para ela.

    **A varredura exclui a si mesma, e isso e sobre capacidade.** O
    `cron(..., unique=True)` do ARQ cunha um id de job por tick, entao cada
    tick de 30 segundos e um job DISTINTO -- e `WorkerSettings` nao fixa
    `max_jobs`, cujo default no ARQ e 10. Um unico worker portanto roda
    passagens sobrepostas sempre que uma passagem passa de 30s, e o pior caso
    desenhado e de 200s (dois lotes de 100s), quase sete ticks. Sem o lock
    consultivo, ate 8 das 10 vagas do worker ficariam indexando exatamente
    quando o provedor esta lento, e `process_message` disputaria o resto --
    que e a regra da card ("falha de embedding nao bloqueia o atendimento")
    caindo pela capacidade, ja que pela correcao a topologia a segura. A
    sobreposicao sempre foi idempotente (mesmo texto, mesmo vetor); o que ela
    nunca foi e barata.
    """
    global _AVISOU_DA_CHAVE_AUSENTE

    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()
    embedar = ctx.get("embedador") or embedar_de_verdade

    # D10, a metade "aviso unico em desenvolvimento". Sem esta guarda o
    # `get_client()` levanta `ConfiguracaoInsegura` dentro do `except
    # Exception` do laco de lotes: nenhuma linha e indexada nunca, entao o
    # retorno da passagem ociosa jamais dispara e sobra um warning por lote a
    # cada 30 segundos, para sempre. Em producao a guarda equivalente esta no
    # `startup` do worker e RECUSA subir.
    #
    # A pergunta e feita ao embedador, e nao so a `Settings`, porque a chave e
    # exigencia do cliente de verdade: a suite injeta um falso em
    # `ctx["embedador"]` e nao precisa de credencial nenhuma para exercitar a
    # varredura inteira.
    if embedar is embedar_de_verdade and not settings.openai_api_key:
        if not _AVISOU_DA_CHAVE_AUSENTE:
            _AVISOU_DA_CHAVE_AUSENTE = True
            log.warning(
                "indexacao_do_catalogo_sem_chave",
                detalhe=(
                    "OPENAI_API_KEY nao configurada: o catalogo fica sem vetor e a "
                    "busca semantica devolve vazio. Este aviso sai UMA vez por "
                    "processo -- nao havera um segundo."
                ),
            )
        return 0

    async with session_factory() as guarda:
        concedido = await guarda.scalar(_TOMAR_O_LOCK, {"chave": _CHAVE_DO_LOCK})
        # Solta a transacao implicita e mantem o lock: ele e de sessao. Sem
        # isto a conexao ficaria `idle in transaction` por toda a passagem.
        await guarda.rollback()

        if not concedido:
            # Outra passagem ainda esta em curso. Sair agora e o ponto: a
            # linha que ela ainda nao pegou continua candidata e o proximo
            # tick a encontra.
            log.info("indexacao_do_catalogo_ja_em_curso")
            return 0

        try:
            return await _uma_passagem(session_factory, settings, embedar, limite)
        finally:
            # No `finally` porque um lock de sessao vazado dura o que durar a
            # conexao -- e a conexao volta para o pool, entao a varredura
            # ficaria travada para sempre em vez de ate o fim da passagem.
            await guarda.execute(_SOLTAR_O_LOCK, {"chave": _CHAVE_DO_LOCK})
            await guarda.rollback()


async def _uma_passagem(
    session_factory: Any,
    settings: Settings,
    embedar: Any,
    limite: int | None,
) -> int:
    """Uma passagem, ja com o lock consultivo nas maos de quem chama."""
    teto = limite if limite is not None else settings.indexacao_limite_por_passagem
    lote_maximo = settings.indexacao_tamanho_do_lote

    async with session_factory() as session:
        resultado = await session.execute(_SELECIONAR_PENDENTES, {"limite": teto})
        linhas = list(resultado)
        identificadores = [linha.id for linha in linhas]

        if not identificadores:
            # A passagem ociosa e barata de proposito: nesta cadencia, a
            # consulta que nao devolve nada e o caso comum.
            await session.rollback()
            return 0

        # Um unico valor para toda a passagem -- ver o comentario acima da
        # consulta sobre por que vem do relogio do banco.
        lido_em = linhas[0].lido_em

        # Carregados pelo ORM, e nao por `SELECT *` cru: `embedding` e uma
        # coluna `Vector`, e reconstruir `Imovel(**linha)` de um mapping
        # entregaria texto onde o tipo espera lista.
        imoveis = list(
            (await session.scalars(select(Imovel).where(Imovel.id.in_(identificadores)))).all()
        )

        pendentes: list[tuple[uuid.UUID, str, str]] = []
        carimbar_apenas: list[uuid.UUID] = []

        # Os atributos sao lidos AQUI, antes do rollback: depois dele os
        # objetos ficam expirados e tocar um campo dispararia I/O de novo.
        for imovel in imoveis:
            texto_do_documento = documento_de(imovel)
            digest = hash_do_documento(
                texto_do_documento, settings.embedding_modelo, settings.embedding_dimensoes
            )

            if imovel.embedding is not None and imovel.documento_hash == digest:
                # O hash bate: o vetor ainda vale. Este e o ramo que cumpre
                # "alteracao de preco nao regera embedding" -- o preco bumpou
                # `updated_at`, a linha virou candidata, e nada e chamado. O
                # carimbo e o que impede a linha de ficar candidata para
                # sempre.
                carimbar_apenas.append(imovel.id)
            else:
                pendentes.append((imovel.id, texto_do_documento, digest))

        candidatos = len(imoveis)

        # Os locks da selecao sao soltos antes de qualquer I/O de rede, pelo
        # mesmo motivo que a `sweep_stalled` documenta: segurar lock de linha
        # no Postgres enquanto se fala com um provedor externo e ruim por si
        # so. A exclusao entre varreduras concorrentes nao depende de manter
        # o lock -- ver o `SKIP LOCKED` acima.
        await session.rollback()

    embeddados = 0

    for inicio in range(0, len(pendentes), lote_maximo):
        lote = pendentes[inicio : inicio + lote_maximo]

        try:
            vetores = await embedar([texto for _, texto, _ in lote])
        except Exception as erro:
            # Loga e CONTINUA para o proximo lote -- nao propaga. A consulta
            # ordena por `updated_at`, entao um documento com problema nao
            # retentavel (texto grande demais, conteudo recusado --
            # MAX_TENTATIVAS = 1 dispensa retry do proprio provedor) tende a
            # cair sempre no primeiro lote de cada passagem; um `raise` aqui
            # abortaria a passagem inteira e junto todo lote seguinte,
            # inclusive imoveis alterados mais recentemente que ordenam
            # depois -- o catalogo pararia de indexar por inteiro por causa
            # de uma linha, com um unico warning por cron como sintoma. O
            # molde da `sweep_stalled` faz o mesmo: loga e segue. A linha
            # deste lote continua pendente e a proxima passagem a pega -- e
            # essa retomada entre passagens, nao um retry dentro desta, e o
            # "a reindexacao fica pendente e e retomada" da card. Um contador
            # de falhas por linha (no molde de `sweep_max_attempts`) e
            # follow-up, nao esta card. O motivo vem de `motivo_do_provedor`,
            # que so devolve texto para erro de protocolo do provedor; para
            # qualquer outra excecao devolve None, porque `str(exc)`
            # arbitrario pode carregar o que nao deve ir para log -- por isso
            # o tipo da excecao tambem vai pro log, para nao perder o sinal
            # quando o motivo sai None.
            log.warning(
                "indexacao_do_catalogo_falhou",
                lote=len(lote),
                embeddados_antes=embeddados,
                motivo=motivo_do_provedor(erro),
                tipo=type(erro).__name__,
            )
            continue

        async with session_factory() as escrita:
            for (identificador, _, digest), vetor in zip(lote, vetores, strict=True):
                await escrita.execute(
                    update(Imovel)
                    .where(Imovel.id == identificador)
                    .values(
                        embedding=vetor,
                        documento_hash=digest,
                        embedding_atualizado_em=lido_em,
                    )
                )
            # Commit por lote: uma falha no lote seguinte preserva este.
            await escrita.commit()
        embeddados += len(lote)

    if carimbar_apenas:
        async with session_factory() as escrita:
            await escrita.execute(
                update(Imovel)
                .where(Imovel.id.in_(carimbar_apenas))
                .values(embedding_atualizado_em=lido_em)
            )
            await escrita.commit()

    log.info(
        "indexacao_do_catalogo",
        candidatos=candidatos,
        embeddados=embeddados,
        carimbados=len(carimbar_apenas),
    )
    return embeddados
