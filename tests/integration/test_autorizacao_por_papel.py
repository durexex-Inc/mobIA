"""Os quatro cenarios do Gherkin da TEC-202, contra banco de verdade.

**Dois deles trocaram de sujeito, e a razao esta no desenho (L1 e L2).** A card
escreve "acessa a configuracao do agente" e "edita a qualificacao de um lead",
e nenhuma das duas rotas existe neste sistema: `GET · PUT /configuracoes/{chave}`
e `PATCH /leads/{leadId}/qualificacao` estao na secao 6 do SRS e nao no codigo.
Cria-las aqui seria inventar a entidade que falta para o teste se
auto-satisfazer. Os cenarios sao exercitados sobre as rotas equivalentes que
existem -- as administrativas de verdade (corretores, catalogo) e as escritas
que ha -- e as lacunas estao declaradas no desenho e no comentario da card.

O terceiro cenario tem ainda a metade que nao depende de rota nenhuma:
`tests/unit/test_matriz_de_permissoes.py` afirma que o papel LEITURA nao tem
permissao de escrita alguma, o que vale tambem para as rotas que virao depois.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.auditoria.models import EventoAuditoria
from mobia.domain.handoff.models import Handoff
from mobia.domain.handoff.vocabulario import Status
from mobia.domain.usuarios import tokens
from mobia.domain.usuarios.models import Usuario
from mobia.domain.usuarios.permissoes import Permissao, permissoes_de
from tests.conftest import eventos_de_log

# Uma rota administrativa de verdade (RN-19.2, papel ADMIN) e uma rota de
# escrita que o CORRETOR tambem alcanca. As duas juntas separam "so o ADMIN" de
# "quem atende lead", que e a distincao que o primeiro cenario exercita.
ROTA_ADMINISTRATIVA = "/api/v1/corretores"
ROTA_DE_CATALOGO = "/api/v1/imoveis/importacoes/00000000-0000-0000-0000-000000000001"

# **Literal, e nunca `uuid4()`, dentro de `parametrize`.** O id do parametro
# entra no nome do teste, e um valor sorteado no COLETA faz cada worker do
# xdist nomear o mesmo teste de um jeito -- o que reprova a execucao inteira
# com "Different tests were collected between gw1 and gw0", antes de rodar
# teste nenhum. Nao precisa existir no banco: a guarda nega antes de olhar.
HANDOFF_INEXISTENTE = "5f9d3a1e-0000-4000-8000-000000000002"


def _token(papel: str, *, corretor_id: uuid.UUID | None = None) -> str:
    """Um JWT valido para este papel, sem passar pelo login.

    O caminho do login ja e exercitado inteiro por `test_autenticacao.py`; o que
    se testa aqui e o que a guarda faz com um token legitimo, e semear senha e
    TOTP para cada um dos quatro papeis so acrescentaria Argon2 ao relogio.
    """
    return tokens.emitir(
        uuid.uuid4(), papel, mfa=papel == "ADMIN", corretor_id=corretor_id, settings=get_settings()
    )


def _bearer(papel: str, *, corretor_id: uuid.UUID | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(papel, corretor_id=corretor_id)}"}


async def _corretor(semear_corretor: Any, nome: str) -> uuid.UUID:
    """Um corretor ativo, pela fixture que ja existe.

    `semear_corretor` e nao um INSERT proprio: ela preenche os mesmos CHECKs
    que `criar_corretor` preenche (jornada, capacidade, especialidades,
    regioes), e uma segunda copia disso aqui divergiria no dia em que um CHECK
    novo aparecesse.
    """
    return uuid.UUID(str((await semear_corretor(email=f"{nome}@imobiliaria.com")).id))


async def _handoff_de(session: AsyncSession, corretor_id: uuid.UUID | None) -> uuid.UUID:
    handoff_id = uuid.uuid4()
    agora = datetime.now(UTC)
    session.add(
        Handoff(
            id=handoff_id,
            channel="whatsapp",
            conversation_key=str(uuid.uuid4())[:20],
            gatilho="PEDIU_HUMANO",
            etiqueta="PEDIU_HUMANO",
            prioridade="NORMAL",
            status=Status.PENDENTE.value,
            corretor_id=corretor_id,
            criado_em=agora,
            atualizado_em=agora,
        )
    )
    await session.commit()
    return handoff_id


# Primeiro cenario do Gherkin, tabela literal: so o ADMIN entra no
# administrativo. O sujeito e o CRUD de corretores (RN-19.2) porque a
# "configuracao do agente" da card nao tem rota (L1).
@pytest.mark.parametrize(
    ("papel", "permitido"),
    [("ADMIN", True), ("GERENTE", False), ("CORRETOR", False), ("LEITURA", False)],
)
async def test_acesso_ao_modulo_administrativo(
    client: AsyncClient, banco_limpo: None, papel: str, permitido: bool
) -> None:
    resposta = await client.get(ROTA_ADMINISTRATIVA, headers=_bearer(papel))

    assert (resposta.status_code != 403) is permitido


@pytest.mark.parametrize(
    ("papel", "permitido"),
    [("ADMIN", True), ("GERENTE", False), ("CORRETOR", False), ("LEITURA", False)],
)
async def test_o_catalogo_tambem_e_so_do_admin(
    client: AsyncClient, banco_limpo: None, papel: str, permitido: bool
) -> None:
    """A mesma tabela sobre a outra rota administrativa que existe.

    Duas rotas e nao uma porque o primeiro cenario afirma algo sobre o MODULO
    administrativo, e uma unica rota deixaria a afirmacao depender de um
    handler so. Aqui a resposta esperada para o ADMIN e 404 (a importacao nao
    existe) -- que e exatamente o ponto: ele passou pela guarda.
    """
    resposta = await client.get(ROTA_DE_CATALOGO, headers=_bearer(papel))

    assert (resposta.status_code != 403) is permitido
    if permitido:
        assert resposta.status_code == 404


async def test_corretor_nao_aceita_handoff_de_outro_corretor(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    caplog: Any,
    semear_corretor: Any,
) -> None:
    """Segundo cenario: o corretor requisita o identificador que nao e dele.

    **O identificador e o do handoff, e nao o de um lead** (D5): o handoff e a
    unica entidade deste sistema que tem dono e e enderecavel por id.
    `GET /api/v1/leads/{leadId}`, que o SRS descreve para este cenario, nao
    existe.
    """
    dono = await _corretor(semear_corretor, "paulo")
    intruso = await _corretor(semear_corretor, "marcia")
    handoff_id = await _handoff_de(session, dono)

    with caplog.at_level("WARNING"):
        resposta = await client.post(
            f"/api/v1/handoffs/{handoff_id}/aceitar",
            headers=_bearer("CORRETOR", corretor_id=intruso),
        )

    assert resposta.status_code == 403
    # "E a tentativa e registrada" -- a segunda linha do cenario, que sem esta
    # asserta ficaria por conta da leitura do codigo.
    ((_, evento),) = eventos_de_log(caplog, "autorizacao.negada")
    assert evento["motivo"] == "corretor_nao_e_o_dono"
    assert evento["papel"] == "CORRETOR"
    assert evento["rota"] == f"/api/v1/handoffs/{handoff_id}/aceitar"


async def test_corretor_aceita_o_proprio_handoff(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    """O outro lado do mesmo cenario, que e o que impede a guarda de negar tudo.

    Uma regra de dono que recusasse tambem o dono passaria no teste de cima e
    quebraria a operacao inteira -- e o modo de falha mais provavel de uma
    comparacao de UUID escrita ao contrario.
    """
    dono = await _corretor(semear_corretor, "paulo")
    handoff_id = await _handoff_de(session, dono)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar",
        headers=_bearer("CORRETOR", corretor_id=dono),
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == Status.ACEITO.value


async def test_gerente_aceita_handoff_de_qualquer_corretor(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    """A regra de dono morde o CORRETOR, e so ele (Emenda E-05 a RN-16.4).

    A escalada de SLA da RN-16.3 chega A GERENTE quando ninguem aceita: um
    destinatario que nao pudesse agir sobre o handoff escalado seria um beco
    sem saida, e e por isso que `ATENDER_LEAD` chega ate ela.
    """
    dono = await _corretor(semear_corretor, "paulo")
    handoff_id = await _handoff_de(session, dono)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar", headers=_bearer("GERENTE")
    )

    assert resposta.status_code == 200


async def test_corretor_sem_vinculo_nao_alcanca_handoff_nenhum(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    """`corretor_id` nulo num CORRETOR nega, nao libera (D4).

    Cadastro incompleto nao e passe livre. A diferenca entre "nao tem dono" e
    "e dono de tudo" e exatamente o erro que esta card existe para nao cometer,
    e sem vinculo o token nao tem com o que comparar.
    """
    dono = await _corretor(semear_corretor, "paulo")
    handoff_id = await _handoff_de(session, dono)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar", headers=_bearer("CORRETOR")
    )

    assert resposta.status_code == 403


async def test_handoff_sem_destinatario_nao_e_de_ninguem(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    """Handoff com `corretor_id` nulo (Emenda E-02 da RN-16.3) recusa o corretor.

    "Nao e de ninguem" nao quer dizer "e de quem pedir" -- e o handoff sem
    destinatario existe de verdade neste sistema, nao e caso de borda inventado.
    A GERENTE continua alcancando, que e como ele volta a ter dono.
    """
    qualquer = await _corretor(semear_corretor, "paulo")
    handoff_id = await _handoff_de(session, None)

    do_corretor = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar",
        headers=_bearer("CORRETOR", corretor_id=qualquer),
    )
    da_gerente = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar", headers=_bearer("GERENTE")
    )

    assert do_corretor.status_code == 403
    assert da_gerente.status_code == 200


async def test_corretor_nao_assume_conversa_em_nome_de_outro(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    caplog: Any,
    semear_corretor: Any,
) -> None:
    """A Emenda E-05 a RN-16.4, que e a mudanca mais valiosa desta card.

    Ate aqui o `corretor_id` do corpo era, nas palavras da Emenda E-01 daquela
    regra, "afirmacao de quem chama, nao identidade provada": quem tinha o token
    assumia em nome de qualquer corretor cadastrado. Para o papel CORRETOR isso
    fecha -- o corpo tem de dizer ele mesmo.
    """
    eu = await _corretor(semear_corretor, "paulo")
    outro = await _corretor(semear_corretor, "marcia")

    with caplog.at_level("WARNING"):
        resposta = await client.post(
            "/api/v1/conversas/assumir",
            json={"channel": "whatsapp", "conversation_key": "5548999", "corretor_id": str(outro)},
            headers=_bearer("CORRETOR", corretor_id=eu),
        )

    assert resposta.status_code == 403
    ((_, evento),) = eventos_de_log(caplog, "autorizacao.negada")
    assert evento["motivo"] == "corretor_nao_e_o_dono"


async def test_corretor_assume_em_nome_de_si_mesmo(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    eu = await _corretor(semear_corretor, "paulo")

    resposta = await client.post(
        "/api/v1/conversas/assumir",
        json={"channel": "whatsapp", "conversation_key": "5548999", "corretor_id": str(eu)},
        headers=_bearer("CORRETOR", corretor_id=eu),
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "SILENCIADA"


async def test_admin_continua_assumindo_em_nome_de_outro(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    """Para ADMIN e GERENTE o campo SEGUE sendo afirmacao, e isso e deliberado.

    Agir em nome de terceiro e a funcao desses papeis -- a conversa travada, o
    corretor que saiu de ferias. O custo que a D2 da TEC-179 aceitou permanece
    inteiro para eles, e e o que este teste fixa para nao ser "consertado" sem
    querer.
    """
    outro = await _corretor(semear_corretor, "marcia")

    resposta = await client.post(
        "/api/v1/conversas/assumir",
        json={"channel": "whatsapp", "conversation_key": "5548777", "corretor_id": str(outro)},
        headers=_bearer("ADMIN"),
    )

    assert resposta.status_code == 200


# Terceiro cenario: o papel LEITURA nao altera nada. As tres escritas que
# existem hoje, ja que `PATCH /leads/{id}/qualificacao` nao existe (L2).
@pytest.mark.parametrize(
    ("metodo", "rota", "corpo"),
    [
        ("POST", "/api/v1/conversas/assumir", {"channel": "whatsapp", "conversation_key": "x"}),
        ("POST", f"/api/v1/handoffs/{HANDOFF_INEXISTENTE}/aceitar", None),
        ("POST", "/api/v1/corretores", None),
    ],
)
async def test_leitura_nao_altera_nada(
    client: AsyncClient,
    banco_limpo: None,
    metodo: str,
    rota: str,
    corpo: dict[str, object] | None,
) -> None:
    if corpo is not None:
        corpo = {**corpo, "corretor_id": str(uuid.uuid4())}

    resposta = await client.request(metodo, rota, json=corpo, headers=_bearer("LEITURA"))

    assert resposta.status_code == 403


async def test_leitura_le_o_funil(client: AsyncClient, banco_limpo: None) -> None:
    """O outro lado: o papel existe para ler, e le.

    Sem esta asserta, um `LEITURA` recusado em toda parte passaria nos testes
    de negacao acima e seria indistinguivel de um papel quebrado.
    """
    resposta = await client.get(
        "/api/v1/metricas/funil",
        params={"de": "2026-09-01", "ate": "2026-09-24"},
        headers=_bearer("LEITURA"),
    )

    assert resposta.status_code == 200


async def test_corretor_nao_le_o_funil(client: AsyncClient, banco_limpo: None) -> None:
    """A linha menos obvia da matriz, exercitada na rota (RN-FE-03.1, TEC-312)."""
    resposta = await client.get(
        "/api/v1/metricas/funil",
        params={"de": "2026-09-01", "ate": "2026-09-24"},
        headers=_bearer("CORRETOR", corretor_id=uuid.uuid4()),
    )

    assert resposta.status_code == 403


async def test_quarto_cenario_rota_administrativa_chamada_direto_sem_credencial(
    client: AsyncClient, banco_limpo: None, caplog: Any
) -> None:
    """ "Protecao e de rota, nao de interface": sem credencial nenhuma, 403.

    A rota EXISTE e recusa -- nao e 404 por ausencia de registro, que era o
    comportamento ate a TEC-201. E a tentativa e registrada com `papel` nulo:
    "ninguem provou quem e" e um fato diferente de "provou e nao pode".
    """
    with caplog.at_level("WARNING"):
        resposta = await client.get(ROTA_ADMINISTRATIVA)

    assert resposta.status_code == 403
    ((_, evento),) = eventos_de_log(caplog, "autorizacao.negada")
    assert evento["papel"] is None
    assert evento["usuario_id"] is None
    assert evento["permissao"] == Permissao.GERIR_CORRETORES.value


async def test_a_negativa_por_papel_registra_quem_tentou(
    client: AsyncClient, banco_limpo: None, caplog: Any
) -> None:
    """A outra metade do registro: autenticado, e sem a permissao.

    E o evento que responde "quem andou tentando abrir o que nao e dele" numa
    investigacao. O log e metade do registro; a outra, desde a TEC-206, e a
    linha em `eventos_auditoria` -- ver
    `test_a_negativa_por_papel_tambem_vai_para_a_trilha`.
    """
    with caplog.at_level("WARNING"):
        await client.get(ROTA_ADMINISTRATIVA, headers=_bearer("LEITURA"))

    ((nivel, evento),) = eventos_de_log(caplog, "autorizacao.negada")

    assert nivel == "WARNING"
    assert evento["papel"] == "LEITURA"
    assert evento["metodo"] == "GET"
    assert evento["motivo"] == "sem_permissao"


@pytest.mark.parametrize(
    "rota",
    [ROTA_ADMINISTRATIVA, "/api/v1/metricas/funil", "/api/v1/imoveis/busca"],
)
async def test_o_token_compartilhado_continua_passando_em_tudo(
    client: AsyncClient, banco_limpo: None, rota: str
) -> None:
    """A coexistencia da D2 -- o teste que garante que esta card nao parou o painel.

    O BFF deixou de mandar `X-Admin-Token` na TEC-309, mas o FastAPI ainda o
    aceita: ele resolve para um ADMIN sintetico e passa em toda permissao da
    matriz, inclusive nas que so o ADMIN tem. **Isto e exposicao declarada
    (L4), nao propriedade desejada**: quando a TEC-382 apagar o token, e este
    teste que sai junto.
    """
    resposta = await client.get(
        rota, headers={"X-Admin-Token": get_settings().catalogo_admin_token}
    )

    assert resposta.status_code != 403


async def test_me_devolve_papel_vinculo_e_permissoes(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """`GET /auth/me`, o consumidor que torna a matriz observavel (D7).

    E a origem do `GET /bff/me` que a RN-FE-03.2 (TEC-312) exige: "papeis e
    permissoes vem de /bff/me; o cliente nao decodifica JWT".
    """
    vinculo = uuid.uuid4()
    resposta = await client.get("/api/v1/auth/me", headers=_bearer("GERENTE", corretor_id=vinculo))

    corpo = resposta.json()
    assert resposta.status_code == 200
    assert corpo["papel"] == "GERENTE"
    assert corpo["corretorId"] == str(vinculo)
    assert corpo["permissoes"] == sorted(p.value for p in permissoes_de("GERENTE"))
    # A permissao que ainda nao mascara nada (L3) e visivel aqui, que e o unico
    # lugar onde ela e observavel ate a TEC-195.
    assert Permissao.VER_DADOS_COMPLETOS.value in corpo["permissoes"]


async def test_me_recusa_o_token_compartilhado(client: AsyncClient, banco_limpo: None) -> None:
    """A unica guarda do sistema em que o token compartilhado NAO serve.

    Ele resolve para um ADMIN sem usuario, e uma rota que responde "quem sou
    eu" nao tem o que responder a quem nao e ninguem. Inventar um corpo para
    esse caso seria ensinar o BFF a confiar numa identidade que nao existe.
    """
    resposta = await client.get(
        "/api/v1/auth/me", headers={"X-Admin-Token": get_settings().catalogo_admin_token}
    )

    assert resposta.status_code == 403


async def test_usuario_do_banco_recebe_no_me_o_papel_que_tem_gravado(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    """O caminho inteiro, do registro no banco ate a resposta.

    Os outros testes deste arquivo emitem o JWT direto, o que e proposital --
    mas nenhum deles provaria que `login` poe no token o papel e o vinculo que
    a linha tem. Este prova, e e o que amarra a matriz ao cadastro.
    """
    from mobia.domain.usuarios import senha as modulo_senha

    corretor_id = await _corretor(semear_corretor, "paulo")
    usuario_id = uuid.uuid4()
    agora = datetime.now(UTC)
    session.add(
        Usuario(
            id=usuario_id,
            nome="Paulo",
            email="paulo@imobiliaria.com",
            papel="CORRETOR",
            corretor_id=corretor_id,
            senha_hash=modulo_senha.gerar_hash("uma-senha-boa"),
            mfa_habilitado=False,
            ativo=True,
            criado_em=agora,
            atualizado_em=agora,
        )
    )
    await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "paulo@imobiliaria.com", "senha": "uma-senha-boa"},
    )
    eu = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access']}"}
    )

    assert eu.json()["papel"] == "CORRETOR"
    assert eu.json()["corretorId"] == str(corretor_id)


async def _negativas(session: AsyncSession) -> list[EventoAuditoria]:
    return list(
        (
            await session.execute(
                select(EventoAuditoria).where(EventoAuditoria.acao == "ACESSO_NEGADO")
            )
        ).scalars()
    )


async def test_a_negativa_com_identidade_vai_para_a_trilha(
    session: AsyncSession,
    client: AsyncClient,
    banco_limpo: None,
    semear_corretor: Any,
) -> None:
    """TEC-206, D7: com identidade resolvida, a negativa tem destino persistente.

    O `entidade_id` e o TEMPLATE da rota, e nao o caminho com o id: o que se
    audita e qual rota foi negada.
    """
    dono = await _corretor(semear_corretor, "paulo")
    intruso = await _corretor(semear_corretor, "marcia")
    handoff_id = await _handoff_de(session, dono)

    resposta = await client.post(
        f"/api/v1/handoffs/{handoff_id}/aceitar",
        headers=_bearer("CORRETOR", corretor_id=intruso),
    )

    assert resposta.status_code == 403
    (evento,) = await _negativas(session)
    assert evento.ator_tipo == "USUARIO"
    assert evento.ator_id is not None
    assert evento.entidade == "rota"
    assert evento.entidade_id == "/api/v1/handoffs/{handoff_id}/aceitar"
    assert evento.detalhes == {
        "permissao": "ATENDER_LEAD",
        "motivo": "corretor_nao_e_o_dono",
        "papel": "CORRETOR",
        "metodo": "POST",
    }
    assert str(evento.ip) == "127.0.0.1"
    assert evento.correlation_id == resposta.headers["X-Request-Id"]


async def test_a_negativa_por_papel_tambem_vai_para_a_trilha(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    resposta = await client.get(ROTA_ADMINISTRATIVA, headers=_bearer("LEITURA"))

    assert resposta.status_code == 403
    (evento,) = await _negativas(session)
    assert evento.entidade_id == ROTA_ADMINISTRATIVA
    assert evento.detalhes is not None
    assert evento.detalhes["motivo"] == "sem_permissao"
    assert evento.detalhes["permissao"] == Permissao.GERIR_CORRETORES.value


async def test_a_negativa_sem_credencial_fica_so_no_log(
    session: AsyncSession, client: AsyncClient, banco_limpo: None, caplog: Any
) -> None:
    """O argumento da TEC-202 vale inteiro: sem credencial, e o varredor em rajada."""
    with caplog.at_level("WARNING"):
        resposta = await client.get(ROTA_ADMINISTRATIVA)

    assert resposta.status_code == 403
    assert len(eventos_de_log(caplog, "autorizacao.negada")) == 1
    assert await _negativas(session) == []


async def test_o_token_compartilhado_sem_sessao_vai_para_a_trilha(
    session: AsyncSession, client: AsyncClient, banco_limpo: None
) -> None:
    """Identidade resolvida, mas sem usuario: `ator_id` e o `para_log` dela."""
    resposta = await client.get(
        "/api/v1/auth/me", headers={"X-Admin-Token": get_settings().catalogo_admin_token}
    )

    assert resposta.status_code == 403
    (evento,) = await _negativas(session)
    assert evento.ator_id == "token-compartilhado"
    assert evento.detalhes is not None
    assert evento.detalhes["motivo"] == "sem_sessao"
    assert evento.detalhes["permissao"] is None
