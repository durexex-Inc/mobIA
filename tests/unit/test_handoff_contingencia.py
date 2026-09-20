from datetime import UTC, datetime

from mobia.domain.agente.schemas import (
    CategoriaDescarte,
    FormaPagamento,
    Intencao,
    TipoImovel,
    Urgencia,
)
from mobia.domain.handoff.contingencia import (
    TETO_CANAL,
    TETO_CODIGO,
    TETO_CONVERSA,
    TETO_ETIQUETA,
    TETO_FORMA_PAGAMENTO,
    TETO_GATILHO,
    TETO_INTENCAO,
    TETO_MOTIVO_DESCARTE,
    TETO_POR_LISTA_DE_ATENCAO,
    TETO_REGIAO,
    TETO_TIPO_IMOVEL,
    TETO_URGENCIA,
    TEXTO_DE_CONTINGENCIA,
    montar,
)
from mobia.domain.handoff.dossie import Dossie, ImovelApresentado
from mobia.domain.handoff.resumo import LIMITE_DE_CARACTERES, MARCADORES, validar
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, Gatilho

QUANDO = datetime(2026, 9, 12, 14, 30, tzinfo=UTC)


def _muitos_imoveis(quantos: int) -> tuple[ImovelApresentado, ...]:
    return tuple(
        ImovelApresentado(f"AP-{i:04d}", 50_000_000 + i, "venda", "GOSTOU", None)
        for i in range(quantos)
    )


def _dossie(**trocas: object) -> Dossie:
    base: dict[str, object] = {
        "canal": "whatsapp",
        "conversa": "5511911112222",
        "primeira_mensagem_em": QUANDO,
        "mensagens_do_lead": 12,
        "intencao": "COMPRA",
        "faixa_min_centavos": None,
        "faixa_max_centavos": 60_000_000,
        "regiao": "Pinheiros",
        "tipo_imovel": "APARTAMENTO",
        "quartos": 2,
        "vagas": 1,
        "urgencia": "ATE_3_MESES",
        "forma_pagamento": "FINANCIAMENTO",
        "tem_imovel_para_vender": False,
        "score_total": 72,
        "score_fatores": (("completude", 25), ("urgencia", 20)),
        "score_causas": ("CAMPOS_OBRIGATORIOS",),
        "temperatura": "QUENTE",
        "temperatura_forcada_motivos": (),
        "imoveis": (ImovelApresentado("AP-001", 58_000_000, "venda", "GOSTOU", None),),
        "campos_recusados": ("renda",),
        "perguntados_sem_resposta": ("prazo",),
        "gatilho": "LEAD_QUENTE",
        "etiqueta": "lead-quente",
        "prioridade": "NORMAL",
        "criado_em": QUANDO,
    }
    return Dossie(**(base | trocas))  # type: ignore[arg-type]


def _vazio() -> Dossie:
    """O quarto cenario: um lead de quem nao se sabe nada."""
    return _dossie(
        primeira_mensagem_em=None,
        mensagens_do_lead=0,
        intencao=None,
        faixa_max_centavos=None,
        regiao=None,
        tipo_imovel=None,
        quartos=None,
        vagas=None,
        urgencia=None,
        forma_pagamento=None,
        tem_imovel_para_vender=None,
        score_total=None,
        score_fatores=(),
        score_causas=(),
        temperatura=None,
        imoveis=(),
        campos_recusados=(),
        perguntados_sem_resposta=(),
    )


