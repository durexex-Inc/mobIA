from decimal import Decimal

from mobia.domain.agente.citacao import Divergencia
from mobia.domain.agente.schemas import Intencao
from mobia.evals.metricas import (
    DISPERSAO_MEDIDA,
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    DecomposicaoDaExtracao,
    Discrepancia,
    DivergenciaDeEstado,
    FalhaDeInfraestrutura,
    Insistencia,
    InvencaoObservada,
    ResumoDaExtracaoEfetiva,
    ResumoDaInvencao,
    ResumoDeConfianca,
    ResumoDeInsistencia,
    ResumoDeNegativos,
    ResumoDoFormato,
    ViolacaoDeFormato,
    acuracia_de_intencao,
    sem_mecanismo,
)
from mobia.evals.relatorio import render

CONFIANTE = Decimal("0.90")
INSEGURA = Decimal("0.50")


def classificacao(
    esperada: Intencao,
    obtida: Intencao,
    *,
    confianca: Decimal = CONFIANTE,
    conversa_id: str = "c-01",
    indice: int = 0,
) -> Classificacao:
    return Classificacao(
        conversa_id=conversa_id,
        indice=indice,
        esperada=esperada,
        obtida=obtida,
        confianca=confianca,
    )


def test_relatorio_aponta_qual_metrica_regrediu() -> None:
    """O criterio de aceite do card exige que o relatorio diga qual metrica
    caiu, nao apenas que algo caiu."""
    metricas = [acuracia_de_intencao([classificacao(Intencao.COMPRA, Intencao.ALUGUEL)])]

    texto = render(metricas, {})

    assert "acuracia de intencao" in texto
    assert "VERMELHO" in texto


def test_as_tres_metricas_sem_mecanismo_aparecem_declaradas() -> None:
    """Elas tem de ser visiveis em toda execucao. Uma metrica ausente do
    relatorio vira uma metrica esquecida."""
    metricas = [
        sem_mecanismo("precisao de extracao", "TEC-145 nao existe"),
        sem_mecanismo("taxa de alucinacao", "bloqueada pela TEC-161"),
        sem_mecanismo("aderencia ao tom", "TEC-140 nao existe"),
    ]

    texto = render(metricas, {})

    assert texto.count("SEM_MECANISMO") == 3
    assert "TEC-161" in texto


def test_matriz_mostra_para_onde_a_intencao_escorreu() -> None:
    confusao = {Intencao.INVESTIMENTO: {Intencao.COMPRA: 7, Intencao.INVESTIMENTO: 2}}

    texto = render([], confusao)

    assert "INVESTIMENTO" in texto
    assert "COMPRA" in texto
    assert "7" in texto


def test_matriz_ordena_erros_por_valor_quando_empata_em_contagem() -> None:
    """Quando duas obtida tem a mesma contagem, deve ordenar deterministica
    por .value do enum, nao pela ordem de insercao do dict. Testa com insercao
    invertida (COMPRA antes de ALUGUEL) para pegar o sort sem desempate."""
    confusao = {
        Intencao.INVESTIMENTO: {
            Intencao.COMPRA: 3,
            Intencao.ALUGUEL: 3,
        }
    }

    texto = render([], confusao)

    linhas = texto.split("\n")
    idx_aluguel = next(i for i, linha in enumerate(linhas) if "ALUGUEL" in linha)
    idx_compra = next(i for i, linha in enumerate(linhas) if "COMPRA" in linha)

    assert idx_aluguel < idx_compra, "ALUGUEL deve aparecer antes de COMPRA (ordem alfabetica)"


def test_relatorio_traz_a_contagem_de_turnos_abaixo_do_limiar() -> None:
    """Sem esta secao, recalibrar o limiar exigiria outra execucao paga: e o
    unico lugar onde as contagens de confianca saem da execucao."""
    resumo = ResumoDeConfianca(
        turnos=100, abaixo_do_limiar=21, acertos_rebaixados=18, acertos_recuperados=3
    )

    texto = render([], {}, confianca=resumo)

    assert "## Confianca" in texto
    assert "21/100" in texto
    assert "acertos rebaixados para INDEFINIDA: 18" in texto
    assert "erros que o rebaixamento acertou: 3" in texto


