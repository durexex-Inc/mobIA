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


def contexto_tls(verificar: bool = True) -> ssl.SSLContext:
    """O contexto TLS de saida para infraestrutura nossa.

    `verificar=True` (o padrao) exige um certificado que encadeia numa CA
    publica e cujo host bate, e piso TLS 1.3 -- a postura de um banco cujo
    certificado sabemos validar.

    `verificar=False` cifra sem verificar cadeia nem host, e baixa o piso para
    TLS 1.2. E o que um provedor gerenciado com certificado auto-assinado
    (Heroku Postgres, entre outros) exige: sem isso a conexao falha na subida
    com `CERTIFICATE_VERIFY_FAILED`, embora o trafego ja fosse cifrado. A
    escolha e de CONFIGURACAO (`DB_SSL_VERIFICAR`), nao um default silencioso:
    quem desliga a verificacao declara que confia na rede do provedor.
    """
    contexto = ssl.create_default_context()
    if verificar:
        contexto.minimum_version = ssl.TLSVersion.TLSv1_3
        return contexto
    contexto.check_hostname = False
    contexto.verify_mode = ssl.CERT_NONE
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    return contexto


def argumentos_de_conexao_do_banco(settings: Settings) -> dict[str, object]:
    """`connect_args` do engine: o contexto TLS em producao, nada fora dela.

    Com `infra_interna_confiavel`, o Postgres esta na rede interna do mesmo
    host (Docker Compose) e o trafego nao sai da maquina: nao ha rede alheia a
    proteger, entao a conexao vai sem TLS -- a mesma postura do ambiente local.
    """
    if not settings.em_producao or settings.infra_interna_confiavel:
        return {}
    return {"ssl": contexto_tls(settings.db_ssl_verificar)}


def exigir_redis_com_tls(dsn: str) -> None:
    if not dsn.startswith("rediss://"):
        raise ConfiguracaoInsegura(
            "REDIS_URL sem TLS em producao. Use rediss://; o Redis gerenciado do "
            "provedor oferece TLS, e sem ele fila e rate limit trafegam em claro."
        )
