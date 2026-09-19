"""A guarda que manda o lead para uma pessoa, testada.

TEC-143. Pura: nao toca banco, nao toca modelo. A decisao de transferir nao
pode depender de um provedor estar de pe, pelo mesmo motivo que a de opt-out
nao pode -- ver `domain/optout/deteccao.py`.
"""

from datetime import UTC, datetime

import pytest

from mobia.app.config import get_settings
from mobia.domain.humano.deteccao import (
    TEXTO_DO_PEDIDO_DE_HUMANO,
    TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO,
    dentro_da_janela_de_atendimento,
    pediu_humano,
)


@pytest.mark.parametrize(
    "texto",
    [
        "quero falar com uma pessoa",
        "Quero Falar Com Uma Pessoa!",
        "me passa pra um atendente por favor",
        "prefiro falar com um humano",
        "queria falar com atendente",
        "quero atendimento humano",
        "cansei de robo, quero uma pessoa",
    ],
)
def test_pedido_explicito_dispara(texto: str) -> None:
    assert pediu_humano(texto) is True


@pytest.mark.parametrize(
    "texto",
    [
        # Os dois casos reais do corpus de evals, ambos sobre assinar a
        # distancia. Medido na TEC-143: "pessoa" aparece 2 vezes nas 147
        # mensagens do corpus, as duas dentro de "pessoalmente".
        "consigo fechar tudo a distancia, sem vir pessoalmente antes?",
        "precisa vir pessoalmente pra assinar ou consigo por procuracao?",
        # O corretor como ASSUNTO, nao como pedido de transferencia.
        "o corretor falou que tem vaga dupla",
        "depois eu falo com o corretor sobre o financiamento",
        # Qualificacao normal.
        "quero um apartamento de dois quartos em Pinheiros",
        "",
    ],
)
def test_conversa_normal_nao_dispara(texto: str) -> None:
    assert pediu_humano(texto) is False


def test_pessoa_sozinha_nao_e_pedido() -> None:
    """A armadilha analoga a do opt-out, e a razao de nenhum termo ser palavra solta.

    `domain/optout/deteccao.py` registra que "nao quero mais receber nada" saiu
    dos inequivocos porque "nada" aceita complemento partitivo. Aqui o termo
    perigoso e "pessoa": casado por substring ele pega "pessoalmente", que no
    corpus aparece so em pergunta sobre procuracao. Todo termo desta lista
    carrega o verbo ou a preposicao que o torna um pedido.
    """
    assert pediu_humano("pessoa") is False
    assert pediu_humano("vou pessoalmente ver o imovel") is False


@pytest.mark.parametrize("texto", ["atendente", "Atendente?", "humano"])
def test_termo_ambiguo_so_casa_a_mensagem_inteira(texto: str) -> None:
    """Mesma faixa estrita do opt-out: sozinho e pedido, no meio de frase nao.

    Um lead que escreve so "atendente" esta pedindo. O mesmo substantivo dentro
    de "o atendente anterior me falou outro valor" e assunto.
    """
    assert pediu_humano(texto) is True
    assert pediu_humano("o atendente anterior me falou outro valor") is False


@pytest.mark.parametrize(
    "texto",
    [
        # Pessoa fisica vs juridica e vocabulario de contrato imobiliario, nao
        # pedido de transferencia. Foi o que tirou "quero uma pessoa" da lista.
        "quero uma pessoa fisica no contrato, nao pessoa juridica",
        "pode ser em nome de pessoa juridica? quero uma pessoa juridica",
        # Comentario sobre o atendimento de OUTRA empresa. Foi o que tirou
        # "atendimento humano" bare.
        "o atendimento humano la na outra imobiliaria era horrivel",
        # Verbo sem objeto, numa conversa sobre pagamento.
        "me transfere o comprovante do pix por favor",
        # A terceira porta da mesma colisao, achada na re-revisao: o objeto
        # existia ("uma pessoa") mas estava nu. Transferir titularidade para
        # uma PJ e assunto de contrato, nao pedido de atendimento.
        "pode me transfere pra uma pessoa juridica, quero mudar o titular",
    ],
)
def test_vocabulario_de_contrato_e_de_pagamento_nao_dispara(texto: str) -> None:
    """Os falsos positivos que as revisoes da TEC-143 acharam, fixados.

    A colisao com "pessoa" tem multiplas portas: "quero uma pessoa" (round 1),
    "me transfere pra uma pessoa" (round 2), resolvidas pelo invariante: quando
    pessoa/humano ocupam papel de DESTINO, carregam qualificador (pessoa fisica/
    juridica e vocabulario de contrato). Quando ocupam papel de INTERLOCUTOR ou
    ATRIBUTO, nao carregam. O modulo de opt-out registra a mesma licao com
    "nada" -- termo curto demais casa dentro de frase que nao e pedido.
    """
    assert pediu_humano(texto) is False


