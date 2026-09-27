"""Nenhuma rota sem decisao de quem pode chama-la. TEC-202, D3 do desenho.

**Este arquivo e o que substitui o middleware.** A regra da card e que a
checagem aconteca em TODA rota, e a guarda escolhida e dependencia por rota --
porque o Starlette so resolve qual rota atende a requisicao depois da pilha de
middleware, e um middleware teria de reimplementar a correspondencia de
caminho em paralelo ao FastAPI. Ver a D3.

A consequencia e que "esqueci de pendurar a guarda na rota nova" deixa de ser
pego pelo runtime e passa a ser pego aqui. E por isso que este teste varre o
app inteiro em vez de conferir uma lista escrita a mao: lista a mao envelhece
junto com quem a escreve.
"""

from starlette.routing import BaseRoute

from mobia.api.autorizacao import ROTAS_PUBLICAS, Exige, ExigeSessao
from mobia.app.main import create_app


def _guarda_de(rota: BaseRoute) -> Exige | ExigeSessao | None:
    """A dependencia de autorizacao desta rota, se houver.

    Olha `dependant.dependencies`, que e onde o FastAPI guarda o que foi
    resolvido dos `Depends` da assinatura -- e nao o codigo-fonte do handler.
    Uma guarda que exista mas nao esteja pendurada como dependencia nao
    protege nada, e e essa a diferenca que este teste precisa enxergar.
    """
    dependant = getattr(rota, "dependant", None)
    if dependant is None:
        return None
    for sub in dependant.dependencies:
        if isinstance(sub.call, Exige | ExigeSessao):
            return sub.call
    return None


def _achatar(rotas: list[BaseRoute]) -> list[BaseRoute]:
    """Todas as rotas, inclusive as que vivem dentro de um router incluido.

    **`app.routes` nao e mais uma lista plana** a partir do FastAPI 0.141: cada
    `include_router` deixa ali um envelope (`_IncludedRouter`) que guarda o
    router original em vez de copiar as rotas dele para cima. Uma varredura que
    olhasse so o primeiro nivel encontraria `/health` e mais nada -- e passaria,
    por vacuidade, exatamente quando deveria reprovar.

    Por `getattr` e nao por `isinstance` na classe do envelope: ela e privada
    (`fastapi.routing._IncludedRouter`), e um teste que importa nome privado
    quebra numa atualizacao de biblioteca por motivo que nao e o dele. O que
    interessa e ter um router dentro, e isso o atributo diz.
    """
    achatadas: list[BaseRoute] = []
    for rota in rotas:
        interno = getattr(rota, "original_router", None)
        if interno is not None:
            achatadas.extend(_achatar(list(interno.routes)))
        else:
            achatadas.append(rota)
    return achatadas


def _rotas_do_app() -> list[BaseRoute]:
    """Tudo o que o app serve: as rotas de negocio, o WebSocket e as do FastAPI.

    **Nao filtra por `APIRoute`**, de proposito. O widget e `APIWebSocketRoute`
    (TEC-124) e as de documentacao sao `Route` cru -- e sao justamente essas
    duas familias que uma varredura distraida deixaria de fora: a mais exposta
    do sistema e as que descrevem a API inteira a quem pedir.
    """
    return [r for r in _achatar(list(create_app().routes)) if getattr(r, "path", None)]


def test_toda_rota_declara_autorizacao() -> None:
    """Ou tem guarda, ou esta na `ROTAS_PUBLICAS` com a razao escrita.

    A mensagem de falha e o ponto deste teste: quem acrescentar uma rota nova
    vai ler aqui o que fazer com ela, e as duas saidas sao decisoes -- nenhuma
    delas e "deixa passar".
    """
    sem_decisao = [
        f"{sorted(getattr(r, 'methods', None) or {'WS'})} {r.path}"
        for r in _rotas_do_app()
        if _guarda_de(r) is None and r.path not in ROTAS_PUBLICAS
    ]

    assert not sem_decisao, (
        "rota sem decisao de autorizacao: "
        + ", ".join(sem_decisao)
        + ". Pendure `Depends(Exige(Permissao.X))` na assinatura, ou "
        "declare a rota em `ROTAS_PUBLICAS` com a razao de ser publica."
    )


def test_rotas_publicas_nao_lista_rota_que_nao_existe() -> None:
    """A lista tambem envelhece, e no sentido perigoso.

    Uma entrada que sobra nao abre buraco nenhum hoje -- mas quando alguem
    criar uma rota com aquele caminho, ela nascera publica por causa de uma
    decisao tomada sobre outra rota, que ja nao existe. Isentar por engano e o
    modo de falha caro desta lista.
    """
    caminhos = {r.path for r in _rotas_do_app()}
    sobrando = sorted(set(ROTAS_PUBLICAS) - caminhos)

    assert not sobrando, f"`ROTAS_PUBLICAS` cita caminho que o app nao serve: {sobrando}"