def test_relatorio_nomeia_cada_turno_errado() -> None:
    """O agregado nao da para investigar. A matriz diz que INVESTIMENTO virou
    COMPRA sete vezes e nao diz quais sete; descobrir isso sem estas linhas
    custa outra execucao paga, porque o relatorio vive em log efemero de CI.
    """
    erradas = [
        classificacao(
            Intencao.INVESTIMENTO,
            Intencao.COMPRA,
            conversa_id="investimento-04",
            indice=2,
            confianca=Decimal("0.91"),
        ),
    ]

    texto = render([], {}, erradas=erradas)

    assert "## Classificacoes erradas" in texto
    assert "- investimento-04[2]: INVESTIMENTO -> COMPRA (0.91)" in texto


def test_relatorio_distingue_o_acerto_rebaixado_do_erro_de_classificacao() -> None:
    """As duas linhas pedem acoes diferentes: uma e calibragem da confianca,
    a outra e o classificador errando. E sem a marca a primeira pareceria bug
    do relatorio, porque mostra `esperada -> obtida` iguais."""
    rebaixada = classificacao(
        Intencao.COMPRA, Intencao.COMPRA, conversa_id="compra-07", indice=1, confianca=INSEGURA
    )
    errada = classificacao(
        Intencao.ALUGUEL, Intencao.COMPRA, conversa_id="aluguel-02", indice=0, confianca=CONFIANTE
    )

    texto = render([], {}, erradas=[rebaixada, errada])

    assert "- compra-07[1]: COMPRA -> COMPRA (0.50)  <-- certa, rebaixada para INDEFINIDA" in texto
    assert "- aluguel-02[0]: ALUGUEL -> COMPRA (0.90)" in texto
    assert "aluguel-02[0]: ALUGUEL -> COMPRA (0.90)  <--" not in texto


def test_relatorio_marca_o_erro_que_o_rebaixamento_acerta() -> None:
    """Explica a acuracia efetiva ficar acima da crua. Sem a marca, esta
    linha na lista de erradas contradiz a metrica logo acima dela."""
    recuperada = classificacao(
        Intencao.INDEFINIDA, Intencao.COMPRA, conversa_id="borda-evasivo-01", confianca=INSEGURA
    )

    texto = render([], {}, erradas=[recuperada])

    assert "<-- errada, mas o rebaixamento acerta o rotulo" in texto


def test_relatorio_sem_erradas_omite_a_secao() -> None:
    """Execucao sem erro nenhum nao ganha um cabecalho vazio."""
    texto = render([], {})

    assert "## Classificacoes erradas" not in texto


def test_relatorio_sem_resumo_de_confianca_omite_a_secao() -> None:
    """Uma secao de confianca com zeros mentiria: zero turnos abaixo do
    limiar e um resultado, "nao foi medido" e outro."""
    texto = render([], {})

    assert "## Confianca" not in texto


def test_relatorio_separa_falha_de_infraestrutura_de_erro_de_classificacao() -> None:
    """Vermelho por 429 e vermelho por regressao pedem acoes opostas -- re-rodar
    contra investigar. A conversa que a rede levou tem de aparecer nomeada, e
    fora da lista de classificacoes erradas: nenhum turno dela foi medido."""
    falhas = [FalhaDeInfraestrutura(conversa_id="compra-12", indice=1, erro="APIStatusError")]
    erradas = [classificacao(Intencao.ALUGUEL, Intencao.COMPRA, conversa_id="aluguel-02")]

    texto = render([], {}, erradas=erradas, infraestrutura=falhas)

    assert "## Falhas de infraestrutura" in texto
    assert "- compra-12[1]: APIStatusError" in texto
    assert "Nao sao erro de classificacao" in texto
    depois_das_erradas = texto.split("## Classificacoes erradas")[1]
    assert "compra-12" not in depois_das_erradas


def test_relatorio_anuncia_o_teto_junto_da_contagem_de_abandono() -> None:
    """Sem o teto ao lado, "3 conversas abandonadas" nao diz se a execucao
    ainda vale -- e essa e a unica pergunta que o leitor tem ali."""
    falhas = [
        FalhaDeInfraestrutura(conversa_id=f"compra-{i}", indice=0, erro="APITimeoutError")
        for i in range(3)
    ]

    texto = render([], {}, infraestrutura=falhas)

    assert f"3 conversa(s) abandonada(s), teto {TETO_DE_CONVERSAS_ABANDONADAS}." in texto


