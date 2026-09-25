"""O JWT de acesso. TEC-201, RNF-11.

Sessenta minutos, HS256, e a validacao com o algoritmo FIXADO -- ver
`validar`, que e onde mora a unica decisao de seguranca deste modulo.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from mobia.app.config import Settings

# **O algoritmo e uma lista de um item, e ele e passado na VALIDACAO.**
#
# Esta e a linha que impede a familia de ataques de confusao de algoritmo: sem
# `algorithms=`, uma biblioteca permissiva aceitaria um token que se declara
# `alg: none` (sem assinatura nenhuma) ou assinado com um algoritmo assimetrico
# usando a chave publica como se fosse segredo. O `pyjwt` ja exige o parametro,
# e este comentario existe para que ninguem o transforme numa lista maior
# "para ser flexivel".
#
# Ha teste explicito para `alg: none` -- ele nao esta ali por desconfianca da
# biblioteca, e sim porque esta e a propriedade que o sistema inteiro assume.
ALGORITMO = "HS256"

_ALGORITMOS_ACEITOS = [ALGORITMO]


@dataclass(frozen=True)
class Identidade:
    """Quem o token diz ser. E so o que as rotas precisam saber."""

    usuario_id: uuid.UUID
    papel: str
    # Se esta sessao passou pelo segundo fator. Nenhuma rota exige isto hoje --
    # a checagem vale no login (D5) --, mas a claim fica porque a TEC-202 vai
    # querer exigir MFA para acoes especificas, e acrescenta-la depois obrigaria
    # todo mundo a relogar.
    mfa: bool


class TokenInvalido(Exception):
    """Assinatura errada, formato errado, expirado ou com claim faltando.

    **Um tipo so para todos esses casos, de proposito.** Distinguir "expirado"
    de "assinatura invalida" na resposta diria a quem sonda qual das duas
    coisas ele acertou. Quem precisa da diferenca e o log, nao o cliente.
    """


def emitir(usuario_id: uuid.UUID, papel: str, *, mfa: bool, settings: Settings) -> str:
    """O JWT de acesso, valido por `jwt_minutos`."""
    agora = datetime.now(UTC)
    corpo = {
        "sub": str(usuario_id),
        "papel": papel,
        "mfa": mfa,
        "iat": agora,
        "exp": agora + timedelta(minutes=settings.jwt_minutos),
    }
    return jwt.encode(corpo, settings.jwt_segredo, algorithm=ALGORITMO)


def validar(token: str, settings: Settings) -> Identidade:
    """A identidade que o token carrega. Levanta `TokenInvalido` para o resto.

    A expiracao e conferida pelo proprio `pyjwt` a partir do `exp` -- nao ha
    comparacao de relogio escrita aqui, e nao deve haver: e o tipo de conta que
    erra por fuso, por `utcnow` ingenuo, ou por esquecer a margem.
    """
    try:
        corpo = jwt.decode(token, settings.jwt_segredo, algorithms=_ALGORITMOS_ACEITOS)
    except jwt.PyJWTError as falha:
        # `type(falha).__name__` e nao `str(falha)`: a mensagem da biblioteca
        # vai para o log, e distinguir os casos para o CLIENTE e o que o
        # docstring de `TokenInvalido` recusa.
        raise TokenInvalido(type(falha).__name__) from falha

    try:
        return Identidade(
            usuario_id=uuid.UUID(corpo["sub"]),
            papel=corpo["papel"],
            mfa=bool(corpo["mfa"]),
        )
    except (KeyError, ValueError) as falha:
        # Assinatura valida e corpo com forma errada significa que alguem com o
        # segredo emitiu algo que este codigo nao entende. Recusar e o certo --
        # aceitar com defaults inventaria um papel.
        raise TokenInvalido(type(falha).__name__) from falha


def emitir_desafio(usuario_id: uuid.UUID, papel: str, *, minutos: int, settings: Settings) -> str:
    """O token de meio caminho do ADMIN com MFA pendente. TEC-201, D5.

    **E um JWT como os outros, e nao um formato novo.** O que o distingue e o
    `mfa: False` com vida curta: ele prova que a senha estava certa e nao prova
    o segundo fator. `POST /auth/mfa` exige exatamente essa combinacao, e e por
    isso que um token de ACESSO completo (com `mfa: True`) nao serve para
    trocar por outro par -- se servisse, uma sessao valida se renovaria para
    sempre sem senha.

    Mora aqui, e nao na rota, porque emitir JWT e decisao deste modulo: o
    algoritmo e o segredo tem UM lugar.
    """
    agora = datetime.now(UTC)
    corpo = {
        "sub": str(usuario_id),
        "papel": papel,
        "mfa": False,
        "iat": agora,
        "exp": agora + timedelta(minutes=minutos),
    }
    return jwt.encode(corpo, settings.jwt_segredo, algorithm=ALGORITMO)