def test_as_rotas_de_auth_sao_as_unicas_publicas_da_api_v1() -> None:
    """Nenhuma rota de negocio entrou na lista de isencao sem ninguem ver.

    `/api/v1/` e o prefixo do que serve o painel. Uma isencao ali e sempre
    suspeita -- as quatro de `auth` sao publicas porque PRODUZEM a credencial,
    e essa e a unica razao conhecida para uma rota de negocio nao ter guarda.
    """
    publicas = {caminho for caminho in ROTAS_PUBLICAS if caminho.startswith("/api/v1/")}

    assert publicas == {
        "/api/v1/auth/login",
        "/api/v1/auth/mfa",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
    }


# A matriz vista pela outra ponta: rota por rota, a permissao que ela exige.
#
# **E o controle positivo da varredura acima.** Se `_guarda_de` parasse de
# reconhecer a dependencia -- por uma mudanca de API do FastAPI, por exemplo --,
# `test_toda_rota_declara_autorizacao` passaria a acusar tudo, e seria dificil
# confundir isso com aprovacao. O modo de falha silencioso e o inverso: uma
# varredura que nao encontra rota nenhuma passa por vacuidade. Este mapa nao
# passa: ele exige que cada uma delas esteja la, com a permissao certa.
PERMISSAO_ESPERADA = {
    ("POST", "/api/v1/imoveis/importar"): "GERIR_CATALOGO",
    ("GET", "/api/v1/imoveis/importacoes/{importacao_id}"): "GERIR_CATALOGO",
    ("POST", "/api/v1/imoveis/busca"): "BUSCAR_IMOVEIS",
    # TEC-197. O CRUD da tela de administracao, e a lista tambem: com inativos
    # e todos os campos, ela nao e a vitrine da secao 6.3 (D1 do desenho).
    ("GET", "/api/v1/imoveis"): "GERIR_CATALOGO",
    ("GET", "/api/v1/imoveis/importacoes"): "GERIR_CATALOGO",
    ("GET", "/api/v1/imoveis/{imovel_id}"): "GERIR_CATALOGO",
    ("POST", "/api/v1/imoveis"): "GERIR_CATALOGO",
    ("PATCH", "/api/v1/imoveis/{imovel_id}"): "GERIR_CATALOGO",
    ("DELETE", "/api/v1/imoveis/{imovel_id}"): "GERIR_CATALOGO",
    ("POST", "/api/v1/corretores"): "GERIR_CORRETORES",
    ("GET", "/api/v1/corretores"): "GERIR_CORRETORES",
    ("GET", "/api/v1/corretores/{corretor_id}"): "GERIR_CORRETORES",
    ("PATCH", "/api/v1/corretores/{corretor_id}"): "GERIR_CORRETORES",
    ("POST", "/api/v1/handoffs/{handoff_id}/resumo"): "ATENDER_LEAD",
    ("POST", "/api/v1/handoffs/{handoff_id}/aceitar"): "ATENDER_LEAD",
    ("POST", "/api/v1/conversas/assumir"): "ATENDER_LEAD",
    ("POST", "/api/v1/conversas/devolver"): "ATENDER_LEAD",
    ("GET", "/api/v1/metricas/funil"): "VER_FUNIL",
    # TEC-191. So somas, e a mesma gerente do funil.
    ("GET", "/api/v1/metricas/custo-ia"): "VER_FUNIL",
    ("GET", "/api/v1/leads"): "VER_LEADS",
    # TEC-195. **A primeira rota a exigir `VER_DADOS_COMPLETOS`**, e a unica
    # que devolve dado pessoal de lead em claro. Ate ela, a permissao era
    # concedida por papel e exigida por rota nenhuma -- `permissoes.py`
    # chegava a dizer que seria "capacidade consultada DENTRO de um handler".
    ("POST", "/api/v1/leads/{lead_id}/revelar"): "VER_DADOS_COMPLETOS",
    # TEC-193. Leitura que registra na trilha (D3), e por isso as duas estao
    # aqui e nao so a do detalhe: a transcricao e a maior parte do dado
    # pessoal do lead, e uma rota dela fora deste mapa seria o furo.
    ("GET", "/api/v1/leads/{lead_id}"): "VER_DETALHE_DO_LEAD",
    ("GET", "/api/v1/leads/{lead_id}/mensagens"): "VER_DETALHE_DO_LEAD",
    # TEC-194. As cinco mudam estado do lead, e a checagem de dono do CORRETOR
    # mora dentro do handler (`intervencao._abrir`), como nas de agendamento.
    ("POST", "/api/v1/leads/{lead_id}/assumir"): "ATENDER_LEAD",
    ("POST", "/api/v1/leads/{lead_id}/devolver"): "ATENDER_LEAD",
    ("POST", "/api/v1/leads/{lead_id}/mensagens"): "ATENDER_LEAD",
    ("PATCH", "/api/v1/leads/{lead_id}/qualificacao"): "ATENDER_LEAD",
    ("POST", "/api/v1/leads/{lead_id}/score/recalcular"): "ATENDER_LEAD",
    ("GET", "/api/v1/auditoria"): "VER_AUDITORIA",
    # TEC-198, RN-19.5. As tres, e nao so a escrita: o historico diz quem mexeu
    # no agente, e a vigente e o que o agente esta fazendo agora.
    ("GET", "/api/v1/configuracao/agente"): "CONFIGURAR_AGENTE",
    ("PATCH", "/api/v1/configuracao/agente"): "CONFIGURAR_AGENTE",
    ("GET", "/api/v1/configuracao/agente/historico"): "CONFIGURAR_AGENTE",
    # TEC-199. A mesma permissao, e as leituras tambem: o texto ativo e o que
    # o agente diz a todo lead agora.
    ("GET", "/api/v1/prompts"): "CONFIGURAR_AGENTE",
    ("GET", "/api/v1/prompts/{agente}"): "CONFIGURAR_AGENTE",
    ("GET", "/api/v1/prompts/{agente}/versoes"): "CONFIGURAR_AGENTE",
    ("GET", "/api/v1/prompts/{agente}/versoes/{numero}"): "CONFIGURAR_AGENTE",
    ("POST", "/api/v1/prompts/{agente}/versoes"): "CONFIGURAR_AGENTE",
    ("POST", "/api/v1/prompts/{agente}/rollback"): "CONFIGURAR_AGENTE",
    ("GET", "/api/v1/prompts/{agente}/historico"): "CONFIGURAR_AGENTE",
    # TEC-209. A DLQ: a lista nao tem dado pessoal, e reprocessar roda o turno.
    ("GET", "/api/v1/mensagens/esgotadas"): "OPERAR_FILA",
    ("POST", "/api/v1/mensagens/{message_id}/reprocessar"): "OPERAR_FILA",
    # TEC-374. `ATENDER_LEAD` mais a checagem de dono dentro do handler --
    # "so o corretor dono do agendamento, ou um gerente". A permissao sozinha
    # nao expressa a segunda metade, e e por isso que ela nao pode ser a unica
    # coisa que este mapa confere.
    ("POST", "/api/v1/agendamentos/{agendamento_id}/realizado"): "ATENDER_LEAD",
    ("POST", "/api/v1/agendamentos/{agendamento_id}/nao-comparecimento"): "ATENDER_LEAD",
    # TEC-207, D4. So do ADMIN, por construcao -- nao ha papel de DPO neste
    # sistema. As duas de `leads` moram no vocabulario daquele prefixo (D2 do
    # desenho da TEC-193: "o painel abre um LEAD"), mas a permissao e outra.
    ("GET", "/api/v1/titular/solicitacoes"): "ATENDER_TITULAR",
    ("GET", "/api/v1/leads/{lead_id}/dados-pessoais"): "ATENDER_TITULAR",
    ("DELETE", "/api/v1/leads/{lead_id}/dados-pessoais"): "ATENDER_TITULAR",
    ("POST", "/api/v1/titular/solicitacoes/{solicitacao_id}/recusa"): "ATENDER_TITULAR",
}


