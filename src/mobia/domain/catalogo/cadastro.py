"""O imovel cadastrado e editado um a um, pela tela de administracao. TEC-197.

RN-19.1 e a secao 6.3. **Nenhuma regra de imovel nasce aqui**: a validacao e
a de `parser.validar_um`, a mesma das linhas do arquivo, e a escrita e a de
`repositorio.sincronizar`, o mesmo upsert por codigo da importacao (D2 do
desenho). Este modulo so traduz o JSON da API para o formato de linha e de
volta, e decide o que e proprio de editar UM imovel: o `PATCH` parcial, o
codigo imutavel e o aviso de reindexacao.

Funcoes livres com `session` posicional e o resto keyword-only, sem commit --
a convencao dos repositorios deste repo.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from mobia.domain.catalogo.documento import documento_de
from mobia.domain.catalogo.enums import StatusImovel
from mobia.domain.catalogo.models import Imovel, Importacao
from mobia.domain.catalogo.parser import validar_um
from mobia.domain.catalogo.repositorio import sincronizar
from mobia.domain.catalogo.schemas import Rejeicao
from mobia.domain.texto import dobrar

# O nome da API -> a coluna. A ordem e a da tela: identificacao, preco,
# localizacao, tamanho, extras. `codigo` fica de fora do `PATCH` (D2), mas
# entra aqui porque o `POST` e a resposta o carregam.
CAMPOS: dict[str, str] = {
    "codigo": "codigo",
    "titulo": "titulo",
    "descricao": "descricao",
    "tipo": "tipo",
    "operacao": "operacao",
    "status": "status",
    "precoVenda": "preco_venda",
    "precoAluguel": "preco_aluguel",
    "condominio": "condominio",
    "iptuMensal": "iptu_mensal",
    "bairro": "bairro",
    "cidade": "cidade",
    "uf": "uf",
    "zona": "zona",
    "latitude": "latitude",
    "longitude": "longitude",
    "areaUtilM2": "area_util_m2",
    "quartos": "quartos",
    "suites": "suites",
    "banheiros": "banheiros",
    "vagas": "vagas",
    "caracteristicas": "caracteristicas",
    "fotos": "fotos",
}

# Os quatro que a API manda em CENTAVOS e a linha do arquivo traz em REAIS --
# e que o parser converte de volta, com Decimal. A ida e a volta sao exatas.
_EM_CENTAVOS = frozenset({"preco_venda", "preco_aluguel", "condominio", "iptu_mensal"})
_LISTAS = frozenset({"caracteristicas", "fotos"})
_SEPARADOR = "|"

DUPLICADO = "duplicado"
INVALIDO = "invalido"
NAO_EXISTE = "nao_existe"
CODIGO_IMUTAVEL = "codigo_imutavel"


class CadastroRecusado(Exception):
    """`motivo` e um dos quatro acima, e vira o status HTTP; `detalhe` e texto."""

    def __init__(self, motivo: str, detalhe: str) -> None:
        super().__init__(detalhe)
        self.motivo = motivo
        self.detalhe = detalhe


def _bruto(colunas: dict[str, object]) -> dict[str, str]:
    """Os valores de coluna no formato de uma linha do arquivo.

    **Item de lista com `|` e recusado aqui**, e nao partido: no arquivo o
    `|` e o separador, e "piscina|churrasqueira" digitado na tela como UMA
    caracteristica viraria duas sem ninguem ter pedido.
    """
    bruto: dict[str, str] = {}
    for coluna, valor in colunas.items():
        if valor is None:
            bruto[coluna] = ""
        elif coluna in _LISTAS:
            itens = [str(item) for item in valor]  # type: ignore[attr-defined]
            if any(_SEPARADOR in item for item in itens):
                raise CadastroRecusado(INVALIDO, f"{coluna} nao pode conter '{_SEPARADOR}'")
            bruto[coluna] = _SEPARADOR.join(itens)
        elif coluna in _EM_CENTAVOS:
            bruto[coluna] = str(Decimal(int(valor)) / 100)  # type: ignore[call-overload]
        else:
            bruto[coluna] = str(valor)
    return bruto


def _colunas_de(imovel: Imovel) -> dict[str, object]:
    return {coluna: getattr(imovel, coluna) for coluna in CAMPOS.values()}


def como_api(imovel: Imovel) -> dict[str, object]:
    """O imovel no formato da API: camelCase, precos em centavos."""
    corpo: dict[str, object] = {"id": str(imovel.id)}
    for nome, coluna in CAMPOS.items():
        valor = getattr(imovel, coluna)
        corpo[nome] = float(valor) if isinstance(valor, Decimal) else valor
    corpo["atualizadoEm"] = imovel.updated_at.isoformat()
    return corpo


async def _gravar(session: AsyncSession, colunas: dict[str, object]) -> Imovel:
    registro = validar_um(_bruto(colunas))
    if isinstance(registro, Rejeicao):
        raise CadastroRecusado(INVALIDO, registro.motivo)
    await sincronizar(session, [registro])
    return (
        await session.execute(
            select(Imovel)
            .where(Imovel.codigo == registro.codigo)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def criar(session: AsyncSession, *, campos: dict[str, object]) -> Imovel:
    """Um imovel novo. Codigo que ja existe e `DUPLICADO` (409 na secao 6.3).

    **A checagem e antes, e nao a UNIQUE**, porque `sincronizar` resolve o
    conflito com `ON CONFLICT DO UPDATE` -- e o que a importacao quer, e o que
    o `POST` nao pode fazer: criar por cima de um existente seria editar sem
    ter pedido. Dois administradores criando o mesmo codigo no mesmo instante
    ainda passam os dois por aqui, e o segundo sobrescreve o primeiro; e a
    mesma corrida que o docstring de `repositorio.py` aceita para a
    importacao, pela mesma razao.
    """
    colunas = {CAMPOS[nome]: valor for nome, valor in campos.items()}
    codigo = str(colunas.get("codigo") or "").strip()
    if codigo:
        existe = await session.scalar(select(Imovel.id).where(Imovel.codigo == codigo))
        if existe is not None:
            raise CadastroRecusado(DUPLICADO, f"codigo {codigo!r} ja cadastrado")
    return await _gravar(session, colunas)


@dataclass(frozen=True)
class Edicao:
    imovel: Imovel
    reindexa: bool


async def editar(
    session: AsyncSession, *, imovel_id: uuid.UUID, campos: dict[str, object]
) -> Edicao:
    """Sobrepoe os campos enviados ao imovel e valida o resultado INTEIRO. D2.

    Validar so o que veio deixaria passar `operacao=ALUGUEL` sobre um imovel
    sem `precoAluguel`, que a importacao recusaria.

    **`reindexa` compara o documento antes e depois**, pela mesma
    `documento_de` que a varredura usa (D3). Nao dispara nada: quem reindexa e
    `indexar_catalogo`, a partir do `updated_at` que `sincronizar` carimbou.
    """
    imovel = await session.get(Imovel, imovel_id)
    if imovel is None:
        raise CadastroRecusado(NAO_EXISTE, "imovel nao existe")
    if "codigo" in campos and campos["codigo"] != imovel.codigo:
        raise CadastroRecusado(
            CODIGO_IMUTAVEL,
            "o codigo e a chave da importacao, e troca-lo criaria um segundo imovel no "
            "proximo arquivo",
        )

    documento_antes = documento_de(imovel)
    colunas = {**_colunas_de(imovel), **{CAMPOS[nome]: valor for nome, valor in campos.items()}}
    editado = await _gravar(session, colunas)
    return Edicao(imovel=editado, reindexa=documento_de(editado) != documento_antes)


async def excluir(session: AsyncSession, *, imovel_id: uuid.UUID) -> None:
    """`status=INATIVO`, e nunca DELETE (secao 6.3). D4.

    Pelo mesmo caminho da edicao, e nao por um UPDATE proprio: o carimbo de
    `updated_at` e de `sincronizar`, e um segundo escritor daquela coluna
    poderia quebrar a invariante de que a varredura depende. Excluir o que ja
    esta inativo nao e erro -- o estado pedido e o estado que ha.
    """
    await editar(session, imovel_id=imovel_id, campos={"status": StatusImovel.INATIVO.value})


LIMITE_PADRAO = 50
LIMITE_MAXIMO = 200


async def listar(
    session: AsyncSession,
    *,
    status: str | None,
    tipo: str | None,
    busca: str | None,
    bairro: str | None,
    limite: int,
    depois_de: str | None,
) -> tuple[list[Imovel], str | None]:
    """A pagina por `codigo`, e o codigo do ultimo quando ha mais. D5.

    O cursor e o proprio codigo, em claro: nao e dado pessoal, e o codigo nao
    muda (D2), entao a ordem e estavel entre paginas.
    """
    consulta = select(Imovel)
    if status is not None:
        consulta = consulta.where(Imovel.status == status)
    if tipo is not None:
        consulta = consulta.where(Imovel.tipo == tipo)
    if busca:
        consulta = consulta.where(
            or_(Imovel.codigo.ilike(f"%{busca}%"), Imovel.titulo.ilike(f"%{busca}%"))
        )
    if bairro:
        # A coluna dobrada, como a busca do agente: sem ela "Joao Paulo" nao
        # acharia "João Paulo".
        consulta = consulta.where(Imovel.bairro_busca.like(f"%{dobrar(bairro)}%"))
    if depois_de is not None:
        consulta = consulta.where(Imovel.codigo > depois_de)

    linhas = list(
        (await session.execute(consulta.order_by(Imovel.codigo).limit(limite + 1))).scalars()
    )
    if len(linhas) > limite:
        return linhas[:limite], linhas[limite - 1].codigo
    return linhas, None


async def importacoes_recentes(session: AsyncSession, *, limite: int) -> list[Importacao]:
    """As ultimas importacoes, da mais nova para a mais velha. D6.

    Sem a coluna `arquivo`: ela guarda os bytes do upload inteiro (ate 10 MB),
    e a lista so precisa dos totais e das rejeicoes.
    """
    return list(
        (
            await session.execute(
                select(Importacao)
                .options(defer(Importacao.arquivo))
                .order_by(Importacao.criada_em.desc(), Importacao.id.desc())
                .limit(limite)
            )
        ).scalars()
    )