def test_a_secao_de_infraestrutura_vem_antes_das_que_dependem_das_metricas() -> None:
    """Ela muda como se le o resto do relatorio, entao precede o resto. Quem
    abre o log de CI tem de saber que a execucao perdeu conversas antes de
    interpretar os numeros que vem depois."""
    texto = render(
        [],
        {Intencao.COMPRA: {Intencao.ALUGUEL: 1}},
        confianca=ResumoDeConfianca(
            turnos=1, abaixo_do_limiar=0, acertos_rebaixados=0, acertos_recuperados=0
        ),
        erradas=[classificacao(Intencao.ALUGUEL, Intencao.COMPRA)],
        infraestrutura=[FalhaDeInfraestrutura("compra-12", 1, "APIStatusError")],
    )

    assert texto.index("## Falhas de infraestrutura") < texto.index("## Confianca")
    assert texto.index("## Confianca") < texto.index("## Classificacoes erradas")
    assert texto.index("## Classificacoes erradas") < texto.index("## Matriz de confusao")


def test_relatorio_sem_falha_de_infraestrutura_omite_a_secao() -> None:
    """Execucao limpa nao ganha um cabecalho que sugere que algo caiu."""
    texto = render([], {})

    assert "## Falhas de infraestrutura" not in texto


# --- TEC-239: a secao de discrepancias da extracao --------------------------


def _d(campo, tipo, *, conversa="compra-01", indice=0):
    return Discrepancia(conversa_id=conversa, indice=indice, campo=campo, tipo=tipo)


def test_sem_discrepancias_a_secao_nao_aparece():
    texto = render([], {})
    assert "extracao" not in texto.lower()


def test_secao_traz_agregado_por_campo_e_tipo():
    texto = render(
        [],
        {},
        discrepancias=[
            _d("vagas", "extra"),
            _d("vagas", "extra", indice=1),
            _d("regiao", "faltou", indice=2),
        ],
    )
    assert "vagas" in texto and "regiao" in texto
    assert "extra: 2" in texto
    assert "faltou: 1" in texto


def test_secao_traz_o_endereco_de_cada_discrepancia():
    """Sem conversa e turno, quem for anotar sabe que falta `urgencia` mas nao
    onde -- e descobrir isso custa outra execucao paga."""
    texto = render([], {}, discrepancias=[_d("urgencia", "extra", conversa="aluguel-09", indice=3)])
    assert "aluguel-09" in texto
    assert "3" in texto
    assert "urgencia" in texto


def test_a_secao_nao_e_gate():
    """Diagnostico, como reperguntas e confianca: nenhuma faixa, nenhum bloqueio."""
    texto = render([], {}, discrepancias=[_d("vagas", "extra")])
    for faixa in ("VERDE", "AMARELO", "VERMELHO"):
        assert faixa not in texto


def test_negativos_sem_discrepancia_ainda_mostra_a_secao() -> None:
    """ "39 turnos negativos, zero invencoes" e o resultado mais valioso de
    imprimir, e ele produz zero discrepancias -- a secao nao pode depender
    so delas para aparecer."""
    texto = render(
        [], {}, negativos=ResumoDeNegativos(turnos=39, com_invencao=0, campos_inventados=0)
    )
    assert "39 turnos negativos" in texto


def test_cabecalho_por_turno_nao_aparece_sem_discrepancias() -> None:
    """Caso ideal: negativos medidos, zero invencao. Sem esta guarda o
    relatorio imprimia "Onde, para quem for anotar:" seguido de nada."""
    texto = render(
        [], {}, negativos=ResumoDeNegativos(turnos=5, com_invencao=0, campos_inventados=0)
    )
    assert "Onde, para quem for anotar" not in texto


def test_a_secao_de_extracao_nomeia_os_turnos_negativos() -> None:
    """Sem isto, um `extra` no relatorio nao diz se foi invencao ou lacuna de
    anotacao -- e a distincao e o motivo de a TEC-238 existir."""
    saida = render(
        [],
        {},
        discrepancias=[_d("regiao", "extra", conversa="borda-fora-01")],
        negativos=ResumoDeNegativos(turnos=39, com_invencao=1, campos_inventados=1),
    )

    assert "39 turnos negativos" in saida
    assert "1 com invencao" in saida