def test_a_permissao_de_cada_rota() -> None:
    """O mapa rota -> permissao, conferido contra o app de verdade.

    Mudar a permissao de uma rota tem de custar uma linha AQUI tambem. E o
    preco de nao deixar a decisao morar so na assinatura do handler, onde uma
    troca passa despercebida numa revisao de diff grande.
    """
    encontrado = {
        (metodo, rota.path): guarda.permissao.value
        for rota in _rotas_do_app()
        if (guarda := _guarda_de(rota)) is not None and isinstance(guarda, Exige)
        for metodo in sorted(getattr(rota, "methods", None) or set())
    }

    assert encontrado == PERMISSAO_ESPERADA


def test_o_me_exige_sessao_e_nao_permissao() -> None:
    """`GET /auth/me` e a unica guardada por `ExigeSessao`. TEC-202, D7.

    Permissao nenhuma e exigida de proposito -- a rota nao da acesso a dado
    nenhum alem do que o token de quem chama ja carrega --, mas ela tambem nao
    e publica: o token compartilhado nao serve, porque nao ha usuario por tras
    dele para descrever.
    """
    por_sessao = [
        rota.path for rota in _rotas_do_app() if isinstance(_guarda_de(rota), ExigeSessao)
    ]

    assert por_sessao == ["/api/v1/auth/me"]
