"""As tres formas puras da importacao: o registro, a rejeicao e o relatorio.

Sem I/O, sem banco, sem FastAPI. O parser produz `RegistroImovel | Rejeicao`
e o orquestrador acumula os dois num `Relatorio`.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel, Zona


@dataclass(frozen=True, slots=True)
class Rejeicao:
    """Uma linha recusada, com TODOS os motivos dela juntos.

    Um motivo por linha, e nao um por problema: linha com tres campos ruins
    devolve uma Rejeicao com os tres motivos separados por "; ". Um relatorio
    que revela um erro por vez faz o admin corrigir e reimportar tres vezes
    para uma linha so, e o valor desta card e a rodada unica. Ver D7.
    """

    linha: int
    motivo: str


@dataclass(frozen=True, slots=True)
class RegistroImovel:
    """Uma linha valida, ja convertida aos tipos do banco.

    `linha` viaja junto ate o fim: quando o upsert falhar, o relatorio ainda
    precisa dizer QUAL linha do arquivo era.

    Precos ja em centavos -- a conversao de reais acontece no parser, na
    borda, com Decimal. Ver D6.
    """

    linha: int
    codigo: str
    titulo: str
    descricao: str
    tipo: TipoImovel
    operacao: Operacao
    preco_venda: int | None
    preco_aluguel: int | None
    condominio: int | None
    iptu_mensal: int | None
    bairro: str
    cidade: str
    uf: str
    zona: Zona | None
    latitude: Decimal | None
    longitude: Decimal | None
    area_util_m2: int
    quartos: int
    suites: int
    banheiros: int
    vagas: int
    caracteristicas: tuple[str, ...]
    fotos: tuple[str, ...]
    status: StatusImovel


@dataclass
class Relatorio:
    """Os cinco totais e a lista de rejeicoes.

    `inalterados` e a emenda E-01 da RN-08.5. Sem ele o cenario 3 do Gherkin
    devolve 500/0/10/0 e 490 linhas ficam sem categoria -- silencio sobre 98%
    do lote, num artefato cujo proposito e "saber exatamente o que falhou".
    Ver D3.
    """

    processados: int = 0
    inseridos: int = 0
    atualizados: int = 0
    inalterados: int = 0
    rejeitados: int = 0
    erros: list[Rejeicao] = field(default_factory=list)

    def fecha(self) -> bool:
        """A identidade que o quinto total existe para tornar verdadeira."""
        return self.processados == (
            self.inseridos + self.atualizados + self.inalterados + self.rejeitados
        )

    def registrar_rejeicao(self, rejeicao: Rejeicao) -> None:
        self.rejeitados += 1
        self.processados += 1
        self.erros.append(rejeicao)