def test_um_campo_inventado_sai_no_singular() -> None:
    """ "1 campos" e erro de portugues que o revisor apontou -- com um so campo
    inventado, a linha tem de ler "1 campo"."""
    saida = render(
        [], {}, negativos=ResumoDeNegativos(turnos=5, com_invencao=1, campos_inventados=1)
    )
    assert "1 campo)" in saida
    assert "1 campos)" not in saida


def test_dois_campos_inventados_seguem_no_plural() -> None:
    saida = render(
        [], {}, negativos=ResumoDeNegativos(turnos=5, com_invencao=1, campos_inventados=2)
    )
    assert "2 campos)" in saida


def test_ha_linha_em_branco_antes_da_lista_por_campo() -> None:
    """Sem a linha em branco, o aviso de ambiguidade do turno negativo emenda
    direto na lista por campo e aperta a leitura."""
    saida = render(
        [],
        {},
        discrepancias=[_d("regiao", "extra")],
        negativos=ResumoDeNegativos(turnos=5, com_invencao=0, campos_inventados=0),
    )
    aviso = "esta anotado por completo, e o completo e vazio."
    posicao = saida.index(aviso) + len(aviso)
    resto = saida[posicao:]
    assert resto.startswith("\n\n")


def test_divergiu_mostra_os_dois_valores_na_linha_do_turno() -> None:
    """Endereco sozinho nao diagnostica `divergiu`. Foi por faltar esta linha
    que os sete `divergiu` de `regiao` da baseline de 30/08/2026 (TEC-247)
    ficaram sem causa, com a execucao paga ja gasta."""
    saida = render(
        [],
        {},
        discrepancias=[
            Discrepancia(
                conversa_id="compra-13",
                indice=0,
                campo="regiao",
                tipo="divergiu",
                esperado="sao roque",
                obtido="Sao Roque",
            )
        ],
    )
    assert "compra-13 turno 0: regiao (divergiu)" in saida
    assert "anotado 'sao roque', obtido 'Sao Roque'" in saida


def test_faltou_mostra_so_o_lado_anotado() -> None:
    """`obtido` e None num `faltou`, e imprimir "obtido None" faria parecer que
    o modelo devolveu um nulo -- coisa que `preenchidos()` nunca faz."""
    saida = render(
        [],
        {},
        discrepancias=[
            Discrepancia(
                conversa_id="compra-02",
                indice=1,
                campo="forma_pagamento",
                tipo="faltou",
                esperado="FGTS",
            )
        ],
    )
    assert "anotado 'FGTS'" in saida
    assert "obtido" not in saida.split("faltou)")[1]


def test_extra_mostra_so_o_lado_obtido() -> None:
    saida = render(
        [],
        {},
        discrepancias=[
            Discrepancia(
                conversa_id="follow-up-03",
                indice=0,
                campo="tipo_imovel",
                tipo="extra",
                obtido="APARTAMENTO",
            )
        ],
    )
    assert "obtido 'APARTAMENTO'" in saida
    assert "anotado" not in saida.split("extra)")[1]


def test_discrepancia_sem_valores_nao_deixa_sobra_de_pontuacao() -> None:
    """Os valores tem default `None`, entao uma `Discrepancia` construida sem
    eles ainda tem de render uma linha limpa -- sem um " -- " orfao no fim."""
    saida = render([], {}, discrepancias=[_d("regiao", "divergiu")])
    linha = next(x for x in saida.splitlines() if "turno" in x and "regiao" in x)
    assert linha.rstrip().endswith("(divergiu)")


def test_relatorio_avisa_quanto_uma_execucao_resolve() -> None:
    """O aviso tem de estar no artefato, nao so no README.

    Quem compara duas execucoes abre o relatorio, nao a documentacao. A
    TEC-250 atribuiu um ganho de 8,1 pontos como "cinco vezes maior que o
    ruido" porque nada no artefato dizia quanto o instrumento resolve.
    """
    texto = render(
        [],
        {},
        decomposicao=DecomposicaoDaExtracao(anotados=96, acertos=88, faltou=8, divergiu=0, extra=3),
    )

    assert "base fixa" in texto
    assert "Poder de resolucao" in texto
    assert f"{DISPERSAO_MEDIDA.uniao_pp:.1f}" in texto
    assert f"{DISPERSAO_MEDIDA.base_fixa_pp:.1f}" in texto


