"""O recorte do painel. TEC-190, RN-17.3. Sem I/O."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.temperatura import Temperatura


class FiltroInvalido(ValueError):
    """Um filtro veio com valor que o vocabulario nao tem.

    Carrega o NOME do campo para a rota poder dize-lo no 422. Um 422 generico
    manda quem usa procurar o erro em cinco filtros.
    """

    def __init__(self, campo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.campo = campo


@dataclass(frozen=True)
class Recorte:
    """O periodo em instantes UTC, mais os quatro filtros opcionais.

    `inicio` inclusivo, `fim` EXCLUSIVO.
    """

    inicio: datetime
    fim: datetime
    canal: str | None
    intencao: str | None
    temperatura: str | None
    corretor_id: uuid.UUID | None


def _instante(dia: date, fuso: ZoneInfo) -> datetime:
    return datetime.combine(dia, time.min, tzinfo=fuso).astimezone(UTC)


def _mais_um_ano(dia: date) -> date:
    """O mesmo dia, um ano depois -- 29/02 sem ano bissexto seguinte vira 28/02."""
    try:
        return dia.replace(year=dia.year + 1)
    except ValueError:
        return dia.replace(year=dia.year + 1, day=28)


def montar_recorte(
    *,
    de: date,
    ate: date,
    fuso: ZoneInfo,
    canal: str | None = None,
    intencao: str | None = None,
    temperatura: str | None = None,
    corretor_id: uuid.UUID | None = None,
) -> Recorte:
    """Traduz os filtros da borda em recorte, ou levanta `FiltroInvalido`.

    **A fronteira do dia e a do FUSO, nao a de UTC.** As colunas sao
    `timestamptz`, e Sao Paulo e UTC-3: interpretar `2026-08-01` como
    `00:00Z` poria as tres primeiras horas do dia 1 local no dia 31. O fuso
    vem por parametro e sai de `settings.fuso_de_envio`, que o `config.py`
    declara ser o fuso UNICO da POC, reaproveitado -- e nao um campo novo.

    **O intervalo e semiaberto**: `fim` e a meia-noite do dia SEGUINTE a
    `ate`. Assim o dia final entra inteiro sem a aproximacao de `23:59:59` --
    que perde o ultimo segundo -- nem a de `23:59:59.999999`, que e a mesma
    coisa com mais digitos.

    `canal` NAO e validado: `messages.channel` e `String(32)` sem CHECK,
    entao nao ha vocabulario fechado contra o que recusar.
    """
    if de > ate:
        raise FiltroInvalido("de", f"de={de.isoformat()} e depois de ate={ate.isoformat()}")

    # TEC-316, RN-FE-05.3: 12 meses, e nao um numero fixo de dias -- o mesmo
    # dia um ano depois, para o limite nao mudar de tamanho conforme o ano
    # tem ou nao 29 de fevereiro no meio.
    limite = _mais_um_ano(de)
    if ate > limite:
        raise FiltroInvalido(
            "ate",
            f"periodo maior que 12 meses: de={de.isoformat()} ate={ate.isoformat()}, "
            f"o limite e {limite.isoformat()}",
        )

    if temperatura is not None and temperatura not in {t.value for t in Temperatura}:
        raise FiltroInvalido("temperatura", f"temperatura={temperatura!r} nao e um valor conhecido")

    if intencao is not None and intencao not in {i.value for i in Intencao}:
        raise FiltroInvalido("intencao", f"intencao={intencao!r} nao e um valor conhecido")

    # **`handoffs.corretor_id` NUNCA e escrito em producao.** A Emenda E-01
    # da RN-16.2 diz isso por extenso: a coluna tem FK desde a TEC-196 e
    # nunca e escrita. A TEC-166 nao mudou isso -- ela aloca corretor ao
    # agendamento, nao ao handoff. A coluna e nula em toda linha, entao o
    # filtro devolvia 200 com o funil inteiro zerado -- e a gerente leria
    # "este corretor nao recebeu lead nenhum" sobre QUALQUER corretor,
    # inclusive o que aceitou dezenas de handoffs no mes.
    #
    # Recusar e melhor que o zero universal pela mesma razao da D1: zero com
    # cara de medicao e pior que ausencia declarada. A consulta que consome
    # `Recorte.corretor_id` continua escrita e testada, esperando quem escreva
    # `handoffs.corretor_id` -- o que se recusa aqui e o PEDIDO, nao a forma
    # do recorte.
    if corretor_id is not None:
        raise FiltroInvalido(
            "corretorId",
            "o filtro por corretor ainda nao funciona: o funil ainda nao sabe qual "
            "corretor atende cada handoff, entao a coluna e nula em toda linha e o funil "
            "sairia zerado para qualquer corretor",
        )

    return Recorte(
        inicio=_instante(de, fuso),
        fim=_instante(ate + timedelta(days=1), fuso),
        canal=canal,
        intencao=intencao,
        temperatura=temperatura,
        corretor_id=corretor_id,
    )
