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
e o que sai torto e isto, com todas as letras:

- a linha e **contada como inserida quando de fato foi atualizada**. Erro de
  rotulagem no relatorio, e nada alem disso;
- o `DO UPDATE` dispara **sem consultar o diff** -- este caminho nao passa por
  `_mudou`. Se o conteudo do lote concorrente for identico ao deste, a linha
  leva um UPDATE e um `updated_at` novo mesmo sem ter mudado, o que e o
  oposto do que a regra do inalterado promete no caminho normal.

Fica assim de proposito: a alternativa seria SELECT ... FOR UPDATE sobre
codigos que ainda nao existem, que nao tranca nada. Duas importacoes
simultaneas do mesmo catalogo sao operacao anomala e a integridade continua
garantida pelo UNIQUE -- mas o custo NAO e so "a rotulagem de uma linha rara",
e dizer isso aqui era descrever um perigo menor que o do codigo.

**`updated_at` entra no SET do ON CONFLICT.** Sem ele o conteudo da linha
perdedora era sobrescrito e o carimbo ficava com o valor antigo: uma linha
cujos dados mudaram e cujo `updated_at` jura que nao. Nesta coluna, mentir
para menos e pior que bumpar a mais.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import RegistroImovel
from mobia.domain.texto import dobrar

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


# `bairro_busca` fica FORA de CAMPOS_COMPARADOS de proposito, e por dois
# motivos: ela nao vem do arquivo (`RegistroImovel` nao tem o campo, e
# `getattr` levantaria), e e derivada de `bairro`, que o diff ja compara --
# incluir as duas nao detecta nada a mais.
#
# Mas ela TEM de ser gravada nos dois caminhos de escrita. Sem isso, a linha
# vencedora da corrida documentada no header deste modulo fica com o
# `bairro` de um lote e a dobra do outro: um imovel que a busca por bairro
# nao encontra, sem erro nenhum e sem sintoma no relatorio.
def _derivados(valores: dict[str, object]) -> dict[str, object]:
    """Os campos que o banco guarda e o arquivo nao carrega. TEC-158, D5."""
    return {"bairro_busca": dobrar(str(valores["bairro"]))}


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
                novos.append(
                    {
                        "id": uuid.uuid4(),
                        "codigo": registro.codigo,
                        **valores,
                        **_derivados(valores),
                    }
                )
                inseridos += 1
                continue

            if not _mudou(existente, valores):
                # Nenhuma escrita, nem em `updated_at`. Ver o comentario da
                # coluna em models.py.
                inalterados += 1
                continue

            for campo, valor in {**valores, **_derivados(valores)}.items():
                setattr(existente, campo, valor)
            # Relogio do servidor, e nao `datetime.now(UTC)`: todo carimbo
            # deste schema nasce de `clock_timestamp()` (os server_default de
            # `created_at`/`updated_at`), e o caminho do ON CONFLICT abaixo usa
            # o mesmo. Misturar o relogio do processo com o do banco na MESMA
            # coluna faria a ordem entre duas linhas depender de qual caminho
            # gravou cada uma.
            existente.updated_at = func.clock_timestamp()
            atualizados += 1

        if novos:
            # ON CONFLICT DO UPDATE, e nao DO NOTHING: sob a corrida descrita
            # no docstring, DO NOTHING descartaria a linha em silencio e o
            # imovel ficaria com o conteudo do lote concorrente.
            comando = insert(Imovel).values(novos)
            await session.execute(
                comando.on_conflict_do_update(
                    index_elements=["codigo"],
                    set_={
                        **{campo: comando.excluded[campo] for campo in CAMPOS_COMPARADOS},
                        # Derivada, entao nao esta em CAMPOS_COMPARADOS -- mas
                        # sem ela a linha perdedora da corrida teria o bairro
                        # sobrescrito e a dobra mantida.
                        "bairro_busca": comando.excluded["bairro_busca"],
                        # `updated_at` NAO esta em CAMPOS_COMPARADOS (o diff
                        # nao pode olhar para ele, senao toda linha pareceria
                        # alterada), mas tem de estar aqui: sem isso a linha
                        # perdedora da corrida tinha o conteudo sobrescrito e o
                        # carimbo mantido, e passava a jurar que nao mudou.
                        "updated_at": func.clock_timestamp(),
                    },
                )
            )

        await session.flush()

    return inseridos, atualizados, inalterados


async def imoveis_por_ids(session: AsyncSession, ids: Sequence[uuid.UUID]) -> tuple[Imovel, ...]:
    """Os imoveis pedidos, NA ORDEM PEDIDA. Nao comita.

    A ordem e o contrato, e nao um detalhe: quem chama e a apresentacao da
    TEC-162, e a ordem que ela pede e a de score da busca. Devolver na ordem
    do banco faria a ficha_1 ser um candidato qualquer, e o lead leria a pior
    opcao primeiro sem que nada falhasse.

    Id sem linha sai da lista em vez de virar `None`: imovel inativado entre
    a busca e a apresentacao e caminho normal (D6 do desenho), e um `None` no
    meio da tupla obrigaria todo chamador a filtrar.
    """
    if not ids:
        return ()

    encontrados = {
        imovel.id: imovel
        for imovel in (await session.scalars(select(Imovel).where(Imovel.id.in_(ids)))).all()
    }
    return tuple(encontrados[chave] for chave in ids if chave in encontrados)
