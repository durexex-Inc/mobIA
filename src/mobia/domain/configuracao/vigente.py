"""O que o administrador pode ajustar no agente, e o padrao. TEC-198.

Modulo sem I/O, no molde de `leads/consulta.py`: e o que deixa os limites e o
padrao serem testados em `tests/unit/` sem Postgres de pe. Quem le e grava a
tabela e `repositorio.py`, ao lado.

**O padrao e o comportamento de antes desta card, valor por valor.** Sem
linha nenhuma em `configuracoes_do_agente`, o sistema se comporta exatamente
como se comportava com as constantes -- e e por isso que as constantes antigas
(`TETO_DE_PERGUNTAS`, `CADENCIA`, os pontos de `score.py`) continuam existindo:
elas SAO o padrao, e `PADRAO` abaixo e montado a partir delas, nao copiado.

**A cadencia e chaveada pelo NOME da temperatura, e nao pelo enum.**
`context/temperatura.py` importa `context/score.py`, que importa este modulo
para os pesos; importar `Temperatura` daqui fecharia o ciclo. Os tres nomes
sao os valores do enum, e `followup/cadencia.py` faz a ponte.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Tom(StrEnum):
    """Vocabulario fechado (D6 do desenho, decisao do Eduardo, 26/09/2026).

    Cada valor vira uma frase fixa, escrita por nos, dentro do prompt de
    sistema -- e nao instrucao livre, cujo custo em tokens dependeria do que o
    administrador escrevesse. `CORDIAL` e a frase que o prompt ja tinha.
    """

    CORDIAL = "CORDIAL"
    FORMAL = "FORMAL"
    DESCONTRAIDO = "DESCONTRAIDO"


@dataclass(frozen=True)
class Pesos:
    """O TETO de cada fator do score (D3). Os pontos internos escalam.

    Os padroes sao os tetos de hoje -- completude 5 x 4 campos, urgencia
    IMEDIATA, catalogo com tres ou mais compativeis, engajamento com seis
    mensagens, capacidade a vista --, e com eles o score e identico ao de antes
    desta card. A penalidade de nao comparecimento (TEC-172) nao e peso de
    fator e fica fora.
    """

    completude: int = 20
    urgencia: int = 25
    catalogo: int = 20
    engajamento: int = 15
    capacidade: int = 15

    @property
    def soma(self) -> int:
        return self.completude + self.urgencia + self.catalogo + self.engajamento + self.capacidade


# O TETO DE REFERENCIA de cada fator: o peso contra o qual os pontos de
# `score.py` foram escritos. E o denominador da escala, e nao muda com a
# configuracao -- se mudasse, a escala seria relativa a ultima edicao, e duas
# edicoes seguidas nao comporiam.
PESOS_DE_REFERENCIA = Pesos()


def _cadencia_padrao() -> dict[str, tuple[timedelta, ...]]:
    # Import tardio: `followup.cadencia` importa `context.temperatura`, que
    # importa `context.score`, que importa este modulo. Chamado so na montagem
    # do `PADRAO`, depois de todos os modulos existirem.
    from mobia.domain.followup.cadencia import CADENCIA

    return {temperatura.value: intervalos for temperatura, intervalos in CADENCIA.items()}


@dataclass(frozen=True)
class ConfiguracaoDoAgente:
    """Um retrato inteiro. O turno le um e usa o mesmo ate o fim (D1)."""

    nome_do_assistente: str | None
    tom: Tom
    teto_de_perguntas: int
    pesos: Pesos
    cadencia: Mapping[str, tuple[timedelta, ...]] = field(default_factory=dict)
    # TEC-191, D3. Mensal, em dolares; o painel de custo o faz proporcional ao
    # periodo consultado. Nulo no padrao: nao ha orcamento que valha inventar.
    orcamento_mensal_usd: Decimal | None = None


def padrao() -> ConfiguracaoDoAgente:
    from mobia.domain.context.qualificacao import TETO_DE_PERGUNTAS

    return ConfiguracaoDoAgente(
        nome_do_assistente=None,
        tom=Tom.CORDIAL,
        teto_de_perguntas=TETO_DE_PERGUNTAS,
        pesos=Pesos(),
        cadencia=_cadencia_padrao(),
    )


class ConfiguracaoInvalida(ValueError):
    """Valor fora da faixa. Vira 422, e nenhuma versao e gravada (D2)."""


# Os limites de D2, cada um com o porque ao lado. Sao eles que a rota devolve
# a tela junto com a vigente, para a tela nao precisar de uma segunda copia.
TETO_DO_NOME = 30
TETO_MINIMO_DE_PERGUNTAS = 1  # a card recusa zero
TETO_MAXIMO_DE_PERGUNTAS = 20  # acima disso o SDR vira interrogatorio
PESO_MAXIMO = 50  # a card recusa negativo; 50 impede um fator so de decidir
SOMA_MAXIMA_DOS_PESOS = 100  # os cortes 70/40 de temperatura supoem 0..~100
INTERVALO_MINIMO_DA_CADENCIA = timedelta(hours=1)
INTERVALO_MAXIMO_DA_CADENCIA = timedelta(days=90)
# TEC-191, D3. O piso e o centavo; o teto e so contra o digito a mais -- um
# orcamento de um milhao por mes numa POC e erro de digitacao, e com ele o
# alerta nunca acenderia.
ORCAMENTO_MINIMO = Decimal("0.01")
ORCAMENTO_MAXIMO = Decimal("100000")


def validar(config: ConfiguracaoDoAgente) -> ConfiguracaoDoAgente:
    """Levanta `ConfiguracaoInvalida` com TODAS as regras violadas juntas.

    Juntas, e nao a primeira: e o argumento da D7 da TEC-156 para o relatorio
    de importacao -- quem corrige tres campos numa rodada so nao quer
    descobrir o segundo erro depois de corrigir o primeiro.
    """
    erros: list[str] = []

    nome = config.nome_do_assistente
    if nome is not None:
        if not nome.strip():
            erros.append("nome do assistente vazio: use null para nao ter nome")
        if len(nome) > TETO_DO_NOME:
            erros.append(
                f"nome do assistente tem {len(nome)} caracteres; o maximo e {TETO_DO_NOME}"
            )
        if "\n" in nome or "\r" in nome:
            # O nome vai para dentro do prompt de sistema (D6), e uma quebra de
            # linha ali e o comeco de uma instrucao nova.
            erros.append("nome do assistente nao pode ter quebra de linha")

    if not TETO_MINIMO_DE_PERGUNTAS <= config.teto_de_perguntas <= TETO_MAXIMO_DE_PERGUNTAS:
        erros.append(
            f"limite de perguntas {config.teto_de_perguntas} fora da faixa "
            f"{TETO_MINIMO_DE_PERGUNTAS}..{TETO_MAXIMO_DE_PERGUNTAS}"
        )

    for fator in ("completude", "urgencia", "catalogo", "engajamento", "capacidade"):
        peso = getattr(config.pesos, fator)
        if not 0 <= peso <= PESO_MAXIMO:
            erros.append(f"peso de {fator} {peso} fora da faixa 0..{PESO_MAXIMO}")
    if not 1 <= config.pesos.soma <= SOMA_MAXIMA_DOS_PESOS:
        erros.append(
            f"a soma dos pesos e {config.pesos.soma}; tem de ficar entre 1 e "
            f"{SOMA_MAXIMA_DOS_PESOS}, a escala que os cortes de temperatura supoem"
        )

    referencia = _cadencia_padrao()
    for temperatura, intervalos_padrao in referencia.items():
        intervalos = config.cadencia.get(temperatura)
        if intervalos is None or len(intervalos) != len(intervalos_padrao):
            # D5: a QUANTIDADE e fixa -- ela esta no CASE SQL do corte de
            # candidatura, gerado na importacao do modulo.
            erros.append(
                f"cadencia {temperatura} precisa de exatamente {len(intervalos_padrao)} intervalos"
            )
            continue
        if any(
            not INTERVALO_MINIMO_DA_CADENCIA <= i <= INTERVALO_MAXIMO_DA_CADENCIA
            for i in intervalos
        ):
            erros.append(f"cadencia {temperatura}: cada intervalo entre 1 hora e 90 dias")
        if any(b <= a for a, b in zip(intervalos, intervalos[1:], strict=False)):
            # A invariante que `tentativa_devida` escreve: a descida pela
            # tabela so acha a MAIOR vencida se os intervalos crescem.
            erros.append(f"cadencia {temperatura}: os intervalos tem de ser crescentes")
    if set(config.cadencia) - set(referencia):
        erros.append("cadencia com temperatura desconhecida")

    orcamento = config.orcamento_mensal_usd
    if orcamento is not None and not ORCAMENTO_MINIMO <= orcamento <= ORCAMENTO_MAXIMO:
        erros.append(
            f"orcamento mensal {orcamento} fora da faixa {ORCAMENTO_MINIMO}..{ORCAMENTO_MAXIMO}; "
            "use null para nao ter orcamento"
        )

    if erros:
        raise ConfiguracaoInvalida("; ".join(erros))
    return config


def aplicar(atual: ConfiguracaoDoAgente, mudancas: Mapping[str, object]) -> ConfiguracaoDoAgente:
    """A vigente com as mudancas por cima. Nao valida -- quem chama valida.

    `mudancas` vem com os nomes de campo desta dataclass e, para os pesos, com
    `peso_<fator>`: o formato plano e o da tabela e o da API, e so aqui ele
    vira a forma aninhada.
    """
    novos_pesos: dict[str, Any] = {
        nome.removeprefix("peso_"): valor
        for nome, valor in mudancas.items()
        if nome.startswith("peso_")
    }
    pesos = replace(atual.pesos, **novos_pesos)
    resto = {n: v for n, v in mudancas.items() if not n.startswith("peso_")}
    return replace(atual, pesos=pesos, **resto)  # type: ignore[arg-type]