def test_um_campo_absurdamente_longo_e_truncado_e_nao_faz_montar_levantar() -> None:
    """Ate a revisao final da TEC-176, este teste provava o OPOSTO do que
    prova agora: que um valor impossivel de vir do banco (`regiao` com 2000
    de um `VARCHAR(120)` real) ainda fazia `montar` levantar. A docstring
    antiga chamava isso de pior caso "REALISTA -- respeitando os tamanhos de
    coluna do banco (regiao e VARCHAR(120), por exemplo)" e apontava para
    `test_o_pior_caso_combinado_ainda_cabe_no_limite` como quem provava que
    esse caso cabia -- so que aquele teste usava `regiao` com 47 de 120,
    nunca o maximo real da coluna. Quem lesse os dois testes juntos nao via
    a lacuna: `regiao=120` SOZINHO ja estourava (1521 de 1500), e foi essa
    lacuna que o Critical da revisao final encontrou. As medicoes viviam num
    comentario acima de `TETO_DE_IMOVEIS`, que a TEC-276 removeu junto com o
    teto fixo: hoje elas sao
    `test_o_pior_caso_do_banco_cabe_e_nao_levanta`, neste arquivo.

    A correcao (Critical 1a) deu teto a TODO campo de texto livre, nao so as
    listas. Consequencia: `montar` agora TRUNCA um valor absurdo em vez de
    deixa-lo estourar -- nao ha mais entrada, possivel ou impossivel de vir
    do banco, que faca `montar` levantar por tamanho. Este teste prova essa
    garantia, e nao mais o caminho antigo.
    """
    texto = montar(_dossie(regiao="x" * 2000))

    assert len(texto) <= LIMITE_DE_CARACTERES
    assert validar(texto)
    assert "x" * TETO_REGIAO in texto
    assert "x" * (TETO_REGIAO + 1) not in texto


def test_todo_campo_de_valor_unico_no_maximo_da_coluna_ainda_cabe() -> None:
    """Critical da revisao final (1a): o teste ao lado (o `_combinado`, mais
    abaixo) so nunca colocou TODOS os campos de valor unico no maximo da
    coluna ao mesmo tempo -- so variava `regiao`, e so ate 47 de 120. Este
    teste poe cada campo de valor unico (e os por-item de `imoveis`) no
    maior tamanho REAL que ele assume -- o da coluna quando o campo e texto
    livre, o do enum quando e um vocabulario fechado -- simultaneamente, e
    confere que `montar` ainda cabe. Os valores que NAO cabem deixaram de
    estar escritos em prosa na TEC-276 -- quem quiser o numero de hoje roda
    `test_o_pior_caso_do_banco_cabe_e_nao_levanta`.
    """
    muitos_imoveis = tuple(
        ImovelApresentado(
            "A" * TETO_CODIGO,
            50_000_000 + i,
            "aluguel",
            "SEM_RESPOSTA",
            "D" * TETO_MOTIVO_DESCARTE,
        )
        for i in range(40)
    )
    muitos_campos = tuple(f"recusado_{i:02d}".ljust(32, "x")[:32] for i in range(50))
    muitas_perguntas = tuple(f"pergunta_{i:02d}".ljust(32, "x")[:32] for i in range(50))

    texto = montar(
        _dossie(
            canal="c" * TETO_CANAL,
            conversa="k" * TETO_CONVERSA,
            intencao="i" * TETO_INTENCAO,
            regiao="r" * TETO_REGIAO,
            tipo_imovel="t" * TETO_TIPO_IMOVEL,
            urgencia="u" * TETO_URGENCIA,
            forma_pagamento="f" * TETO_FORMA_PAGAMENTO,
            imoveis=muitos_imoveis,
            campos_recusados=muitos_campos,
            perguntados_sem_resposta=muitas_perguntas,
            gatilho="g" * TETO_GATILHO,
            etiqueta="e" * TETO_ETIQUETA,
        )
    )

    assert len(texto) <= LIMITE_DE_CARACTERES
    assert validar(texto)


def test_o_sufixo_de_temperatura_forcada_e_o_mesmo_texto_literal() -> None:
    """Regressao do Critical da revisao: `renderizar` e `montar` reescreviam
    a mesma expressao ("(forcada por ...)") cada um por conta propria, sem
    teste nenhum que afirmasse o texto literal -- so o tamanho e o
    validar(). Depois da correcao os dois chamam `forcada_por` de
    `dossie.py`; este teste afirma o texto exato, para a proxima divergencia
    quebrar em vez de passar calada."""
    texto = montar(_dossie(temperatura_forcada_motivos=("PEDIU_VISITA", "FALOU_EM_PROPOSTA")))

    assert "temperatura: QUENTE (forcada por PEDIU_VISITA, FALOU_EM_PROPOSTA)" in texto


