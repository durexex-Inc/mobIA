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
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, text, update

from mobia.app.config import Settings, get_settings
from mobia.domain.catalogo.documento import documento_de, hash_do_documento
from mobia.domain.catalogo.models import Imovel
from mobia.infra.embeddings import embedar as embedar_de_verdade
from mobia.infra.embeddings import motivo_do_provedor

log = structlog.get_logger(__name__)

# O `embedding_atualizado_em IS NULL` esta explicito de proposito: sem ele,
# `updated_at > NULL` da NULL e imovel recem-inserido nunca seria candidato.
#
# Nenhum nome de campo do documento aparece aqui, e isso e o ponto da D3: a
# definicao do documento mora em `documento.py` e a comparacao exata e feita
# em Python. Um `md5` de colunas concatenadas nesta consulta duplicaria a
# lista de campos, e a divergencia se manifestaria como vetor velho e mudo.
_SELECIONAR_PENDENTES = text(
    """
    SELECT id
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
    """
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()
    embedar = ctx.get("embedador") or embedar_de_verdade

    teto = limite if limite is not None else settings.indexacao_limite_por_passagem
    lote_maximo = settings.indexacao_tamanho_do_lote

    async with session_factory() as session:
        resultado = await session.execute(_SELECIONAR_PENDENTES, {"limite": teto})
        identificadores = [linha.id for linha in resultado]

        if not identificadores:
            # A passagem ociosa e barata de proposito: nesta cadencia, a
            # consulta que nao devolve nada e o caso comum.
            await session.rollback()
            return 0

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
            digest = hash_do_documento(texto_do_documento)

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
        # o lock -- ver o `SKIP LOCKED` acima e o teste de concorrencia.
        await session.rollback()

    embeddados = 0
    agora = datetime.now(UTC)

    for inicio in range(0, len(pendentes), lote_maximo):
        lote = pendentes[inicio : inicio + lote_maximo]

        try:
            vetores = await embedar([texto for _, texto, _ in lote])
        except Exception as erro:
            # Loga o porque e RELEVANTA. Nao engolir e deliberado: a linha
            # continua pendente e a proxima passagem a pega, entao a falha
            # nao precisa de tratamento -- precisa de registro. O motivo vem
            # de `motivo_do_provedor`, que so devolve texto para erro de
            # protocolo do provedor; para qualquer outra excecao devolve None,
            # porque `str(exc)` arbitrario pode carregar o que nao deve ir
            # para log.
            log.warning(
                "indexacao_do_catalogo_falhou",
                lote=len(lote),
                embeddados_antes=embeddados,
                motivo=motivo_do_provedor(erro),
            )
            raise

        async with session_factory() as escrita:
            for (identificador, _, digest), vetor in zip(lote, vetores, strict=True):
                await escrita.execute(
                    update(Imovel)
                    .where(Imovel.id == identificador)
                    .values(
                        embedding=vetor,
                        documento_hash=digest,
                        embedding_atualizado_em=agora,
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
                .values(embedding_atualizado_em=agora)
            )
            await escrita.commit()

    log.info(
        "indexacao_do_catalogo",
        candidatos=candidatos,
        embeddados=embeddados,
        carimbados=len(carimbar_apenas),
    )
    return embeddados
