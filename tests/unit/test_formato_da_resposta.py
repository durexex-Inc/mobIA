from mobia.domain.agente.formato import (
    MAX_CARACTERES_POR_MENSAGEM,
    quebrar_em_mensagens,
)


def test_texto_curto_sai_inteiro_numa_parte_so() -> None:
    """O caminho de 99% dos turnos. Uma regressao aqui trocaria o comum pelo
    raro -- todo lead passaria a receber duas mensagens para caber o 1 em 10
    que estoura.
    """
    assert quebrar_em_mensagens("Oi! Em qual regiao voce procura?") == (
        "Oi! Em qual regiao voce procura?",
    )


def test_texto_no_limite_exato_nao_quebra() -> None:
    """O empate nao fica ao acaso: exatamente 600 ainda cabe numa mensagem.
    A TEC-229 existe porque um teste de janela se apoiou em empate exato.
    """
    texto = "a" * MAX_CARACTERES_POR_MENSAGEM
    assert quebrar_em_mensagens(texto) == (texto,)


def test_quebra_na_fronteira_de_frase() -> None:
    """Corta onde o leitor ja pararia. Quebrar no meio de uma frase entrega
    duas mensagens que so fazem sentido juntas, que e pior que uma longa.
    """
    primeira = "Encontrei tres opcoes no centro. " * 18  # ~594 chars
    segunda = "Quer que eu detalhe alguma?"
    partes = quebrar_em_mensagens(primeira + segunda)

    assert len(partes) == 2
    assert partes[0].endswith(".")
    assert partes[1] == segunda


def test_sem_fronteira_de_frase_cai_para_fronteira_de_palavra() -> None:
    """Um paragrafo unico e longo nao tem ponto final para cortar. Cortar no
    meio da palavra pareceria bug ao lead -- o mesmo argumento que
    `_prosa_que_cabe` ja usa em `apresentacao.py`.
    """
    partes = quebrar_em_mensagens("palavra " * 100)

    assert len(partes) == 2
    assert not partes[0].endswith("palavr")
    assert partes[0].endswith("palavra")


def test_nada_se_perde_nunca() -> None:
    """A invariante da D2, e a razao de nao cortarmos o excedente: o lead
    nunca perde, sem saber, conteudo que o agente tinha a dizer.
    """
    for texto in (
        "curto",
        "a" * 599,
        "a" * 600,
        "a" * 601,
        "frase. " * 200,
        "palavra " * 400,
    ):
        assert "".join(quebrar_em_mensagens(texto)).replace(" ", "") == texto.replace(" ", "")


def test_acima_de_1200_a_segunda_parte_estoura_e_isso_e_deliberado() -> None:
    """Degradacao declarada (D2). Entre perder conteudo, estourar o teto de
    duas mensagens da emenda E-02 -- clausula da MESMA regra -- e entregar uma
    segunda mensagem longa, a terceira e a menos ruim. O gate continua
    contando o excedente.
    """
    partes = quebrar_em_mensagens("frase curta. " * 200)

    assert len(partes) == 2
    assert len(partes[1]) > MAX_CARACTERES_POR_MENSAGEM


def test_segunda_parte_vazia_apos_strip_colapsa_para_uma_mensagem_so() -> None:
    """Artefato comum de saida de LLM: um `\\n` final sozinho depois do ponto.

    Sem o colapso, a funcao devolveria `(conteudo, '')` -- duas partes de
    nome, mas so uma com conteudo. A Task 3 pareia cada parte com um `kind` e
    despacha as duas como mensagem; a segunda vazia viraria envio em branco ao
    lead, com reserva gravada em `outbound_dispatches` para nada.
    """
    conteudo = "a" * (MAX_CARACTERES_POR_MENSAGEM - 1) + "."
    texto = conteudo + "\n"

    assert quebrar_em_mensagens(texto) == (conteudo,)


def test_primeira_parte_vazia_apos_strip_colapsa_para_uma_mensagem_so() -> None:
    """Gemeo do teste da segunda parte vazia (Important 1, revisao final da
    TEC-140). Uma resposta comecando com quebra de linha faz a ULTIMA
    fronteira de frase dentro dos 600 primeiros caracteres ser um `\\n` sem
    nada alem de espaco antes dele -- a primeira parte sai vazia depois do
    strip().

    Sem o colapso, `quebrar_em_mensagens` devolveria `("", "a"*700)`: a Task 3
    despacharia a primeira parte como `{"texto": ""}`, o adaptador devolveria
    4xx (`EnvioRecusado`), e como NENHUMA parte teria saido ainda a excecao
    subiria crua -- o turno inteiro (as 700 letras incluidas) se perderia como
    "sem_resposta".
    """
    conteudo = "a" * 700
    texto = "\n\n" + conteudo

    assert quebrar_em_mensagens(texto) == (conteudo,)