def test_a_forma_com_objeto_continua_disparando() -> None:
    assert pediu_humano("quero uma pessoa de verdade, nao um robo") is True
    assert pediu_humano("me transfere pra um atendente") is True
    assert pediu_humano("quero atendimento humano") is True


def test_falar_com_uma_pessoa_juridica_dispara_e_isso_e_aceito() -> None:
    """O residual que o invariante deixa de pe, declarado em vez de escondido.

    "pessoa" como INTERLOCUTOR nao leva qualificador, porque "falar com" ja a
    desambigua -- e sem isso "quero falar com uma pessoa", a frase do criterio
    de aceite da card, deixaria de disparar. O preco e este caso: quem pergunta
    sobre PJ usando "falar com" vai para um humano. Erra na direcao barata,
    porque quem pergunta assim provavelmente quer mesmo falar com alguem.
    """
    assert pediu_humano("posso falar com uma pessoa juridica sobre esse contrato?") is True


@pytest.mark.parametrize(
    "texto",
    [
        "nao quero falar com atendente, so me manda os imoveis",
        "nao precisa falar com um humano, resolvo por aqui",
        "nao queria falar com uma pessoa agora, depois eu vejo",
        # A negacao vale mesmo com o verbo DENTRO do termo: aqui o prefixo e
        # so "nao ", porque "quero" e a primeira palavra de
        # "quero uma pessoa de verdade".
        "nao quero uma pessoa de verdade, o robo resolve",
        # Sujeito antes da negacao nao a desfaz.
        "eu nao quero falar com atendente",
    ],
)
def test_negacao_imediata_nao_dispara(texto: str) -> None:
    """Important 4 da revisao final. O invariante dos tres papeis nao olha polaridade.

    As duas primeiras frases DISPARAVAM -- conferido rodando antes do fix. O
    argumento do desenho para aceitar falso positivo ("errar por sobra manda o
    lead para um humano, que e o destino que ele teria de qualquer forma") nao
    cobre este caso: aqui o lead disse o contrario, e o preco nao e uma
    transferencia a mais -- e o agente calar para sempre numa conversa que o
    lead quis seguir com o robo.

    Repare que nenhuma destas tem pontuacao entre o "nao" e o pedido: e esse o
    sinal que separa a recusa do contraste ("Nao, quero falar com atendente"),
    e `test_nao_de_contraste_nao_e_negacao_do_pedido` cobre o outro lado.
    """
    assert pediu_humano(texto) is False


def test_a_negacao_sobre_o_robo_continua_disparando() -> None:
    """A guarda de negacao nao pode matar "nao quero falar com robo".

    Ali a negacao e sobre o ROBO, nao sobre o humano -- e a frase e um pedido
    de transferencia, nao a recusa de um. O termo INTEIRO esta na lista de
    inequivocos e casa no comeco da mensagem, sem prefixo nenhum para a guarda
    olhar; e essa a razao de ela so olhar o que vem IMEDIATAMENTE antes do
    termo casado.
    """
    assert pediu_humano("nao quero falar com robo") is True
    assert pediu_humano("ja falei, nao quero falar com robo") is True


def test_duvida_no_meio_nao_e_negacao() -> None:
    """So nega o que esta imediatamente antes. Palavra no meio devolve o caso a duvida.

    "nao sei se quero falar com uma pessoa" nao e uma recusa -- e uma duvida,
    e ali o desenho vale: errar por sobra manda o lead para um humano.
    """
    assert pediu_humano("nao sei se quero falar com uma pessoa") is True
    assert pediu_humano("nao aguento mais robo, quero falar com uma pessoa") is True


def test_uma_ocorrencia_limpa_basta() -> None:
    """A guarda percorre todas as ocorrencias, nao so a primeira.

    Parar na primeira transformaria a guarda de negacao numa guarda de ordem
    das frases: quem nega e depois pede continuaria sem ser transferido.
    """
    texto = "nao quero falar com atendente agora, mas amanha quero falar com atendente"
    assert pediu_humano(texto) is True


def test_o_interlocutor_de_terceiro_dispara_e_e_lacuna_declarada() -> None:
    """Important 5 da revisao final, fixado como LACUNA e nao como conserto.

    "falar com uma pessoa" e a frase literal do criterio de aceite da card;
    qualifica-la para exigir que o interlocutor seja nosso mataria o caso
    central. O preco e este: banco, cartorio, financiamento, familia e
    prefeitura disparam. Esta assercao existe para o dia em que alguem
    "consertar" isso descobrir que a decisao foi deliberada -- ver o quarto
    eixo do invariante em `deteccao.py` e as lacunas declaradas do desenho.
    """
    assert pediu_humano("preciso falar com uma pessoa do banco antes de fechar") is True
    assert pediu_humano("tenho que falar com uma pessoa do cartorio sobre a escritura") is True
    assert pediu_humano("vou falar com uma pessoa da minha familia e te retorno") is True