def test_o_pior_caso_combinado_ainda_cabe_no_limite() -> None:
    """D6, com os DOIS pontos que a revisao da Task 1 achou sem teto ao
    mesmo tempo: a lista de imoveis (ja tinha teto) E as duas listas do
    bloco de pontos de atencao (`campos_recusados`,
    `perguntados_sem_resposta`) -- que sao `ARRAY(String(32))` sem
    cardinalidade maxima no banco. Este e o pior caso plausivel que a coluna
    permite: 50 itens de 32 caracteres em cada lista, e 40 imoveis com a
    linha mais longa que `imoveis()` escreve."""

    def item_de_32_caracteres(prefixo: str, i: int) -> str:
        # 32 e o teto real da coluna (`ARRAY(String(32))`); o pior caso usa
        # o tamanho maximo que o banco aceita por item.
        return f"{prefixo}{i:02d}".ljust(32, "x")[:32]

    muitos_imoveis = tuple(
        ImovelApresentado(f"AP-{i:03d}", 50_000_000 + i, "aluguel", "DESCARTOU", "PRECO")
        for i in range(40)
    )
    prefixo_recusado = "recusado_"
    prefixo_pergunta = "pergunta_"
    muitos_campos = tuple(item_de_32_caracteres(prefixo_recusado, i) for i in range(50))
    muitas_perguntas = tuple(item_de_32_caracteres(prefixo_pergunta, i) for i in range(50))

    texto = montar(
        _dossie(
            imoveis=muitos_imoveis,
            regiao="Vila Madalena, Pinheiros, Perdizes e adjacencias",
            campos_recusados=muitos_campos,
            perguntados_sem_resposta=muitas_perguntas,
            score_fatores=(
                ("completude", 25),
                ("urgencia", 20),
                ("catalogo", 12),
                ("engajamento", 10),
                ("capacidade", 5),
            ),
            temperatura_forcada_motivos=("PEDIU_VISITA", "FALOU_EM_PROPOSTA"),
        )
    )

    assert len(texto) <= LIMITE_DE_CARACTERES
    assert validar(texto)
    assert "50 no total" in texto
    assert texto.count(prefixo_recusado) == TETO_POR_LISTA_DE_ATENCAO
    assert texto.count(prefixo_pergunta) == TETO_POR_LISTA_DE_ATENCAO


def test_o_template_se_identifica_como_tal() -> None:
    assert TEXTO_DE_CONTINGENCIA in montar(_dossie())


def test_o_template_cita_os_numeros_do_dossie() -> None:
    texto = montar(_dossie())

    assert "72" in texto
    assert "R$ 600.000" in texto
    assert "Pinheiros" in texto


def test_dossie_vazio_nao_inventa_objecao_nem_proxima_acao() -> None:
    """Quarto cenario do Gherkin, e a razao de existir da D4."""
    texto = montar(_vazio())

    assert validar(texto)
    assert "nenhum ponto de atencao registrado" in texto
    # O bloco da proxima acao apresenta FATOS -- gatilho, etiqueta, prioridade
    # --, nunca uma recomendacao. Recomendar e julgamento, e e o que o modelo
    # fazia.
    assert "LEAD_QUENTE" in texto
    assert "recomend" not in texto.lower()


def test_dossie_vazio_nao_escreve_None_em_lugar_nenhum() -> None:
    assert "None" not in montar(_vazio())


def test_a_lista_de_imoveis_diz_o_total_mesmo_cortando() -> None:
    """D6: o template cabe nos 1.500 por construcao, nao por truncamento.

    O corte existe -- 300 imoveis nao cabem em 1.500 caracteres --, mas o
    corretor sempre ve QUANTOS existem, e nao so os que couberam. Desde a
    TEC-276 quantos cabem depende do resto do dossie, entao a asserta e
    sobre a relacao (cortou, e disse o total), nao sobre um numero fixo.
    """
    texto = montar(_dossie(imoveis=_muitos_imoveis(300)))

    assert "300 no total" in texto
    assert 0 < texto.count("AP-") < 300
    assert len(texto) <= LIMITE_DE_CARACTERES


