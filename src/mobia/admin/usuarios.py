"""Cria um usuario do dashboard pela linha de comando. TEC-309, D8.

**Existe porque, sem ele, ninguem entra.** A TEC-201 entregou login, MFA e
refresh, e nenhuma rota que crie usuario ou habilite TOTP -- a lacuna L2 do
desenho dela. A TEC-309 poe a tela de login na frente dessas rotas, e uma tela
de login sem ninguem que consiga logar nao e verificavel. Cadastro por tela e
convite continuam sendo outra card.

A logica mora aqui, e `scripts/criar_usuario.py` so junta os argumentos e pede
a senha -- mesma divisao de `mobia.admin.recifrar`, para o teste chamar a
funcao sem `asyncio.run` nem terminal.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.usuarios import senha, totp
from mobia.domain.usuarios.models import PAPEIS, Usuario

# O nome que o aplicativo autenticador mostra ao lado do codigo. Sem ele, quem
# tem mais de uma conta no aplicativo nao sabe qual e esta.
EMISSOR_DO_TOTP = "mobIA"

# O minimo de senha que o script aceita. **Nao e politica de senha** -- a
# TEC-201 nao escreveu nenhuma, e esta card nao a inventa. E so o piso que
# impede criar um ADMIN com senha vazia por um Enter apertado cedo demais.
TAMANHO_MINIMO_DA_SENHA = 12


class RecusaDeCadastro(ValueError):
    """O cadastro nao foi feito, e a mensagem diz por que."""


@dataclass(frozen=True)
class UsuarioCriado:
    usuario_id: uuid.UUID
    # A URI `otpauth://` que o aplicativo autenticador le, ou None quando o
    # usuario nasce sem MFA. **Leva a semente em claro** -- quem a imprime
    # precisa saber que esta entregando o segundo fator.
    uri_do_totp: str | None


async def criar_usuario(
    session: AsyncSession,
    *,
    email: str,
    nome: str,
    papel: str,
    senha_em_claro: str,
    corretor_id: uuid.UUID | None = None,
    com_mfa: bool = False,
) -> UsuarioCriado:
    """Grava o usuario e devolve o que o operador precisa ver.

    **ADMIN nasce com MFA sempre, com ou sem `com_mfa`.** Um ADMIN sem
    `mfa_habilitado` e barrado no login pela D5 da TEC-201; cria-lo assim seria
    criar alguem que nao consegue entrar, e o operador so descobriria na tela.

    **O e-mail e gravado em minusculas.** `repositorio.por_email` procura em
    minusculas e o `UNIQUE` da coluna e sensivel a caixa: gravar "Ana@x.com"
    criaria um usuario que o login nunca acha.

    Nao faz commit: quem chama decide, e o teste pode olhar antes.
    """
    email = email.strip().lower()
    papel = papel.strip().upper()

    if papel not in PAPEIS:
        raise RecusaDeCadastro(f"papel desconhecido: {papel}. Os papeis sao {', '.join(PAPEIS)}.")
    if papel == "CORRETOR" and corretor_id is None:
        # Nulo num CORRETOR NEGA tudo que e por dono (comentario de
        # `Usuario.corretor_id`) -- seria um corretor que nao ve lead nenhum.
        raise RecusaDeCadastro("um usuario CORRETOR precisa de --corretor-id.")
    if papel != "CORRETOR" and corretor_id is not None:
        raise RecusaDeCadastro("so um usuario CORRETOR tem --corretor-id.")
    if len(senha_em_claro) < TAMANHO_MINIMO_DA_SENHA:
        raise RecusaDeCadastro(
            f"a senha precisa ter pelo menos {TAMANHO_MINIMO_DA_SENHA} caracteres."
        )

    # Checado antes, e nao so pelo `UNIQUE`: o `IntegrityError` do driver traz
    # o valor na mensagem, e aqui a mensagem certa e curta.
    existente = await session.scalar(select(Usuario.id).where(Usuario.email == email))
    if existente is not None:
        raise RecusaDeCadastro(f"ja existe usuario com o e-mail {email}.")

    usuario_id = uuid.uuid4()
    com_mfa = com_mfa or papel == "ADMIN"
    semente = totp.gerar_semente() if com_mfa else None
    agora = datetime.now(UTC)

    session.add(
        Usuario(
            id=usuario_id,
            nome=nome.strip(),
            email=email,
            papel=papel,
            corretor_id=corretor_id,
            senha_hash=senha.gerar_hash(senha_em_claro),
            totp_segredo=totp.cifrar_semente(semente, usuario_id) if semente else None,
            mfa_habilitado=com_mfa,
            criado_em=agora,
            atualizado_em=agora,
        )
    )
    await session.flush()

    uri = (
        pyotp.TOTP(semente).provisioning_uri(name=email, issuer_name=EMISSOR_DO_TOTP)
        if semente
        else None
    )
    return UsuarioCriado(usuario_id=usuario_id, uri_do_totp=uri)
