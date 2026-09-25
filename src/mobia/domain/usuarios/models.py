"""O usuario do dashboard e a sessao de refresh dele. TEC-201, RNF-11.

Ver `alembic/versions/0045_usuarios_e_sessoes.py` para o porque de cada coluna
e o desenho para as decisoes que as governam.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from mobia.domain.corretores.models import Corretor
from mobia.domain.messages.models import Base
from mobia.infra.crypto import aad_de

# Os quatro papeis da RNF-12. Nascem completos, pelo mesmo argumento que o
# enum de `handoffs.status` da TEC-174: mudar valor de enum depois custa
# migration, e o `IN` do CHECK e o unico lugar a mexer.
#
# **Os quatro governam rota desde a TEC-202**, que era a lacuna L1 desta card:
# cada rota declara a permissao que exerce e a matriz de
# `domain/usuarios/permissoes.py` diz que papeis a tem. Ate la, so o ADMIN
# significava alguma coisa.
PAPEIS = ("ADMIN", "GERENTE", "CORRETOR", "LEITURA")


def aad_do_totp(usuario_id: uuid.UUID) -> str:
    """Amarra a semente do TOTP ao usuario dela.

    Mesmo molde de `aad_do_resumo_de_handoff`: a identidade da linha e um UUID,
    que nao colide com outro por concatenacao ambigua, entao `aad_de` basta.
    """
    return aad_de(usuario_id, "totp_usuario")


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    # **Em claro, apesar de o modelo da secao 5.1 marcar os dois como DP.** E o
    # precedente que a TEC-196 escreveu para `corretores`: este repo cifra
    # CONTEUDO e nao IDENTIFICADOR. Aqui vale com mais forca que la -- o
    # e-mail e a CHAVE DE LOGIN, e indice unico sobre valor cifrado com nonce
    # aleatorio nao existe. Ver a D6 do desenho.
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False)

    papel: Mapped[str] = mapped_column(String(16), nullable=False)

    # Quem e este usuario na tabela de corretores, quando for um. Nulavel: o
    # ADMIN e a GERENTE nao sao corretores.
    #
    # **Desde a TEC-202 e daqui que sai a regra "corretor so ve os proprios
    # leads" da RNF-12**, por uma claim do JWT (D4 de la) e nao por consulta a
    # esta linha em cada requisicao -- entao mudar o vinculo so passa a valer
    # no proximo `refresh`, em ate 60 minutos. E num usuario de papel CORRETOR,
    # nulo NEGA tudo o que e por dono, em vez de liberar.
    corretor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey(Corretor.id), nullable=True
    )

    # Argon2id. **Nao e cifrado com a chave do `crypto.py`, e isso e
    # deliberado:** cifra e reversivel e senha nao deve ser. Quem tiver a chave
    # de conteudo nao deve poder ler senha nenhuma. Ver a D3 do desenho.
    #
    # `String(255)` porque o formato do Argon2 e texto (`$argon2id$v=19$...`),
    # e nao bytes opacos -- ele carrega os parametros junto, que e o que
    # permite trocar o custo sem invalidar os hashes antigos.
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Cifrada com AES-GCM, AAD de `aad_do_totp`. **O unico segredo desta card
    # que fica ao alcance da chave de conteudo**, e por necessidade: conferir
    # um codigo TOTP exige a semente de volta, entao hash nao serve. Fica dito
    # que e uma exposicao real -- comprometida a chave, o segundo fator de
    # todos cai junto.
    totp_segredo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Nasce FALSO. Um ADMIN com isto falso NAO CONSEGUE ENTRAR -- e a regra da
    # RNF-11, nao um efeito colateral. Ver a D5 e a lacuna L2 do desenho: nao
    # ha rota que habilite TOTP nesta card, entao o primeiro ADMIN precisa ser
    # preparado a mao.
    mfa_habilitado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # Desativar impede o REFRESH, e nao o JWT que ja foi emitido: ele continua
    # valendo ate expirar, em ate 60 minutos. E a lacuna L5 do desenho, aceita
    # em troca de nao consultar o banco a cada requisicao.
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @validates("totp_segredo")
    def _recusar_texto_claro(self, coluna: str, valor: object) -> object:
        """Mesma guarda de `Handoff.resumo` e `Message.body`.

        O driver embute o argumento recusado na propria mensagem de excecao,
        antes de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log
        -- o que, para uma semente de TOTP, seria entregar o segundo fator.
        """
        if valor is not None and not isinstance(valor, bytes | bytearray | memoryview):
            raise TypeError(
                f"{coluna} aceita apenas bytes cifrados, recebeu {type(valor).__name__}"
            )
        return valor

    __table_args__ = (
        CheckConstraint(
            "papel IN ('ADMIN', 'GERENTE', 'CORRETOR', 'LEITURA')", name="ck_usuarios_papel"
        ),
        UniqueConstraint("email", name="uq_usuarios_email"),
    )


class SessaoDeRefresh(Base):
    """Uma emissao de refresh token. TEC-201, D4.

    **Uma LINHA POR EMISSAO, e nao uma por sessao.** A rotacao cria linha nova
    a cada uso, e e justamente o rastro de linhas usadas que permite detectar
    reuso: um refresh ja consumido, apresentado de novo, significa que duas
    partes tem o mesmo token -- a legitima e quem o copiou.
    """

    __tablename__ = "sessoes_de_refresh"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey(Usuario.id, ondelete="CASCADE"), nullable=False
    )

    # A corrente de rotacoes que nasceu de um login. Revogar por familia e o
    # que derruba o ladrao E o legitimo quando ha reuso -- deixar o legitimo
    # dentro seria deixar os dois. Ver a D4.
    familia: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    # **SHA-256 do token, nunca o token.** O que vai para o cliente e aleatorio
    # e opaco; o banco guarda so o digest. Vazamento desta tabela nao da sessao
    # a ninguem. Hash simples e nao Argon2 de proposito: a entrada ja tem 256
    # bits de entropia, entao nao ha o que um ataque de dicionario ataque, e o
    # custo de Argon2 por requisicao de refresh seria pago a toa.
    digest: Mapped[str] = mapped_column(String(64), nullable=False)

    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Preenchido quando o token e trocado por um novo. Reapresentar um token
    # com `usado_em` preenchido e o sinal de roubo.
    usado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Preenchido pelo logout ou pela revogacao em cascata da familia.
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # O caminho unico da validacao: "existe sessao com este digest?".
        UniqueConstraint("digest", name="uq_sessoes_digest"),
        # O caminho da revogacao em cascata.
        Index("ix_sessoes_familia", "familia"),
    )