def test_quebra_de_paragrafo_e_fronteira_de_frase() -> None:
    """`\\n` conta como fronteira de frase tanto quanto pontuacao -- nenhum
    dos seis testes originais cobria esse ramo.

    A quebra de paragrafo dupla (`\\n\\n`) fica entre as duas partes. O
    `strip()` da ponta come as DUAS quebras de linha contiguas, nao so a que
    decidiu o corte -- isso nao perde conteudo, porque linha em branco nao e
    conteudo, mas so a asercao com normalizacao que tambem desconta `\\n`
    prova essa invariante: `replace(" ", "")` sozinho, como em
    `test_nada_se_perde_nunca`, e frouxo demais aqui e passaria mesmo se a
    funcao perdesse as quebras de linha do meio do texto.
    """
    primeira = "a" * 550 + "."
    segunda = "b" * 100
    texto = primeira + "\n\n" + segunda

    partes = quebrar_em_mensagens(texto)

    assert len(partes) == 2
    assert partes[0] == primeira
    assert partes[1] == segunda

    sem_espaco_e_quebra = "".join(partes).replace(" ", "").replace("\n", "")
    assert sem_espaco_e_quebra == texto.replace(" ", "").replace("\n", "")


def test_o_primeiro_kind_continua_sendo_reply() -> None:
    """`outbound_dispatches` ja tem linhas gravadas com "reply", e varios
    testes afirmam `_kinds_reservados() == ["reply"]`. Renomear o primeiro
    kind invalidaria as duas coisas para ganhar nada.
    """
    from mobia.domain.agente.turno import KIND_DA_RESPOSTA, KINDS_DA_RESPOSTA

    assert KINDS_DA_RESPOSTA[0] == KIND_DA_RESPOSTA == "reply"


def test_os_dois_kinds_sao_distintos_e_nao_colidem_com_os_vizinhos() -> None:
    """A UNIQUE (message_id, kind) e o que torna o reprocessamento seguro. Dois
    kinds iguais no mesmo turno fariam a SEGUNDA mensagem ser suprimida como
    reentrega -- o lead receberia metade da resposta, em silencio, e o log
    diria que estava tudo certo.
    """
    from mobia.domain.agente.turno import KINDS_DA_RESPOSTA, KINDS_DAS_FICHAS
    from mobia.domain.optout.deteccao import KIND_DA_CONFIRMACAO_DE_OPTOUT

    assert len(set(KINDS_DA_RESPOSTA)) == len(KINDS_DA_RESPOSTA)
    assert not set(KINDS_DA_RESPOSTA) & set(KINDS_DAS_FICHAS)
    assert KIND_DA_CONFIRMACAO_DE_OPTOUT not in KINDS_DA_RESPOSTA


def test_toda_constante_de_texto_fixo_cabe_numa_mensagem() -> None:
    """As tres trilhas de `_entregar_texto_fixo` NAO passam pela quebra (D1):
    aqueles textos sao constantes deste repositorio, escolhidas curtas de
    proposito. Este teste existe para que uma constante longa escrita no futuro
    reprove aqui, e nao chegue ao lead sem guarda nenhuma -- quem a escrevesse
    nao teria motivo para saber que aquele caminho e desguarnecido.
    """
    from mobia.domain.agente.identificacao import TEXTO_DA_IDENTIFICACAO
    from mobia.domain.agente.turno import TEXTO_DA_BUSCA_INCONCLUSIVA
    from mobia.domain.moderacao.port import (
        TEXTO_DA_RECUSA_DE_ENTRADA,
        TEXTO_NEUTRO_DE_SAIDA,
    )
    from mobia.domain.optout.deteccao import TEXTO_DA_CONFIRMACAO_DE_OPTOUT

    for constante in (
        TEXTO_DA_IDENTIFICACAO,
        TEXTO_DA_BUSCA_INCONCLUSIVA,
        TEXTO_DA_RECUSA_DE_ENTRADA,
        TEXTO_NEUTRO_DE_SAIDA,
        TEXTO_DA_CONFIRMACAO_DE_OPTOUT,
    ):
        assert 0 < len(constante) <= MAX_CARACTERES_POR_MENSAGEM
