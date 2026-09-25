"""Senha, TOTP e JWT: o que se verifica sem banco. TEC-201.

Estes testes existem por uma razao diferente da dos vizinhos: nao protegem uma
regra de negocio, protegem as PROPRIEDADES que o resto do sistema assume. Um
JWT que aceite `alg: none` nao produz teste vermelho em lugar nenhum -- produz
um sistema onde qualquer um e ADMIN.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
import pytest

from mobia.app.config import Settings
from mobia.domain.usuarios import senha, tokens

USUARIO = uuid.UUID("11111111-2222-3333-4444-555555555555")

# 32 bytes ou mais: abaixo disso o `pyjwt` avisa (RFC 7518), e aviso em teste
# vira ruido que treina quem le a ignorar.
SEGREDO = "segredo-de-teste-com-32-bytes-ou-mais"
OUTRO_SEGREDO = "outro-segredo-de-teste-com-32-bytes-ou-mais"


def _settings(**trocas: object) -> Settings:
    base: dict[str, object] = {"jwt_segredo": SEGREDO, "jwt_minutos": 60}
    return Settings(**(base | trocas))  # type: ignore[arg-type]


class TestSenha:
    def test_confere_a_senha_certa(self) -> None:
        assert senha.confere("correta", senha.gerar_hash("correta"))

    def test_recusa_a_errada(self) -> None:
        assert not senha.confere("errada", senha.gerar_hash("correta"))

    def test_a_mesma_senha_gera_hashes_diferentes(self) -> None:
        """O sal e novo a cada chamada.

        Sem isso, olhar a tabela diria quais usuarios compartilham senha -- e
        um hash quebrado abriria todos eles de uma vez.
        """
        assert senha.gerar_hash("igual") != senha.gerar_hash("igual")

    def test_hash_corrompido_recusa_em_vez_de_estourar(self) -> None:
        """Um 500 aqui diria a quem tenta que aquele registro existe e esta
        quebrado. "Nao entra" e o desfecho certo."""
        assert not senha.confere("qualquer", "isto-nao-e-um-hash-argon2")


class TestTotp:
    def test_aceita_o_codigo_do_momento(self) -> None:
        semente = pyotp.random_base32()
        assert pyotp.TOTP(semente).verify(pyotp.TOTP(semente).now())

    def test_recusa_codigo_de_outra_semente(self) -> None:
        assert not pyotp.TOTP(pyotp.random_base32()).verify(pyotp.TOTP(pyotp.random_base32()).now())


class TestJwt:
    def test_ida_e_volta_preserva_papel_e_mfa(self) -> None:
        s = _settings()
        token = tokens.emitir(USUARIO, "ADMIN", mfa=True, settings=s)
        identidade = tokens.validar(token, s)

        assert identidade.usuario_id == USUARIO
        assert identidade.papel == "ADMIN"
        assert identidade.mfa is True

    def test_token_expirado_e_recusado(self) -> None:
        """Segundo cenario do Gherkin, em unidade.

        `jwt_minutos` negativo emite um token que ja nasceu vencido -- e o que
        evita esperar 61 minutos para exercitar a regra.
        """
        s = _settings(jwt_minutos=-1)
        token = tokens.emitir(USUARIO, "GERENTE", mfa=False, settings=s)

        with pytest.raises(tokens.TokenInvalido):
            tokens.validar(token, _settings())

    def test_assinatura_de_outro_segredo_e_recusada(self) -> None:
        token = tokens.emitir(USUARIO, "ADMIN", mfa=True, settings=_settings())

        with pytest.raises(tokens.TokenInvalido):
            tokens.validar(token, _settings(jwt_segredo=OUTRO_SEGREDO))

    def test_alg_none_e_recusado(self) -> None:
        """**O teste mais importante deste arquivo.**

        Um token que se declara `alg: none` nao tem assinatura nenhuma: quem o
        monta escolhe o proprio papel. A defesa e passar `algorithms=` na
        validacao, e e uma linha que alguem pode "simplificar" sem que nada
        mais fique vermelho.

        Nao esta aqui por desconfianca do `pyjwt` -- esta porque esta e a
        propriedade que o sistema inteiro assume, e propriedade assumida sem
        teste e propriedade que se perde numa atualizacao.
        """
        forjado = jwt.encode(
            {
                "sub": str(USUARIO),
                "papel": "ADMIN",
                "mfa": True,
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            key="",
            algorithm="none",
        )

        with pytest.raises(tokens.TokenInvalido):
            tokens.validar(forjado, _settings())

    def test_corpo_sem_papel_e_recusado(self) -> None:
        """Assinatura valida com forma errada: recusa, e nao papel inventado.

        Aceitar com default daria a alguem com o segredo um caminho para emitir
        token sem dizer o papel e receber um qualquer.
        """
        s = _settings()
        sem_papel = jwt.encode(
            {"sub": str(USUARIO), "mfa": True, "exp": datetime.now(UTC) + timedelta(hours=1)},
            s.jwt_segredo,
            algorithm=tokens.ALGORITMO,
        )

        with pytest.raises(tokens.TokenInvalido):
            tokens.validar(sem_papel, s)

    def test_o_desafio_nasce_sem_mfa(self) -> None:
        """E o que impede um token de ACESSO de ser trocado por outro par.

        `POST /auth/mfa` exige `mfa: False`; se o desafio nascesse com `True`, a
        rota aceitaria um token de acesso completo e uma sessao valida se
        renovaria para sempre sem senha.
        """
        s = _settings()
        desafio = tokens.emitir_desafio(USUARIO, "ADMIN", minutos=5, settings=s)

        assert tokens.validar(desafio, s).mfa is False
