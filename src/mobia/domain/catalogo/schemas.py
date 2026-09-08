"""As formas puras de duas familias: a importacao e a busca hibrida.

Sem I/O, sem banco, sem FastAPI. Da importacao: o registro, a rejeicao e o
relatorio -- o parser produz `RegistroImovel | Rejeicao` e o orquestrador
acumula os dois num `Relatorio`. Da busca (TEC-158): o filtro que o lead
pediu, o candidato que volta e o resultado que embrulha os dois.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal

from mobia.domain.catalogo.enums import (
    Operacao,
    StatusImovel,
    StatusImportacao,
    TipoImovel,
    Zona,
)


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
    """Os cinco totais, o desfecho e a lista de rejeicoes.

    `inalterados` e a emenda E-01 da RN-08.5. Sem ele o cenario 3 do Gherkin
    devolve 500/0/10/0 e 490 linhas ficam sem categoria -- silencio sobre 98%
    do lote, num artefato cujo proposito e "saber exatamente o que falhou".
    Ver D3.

    `status` e o mesmo campo que a linha `importacoes` guarda, e nao um
    booleano proprio: quem chama `executar` recebe este objeto, quem consulta
    o `GET` le a linha, e os dois precisam responder a mesma pergunta com a
    mesma palavra. Sem ele o objeto devolvido num FALHOU era indistinguivel de
    uma importacao limpa sobre arquivo vazio -- zero em tudo, `erros` vazia --
    e a CLI saia com 0 sobre um catalogo que nao entrou.

    Comeca em PROCESSANDO pelo mesmo motivo que a coluna: o desfecho e o que
    `executar` decide no fim, e um default de CONCLUIDO faria um relatorio
    abandonado no meio se declarar bem-sucedido.
    """

    status: StatusImportacao = StatusImportacao.PROCESSANDO
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

    def registrar_falha(self, falha: Rejeicao) -> None:
        """Marca a importacao inteira como FALHOU e poe o motivo na frente.

        Na frente e nao no fim porque a falha do arquivo explica por que os
        totais pararam onde pararam; lida depois de 300 rejeicoes de linha ela
        chega tarde demais.

        NAO incrementa `rejeitados` nem `processados`: um FALHOU nunca e "uma
        linha" (D11), e conta-lo ali quebraria a identidade de `fecha()`.
        """
        self.status = StatusImportacao.FALHOU
        self.erros.insert(0, falha)


# `Embedador` e a porta, e nao o cliente: a busca recebe a funcao e nunca
# importa `infra.embeddings`. E o que permite a suite exercitar o caminho
# inteiro sem credencial e sem rede. Ver D9.
Embedador = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass(frozen=True, slots=True)
class FiltroDeBusca:
    """O que o lead pediu, em dimensoes que o SQL resolve. TEC-158, RN-09.1.

    `operacao` e OBRIGATORIA e nao tem default, e e ela que escolhe a coluna
    de preco: o imovel tem `preco_venda` e `preco_aluguel`, o CHECK da tabela
    so garante que um dos dois existe, e a faixa do lead e um par de centavos
    que nao diz de qual universo e. Um default aqui faria "ate R$ 600.000"
    casar todo aluguel do catalogo, e a Marina receberia apartamento de
    R$ 3.500 por mes como se fosse a compra que ela pediu. Ver D2.

    **`status` NAO esta aqui, de proposito.** A RN-08.4 exclui da busca o que
    nao esta DISPONIVEL, e aceita-lo como filtro daria ao chamador um jeito de
    pedir imovel vendido pela mesma porta que o agente usa. Ele e literal no
    WHERE. Ver D3.

    **Nao ha filtro de cidade**, e a RN-09.1 nao o lista: "centro" casa o
    Centro de todas as cidades do catalogo. Enquanto o catalogo e de uma
    cidade so, e inocuo -- ver a lacuna 8 do desenho.

    `regioes` e tupla e nao list porque o dataclass e frozen. Vazia significa
    "sem filtro de regiao", nunca "nenhuma regiao casa".
    """

    operacao: Operacao
    preco_min_centavos: int | None = None
    preco_max_centavos: int | None = None
    tipo: TipoImovel | None = None
    quartos_min: int | None = None
    vagas_min: int | None = None
    regioes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Candidato:
    """Um imovel devolvido ao agente, com o id e o preco vindos do banco.

    RN-09.4, e o quarto cenario do Gherkin. O preco e o da OPERACAO buscada --
    a mesma coluna que o filtro comparou --, e por isso o campo se chama
    `preco_centavos` e nao `preco_venda`: numa busca de aluguel, devolver o
    preco de venda seria devolver o campo errado. O exemplo da secao 6.3 do
    SRS mostra `precoVenda` porque o exemplo dele e de venda.

    `tem_vetor` existe para que a degradacao da D8 seja legivel: sem ele,
    "a ordenacao esta estranha" e "o provedor esta fora" sao indistinguiveis
    para quem investiga.
    """

    imovel_id: uuid.UUID
    codigo: str
    titulo: str
    bairro: str
    preco_centavos: int
    quartos: int
    vagas: int
    area_util_m2: int
    score: float
    tem_vetor: bool


@dataclass(frozen=True, slots=True)
class ResultadoDaBusca:
    """Os candidatos e o que o chamador precisa saber sobre como eles sairam.

    `total_candidatos` e a contagem ANTES do teto de 10 -- e o
    `totalCandidatos` da secao 6.3, e e ele que diz ao agente que havia 40
    opcoes e ele esta vendo 10.
    """

    candidatos: tuple[Candidato, ...]
    total_candidatos: int
    consulta_vetorizada: bool

    @property
    def candidatos_sem_vetor(self) -> int:
        return sum(1 for candidato in self.candidatos if not candidato.tem_vetor)