def test_a_conta_aberta_vem_antes_da_lista_de_discrepancias() -> None:
    """Ordem deliberada: o poder de resolucao antes do detalhe.

    Quem abre o relatorio para comparar com a execucao anterior precisa
    esbarrar no aviso antes de formar opiniao sobre os numeros, nao depois de
    ja ter lido a lista inteira.
    """
    texto = render(
        [],
        {},
        discrepancias=[
            Discrepancia(conversa_id="c-01", indice=0, campo="quartos", tipo="faltou", esperado=2)
        ],
        decomposicao=DecomposicaoDaExtracao(anotados=96, acertos=88, faltou=8, divergiu=0, extra=3),
    )

    assert texto.index("Poder de resolucao") < texto.index("campos que nao casaram")


def test_relatorio_sem_decomposicao_omite_a_secao() -> None:
    assert "Poder de resolucao" not in render([], {})


def test_relatorio_traz_a_extracao_efetiva_com_o_endereco_da_divergencia() -> None:
    """Endereco, e nao so contagem: quem for arrumar precisa saber onde.

    Mesma razao de `Discrepancia` carregar `conversa_id` -- descobrir *onde*
    nao pode custar outra execucao paga.
    """
    texto = render(
        [],
        {},
        efetiva=ResumoDaExtracaoEfetiva(
            conversas=40,
            acertos=85,
            total=88,
            divergencias=[
                DivergenciaDeEstado(
                    conversa_id="compra-10",
                    campo="tem_imovel_para_vender",
                    tipo="faltou",
                    esperado=False,
                )
            ],
        ),
    )

    assert "Extracao efetiva" in texto
    assert "85/88 (96.6%)" in texto
    assert "compra-10: tem_imovel_para_vender (faltou)" in texto


def test_relatorio_sem_extracao_efetiva_omite_a_secao() -> None:
    assert "Extracao efetiva" not in render([], {})


def test_relatorio_mostra_o_porque_da_falha_de_infraestrutura() -> None:
    """91 linhas de `BadRequestError` e nenhuma pista custaram um dia (TEC-237).

    O motivo vem indentado sob a falha, e nao concatenado nela: a mensagem do
    provedor pode ter 300 caracteres, e a lista continua legivel de relance.
    """
    texto = render(
        [],
        {},
        infraestrutura=[
            FalhaDeInfraestrutura(
                conversa_id="compra-01",
                indice=0,
                erro="BadRequestError",
                motivo="400 invalid_request_error: Your credit balance is too low.",
            )
        ],
    )

    assert "compra-01[0]: BadRequestError" in texto
    assert "    400 invalid_request_error: Your credit balance is too low." in texto


def test_falha_sem_motivo_nao_ganha_linha_vazia() -> None:
    """Timeout e 429 nao tem corpo de erro do servidor, e a maioria das falhas
    de infraestrutura e disso."""
    texto = render(
        [],
        {},
        infraestrutura=[FalhaDeInfraestrutura(conversa_id="c-01", indice=0, erro="TimeoutError")],
    )

    assert "c-01[0]: TimeoutError" in texto
    assert "\n    \n" not in texto


def test_relatorio_abre_o_formato_por_regra() -> None:
    """Tamanho e numero de perguntas pedem consertos diferentes.

    Um total unico esconderia qual dos dois esta acontecendo -- encurtar o
    texto e mudar a instrucao de perguntas sao mudancas diferentes, e a
    segunda custa orcamento de prompt que hoje nao existe.
    """
    texto = render(
        [],
        {},
        formato=ResumoDoFormato(
            respostas=147,
            violacoes=[
                ViolacaoDeFormato(
                    conversa_id="compra-01",
                    indice=2,
                    regra="comprimento",
                    medido=812,
                    texto="resposta longa demais",
                ),
                ViolacaoDeFormato(
                    conversa_id="aluguel-03",
                    indice=0,
                    regra="perguntas",
                    medido=3,
                    texto="qual regiao? quantos quartos? e o prazo?",
                ),
            ],
            com_emoji=9,
            emojis=14,
        ),
    )

    assert "147 respostas do agente medidas" in texto
    assert "compra-01 turno 2: comprimento -- 812" in texto
    assert "aluguel-03 turno 0: perguntas -- 3" in texto
    assert "com emoji: 9 (14 no total)" in texto


