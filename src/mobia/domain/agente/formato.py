"""Quebra a resposta do agente em ate duas mensagens de texto. TEC-140.

Puro de proposito: sem I/O, sem banco, sem chamada ao modelo -- mesma forma de
`dinheiro.py` e `apresentacao.py`. Quebrar a resposta e decisao de formato, e
nao de conteudo, entao nao ha por que este modulo tocar o classificador ou o
catalogo.

**Por que a segunda parte pode estourar 600 caracteres.** A RN-04.2 carrega
tres clausulas, e duas delas competem acima de ~1.200 caracteres: no maximo
`MAX_CARACTERES_POR_MENSAGEM` por mensagem, e no maximo
`MAX_MENSAGENS_DE_TEXTO` mensagens consecutivas (esta ultima, a emenda E-02 da
mesma regra). Um texto de 1.500 caracteres nao cabe em duas mensagens de 600
sem perder 300 caracteres em algum lugar. As tres saidas possiveis sao cortar
o excedente, abrir uma terceira mensagem, ou deixar a segunda passar do teto:

- Cortar descarta conteudo que o agente tinha a dizer, e o lead nunca fica
  sabendo que faltou pedaco -- e o desenho (D2) recusa isso de proposito, e
  `test_nada_se_perde_nunca` e a prova em codigo dessa recusa.
- Uma terceira mensagem cumpre o limite de 600 mas viola a OUTRA clausula da
  mesma RN-04.2 (o maximo de mensagens consecutivas) -- trocar uma violacao
  por outra da mesma regra nao e ganho nenhum.
- Deixar a segunda parte estourar viola so a clausula de tamanho, mantem o
  conteudo inteiro, e o gate de avaliacao (piso de 90%) continua contando o
  excedente -- entao a degradacao fica visivel em vez de escondida.

A D2 do desenho escolhe a terceira opcao. `quebrar_em_mensagens` nunca produz
mais que `MAX_MENSAGENS_DE_TEXTO` partes, e nunca descarta um caractere de
conteudo -- se as duas coisas nao cabem juntas, quem cede e o tamanho da
segunda parte.
"""

import re

# RN-04.2. Teto por mensagem.
MAX_CARACTERES_POR_MENSAGEM = 600

# RN-04.2, emenda E-02. Teto de mensagens de texto consecutivas por turno.
MAX_MENSAGENS_DE_TEXTO = 2

# Fim de frase reconhecido: ponto, exclamacao, interrogacao ou quebra de
# linha. Cortar aqui e cortar onde o leitor ja pararia -- ver o docstring de
# `quebrar_em_mensagens`.
_FRONTEIRA_DE_FRASE = re.compile(r"[.!?\n]")

_FRONTEIRA_DE_PALAVRA = re.compile(r" ")


def _ultima_posicao(padrao: re.Pattern[str], janela: str) -> int | None:
    """Indice da ULTIMA ocorrencia do padrao na janela, ou None se nao ha nenhuma."""
    ocorrencias = list(padrao.finditer(janela))
    if not ocorrencias:
        return None
    return ocorrencias[-1].start()


