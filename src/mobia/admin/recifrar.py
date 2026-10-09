"""Reescreve todo blob de outra chave com a chave ativa. TEC-203, D1.

E o passo que permite TIRAR uma chave do keyring. Roda com o servico de pe:
cada lote e uma transacao curta, e uma linha recifrada no meio de uma leitura
continua decifravel pelas duas chaves enquanto as duas estiverem no keyring.

**Nao cobre os arquivos de midia** (`.midias/` ou S3, TEC-132). Enquanto houver
midia gravada sob uma chave, ela fica no keyring -- ver o spec da TEC-203.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.context.models import aad_do_resumo
from mobia.domain.handoff.models import aad_do_resumo_de_handoff
from mobia.domain.identidade.models import aad_da_identidade, aad_do_vinculo
from mobia.domain.portal.interesse import aad_do_email_de_interesse
from mobia.domain.usuarios.models import aad_do_totp
from mobia.infra.crypto import aad_de, decrypt_bytes, encrypt_bytes, id_da_chave, id_da_chave_ativa


@dataclass(frozen=True)
class ColunaCifrada:
    tabela: str
    chave_primaria: tuple[str, ...]
    coluna: str
    aad: Callable[..., str]


COLUNAS_CIFRADAS = (
    ColunaCifrada("messages", ("id",), "text_body", lambda i: aad_de(i, "text_body")),
    ColunaCifrada("messages", ("id",), "raw_payload", lambda i: aad_de(i, "raw_payload")),
    ColunaCifrada("messages", ("id",), "envelope_context", lambda i: aad_de(i, "envelope_context")),
    ColunaCifrada(
        "conversation_summaries", ("channel", "conversation_key"), "resumo", aad_do_resumo
    ),
    ColunaCifrada("handoffs", ("id",), "resumo", aad_do_resumo_de_handoff),
    ColunaCifrada("usuarios", ("id",), "totp_segredo", aad_do_totp),
    ColunaCifrada(
        "identidades_de_lead", ("channel", "conversation_key"), "valor_cifrado", aad_da_identidade
    ),
    ColunaCifrada(
        "vinculos_de_sessao", ("channel", "conversation_key"), "telefone_cifrado", aad_do_vinculo
    ),
    ColunaCifrada("solicitacoes_de_interesse", ("id",), "email_cifrado", aad_do_email_de_interesse),
)


def _condicao_de_pagina(
    colunas: tuple[str, ...], ultimo: tuple[Any, ...] | None
) -> tuple[str, dict[str, Any]]:
    """A clausula `WHERE` da proxima pagina, com um bind por coluna da PK.

    Comparacao de tupla por bind so (`WHERE (a, b) > :ultimo`) exige que o
    driver aceite um valor Python tupla como parametro, e o asyncpg nao
    aceita: o ROW() do lado esquerdo continua SQL, so o lado direito precisa
    virar `(:u0, :u1)` -- um bind escalar por coluna.
    """
    if ultimo is None:
        return "", {}
    lado_direito = ", ".join(f":u{n}" for n in range(len(colunas)))
    lado_esquerdo = ", ".join(colunas)
    condicao = f"WHERE ({lado_esquerdo}) > ({lado_direito})"
    parametros = {f"u{n}": valor for n, valor in enumerate(ultimo)}
    return condicao, parametros


async def recifrar(
    session_factory: async_sessionmaker[AsyncSession], *, lote: int = 500, so_contar: bool = False
) -> dict[str, dict[int | None, int]]:
    """Por coluna cifrada, recifra com a chave ativa todo blob de outra chave.

    Devolve, por coluna, quantos blobs ha por id de chave (`None` e a v1
    legada) -- contagem de ANTES da recifra quando `so_contar`, e do que
    SOBROU sob outra chave quando nao (o que passou pela recifra entra na
    contagem da ativa; a linha que mudou entre a leitura e a escrita nao
    entra em balde nenhum, porque a recifra nao a reescreveu). Sem chave
    ativa a recifra reprova de saida: nao ha para onde reescrever -- exceto
    so contando, que so le.
    """
    ativa = id_da_chave_ativa()
    if ativa is None and not so_contar:
        raise RuntimeError("keyring vazio: nao ha chave ativa para onde recifrar")
    relatorio: dict[str, dict[int | None, int]] = {}
    for alvo in COLUNAS_CIFRADAS:
        contagem: Counter[int | None] = Counter()
        pk = ", ".join(alvo.chave_primaria)
        ultimo: tuple[Any, ...] | None = None
        while True:
            async with session_factory() as session:
                condicao, parametros_de_pagina = _condicao_de_pagina(alvo.chave_primaria, ultimo)
                linhas = (
                    await session.execute(
                        text(
                            f"SELECT {pk}, {alvo.coluna} FROM {alvo.tabela} {condicao} "
                            f"ORDER BY {pk} LIMIT :lote"
                        ),
                        {"lote": lote, **parametros_de_pagina},
                    )
                ).all()
                if not linhas:
                    break
                for linha in linhas:
                    *chaves, blob = linha
                    chaves_da_linha = tuple(chaves)
                    ultimo = chaves_da_linha
                    if blob is None:
                        continue
                    atual = id_da_chave(bytes(blob))
                    if so_contar or atual == ativa:
                        contagem[atual] += 1
                        continue
                    aad = alvo.aad(*chaves_da_linha)
                    novo = encrypt_bytes(decrypt_bytes(bytes(blob), aad), aad)
                    onde = " AND ".join(f"{c} = :pk{n}" for n, c in enumerate(alvo.chave_primaria))
                    # Compare-and-swap: so reescreve se a coluna ainda guarda o
                    # blob LIDO. Com o servico de pe, o turno pode ter feito
                    # upsert do resumo (ou alguem trocado o TOTP) entre a
                    # leitura e esta escrita; sem a condicao, o valor novo seria
                    # sobrescrito pelo velho recifrado. Quem gravou no meio
                    # gravou com a chave ativa, e a leitura de verificacao de
                    # `scripts/recifrar.py` conta o que de fato ficou.
                    resultado = await session.execute(
                        text(
                            f"UPDATE {alvo.tabela} SET {alvo.coluna} = :novo "
                            f"WHERE {onde} AND {alvo.coluna} = :lido"
                        ),
                        {
                            "novo": novo,
                            "lido": bytes(blob),
                            **{f"pk{n}": v for n, v in enumerate(chaves_da_linha)},
                        },
                    )
                    if resultado.rowcount:  # type: ignore[attr-defined]
                        contagem[ativa] += 1
                await session.commit()
        relatorio[f"{alvo.tabela}.{alvo.coluna}"] = dict(contagem)
    return relatorio