def test_o_relatorio_diz_que_a_contagem_de_emoji_nao_e_criterio() -> None:
    """A ressalva tem de viajar junto do numero.

    Sem ela, `com emoji: 9` numa lista de metricas le como se 9 fosse erro --
    e a regra do card ("a informacao essencial nunca depende de emoji") nao e
    o que essa contagem mede.
    """
    texto = render(
        [],
        {},
        formato=ResumoDoFormato(respostas=10, violacoes=[], com_emoji=3, emojis=5),
    )

    assert "nao** entra na metrica" in texto


def test_relatorio_sem_formato_omite_a_secao() -> None:
    assert "Formato da resposta" not in render([], {})


def test_o_texto_da_violacao_viaja_junto_do_endereco() -> None:
    """Endereco sozinho nao diagnostica, e a primeira execucao provou.

    Em 31/08 sairam 26 violacoes de "uma pergunta", 24 com exatamente duas --
    e nao havia como saber se eram duas perguntas de verdade ou erro do proxy
    de `?`. Descobrir exigiria outra execucao paga. Mesma licao que
    `Discrepancia` ja carregava ao guardar `esperado` e `obtido` crus.
    """
    texto = render(
        [],
        {},
        formato=ResumoDoFormato(
            respostas=1,
            violacoes=[
                ViolacaoDeFormato(
                    conversa_id="investimento-03",
                    indice=0,
                    regra="perguntas",
                    medido=2,
                    texto="voce ja investe em imoveis? qual valor pretende aplicar?",
                )
            ],
            com_emoji=0,
            emojis=0,
        ),
    )

    assert "investimento-03 turno 0: perguntas -- 2" in texto
    assert "voce ja investe em imoveis? qual valor pretende aplicar?" in texto


def test_relatorio_ordena_a_insistencia_do_pior_para_o_menos_grave() -> None:
    """Tres turnos seguidos e pior que dois, e a lista pode ficar longa.

    Quem abre o relatorio tem de ver o caso grave antes de rolar -- mesma
    razao pela qual a secao da conta aberta vem antes das discrepancias.
    """
    texto = render(
        [],
        {},
        insistencia=ResumoDeInsistencia(
            conversas=53,
            insistencias=[
                Insistencia(conversa_id="compra-14", campo="regiao", turnos=(0, 1, 2)),
                Insistencia(conversa_id="compra-13", campo="quartos", turnos=(0, 1)),
            ],
        ),
    )

    assert "compra-14: regiao -- turnos 0, 1, 2" in texto
    assert "compra-13: quartos -- turnos 0, 1" in texto
    assert texto.index("compra-14") < texto.index("compra-13")


def test_a_secao_de_insistencia_distingue_conversas_de_ocorrencias() -> None:
    """Um lead incomodado em dois campos e UMA conversa, nao duas.

    Sem a distincao, o numero da secao inflaria com campos e sugeriria mais
    leads afetados do que existem.
    """
    texto = render(
        [],
        {},
        insistencia=ResumoDeInsistencia(
            conversas=53,
            insistencias=[
                Insistencia(conversa_id="compra-14", campo="regiao", turnos=(0, 1)),
                Insistencia(conversa_id="compra-14", campo="vagas", turnos=(0, 1)),
            ],
        ),
    )

    assert "perguntado mais de uma vez: 1" in texto


def test_relatorio_sem_insistencia_omite_a_secao() -> None:
    assert "Insistencia" not in render([], {})


def _invencao(indice: int, *divergencias: Divergencia) -> InvencaoObservada:
    return InvencaoObservada(conversa_id="compra-07", indice=indice, divergencias=divergencias)