def quebrar_em_mensagens(texto: str) -> tuple[str, ...]:
    """Quebra `texto` em uma ou duas mensagens, sem perder nenhum caractere.

    Texto que cabe em `MAX_CARACTERES_POR_MENSAGEM` sai inteiro, numa parte so
    -- e o caminho comum, e uma regressao aqui trocaria o comum pelo raro (ver
    `test_texto_curto_sai_inteiro_numa_parte_so`).

    Quando nao cabe, procura a ULTIMA fronteira de frase (`.`, `!`, `?`, quebra
    de linha) em ou antes de `MAX_CARACTERES_POR_MENSAGEM`. Achando, a primeira
    parte termina ali -- pontuacao incluida -- e a segunda comeca depois dela.
    Nao achando fronteira de frase, cai para a ultima fronteira de PALAVRA no
    mesmo intervalo: cortar no meio de uma palavra pareceria bug ao lead, o
    mesmo argumento que `_prosa_que_cabe` ja usa em `apresentacao.py`. Na
    ausencia de qualquer fronteira -- um bloco sem espaco nem pontuacao --
    corta na marca exata, porque nao ha onde mais cortar.

    Cada parte devolvida vem sem espaco em branco nas pontas: mandar ao lead
    uma mensagem com espaco sobrando e desleixo, quebra tendo ou nao fronteira
    de frase para se apoiar. Quando a fronteira escolhida cai dentro de uma
    sequencia de quebras de linha (quebra de paragrafo dupla), o strip() come
    todas elas, nao so a que decidiu o corte -- sem perda de conteudo, porque
    linha em branco nao e conteudo.

    Se depois de limpar as pontas a segunda parte ficar vazia -- artefato
    comum de saida de LLM e um `\\n` final sozinho depois do ponto --, o texto
    cabia numa mensagem so e a funcao devolve uma 1-tupla. Sem este colapso, a
    Task 3 pareia as duas partes com um `kind` cada e despacharia a segunda,
    vazia, como mensagem real ao lead. O mesmo colapso vale do OUTRO lado: se
    a fronteira escolhida cair dentro de espaco em branco do INICIO do texto
    -- a resposta do modelo comecando com uma quebra de linha, por exemplo --
    e a PRIMEIRA parte fica vazia depois do strip(), a funcao devolve so a
    segunda como 1-tupla. Nenhuma das duas partes devolvidas por esta funcao
    sai vazia (fix de revisao final, TEC-140).

    Nunca devolve mais que `MAX_MENSAGENS_DE_TEXTO` partes. Acima de
    ~1.200 caracteres a segunda parte pode passar de
    `MAX_CARACTERES_POR_MENSAGEM` -- degradacao deliberada, ver o docstring do
    modulo.
    """
    if len(texto) <= MAX_CARACTERES_POR_MENSAGEM:
        return (texto,)

    janela = texto[:MAX_CARACTERES_POR_MENSAGEM]

    posicao_de_frase = _ultima_posicao(_FRONTEIRA_DE_FRASE, janela)
    if posicao_de_frase is not None:
        primeira = texto[: posicao_de_frase + 1]
        segunda = texto[posicao_de_frase + 1 :]
    else:
        posicao_de_palavra = _ultima_posicao(_FRONTEIRA_DE_PALAVRA, janela)
        if posicao_de_palavra is not None:
            primeira = texto[:posicao_de_palavra]
            segunda = texto[posicao_de_palavra:]
        else:
            primeira = texto[:MAX_CARACTERES_POR_MENSAGEM]
            segunda = texto[MAX_CARACTERES_POR_MENSAGEM:]

    primeira_final = primeira.strip()
    segunda_final = segunda.strip()
    if not primeira_final:
        # Fix de revisao final (Important 1, TEC-140). A fronteira de frase
        # (ou de palavra) escolhida caiu dentro de espaco em branco do INICIO
        # do texto -- basta a resposta do modelo comecar com uma quebra de
        # linha para a ULTIMA fronteira dentro dos 600 primeiros caracteres
        # ser um `\n` sem nada antes dele alem de espaco. Sem este colapso,
        # `outbound.send` recebia um payload com `"texto": ""`, o adaptador
        # devolvia 4xx, `EnvioRecusado` subia, e como nenhuma parte tinha
        # saido ainda (`entregue` False) a excecao subia crua e o turno
        # inteiro se perdia como "sem_resposta" -- com um log
        # (`outbound.recusado_permanente`) que aponta para o adaptador, nao
        # para a quebra que produziu o payload vazio.
        return (segunda_final,)
    if not segunda_final:
        # A quebra escolhida so tinha espaco em branco depois dela -- o texto
        # inteiro cabe na primeira parte, e devolver a segunda vazia violaria
        # a propria promessa do docstring ("uma ou duas mensagens").
        return (primeira_final,)
    return (primeira_final, segunda_final)
