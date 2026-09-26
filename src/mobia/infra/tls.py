"""TLS das conexoes que saem do processo para infraestrutura nossa. TEC-203, D6.

So producao. Fora dela o compose local nao tem TLS, e exigi-lo quebraria a
maquina de todo mundo por uma protecao que so faz sentido em rede alheia.

**O piso 1.3 vale para o Postgres e nao para o Redis.** O `RedisSettings` do
ARQ 0.28 nao expoe versao minima de TLS; ali se exige `rediss://` e
verificacao de certificado, e a divergencia esta registrada no spec. APIs de
terceiros ficam com o piso padrao do `ssl`, que negocia 1.3 quando o servidor
oferece -- forcar 1.3 num servidor que nao controlamos derrubaria a
integracao no dia em que ele oferecer so 1.2.
"""

import ssl

from mobia.app.config import ConfiguracaoInsegura, Settings


def contexto_tls() -> ssl.SSLContext:
    contexto = ssl.create_default_context()
    contexto.minimum_version = ssl.TLSVersion.TLSv1_3
    return contexto


def argumentos_de_conexao_do_banco(settings: Settings) -> dict[str, object]:
    """`connect_args` do engine: o contexto TLS em producao, nada fora dela."""
    if not settings.em_producao:
        return {}
    return {"ssl": contexto_tls()}


def exigir_redis_com_tls(dsn: str) -> None:
    if not dsn.startswith("rediss://"):
        raise ConfiguracaoInsegura(
            "REDIS_URL sem TLS em producao. Use rediss://; o Redis gerenciado do "
            "provedor oferece TLS, e sem ele fila e rate limit trafegam em claro."
        )