def test_a_secao_de_ancoragem_diz_quais_turnos_inventaram() -> None:
    """A pergunta que ate a TEC-270 custava outra execucao paga.

    Em 10/09/2026 duas execucoes do gate deram 1/147 e 0/145, e a segunda nao
    pode confirmar nem refutar a primeira: o turno que citou sem base podia
    estar na conversa que a infraestrutura derrubou, e nao havia como saber
    qual era.
    """
    texto = render(
        [],
        {},
        invencao=ResumoDaInvencao(
            respostas=147,
            turnos=[
                _invencao(3, Divergencia(tipo="preco", citado="R$ 1.250.000")),
                _invencao(8, Divergencia(tipo="codigo", citado="AP-9999")),
            ],
        ),
    )

    assert "## Ancoragem: turnos que citaram sem base (diagnostico)" in texto
    assert "turnos com cifra ou codigo sem base: 2" in texto
    assert "compra-07 turno 3: preco -- R$ 1.250.000" in texto
    assert "compra-07 turno 8: codigo -- AP-9999" in texto


def test_a_execucao_limpa_tambem_produz_a_secao() -> None:
    """Secao que some quando esta tudo bem treina o leitor a nao procura-la.

    E o mesmo argumento pelo qual `ResumoDaInvencao` carrega `respostas`: sem
    o total nao daria para escrever o zero com denominador.
    """
    texto = render([], {}, invencao=ResumoDaInvencao(respostas=145, turnos=[]))

    assert "## Ancoragem: turnos que citaram sem base (diagnostico)" in texto
    assert "turnos com cifra ou codigo sem base: 0" in texto
    assert "145 turnos medidos" in texto


def test_sem_medicao_nenhuma_a_secao_nao_aparece() -> None:
    """`None` e "nao houve medicao", e nao "deu zero" -- sao estados distintos."""
    assert "Ancoragem" not in render([], {})


def test_a_prosa_do_turno_nao_entra_no_relatorio() -> None:
    """A regra da TEC-161, aplicada ao artefato em vez de ao log.

    Registrar a prosa barrada recria no relatorio exatamente aquilo que a
    guarda impediu de sair. Hoje `InvencaoObservada` nem carrega o texto,
    entao isto e impossivel por construcao -- e este teste existe para que
    continue sendo: quem acrescentar o campo um dia vai ter de decidir
    conscientemente renderiza-lo, contra um teste vermelho.

    Difere da secao vizinha de propósito: `_secao_de_formato` IMPRIME o texto
    da violacao, porque sem ele nao da para separar duas perguntas de verdade
    de erro do proxy de `?`. La o texto e a unica coisa que diagnostica; aqui
    o tipo e o valor citado ja diagnosticam sozinhos.
    """
    sentinela = "SENTINELA-PROSA o apartamento sai por R$ 1.250.000"
    texto = render(
        [],
        {},
        invencao=ResumoDaInvencao(
            respostas=1,
            turnos=[_invencao(0, Divergencia(tipo="preco", citado="R$ 1.250.000"))],
        ),
    )

    assert sentinela not in texto
    assert "SENTINELA-PROSA" not in texto


def test_o_valor_citado_sai_legivel_e_nao_em_centavos() -> None:
    """D10 da TEC-161, herdada: `citado` ja chega formatado de `citacao.py`.

    `_mascarar_digitos` (app/logging.py) come corridas de 10 a 15 digitos, e
    R$ 10 milhoes em centavos sao exatamente dez. O relatorio nao reformata
    nada -- so nao pode desfazer o que a origem ja fez, e esta asserta e o
    que denuncia quem um dia trocar `citado` pelo inteiro cru.
    """
    texto = render(
        [],
        {},
        invencao=ResumoDaInvencao(
            respostas=1,
            turnos=[_invencao(0, Divergencia(tipo="preco", citado="R$ 10.000.000"))],
        ),
    )

    assert "R$ 10.000.000" in texto
    assert "1000000000" not in texto


def test_um_turno_com_duas_divergencias_rende_duas_linhas() -> None:
    """Um turno que inventou preco E codigo mostra os dois.

    A metrica conta o turno uma vez -- o lead vive o turno --, mas o
    diagnostico precisa das duas, senao quem le conserta metade.
    """
    texto = render(
        [],
        {},
        invencao=ResumoDaInvencao(
            respostas=10,
            turnos=[
                _invencao(
                    2,
                    Divergencia(tipo="preco", citado="R$ 700.000"),
                    Divergencia(tipo="codigo", citado="AP-0001"),
                )
            ],
        ),
    )

    assert "compra-07 turno 2: preco -- R$ 700.000" in texto
    assert "compra-07 turno 2: codigo -- AP-0001" in texto
    assert "turnos com cifra ou codigo sem base: 1" in texto
