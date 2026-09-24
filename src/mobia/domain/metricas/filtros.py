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

    if temperatura is not None and temperatura not in {t.value for t in Temperatura}:
        raise FiltroInvalido("temperatura", f"temperatura={temperatura!r} nao e um valor conhecido")

    if intencao is not None and intencao not in {i.value for i in Intencao}:
        raise FiltroInvalido("intencao", f"intencao={intencao!r} nao e um valor conhecido")

    return Recorte(
        inicio=_instante(de, fuso),
        fim=_instante(ate + timedelta(days=1), fuso),
        canal=canal,
        intencao=intencao,
        temperatura=temperatura,
        corretor_id=corretor_id,
    )
