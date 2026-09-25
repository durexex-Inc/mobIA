"""O JWT de acesso. TEC-201 e TEC-202, RNF-11 e RNF-12.

Sessenta minutos, HS256, e a validacao com o algoritmo FIXADO -- ver
`validar`, que e onde mora a unica decisao de seguranca deste modulo.

O corpo carrega papel, MFA e vinculo de corretor. **As tres claims sao
obrigatorias em `validar`**, inclusive no desafio de MFA: uma forma so de
corpo e o que impede um token com claim faltando de virar identidade com
default inventado.
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
    # a checagem vale no login (D5 da TEC-201).
    #
    # **A TEC-202 chegou e NAO passou a exigir MFA por acao**, ao contrario do
    # que este comentario previa: a matriz dela autoriza por papel, e nenhuma
    # permissao pede segundo fator alem do que o login ja exigiu do ADMIN. A
    # claim fica pela outra metade do argumento original, que continua de pe --
    # acrescenta-la depois obrigaria todo mundo a relogar.
    mfa: bool
    # Qual corretor e este usuario, quando for um. TEC-202, D4.
    #
    # **Vem do token e nao de uma consulta por requisicao**, o que herda a
    # lacuna L5 da TEC-201: mudar o vinculo so passa a valer no proximo
    # `refresh`, em ate 60 minutos -- a mesma janela que ja vale para o papel.
    #
    # `None` e valor legitimo e quer dizer "nao e corretor": o ADMIN e a
    # GERENTE nao sao. **Num usuario de papel CORRETOR, `None` NEGA tudo o que
    # e por dono**, em vez de liberar -- cadastro incompleto nao e passe livre,
    # e a diferenca entre "nao tem dono" e "e dono de tudo" e exatamente o erro
    # que esta card existe para nao cometer.
    corretor_id: uuid.UUID | None


class TokenInvalido(Exception):
    """Assinatura errada, formato errado, expirado ou com claim faltando.

    **Um tipo so para todos esses casos, de proposito.** Distinguir "expirado"
    de "assinatura invalida" na resposta diria a quem sonda qual das duas
    coisas ele acertou. Quem precisa da diferenca e o log, nao o cliente.
    """


def emitir(
    usuario_id: uuid.UUID,
    papel: str,
    *,
    mfa: bool,
    corretor_id: uuid.UUID | None,
    settings: Settings,
) -> str:
    """O JWT de acesso, valido por `jwt_minutos`.

    `corretor_id` e obrigatorio na assinatura e nulavel no valor (TEC-202, D4):
    quem emite tem de ter OLHADO o vinculo do usuario, e `None` precisa ser uma
    afirmacao ("nao e corretor") e nao um esquecimento.
    """
    agora = datetime.now(UTC)
    corpo = {
        "sub": str(usuario_id),
        "papel": papel,
        "mfa": mfa,
        "corretor_id": str(corretor_id) if corretor_id else None,
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
        vinculo = corpo["corretor_id"]
        return Identidade(
            usuario_id=uuid.UUID(corpo["sub"]),
            papel=corpo["papel"],
            mfa=bool(corpo["mfa"]),
            # `corpo["corretor_id"]` e nao `.get`: a claim e OBRIGATORIA, e o
            # que e opcional e o VALOR dela. Com `.get`, um token emitido antes
            # da TEC-202 viraria uma identidade sem vinculo em silencio -- que
            # e justamente a forma que nega tudo o que e por dono, e seria
            # negada sem ninguem entender por que.
            corretor_id=uuid.UUID(vinculo) if vinculo is not None else None,
        )
    except (KeyError, ValueError) as falha:
        # Assinatura valida e corpo com forma errada significa que alguem com o
        # segredo emitiu algo que este codigo nao entende. Recusar e o certo --
        # aceitar com defaults inventaria um papel.
        raise TokenInvalido(type(falha).__name__) from falha


def emitir_desafio(
    usuario_id: uuid.UUID,
    papel: str,
    *,
    minutos: int,
    corretor_id: uuid.UUID | None,
    settings: Settings,
) -> str:
    """O token de meio caminho do ADMIN com MFA pendente. TEC-201, D5.

    **E um JWT como os outros, e nao um formato novo.** O que o distingue e o
    `mfa: False` com vida curta: ele prova que a senha estava certa e nao prova
    o segundo fator. `POST /auth/mfa` exige exatamente essa combinacao, e e por
    isso que um token de ACESSO completo (com `mfa: True`) nao serve para
    trocar por outro par -- se servisse, uma sessao valida se renovaria para
    sempre sem senha.

    Mora aqui, e nao na rota, porque emitir JWT e decisao deste modulo: o
    algoritmo e o segredo tem UM lugar.

    **Carrega `corretor_id` como o token de acesso, embora nada o leia daqui**
    (TEC-202, D4): ha UMA forma de corpo de JWT neste sistema, e `validar` a
    exige inteira. Um segundo formato obrigaria `validar` a tolerar a ausencia
    da claim -- e tolerar ausencia e o caminho pelo qual um token de acesso sem
    vinculo passaria despercebido.
    """
    agora = datetime.now(UTC)
    corpo = {
        "sub": str(usuario_id),
        "papel": papel,
        "mfa": False,
        "corretor_id": str(corretor_id) if corretor_id else None,
        "iat": agora,
        "exp": agora + timedelta(minutes=minutos),
    }
    return jwt.encode(corpo, settings.jwt_segredo, algorithm=ALGORITMO)