def test_a_lista_de_imoveis_mostra_os_mais_recentes_do_mais_novo_ao_mais_antigo() -> None:
    """Important 3 da revisao final. `carregar_dossie` ordena por
    `apresentado_em` ASCENDENTE (`repositorio.py`), e ate a correcao
    `imoveis()` fazia `dossie.imoveis[:teto]` -- os PRIMEIROS da lista, ou
    seja, os mais VELHOS. A D6 do desenho pede o oposto, com exemplo
    literal: "30 imoveis apresentados, os 5 mais recentes". Este teste prova
    que os mostrados sao os ULTIMOS da lista (os mais recentes) e aparecem
    do mais novo para o mais antigo -- ver o porque dessa ordem no docstring
    de `dossie.imoveis`. QUANTOS sao passou a ser do orcamento (TEC-276);
    quais, continua sendo regra.
    """
    imoveis_em_ordem_de_apresentacao = _muitos_imoveis(40)
    texto = montar(_dossie(imoveis=imoveis_em_ordem_de_apresentacao))

    codigos_no_texto = [
        linha.split(",")[0].removeprefix("- ")
        for linha in texto.splitlines()
        if linha.startswith("- AP-")
    ]
    # Quantos cabem e do orcamento (TEC-276); QUAIS cabem continua sendo
    # regra -- os mais recentes, do mais novo para o mais antigo. O teste
    # deriva a quantidade do proprio texto para nao voltar a prender um
    # numero que o orcamento decide.
    quantos_couberam = len(codigos_no_texto)
    mais_recentes_do_mais_novo_ao_mais_antigo = list(
        reversed(imoveis_em_ordem_de_apresentacao[-quantos_couberam:])
    )

    assert quantos_couberam > 2
    assert codigos_no_texto == [i.codigo for i in mais_recentes_do_mais_novo_ao_mais_antigo]


def test_um_dossie_grande_ainda_cabe_no_limite() -> None:
    """O caso ruim inteiro: todo campo preenchido e a lista estourada."""
    muitos = tuple(
        ImovelApresentado(f"AP-{i:03d}", 50_000_000 + i, "aluguel", "DESCARTOU", "PRECO")
        for i in range(40)
    )
    texto = montar(
        _dossie(
            imoveis=muitos,
            regiao="Vila Madalena, Pinheiros, Perdizes e adjacencias",
            campos_recusados=("renda", "profissao", "estado civil"),
            perguntados_sem_resposta=("prazo", "entrada", "financiamento aprovado"),
            score_fatores=(
                ("completude", 25),
                ("urgencia", 20),
                ("catalogo", 12),
                ("engajamento", 10),
                ("capacidade", 5),
            ),
            temperatura_forcada_motivos=("PEDIU_VISITA", "FALOU_EM_PROPOSTA"),
        )
    )

    assert len(texto) <= LIMITE_DE_CARACTERES
    assert validar(texto)


def test_os_seis_marcadores_estao_na_ordem() -> None:
    texto = montar(_dossie())
    posicoes = [texto.find(m) for m in MARCADORES]

    assert all(p >= 0 for p in posicoes)
    assert posicoes == sorted(posicoes)


def _maior_membro(enum: type) -> str:
    """O membro de maior `value` -- o pior caso de um vocabulario fechado."""
    return max((m.value for m in enum), key=len)