# `America/Sao_Paulo` e UTC-3 sem horario de verao desde 2019 (Brasil aboliu a
# troca), entao todo horario abaixo e o UTC do teste menos 3h -- conferido
# rodando, nao presumido. O default da janela e 9-18.
def test_a_janela_inclui_a_hora_de_abertura() -> None:
    """9h em ponto ja e atendimento, com o default de inicio 9."""
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 15, 12, 0, tzinfo=UTC)) is True


def test_fora_da_janela_de_madrugada() -> None:
    """As 23h de uma terca -- o cenario Gherkin da card."""
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 16, 2, 0, tzinfo=UTC)) is False


def test_a_janela_inclui_a_hora_de_fechamento() -> None:
    """19h em ponto ainda e atendimento -- fim e o ultimo MINUTO valido, nao a ultima hora.

    Mesma convencao de `followup_horario_fim`/`horario_permite_envio`: a borda
    de fim e inclusiva. 19:00 local = 22:00 UTC. O numero saiu de 18 para 19 na
    TEC-285; a convencao de borda nao mudou.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 15, 22, 0, tzinfo=UTC)) is True


def test_um_minuto_apos_o_fechamento_ja_e_fora() -> None:
    """19:01 local = 22:01 UTC recusa, e e essa recusa que a borda inclusiva de fim admite."""
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 15, 22, 1, tzinfo=UTC)) is False


def test_sabado_as_dezoito_e_meia_passou_a_ser_atendimento() -> None:
    """A mudanca de horas alcanca os seis dias, e nao so o domingo.

    18:30 de sabado ficava FORA da janela ate a TEC-285 (o fim era 18) e passa
    a ficar dentro. Esta escrito como teste porque e o tipo de consequencia que
    se descobre por acidente: a card fala de dia da semana, e o numero das
    horas mudou junto. 18:30 local = 21:30 UTC de 2026-09-19, sabado.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 19, 21, 30, tzinfo=UTC)) is True


def test_a_borda_de_minuto_vale_no_sabado_tambem() -> None:
    """O ultimo dia da janela nao ganha regra propria: 19:01 recusa no sabado como na terca.

    Existe porque a guarda de domingo e a checagem de hora sao dois eixos, e
    um deles roda antes do outro -- um corpo que devolvesse cedo por dia
    poderia, escrito errado, pular a borda no unico dia que faz fronteira com
    domingo. 19:01 local = 22:01 UTC de 2026-09-19, sabado.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 19, 22, 1, tzinfo=UTC)) is False


def test_domingo_dentro_do_intervalo_de_horas_recusa() -> None:
    """Domingo as 15h esta no meio do intervalo e fora do atendimento.

    E o caso que a TEC-285 existe para consertar: ate ela, o unico eixo era a
    hora, e domingo era dia util como qualquer outro. 15:00 local = 18:00 UTC
    de 2026-09-20, que e domingo -- conferido rodando, nao presumido.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 20, 18, 0, tzinfo=UTC)) is False


def test_sabado_dentro_do_intervalo_de_horas_aceita() -> None:
    """Sabado e dia de atendimento, e e a borda que separa "sem domingo" de "so dia util".

    Sem este teste, uma guarda que recusasse o fim de semana inteiro passaria
    igual -- o teste de domingo sozinho nao distingue as duas. 17:00 local =
    20:00 UTC de 2026-09-19, que e sabado.
    """
    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 19, 20, 0, tzinfo=UTC)) is True


def test_o_dia_e_lido_no_fuso_local_e_nao_em_utc(
    monkeypatch: pytest.MonkeyPatch, caches_de_cliente_limpos: None
) -> None:
    """O mesmo instante e sabado em UTC e domingo no fuso -- e o fuso e que manda.

    Com `America/Sao_Paulo` (UTC-3) esta distincao e inalcancavel: dentro da
    janela de 9h-19h local o dia coincide com o de UTC, entao uma
    implementacao que lesse `agora.weekday()` passaria por todos os outros
    testes deste arquivo. `Pacific/Tarawa` e UTC+12 fixo, sem horario de verao
    nunca, e faz 22:00 UTC de sabado virar 10:00 de DOMINGO local -- dentro do
    intervalo de horas, e portanto recusavel so pelo dia.

    Conferido rodando: `datetime(2026, 9, 19, 22, 0, tzinfo=UTC)` e sabado em
    UTC e domingo 10:00 em Tarawa.

    `caches_de_cliente_limpos` nao e enfeite: o docstring daquela fixture manda
    que todo teste que mexa em `Settings` dependa dela em vez de chamar
    `cache_clear()` na mao, senao um fuso do Pacifico vaza para o `Settings`
    cacheado de todo teste seguinte deste worker.
    """
    monkeypatch.setenv("FOLLOWUP_FUSO", "Pacific/Tarawa")
    get_settings.cache_clear()

    assert dentro_da_janela_de_atendimento(datetime(2026, 9, 19, 22, 0, tzinfo=UTC)) is False


