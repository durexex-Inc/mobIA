"""Upsert do catalogo por `codigo`, com diff campo a campo.

TEC-156. Devolve os tres numeros que o relatorio precisa distinguir:
inseridos, atualizados e inalterados.

**Por que o diff e em Python e nao um ON CONFLICT esperto.** Da para resolver
tudo numa instrucao:

    INSERT ... ON CONFLICT (codigo) DO UPDATE SET ...
      WHERE imoveis IS DISTINCT FROM EXCLUDED
      RETURNING (xmax = 0) AS inserido

E mais rapido, e perde exatamente a informacao que a proxima card precisa. A
RN-08.3 manda regerar embedding quando campo TEXTUAL muda e nao quando so o
preco muda; `IS DISTINCT FROM` responde apenas SE mudou, nunca O QUE mudou.
A TEC-157 teria que reconstruir este diff do zero. Com lotes de 500 as duas
abordagens sao instantaneas; a diferenca esta em qual deixa o gancho. Ver D4.

**A corrida, dita em voz alta.** Entre o SELECT e o INSERT, outro lote pode
inserir o mesmo codigo. O INSERT leva ON CONFLICT DO UPDATE para nao levantar,
e a linha acaba contada como inserida quando de fato foi atualizada. Fica
assim de proposito: a alternativa seria SELECT ... FOR UPDATE sobre codigos
que ainda nao existem, que nao tranca nada. Duas importacoes simultaneas do
mesmo catalogo sao operacao anomala, a integridade continua garantida pelo
UNIQUE, e so a rotulagem de uma linha rara sai imprecisa.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import RegistroImovel

TAMANHO_DO_LOTE = 500

# Os campos que o arquivo carrega -- e portanto os unicos que a comparacao
# pode olhar. `id`, `created_at` e `updated_at` sao do banco e nunca vem do
# arquivo; incluir qualquer um deles faria toda linha parecer alterada.
CAMPOS_COMPARADOS: tuple[str, ...] = (
    "titulo",
    "descricao",
    "tipo",
    "operacao",
    "preco_venda",
    "preco_aluguel",
    "condominio",
    "iptu_mensal",
    "bairro",
    "cidade",
    "uf",
    "zona",
    "latitude",
    "longitude",
    "area_util_m2",
    "quartos",
    "suites",
    "banheiros",
    "vagas",
    "caracteristicas",
    "fotos",
    "status",
)


def _valores(registro: RegistroImovel) -> dict[str, object]:
    """O registro do arquivo no formato de coluna.

    Enums viram `str` (a coluna e String) e tuplas viram `list` (a coluna e
    ARRAY): sem essa normalizacao a comparacao com o que voltou do banco
    acusaria diferenca em toda linha, e tudo apareceria como atualizado.
    """
    valores: dict[str, object] = {}
    for campo in CAMPOS_COMPARADOS:
        valor = getattr(registro, campo)
        if isinstance(valor, tuple):
            valor = list(valor)
        elif valor is not None and hasattr(valor, "value"):
            valor = str(valor)
        valores[campo] = valor
    return valores


def _mudou(existente: Imovel, valores: dict[str, object]) -> bool:
    return any(getattr(existente, campo) != valores[campo] for campo in CAMPOS_COMPARADOS)


async def sincronizar(
    session: AsyncSession, registros: Sequence[RegistroImovel]
) -> tuple[int, int, int]:
    """Devolve (inseridos, atualizados, inalterados). Nao comita."""
    inseridos = atualizados = inalterados = 0

    for comeco in range(0, len(registros), TAMANHO_DO_LOTE):
        lote = registros[comeco : comeco + TAMANHO_DO_LOTE]
        codigos = [r.codigo for r in lote]

        existentes = {
            imovel.codigo: imovel
            for imovel in (
                await session.scalars(select(Imovel).where(Imovel.codigo.in_(codigos)))
            ).all()
        }

        novos: list[dict[str, object]] = []
        for registro in lote:
            valores = _valores(registro)
            existente = existentes.get(registro.codigo)

            if existente is None:
                novos.append({"id": uuid.uuid4(), "codigo": registro.codigo, **valores})
                inseridos += 1
                continue

            if not _mudou(existente, valores):
                # Nenhuma escrita, nem em `updated_at`. Ver o comentario da
                # coluna em models.py.
                inalterados += 1
                continue

            for campo, valor in valores.items():
                setattr(existente, campo, valor)
            existente.updated_at = datetime.now(UTC)
            atualizados += 1

        if novos:
            # ON CONFLICT DO UPDATE, e nao DO NOTHING: sob a corrida descrita
            # no docstring, DO NOTHING descartaria a linha em silencio e o
            # imovel ficaria com o conteudo do lote concorrente.
            comando = insert(Imovel).values(novos)
            await session.execute(
                comando.on_conflict_do_update(
                    index_elements=["codigo"],
                    set_={campo: comando.excluded[campo] for campo in CAMPOS_COMPARADOS},
                )
            )

        await session.flush()

    return inseridos, atualizados, inalterados