def _pior_caso_do_banco(*, imoveis_no_dossie: int = 40, itens_por_lista: int = 50) -> Dossie:
    """O dossie mais longo que as COLUNAS conseguem produzir. TEC-276.

    Derivado dos `TETO_*` que o proprio modulo calcula, e nao de literais
    escolhidos a mao -- e essa derivacao que torna a medicao reproduzivel:
    quem alargar `LeadQualification.regiao` para `String(200)` muda este
    pior caso junto, sem editar uma linha daqui. Foi a falta disso que
    produziu as tres medicoes discordantes que a TEC-276 encontrou (a
    tabela do codigo dizia 1452, a revisao da TEC-176 dizia outra coisa, e a
    reconstrucao desta card mediu 1425).

    `ARRAY(String(32))` nao tem cardinalidade maxima no banco: 50 itens de
    32 caracteres e o pior caso plausivel, nao um limite da coluna.
    """
    return _dossie(
        canal="w" * TETO_CANAL,
        conversa="9" * TETO_CONVERSA,
        intencao=_maior_membro(Intencao),
        regiao="R" * TETO_REGIAO,
        tipo_imovel=_maior_membro(TipoImovel),
        urgencia=_maior_membro(Urgencia),
        forma_pagamento=_maior_membro(FormaPagamento),
        faixa_min_centavos=99_999_999_999,
        faixa_max_centavos=99_999_999_999,
        quartos=99,
        vagas=99,
        mensagens_do_lead=999,
        score_total=100,
        score_fatores=(("completude", 25), ("urgencia", 20), ("engajamento", 15)),
        temperatura_forcada_motivos=("PEDIU_VISITA", "FALOU_EM_PROPOSTA"),
        imoveis=tuple(
            ImovelApresentado(
                "C" * TETO_CODIGO,
                99_999_999_999,
                "aluguel",
                "DESCARTOU",
                _maior_membro(CategoriaDescarte),
            )
            for _ in range(imoveis_no_dossie)
        ),
        campos_recusados=tuple("r" * 32 for _ in range(itens_por_lista)),
        perguntados_sem_resposta=tuple("p" * 32 for _ in range(itens_por_lista)),
        gatilho=_maior_membro(Gatilho),
        etiqueta=max(ETIQUETA_DE.values(), key=len),
    )


def test_o_pior_caso_do_banco_cabe_e_nao_levanta() -> None:
    """A garantia da RN-15.2 para qualquer entrada que o banco produza.

    Substitui a tabela de folgas que vivia em comentario acima do antigo
    `TETO_DE_IMOVEIS`: ela nao era reproduzivel -- tres pessoas a
    re-derivaram e acharam tres numeros -- e nenhum deles sobrevivia a uma
    palavra acrescentada a um bloco. Aqui a garantia e do algoritmo: o texto
    e medido antes de sair.
    """
    texto = montar(_pior_caso_do_banco())

    assert len(texto) <= LIMITE_DE_CARACTERES
    assert validar(texto)


def test_o_lead_tipico_ve_muito_mais_do_que_dois_imoveis() -> None:
    """O que a TEC-276 comprou, e por que ela existe.

    Ate aqui o teto era fixo em 2, dimensionado para o pior caso do banco --
    e um lead real gastava 923 dos 1.500 caracteres, deixando 577 de
    contexto na mesa no dia ruim, que e justamente quando este modo entra.

    A asserta e contra DOIS, e nao contra o numero que hoje cabe (17):
    fixar 17 faria este teste reprovar na primeira palavra acrescentada a um
    bloco, que e exatamente o acoplamento que a card removeu.
    """
    texto = montar(_dossie(imoveis=_muitos_imoveis(30)))

    assert texto.count("AP-") > 2
    assert len(texto) <= LIMITE_DE_CARACTERES


def test_o_custo_da_busca_acompanha_o_orcamento_e_nao_o_dossie() -> None:
    """Duzentos imoveis no dossie nao custam duzentas montagens.

    A busca sobe do zero e para no primeiro que estoura, entao o numero de
    montagens e limitado pelo ORCAMENTO -- uma linha de imovel nao tem menos
    de ~30 caracteres, logo nunca ha mais de ~40 candidatas -- e nao pelo
    tamanho do dossie. Descendo do topo, um dossie de 200 imoveis gastaria
    ~17 ms em candidatas que estouram (medido: 0,084 ms por montagem).
    """
    texto = montar(_dossie(imoveis=_muitos_imoveis(200)))

    assert len(texto) <= LIMITE_DE_CARACTERES
    assert "200 no total" in texto
