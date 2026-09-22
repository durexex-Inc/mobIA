"""O limite de requisicoes por IP (TEC-205, RNF-16).

Primeiro middleware do projeto. Ate a TEC-205 `create_app` so fazia
`include_router`, e ate o `correlation_id` era setado dentro do handler.
"""

# `chave` em `rate_limit_events` e String(64). O header e entrada externa: sem
# teto, um `X-Forwarded-For` longo viraria erro de INSERT na hora de registrar
# justamente o abuso que a coluna existe para guardar.
_TAMANHO_MAXIMO_DA_CHAVE = 64


def resolver_ip(
    *,
    socket_host: str | None,
    forwarded_for: str | None,
    confiar_em_forwarded_for: bool,
) -> str | None:
    """O endereco que o limitador conta.

    Sem confiar (o default), e o socket: nao forjavel, correto no deploy de
    hoje, que nao tem proxy. Confiando, e o ULTIMO salto de `X-Forwarded-For`
    -- o ultimo, e nao o primeiro, porque e o unico que o proxy imediato
    escreveu e portanto o unico que o cliente nao controla. Confiar no
    primeiro deixaria qualquer cliente escapar do limite com um header
    forjado, que e exatamente o abuso que esta card existe para conter.

    Devolve None quando nao ha endereco nenhum. Quem chama deixa passar: e o
    mesmo fail-open do limitador.
    """
    if confiar_em_forwarded_for and forwarded_for:
        saltos = [salto.strip() for salto in forwarded_for.split(",")]
        ultimo = next((salto for salto in reversed(saltos) if salto), None)
        if ultimo:
            return ultimo[:_TAMANHO_MAXIMO_DA_CHAVE]
    if socket_host:
        return socket_host[:_TAMANHO_MAXIMO_DA_CHAVE]
    return None