def test_o_momento_ingenuo_continua_levantando() -> None:
    """A guarda de domingo nao pode engolir a excecao de `tzinfo` ausente.

    A ordem do corpo e que garante isso: `horario_permite_envio` roda PRIMEIRO
    e incondicionalmente, e e de la que a excecao vem. Uma implementacao que
    convertesse o fuso antes, para olhar o dia, faria um naive ser interpretado
    como hora do SISTEMA -- que difere entre esta maquina (UTC-3) e o runner do
    CI (UTC) -- e a excecao so apareceria em alguns dias da semana.
    """
    with pytest.raises(ValueError, match="tzinfo"):
        dentro_da_janela_de_atendimento(datetime(2026, 9, 20, 18, 0))


@pytest.mark.parametrize(
    "texto", [TEXTO_DO_PEDIDO_DE_HUMANO, TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO]
)
def test_o_texto_ao_lead_nao_promete_que_alguem_foi_avisado(texto: str) -> None:
    """Critical 3 da revisao final, e a mesma guarda que `test_notificacao_envio.py` ja tem.

    Criar handoff nao notifica ninguem: os dois adaptadores de
    `notificacao/canais.py` REGISTRAM e NAO ENTREGAM. As duas constantes
    diziam "Ja avisei nossa equipe" -- a TERCEIRA aparicao da frase no repo,
    depois de a TEC-174 ter reescrito "ja avisei um corretor" e de
    `notificacao/envio.py` ter escrito "Nao reintroduza a promessa". Esta
    assercao existe para nao haver uma quarta.
    """
    assert "avisei" not in texto.lower()
    assert "avisamos" not in texto.lower()


@pytest.mark.parametrize(
    "texto",
    [
        "Nao, quero falar com atendente",
        "nao, prefiro falar com um humano",
        "Nao. Quero falar com uma pessoa",
    ],
)
def test_nao_de_contraste_nao_e_negacao_do_pedido(texto: str) -> None:
    """O "nao" que nega o que veio ANTES, e nao o pedido que vem depois.

    "Nao, quero falar com atendente" e pedido: o lead esta negando seguir com o
    robo. A guarda de negacao introduzida contra "nao quero falar com atendente"
    matava estes tambem, porque o normalizador tira a virgula e as duas formas
    colapsam na mesma string. Falso negativo aqui e a direcao cara -- o lead pede
    e continua no loop.

    A assimetria era a pista de que a guarda acertava por acaso:
    "nao, prefiro falar com um humano" escapava (ha uma palavra a mais entre o
    "nao" e o termo) enquanto "Nao, quero falar com atendente" nao.
    """
    assert pediu_humano(texto) is True


def test_a_pausa_pode_partir_o_proprio_termo_e_o_lado_barato_e_disparar() -> None:
    """ "nao quero falar com robo" e termo inequivoco, e a pontuacao o parte em dois.

    Na normalizacao com pausa a frase vira "nao | quero falar com robo", e o
    termo deixa de ser encontrado ali -- a guarda nao tem como julgar negacao
    de um termo que ela nao acha. `_dispara` resolve pelo lado barato: o termo
    esta na string normalizada, entao dispara. Antes da pausa isto ja
    disparava, e nao podia parar de disparar por causa de um fix de negacao.
    """
    assert pediu_humano("Nao. Quero falar com robo") is True


@pytest.mark.parametrize(
    "texto",
    [
        "nao quero falar com atendente, so me manda os imoveis",
        "nao precisa falar com um humano",
        "nao precisa falar com um humano, resolvo por aqui",
    ],
)
def test_a_negacao_sem_pontuacao_continua_barrando(texto: str) -> None:
    """A re-revisao nao afrouxou a guarda -- ela so deixou de confundir os dois usos.

    Sem pontuacao entre o "nao" e o pedido, o "nao" nega o pedido: continua
    `False`. E a contraprova do teste de contraste acima; sem ela, "consertar"
    o contraste desligando a guarda inteira passaria despercebido.
    """
    assert pediu_humano(texto) is False
