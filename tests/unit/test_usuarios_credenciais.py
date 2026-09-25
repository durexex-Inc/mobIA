"""Senha, TOTP e JWT: o que se verifica sem banco. TEC-201 e TEC-202.

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
        token = tokens.emitir(USUARIO, "ADMIN", mfa=True, corretor_id=None, settings=s)
        identidade = tokens.validar(token, s)

        assert identidade.usuario_id == USUARIO
        assert identidade.papel == "ADMIN"
        assert identidade.mfa is True
        assert identidade.corretor_id is None

    def test_ida_e_volta_preserva_o_vinculo_de_corretor(self) -> None:
        """A claim da TEC-202 (D4), que e o que a regra de dono consulta.

        Sem ela o papel CORRETOR nao teria como provar de quem e o lead -- e a
        alternativa, consultar `usuarios` a cada requisicao, e a que a lacuna
        L5 da TEC-201 ja recusou.
        """
        s = _settings()
        vinculo = uuid.uuid4()
        token = tokens.emitir(USUARIO, "CORRETOR", mfa=False, corretor_id=vinculo, settings=s)

        assert tokens.validar(token, s).corretor_id == vinculo

    def test_corpo_sem_a_claim_de_vinculo_e_recusado(self) -> None:
        """Um token anterior a TEC-202 nao vira identidade sem vinculo.

        E o caso que `corpo.get("corretor_id")` teria deixado passar: a
        identidade nasceria com `corretor_id=None`, que num CORRETOR nega tudo
        o que e por dono -- e a pessoa seria recusada sem que nada dissesse por
        que. Recusar o TOKEN diz.
        """
        s = _settings()
        antigo = jwt.encode(
            {
                "sub": str(USUARIO),
                "papel": "CORRETOR",
                "mfa": False,
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            s.jwt_segredo,
            algorithm=tokens.ALGORITMO,
        )

        with pytest.raises(tokens.TokenInvalido):
            tokens.validar(antigo, s)

    def test_token_expirado_e_recusado(self) -> None:
        """Segundo cenario do Gherkin, em unidade.

        `jwt_minutos` negativo emite um token que ja nasceu vencido -- e o que
        evita esperar 61 minutos para exercitar a regra.
        """
        s = _settings(jwt_minutos=-1)
        token = tokens.emitir(USUARIO, "GERENTE", mfa=False, corretor_id=None, settings=s)

        with pytest.raises(tokens.TokenInvalido):
            tokens.validar(token, _settings())

    def test_assinatura_de_outro_segredo_e_recusada(self) -> None:
        token = tokens.emitir(USUARIO, "ADMIN", mfa=True, corretor_id=None, settings=_settings())

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
        desafio = tokens.emitir_desafio(USUARIO, "ADMIN", minutos=5, corretor_id=None, settings=s)

        assert tokens.validar(desafio, s).mfa is False
