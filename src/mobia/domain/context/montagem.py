import asyncio
import math
from dataclasses import dataclass
from decimal import Decimal

import structlog
from anthropic import APITimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.context.janela import (
    Marca,
    deve_regenerar,
    dividir,
    literais_apos,
    marca_de,
)
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import (
    ResumoDaConversa,
    gravar_resumo,
    ler_estado,
    ler_resumo,
)
from mobia.domain.context.resumo import (
    INSTRUCAO_COMPRIMIR,
    INSTRUCAO_DOBRAR,
    ContadorPort,
    ResumidorPort,
)
from mobia.domain.messages.enums import MessageContentType
from mobia.domain.messages.models import Message
from mobia.infra.anthropic import TETO_DO_RESUMO, motivo_do_provedor
from mobia.infra.crypto import DecryptionError, aad_de, decrypt

log = structlog.get_logger(__name__)

SISTEMA = (
    "Voce e o assistente virtual de uma imobiliaria, atendendo um lead. "
    "Use o resumo e o estado de qualificacao abaixo como memoria: nao repergunte "
    "o que ja esta preenchido."
)


class ContextoIrreducivel(RuntimeError):
    """Nem uma unica mensagem sem resumo cabe no teto de tokens.

    Ultimo degrau da cascata: truncar para uma literal e depois descartar o
    resumo ja tiraram tudo que dava para tirar sem violar o dominio. Se ainda
    assim estoura, nao ha contexto valido para mandar -- o provedor recusaria a
    chamada de qualquer jeito, ja que uma mensagem sozinha excede o limite
    fisico -- entao levantar aqui e estritamente melhor que devolver algo que
    este modulo promete, pelo proprio teto, que nao pode existir.
    """


@dataclass(frozen=True, repr=False)
class ContextoMontado:
    """As partes em ordem, nao uma string pronta.

    A ordem pertence ao dominio porque e ela que determina o custo: prompt
    caching e casamento de prefixo, entao o que muda devagar vem primeiro. O
    estado vai por ultimo de proposito -- no topo, cada campo extraido pela
    TEC-145 invalidaria o resumo e as vinte mensagens junto.
    """

    sistema: str
    resumo: str | None
    literais: list[Message]
    estado: LeadQualification | None
    tokens: int
    degradado: bool

    def __repr__(self) -> str:
        """Elide o conteudo do lead -- `repr=False` no dataclass e de proposito.

        A mascara de PII do log desce por dict, list e tuple, mas nao por
        dataclass. Um `log.info("turno", contexto=contexto)` na TEC-134
        renderizaria o resumo em claro sob a chave `contexto`, que nao esta na
        lista de campos redigidos, e `literais` carrega as `Message` inteiras.
        Aqui o repr nao carrega texto nenhum: so a forma do contexto, que e o
        que serve para depurar.
        """
        return (
            f"ContextoMontado(resumo={'<omitido>' if self.resumo is not None else None}, "
            f"literais={len(self.literais)}, "
            f"estado={'<presente>' if self.estado is not None else None}, "
            f"tokens={self.tokens}, degradado={self.degradado})"
        )


# Marcador por tipo para a mensagem que chega sem texto. AUDIO, IMAGEM e
# DOCUMENTO gravam `text_body` NULL hoje -- transcricao e OCR sao historias
# proprias -- e DESCONHECIDO e por definicao o que ninguem mapeou.
#
# Sem marcador, tres audios do lead entram no prompt como tres turnos vazios,
# indistinguiveis de tres mensagens em branco. O estrago nao para no turno: e
# esse mesmo texto que a dobra manda para o resumo, entao a memoria permanente
# da conversa passa a registrar "o lead nao disse nada" onde o lead mandou tres
# audios, e todo turno seguinte le isso. O marcador nao inventa conteudo: diz o
# que de fato se sabe -- veio um audio, e ele ainda nao foi transcrito.
_SEM_TEXTO: dict[str, str] = {
    MessageContentType.AUDIO: "(audio, sem transcricao)",
    MessageContentType.IMAGEM: "(imagem, sem descricao)",
    MessageContentType.DOCUMENTO: "(documento, sem texto extraido)",
}
_SEM_TEXTO_PADRAO = "(mensagem sem texto)"


def _texto_da(linha: Message) -> str:
    """Decifra o corpo para montar o prompt.

    O conteudo real e obrigatorio aqui por dois motivos: o resumo so e util se
    resumir o que foi dito, e a contagem de tokens tem de medir o que vai de
    fato ser enviado. Este texto nunca entra num `log.*`.
    """
    corpo = decrypt(linha.text_body, aad_de(linha.id, "text_body"))
    if corpo is None:
        corpo = _SEM_TEXTO.get(linha.content_type, _SEM_TEXTO_PADRAO)
    return f"[{linha.role}] {corpo}"


def _texto_das(literais: list[Message]) -> str:
    return "\n".join(_texto_da(linha) for linha in literais)


# TEC-257. Fica no bloco de estado que ja existe, e nao numa secao nova de
# `montar_prompt`: um rotulo novo sairia da subcontagem fixa do orcamento, que
# tinha 4,2 tokens de margem. Reusar o rotulo custa zero ali -- o texto por
# turno cresce, e esse `montar_contexto` conta, que e o correto porque ele e
# de fato enviado.
_MARCA_SEM_RESPOSTA = "(perguntado, sem resposta)"


def _em_reais(centavos: int | None) -> Decimal | None:
    """Converte centavos (armazenamento exato) para reais (leitura humana e do modelo).

    TEC-146: o banco guarda centavos porque inteiro nao tem erro de
    arredondamento; quem le -- humano ou modelo -- le reais, pela mesma razao
    que a D7 da spec manda o corpus de eval ficar anotado em reais: um inteiro
    grande demais (60000000) convida a um zero a mais ou a menos, e aqui o
    erro chegaria ao lead como preco errado numa mensagem real.

    `scaleb(-2)` desloca o ponto decimal sem dividir -- reproduz o mesmo texto
    que a coluna `numeric(12,2)` produzia antes desta migracao (com os zeros a
    direita, ex.: 60000000 -> "600000.00"), byte a byte. Uma divisao por 100
    normalizaria a casa decimal e perderia esse zero a direita.
    """
    if centavos is None:
        return None
    return Decimal(centavos).scaleb(-2)


def _texto_do_estado(estado: LeadQualification | None) -> str:
    """Representa o estado de qualificacao -- e para a medicao de tokens, e
    para o prompt de verdade.

    Serve os dois: a estimativa de `_estimar`/`_contar_se_valer` (que precisa
    medir perto do que sera de fato enviado, sob pena de subcontar) e a linha
    "Estado de qualificacao" que `montar_prompt` manda para o modelo. Por
    servir o prompt real, o texto que esta funcao produz **nao e livre para
    mudar**: uma mudanca de unidade ou de nome de campo aqui e uma mudanca no
    que o lead pode ouvir de volta, nao um detalhe de implementacao.

    A partir da TEC-257 carrega tambem os campos perguntados sem resposta, e
    a partir da TEC-148 os campos recusados junto -- **as duas colunas
    marcam com o mesmo texto**. Do ponto de vista do prompt as duas dizem a
    mesma coisa ("nao ha valor, e ja se pediu"), e a clausula
    "nao repergunte o preenchido nem o ignorado" cobre as duas. Distinguir
    "sem resposta" de "recusado" aqui custaria um segundo marcador em texto
    que sai em todo turno, e a margem do orcamento do prompt e de 6,2 tokens.

    A uniao existe porque a marca da TEC-257 **nao** e garantida no turno
    que pergunta: `marcar_perguntados` nao roda quando nao ha nada a gravar,
    o caminho de desambiguacao nao chega la, e saida bloqueada tambem nao.
    Sem a uniao, a promessa central da TEC-148 -- nao reperguntar o que o
    lead recusou -- valeria so quando a marca irma tivesse sido gravada por
    acaso. As duas colunas guardam o orcamento sob o mesmo nome canonico
    (`faixa_preco_max`, via `_NOME_DA_MARCA` em `repositorio.py`), entao unir
    os dois conjuntos nao precisa de traducao nenhuma.

    **Valor vence marca**, e a ordem dos campos nao muda: o campo marcado sai
    no lugar dele, nao no fim. Ordem instavel no fim do prompt seria mudanca
    de cache e de geracao a cada turno, de graca. Vale igual para a recusa:
    um campo recusado com valor de um turno anterior renderiza o valor, e a
    consequencia de qualificacao dele e resolvida em codigo
    (`esta_qualificado`, `calcular_score`), nunca aqui -- e a D4 do desenho.

    `NULL` e `{}` nas colunas significam coisas diferentes (ver o modelo) e a
    **leitura** trata os dois igual: `or ()`.

    TEC-146: o preco fica em centavos no banco (`_em_reais` explica o porque),
    mas aqui vira reais de volta e sai sob as chaves antigas
    `faixa_preco_min`/`faixa_preco_max` -- nem a unidade nem o nome que o
    modelo le podem mudar so porque o armazenamento mudou.

    Consequencia disso para a marca da TEC-257: `perguntados_sem_resposta`
    guarda a marca de orcamento sob `faixa_preco_max`, e nao sob nenhum dos
    nomes de coluna, porque e a chave renderizada aqui que o `elif` abaixo
    compara. Quem grava a marca ja traduz (`_NOME_DA_MARCA`, em
    `repositorio.py`), e `test_toda_chave_do_estado_tem_marca_alcancavel`
    pina os dois lados contra este dicionario.

    TEC-153: os seis campos do investidor saem aqui tambem, sob os nomes que
    o subagente usa. Eles nunca recebem marca -- `_marca_de` nao os conhece,
    de proposito (ver `_nome_contavel`, em `repositorio.py`) --, entao o que
    esta funcao leva ao prompt deles e o VALOR, que e o que impede a
    repergunta. Ver o comentario no corpo.
    """
    if estado is None:
        return ""
    marcados = set(estado.perguntados_sem_resposta or ()) | set(estado.campos_recusados or ())
    campos = {
        "intencao": estado.intencao,
        "faixa_preco_min": _em_reais(estado.faixa_preco_min_centavos),
        "faixa_preco_max": _em_reais(estado.faixa_preco_max_centavos),
        "regiao": estado.regiao,
        "tipo_imovel": estado.tipo_imovel,
        "quartos": estado.quartos,
        "vagas": estado.vagas,
        "urgencia": estado.urgencia,
        "forma_pagamento": estado.forma_pagamento,
        "tem_imovel_para_vender": estado.tem_imovel_para_vender,
        # TEC-153. A memoria da trilha do investidor. `SISTEMA_DO_INVESTIDOR`
        # manda o subagente usar "o resumo e o estado de qualificacao como
        # memoria: nao repergunte o preenchido nem o ignorado" -- sem estas
        # linhas o estado nunca chegava, e a promessa do prompt era falsa: o
        # subagente repergunta ticket, horizonte e o resto a cada turno.
        #
        # **Custa zero a quem nunca falou de investimento**: o laco abaixo so
        # emite valor nao-`None`, e para esse lead as sete colunas sao nulas,
        # entao o texto sai byte-identico ao de antes desta branch.
        #
        # As chaves sao os nomes que o SUBAGENTE escreve em `investidor`
        # (campos de `ExtracaoDoInvestidor`), e nao os nomes das colunas. E a
        # licao da TEC-146 aplicada antes de doer: quando o nome que o modelo
        # diz e o nome que o prompt renderiza coincidem, a pergunta contada
        # (`perguntas_contaveis`) e a chave lida aqui sao a mesma palavra e
        # nao ha traducao para manter certa -- que e a divergencia que
        # `_NOME_DA_MARCA` existe para remendar do lado do orcamento. Nada
        # aqui esta preso a historico: estas linhas nascem nesta branch.
        #
        # O ticket sai em reais pela mesma ruling R6 do orcamento: a coluna e
        # centavos porque inteiro nao arredonda, e quem le -- humano ou
        # modelo -- le reais.
        #
        # `perfil_investidor` fica FORA, e e a unica das sete colunas que
        # fica. Ele e DERIVADO (`perfil_de`), o modelo nunca declara te-lo
        # perguntado e o subagente nao pergunta perfil a ninguem -- renderiza-lo
        # custaria uma linha em todo turno do investidor sem evitar uma unica
        # repergunta. Mesma razao pela qual `intencao` nao e marcavel.
        "ticket_expressao": _em_reais(estado.ticket_investimento_centavos),
        "retorno_esperado_pct": estado.retorno_esperado_pct,
        "retorno_esperado_tipo": estado.retorno_esperado_tipo,
        "horizonte": estado.horizonte,
        "tolerancia_reforma": estado.tolerancia_reforma,
        "ja_investe_em_imoveis": estado.ja_investe_em_imoveis,
    }
    linhas = []
    for chave, valor in campos.items():
        if valor is not None:
            linhas.append(f"{chave}: {valor}")
        elif chave in marcados:
            linhas.append(f"{chave}: {_MARCA_SEM_RESPOSTA}")
    return "\n".join(linhas)


# Caracteres por token do portugues, MEDIDO -- nao suposto.
#
# Medicao de 20/09/2026 com `ContadorAnthropic` contra claude-sonnet-5, pela
# inclinacao entre um texto e o mesmo texto oito vezes (o que cancela a
# sobrecarga fixa da chamada): portugues sem acento 2,34, com acento 2,38.
#
# O valor anterior era 4, que e o INGLES (3,15 medido). A consequencia estava
# documentada ao contrario: `Settings.limiar_de_contagem_efetivo` afirmava que
# o portugues ficava "coberto com folga" pela razao de seguranca de 2,4, e a
# folga real era de 2,6%. Ver o desenho da TEC-225.
#
# 2,3 e o arredondamento para baixo do medido (2,34/2,38), de proposito: chars/token
# mais baixo estima MAIS tokens para o mesmo texto, entao o arredondamento erra na
# direcao segura da D2 -- superestimar, nunca subestimar.
_CHARS_POR_TOKEN_EM_PORTUGUES = 2.3

# Tokens por caractere NAO-ASCII.
#
# Um emoji e UM caractere Python e custa cerca de 2,9 tokens (0,35 chars/token
# medido). Para `len` ele vale o mesmo que uma vogal, e e exatamente essa
# cegueira que fazia 600 caracteres de emoji serem estimados em 150 tokens
# quando custam 1706.
#
# O acento do portugues paga este mesmo preco, o que superestima um pouco
# (1,23 do real, contra 1,02 do texto sem acento). Superestimar e a direcao
# segura, e a folga de latencia aguenta -- ver a D3 do desenho.
_TOKENS_POR_CARACTERE_NAO_ASCII = 3


def _estimar(resumo: str | None, literais: list[Message], estado: LeadQualification | None) -> int:
    """Estimativa barata de tokens, ciente de densidade (TEC-225).

    Separa ASCII de nao-ASCII porque os dois custam ordens diferentes: o
    portugues roda a 2,3 caracteres por token (medido em 2,34/2,38;
    arredondado para baixo, que e a direcao que superestima tokens) e o
    emoji a 0,35 -- e `len` nao distingue os dois. A formula anterior
    (`len // 4`) supunha o ingles e subcontava tudo que este produto
    processa.
    """
    texto = SISTEMA + (resumo or "") + _texto_das(literais) + _texto_do_estado(estado)
    nao_ascii = sum(1 for caractere in texto if ord(caractere) > 127)
    ascii_ = len(texto) - nao_ascii
    return int(ascii_ / _CHARS_POR_TOKEN_EM_PORTUGUES + nao_ascii * _TOKENS_POR_CARACTERE_NAO_ASCII)


# A razao entre a estimativa nova e a contagem real no pior caso PLAUSIVEL
# medido: a URL, em 0,80 (1.584 caracteres de URL estimam 688 contra 859
# reais -- int(1584 / 2,3) = 688, 688 / 859 = 0,8009).
#
# A folga sobre a URL medida e de 0,54%, e e fina: a taxa efetiva deste fator
# e 1/(2,3 x 0,80) = 1/1,84 chars/token contra a URL medida em 1/1,85.
#
# A razao cresce com a taxa -- ela e `taxa / 2,3` --, entao o perigo e a URL
# medir MENOS que 1,84 chars/token, nao mais. Uma remedicao que a ponha abaixo
# disso derruba a razao para baixo de 0,80 e o fator deixa de cobrir o pior
# caso plausivel.
#
# Base64 fica de fora de proposito -- 0,43 -- porque cobri-lo exigiria um
# detector de "sequencia longa sem espaco", que tem falso-positivo proprio
# (uma URL longa tambem e uma). Ver a D4 do desenho.
_PIOR_RAZAO_PLAUSIVEL = 0.80

# Derivado, e nao escrito como 1.25: o fator existe para devolver ao pior caso
# plausivel a folga que a estimativa nao lhe da. O valor calhar de ser o mesmo
# que o de antes e coincidencia -- aquele saia de `4 / 3.2`, dois numeros que a
# medicao da TEC-225 derrubou.
_FATOR_PESSIMISTA = 1 / _PIOR_RAZAO_PLAUSIVEL


def _estimar_pessimista(
    resumo: str | None, literais: list[Message], estado: LeadQualification | None
) -> int:
    """A estimativa de `_estimar` corrigida para errar para cima.

    Usada so pelo modo sem modelo. Cortar literais a mais num caminho que ja
    e degradacao declarada e a direcao segura do erro; devolver contexto
    acima do teto nao e.

    O `+ 1` compensa o truncamento do proprio `int()` de `_estimar`: a soma
    `ascii/2,3 + nao_ascii*3` e um float, e `int()` descarta a parte
    fracionaria, que pode chegar perto de um token inteiro. Escalar esse
    valor ja truncado por `_FATOR_PESSIMISTA` sem repor essa perda devolveria
    menos folga do que o fator promete.
    """
    return math.ceil((_estimar(resumo, literais, estado) + 1) * _FATOR_PESSIMISTA)


async def _contar_se_valer(
    contador: ContadorPort,
    resumo: str | None,
    literais: list[Message],
    estado: LeadQualification | None,
    *,
    sem_modelo: bool = False,
) -> int:
    """Estimativa barata decide se vale pagar o round trip da contagem real.

    Turno normal nao paga nada; turno perto do limite paga um e acerta.

    Abaixo do limiar a estimativa **e** a resposta: e ela que decide se cabe e
    e ela que sai em `ContextoMontado.tokens`. Nao ha aqui uma segunda medida
    conferindo o palpite -- o limiar existe para que o palpite so responda
    onde errar nao muda a decisao, nao para tira-lo da decisao.

    `_estimar` (TEC-225) roda ASCII a 2,3 caracteres por token e nao-ASCII a
    3 tokens por caractere -- nao mais o `len/4` que supunha o ingles e
    subestimava o que este produto processa: o portugues real mede 2,34 a
    2,38 chars/token, contra os 4 que aquela formula supunha. Ver a
    derivacao completa e o que ainda escapa desta contagem (so base64) em
    `Settings.limiar_de_contagem_efetivo`.
    """
    # O modo sem modelo nao consulta o limiar: ele nao esta escolhendo entre a
    # estimativa e a contagem, esta declarando que a contagem nao esta
    # disponivel. Ver `_estimar_pessimista`.
    if sem_modelo:
        return _estimar_pessimista(resumo, literais, estado)

    settings = get_settings()
    estimativa = _estimar(resumo, literais, estado)
    # Backstop duro, independente do limiar: `estimativa >= teto` e o mesmo que
    # `len(texto) >= 2,3 * teto` para texto ASCII -- a formula ciente de
    # densidade da TEC-225 (ver `_estimar`), nao mais uma hipotese de 4
    # caracteres por token. Devolver a estimativa ai seria decidir "cabe" a
    # partir do unico numero que diz o contrario. Uma comparacao, de graca no
    # trafego normal. Com o limiar default (0.6 do teto) ela nunca e o
    # gatilho -- so passa a valer se alguem subir CONTEXTO_LIMIAR_DE_CONTAGEM
    # acima do teto.
    if estimativa < settings.limiar_de_contagem_efetivo and estimativa < (
        settings.teto_de_tokens_efetivo
    ):
        return estimativa
    return await contador.contar(
        f"{SISTEMA}\n{resumo or ''}\n{_texto_das(literais)}\n{_texto_do_estado(estado)}"
    )


async def _truncar_ate_caber(
    contador: ContadorPort,
    channel: str,
    texto_do_resumo: str | None,
    literais: list[Message],
    estado: LeadQualification | None,
    tokens: int,
    teto: int,
    *,
    sem_modelo: bool = False,
) -> tuple[str | None, list[Message], int]:
    """Ultimo recurso: o teto e limite fisico da chamada, o piso e preferencia
    de qualidade. Quando se contradizem, o teto vence -- ate o fim, nao so na
    primeira tentativa.

    Reduz a janela pela metade a cada passo, em vez de cortar direto para uma
    unica literal: uma falha transitoria do provedor (ou um estouro de sobra)
    nao pode custar toda a memoria da conversa quando a metade dela ja
    resolveria. O numero de passos continua limitado -- cada volta corta pelo
    menos a metade do que resta, entao chega a 1 em no maximo log2(N) voltas.

    Se cortar tudo ainda nao bastar, descarta o resumo tambem -- uma unica
    mensagem sem memoria nenhuma e pior que uma unica mensagem com memoria,
    mas ainda e melhor que nada. Se nem isso bastar, quem chama nao tem
    contexto nenhum que caiba: a excecao tipada avisa em vez de devolver algo
    acima do teto.

    `sem_modelo` existe para o estouro do deadline de `montar_contexto`:
    contar aqui pagaria um round trip ao provedor no unico momento em que
    ja se sabe que nao ha tempo para ele.
    """
    piso = get_settings().contexto_literais_minimas
    avisou_do_piso = False
    while len(literais) > 1 and tokens > teto:
        corte = max(len(literais) // 2, 1)
        descartadas = len(literais) - corte
        literais = literais[-corte:]
        if len(literais) < piso and not avisou_do_piso:
            # O piso cedeu aqui tambem, e da pior forma: o corte nao dobra o
            # conteudo em lugar nenhum, ele some. Mesmo evento da dobra abaixo
            # do piso -- quem pagina em `contexto.piso_violado` tem de ver os
            # dois casos, e este e o mais grave dos dois.
            log.warning("contexto.piso_violado", channel=channel, literais=len(literais), piso=piso)
            avisou_do_piso = True
        log.warning("contexto.truncado", channel=channel, descartadas=descartadas, tokens=tokens)
        tokens = await _contar_se_valer(
            contador, texto_do_resumo, literais, estado, sem_modelo=sem_modelo
        )

    if tokens > teto and texto_do_resumo is not None:
        texto_do_resumo = None
        log.warning("contexto.resumo_descartado", channel=channel, tokens=tokens)
        tokens = await _contar_se_valer(
            contador, texto_do_resumo, literais, estado, sem_modelo=sem_modelo
        )

    if tokens > teto:
        raise ContextoIrreducivel(
            f"uma unica mensagem sem resumo ainda excede o teto: tokens={tokens}, teto={teto}"
        )

    return texto_do_resumo, literais, tokens


async def montar_contexto(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    resumidor: ResumidorPort,
    contador: ContadorPort,
    forcar_dobra: bool = False,
) -> ContextoMontado:
    settings = get_settings()

    degradado = False

    async with session_factory() as session:
        resumo_atual: ResumoDaConversa | None = None
        try:
            resumo_atual = await ler_resumo(session, channel, conversation_key)
        except DecryptionError:
            # Resumo ilegivel -- rotacao de chave, escrita parcial, restore de
            # um ambiente com outra chave -- nao pode travar a conversa. Sem
            # esta guarda uma unica linha corrompida faz todo turno seguinte
            # deste lead levantar, para sempre: e o unico modo de falha deste
            # modulo que nao tinha caminho degradado, e nao e mais raro que a
            # queda do provedor, que tem.
            #
            # Degradar e seguro: sem marca, tudo depois do inicio da conversa
            # volta literal -- nada some, so cresce -- e a proxima dobra
            # sobrescreve a linha ilegivel com um resumo novo. So o tipo do
            # erro vai para o log: o texto dele nunca carrega conteudo do lead
            # (ver `_marca_do_aad` em `infra/crypto.py`), mas registrar o
            # minimo aqui e mais barato que confiar nisso a cada refactor.
            degradado = True
            log.warning("contexto.resumo_ilegivel", channel=channel)
        literais = await literais_apos(session, channel, conversation_key, marca_de(resumo_atual))
        estado = await ler_estado(session, channel, conversation_key)

    texto_do_resumo = resumo_atual.texto if resumo_atual else None
    cobertas = resumo_atual.mensagens_cobertas if resumo_atual else 0
    marca_atual = marca_de(resumo_atual)

    # Teto ja com a reserva descontada: o contador mede um proxy menor que a
    # requisicao real da TEC-134 -- ver `Settings.teto_de_tokens_efetivo`.
    #
    # Fica ANTES do deadline porque o caminho degradado tambem precisa dele, e
    # calcula-lo la dentro o deixaria indisponivel no unico ramo que nao
    # chegou ao fim.
    teto = settings.teto_de_tokens_efetivo

    # O relogio da fase inteira (TEC-290). As leituras de banco acima ficam de
    # FORA de proposito: elas pertencem a reserva de banco do orcamento, e
    # inclui-las faria uma lentidao de Postgres consumir tempo de modelo.
    #
    # `asyncio.timeout` aqui e o segundo do repo, e o primeiro fora do
    # pos-cancelamento (o outro e `SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO`, em
    # `workers/jobs/process_message.py`). O padrao da casa para prazo normal e
    # o `timeout=` do SDK por chamada -- que e exatamente o que nao resolve
    # este caso, porque a fase faz N chamadas.
    try:
        async with asyncio.timeout(settings.contexto_deadline_de_montagem_segundos):
            # `forcar_dobra` passa por cima do gatilho de acumulo: a conversa
            # que reabre pode ter cinco mensagens, muito abaixo das 40, e e
            # justamente essas cinco que nao podem chegar ao prompt da
            # conversa nova (TEC-130, D4). Sem a flag, o gatilho continua o
            # mesmo de sempre: quarenta literais dobram as vinte mais antigas
            # e deixam vinte -- por proximidade, a marca colaria no presente.
            if forcar_dobra or deve_regenerar(
                len(literais), settings.contexto_gatilho_de_regeneracao
            ):
                texto_do_resumo, literais, cobertas, marca_atual, falhou = await _dobrar(
                    session_factory,
                    channel,
                    conversation_key,
                    resumidor,
                    texto_do_resumo,
                    literais,
                    cobertas,
                    marca_atual,
                    INSTRUCAO_DOBRAR,
                    dobrar_tudo=forcar_dobra,
                )
                degradado = degradado or falhou
                if forcar_dobra and falhou:
                    # Alarme proprio, e nao so o `contexto.degradado` que
                    # `_dobrar` ja emite: aqui a degradacao tem consequencia
                    # que ela nao tem no caso normal -- a transcricao da
                    # conversa ANTERIOR volta ao prompt, que e exatamente o
                    # que esta card impede. Quem investiga precisa separar os
                    # dois casos pelo nome, nao pela correlacao de horario.
                    log.warning(
                        "contexto.dobra_forcada_falhou",
                        channel=channel,
                        literais=len(literais),
                    )

            tokens = await _contar_se_valer(contador, texto_do_resumo, literais, estado)

            iteracao = 0
            ja_comprimiu = False
            while tokens > teto:
                if iteracao >= settings.contexto_max_iteracoes:
                    degradado = True
                    texto_do_resumo, literais, tokens = await _truncar_ate_caber(
                        contador, channel, texto_do_resumo, literais, estado, tokens, teto
                    )
                    break

                piso_cede = False
                if len(literais) > settings.contexto_literais_minimas:
                    # Degrau 1: dobrar mensagem em resumo e perda normal, e o piso fica
                    # de pe. E a mesma operacao da regeneracao, disparada por token em
                    # vez de por contagem.
                    instrucao = INSTRUCAO_DOBRAR
                elif texto_do_resumo is not None and not ja_comprimiu:
                    # Degrau 2: re-resumir o resumo e perda em cascata, entao so
                    # acontece depois que o degrau 1 nao bastou. Uma vez por turno:
                    # comprimir de novo o que ja foi comprimido paga outra chamada de
                    # modelo para tirar cada vez menos e trava o degrau 3, que tira
                    # mais e preserva o conteudo em vez de descarta-lo.
                    instrucao = INSTRUCAO_COMPRIMIR
                elif len(literais) > 1:
                    # Degrau 3, o unico lugar onde o piso cede -- e o spec diz que
                    # cede-lo e permitido justamente aqui. Vinte mensagens que sozinhas
                    # passam do teto existem (vinte audios transcritos longos chegam
                    # la) e o teto, limite fisico da chamada, vence o piso, que e
                    # preferencia de qualidade.
                    #
                    # O que importa e *como* o piso cede: dobrando, nao descartando. A
                    # dobra manda o conteudo para o resumo e avanca a marca junto,
                    # entao continua nao existindo lacuna entre o que esta resumido e o
                    # que esta literal -- a propriedade que a marca d'agua inteira
                    # existe para comprar. Descartar (o degrau seguinte) poupa uma
                    # chamada de modelo e perde a fala do lead para sempre.
                    instrucao = INSTRUCAO_DOBRAR
                    piso_cede = True
                else:
                    # Uma unica literal e nada que dobrar. Pedir ao provedor para
                    # comprimir uma string vazia nao produz um resumo, produz um resumo
                    # inventado -- a mesma classe de falha que a Task 4 evita ao
                    # recusar um resumo vazio/so-espaco. Vai direto para o corte de
                    # emergencia em vez de fabricar memoria.
                    degradado = True
                    log.warning("contexto.sem_reducao_possivel", channel=channel, tokens=tokens)
                    texto_do_resumo, literais, tokens = await _truncar_ate_caber(
                        contador, channel, texto_do_resumo, literais, estado, tokens, teto
                    )
                    break

                texto_do_resumo, literais, cobertas, marca_atual, falhou = await _dobrar(
                    session_factory,
                    channel,
                    conversation_key,
                    resumidor,
                    texto_do_resumo,
                    literais,
                    cobertas,
                    marca_atual,
                    instrucao,
                    piso_pode_ceder=piso_cede,
                )
                degradado = degradado or falhou
                if falhou:
                    # O teto nao negocia: se o provedor falhou e nao da pra dobrar ou
                    # comprimir, o mesmo corte de emergencia do teto de iteracoes entra
                    # em cena agora -- nunca devolver contexto acima do teto so porque
                    # o provedor caiu no meio do laco.
                    texto_do_resumo, literais, tokens = await _truncar_ate_caber(
                        contador, channel, texto_do_resumo, literais, estado, tokens, teto
                    )
                    break
                ja_comprimiu = ja_comprimiu or instrucao == INSTRUCAO_COMPRIMIR
                if piso_cede:
                    # Aqui, e so aqui na dobra, o piso de fato cedeu -- o outro lugar e
                    # o truncamento, que avisa por conta propria. E sinal de que a
                    # conversa tem um formato que ninguem previu, e por isso vale
                    # paginar em cima dele: o alerta so acorda alguem quando o piso
                    # realmente quebrou.
                    degradado = True
                    log.warning(
                        "contexto.piso_violado",
                        channel=channel,
                        literais=len(literais),
                        piso=settings.contexto_literais_minimas,
                        tokens=tokens,
                    )
                tokens = await _contar_se_valer(contador, texto_do_resumo, literais, estado)
                iteracao += 1
    except TimeoutError:
        # So `TimeoutError`. O `CancelledError` do `job_timeout` do ARQ e
        # `BaseException` e continua propagando: quem tem de recebe-lo e a
        # clausula de `process_message` da TEC-227, que marca FAILED e conta a
        # tentativa. Engoli-lo aqui devolveria a perda silenciosa que aquela
        # card acabou.
        #
        # Overlap conhecido e aceito: `_dobrar` guarda so `resumidor.resumir`
        # com `except Exception` -- `gravar_resumo` e o `session.commit()`
        # ficam sem guarda propria dentro deste bloco. Um `TimeoutError` de
        # driver de banco vindo de la cai aqui tambem (desde o Python 3.11
        # `TimeoutError` embutido e superclasse do que `asyncio.timeout`
        # levanta), e a linha de log abaixo nomearia a causa errada -- diria
        # deadline da fase quando foi o banco. Nao estreitar a captura para
        # excluir esse caso: exigiria um sentinela so para isso, e a direcao
        # da degradacao continua segura nos dois casos.
        degradado = True
        log.warning(
            "contexto.deadline_estourado",
            channel=channel,
            deadline_s=settings.contexto_deadline_de_montagem_segundos,
            literais=len(literais),
        )
        # Recontado aqui, e nao herdado do laco: o estouro pode cair antes de
        # `tokens` receber valor algum, e um `tokens` zerado faria o
        # truncamento decidir que ja cabe.
        tokens = _estimar_pessimista(texto_do_resumo, literais, estado)
        texto_do_resumo, literais, tokens = await _truncar_ate_caber(
            contador, channel, texto_do_resumo, literais, estado, tokens, teto, sem_modelo=True
        )

    return ContextoMontado(
        sistema=SISTEMA,
        resumo=texto_do_resumo,
        literais=literais,
        estado=estado,
        tokens=tokens,
        degradado=degradado,
    )


def montar_prompt(contexto: ContextoMontado, *, omitir_sistema: bool = False) -> str:
    """Renderiza as partes na ordem que determina o custo.

    Publico de proposito: a TEC-134 precisa do texto, e a ordem e decisao deste
    modulo, nao dela. Sistema e resumo primeiro porque mudam devagar e ficam
    quentes no cache; estado por ultimo porque muda a cada extracao da TEC-145.

    `omitir_sistema=True` e para quem ja manda a propria persona pelo campo
    `system` dedicado da API (a TEC-134 manda `SISTEMA_DO_AGENTE`): reenviar
    `contexto.sistema` aqui dentro do turno do usuario duplicaria a persona
    com um texto mais fraco que o oficial. O default mantem o texto completo
    para quem ainda nao tem um canal de sistema proprio.
    """
    partes = [] if omitir_sistema else [contexto.sistema]
    if contexto.resumo is not None:
        partes.append(f"Resumo da conversa ate aqui:\n{contexto.resumo}")
    partes.append(f"Mensagens recentes:\n{_texto_das(contexto.literais)}")
    partes.append(f"Estado de qualificacao:\n{_texto_do_estado(contexto.estado)}")
    return "\n\n".join(partes)


async def _dobrar(
    session_factory: async_sessionmaker[AsyncSession],
    channel: str,
    conversation_key: str,
    resumidor: ResumidorPort,
    texto_do_resumo: str | None,
    literais: list[Message],
    cobertas: int,
    marca: Marca | None,
    instrucao: str,
    *,
    piso_pode_ceder: bool = False,
    dobrar_tudo: bool = False,
) -> tuple[str | None, list[Message], int, Marca | None, bool]:
    """Uma passada: gera o resumo novo, grava a marca e devolve o que sobrou.

    Falha do provedor nao propaga. A Marina esta esperando: o caminho degradado
    usa o resumo antigo e o chamador corta literais ate caber. E a mesma
    filosofia do `_try_enqueue` da TEC-122 -- o caminho principal sobrevive, o
    efeito secundario engole a propria falha e grita no log.
    """
    settings = get_settings()

    if instrucao == INSTRUCAO_COMPRIMIR:
        a_dobrar: list[Message] = []
        a_manter = literais
        conteudo = texto_do_resumo or ""
    else:
        # `minimas=0` faz `dividir` devolver tudo para dobrar e nada para
        # manter -- e o que apaga a transcricao da conversa anterior sem
        # perde-la, porque ela vai inteira para o resumo. Ver a D4 da TEC-130.
        #
        # **`dobrar_tudo` nao e `piso_pode_ceder`.** Aquele cede o piso para
        # UMA mensagem, por causa do estouro de teto, e a mais recente tem de
        # sobrar porque e a fala a que o modelo responde. Aqui nenhuma tem de
        # sobrar: a fala deste turno nao esta nesta lista (o turno a grava e
        # `montar_contexto` nao a inclui), entao dobrar tudo nao deixa o turno
        # sem pergunta.
        minimas = 0 if dobrar_tudo else settings.contexto_literais_minimas
        a_dobrar, a_manter = dividir(literais, minimas, piso_pode_ceder=piso_pode_ceder)
        if not a_dobrar:
            return texto_do_resumo, literais, cobertas, marca, False
        conteudo = (
            f"Resumo atual:\n{texto_do_resumo or '(vazio)'}\n\n"
            f"Novas mensagens:\n{_texto_das(a_dobrar)}"
        )

    try:
        gerado = await resumidor.resumir(instrucao, conteudo)
    except Exception as exc:
        # So o tipo da excecao vai pro log. `conteudo`, aqui em cima, carrega
        # texto decifrado do lead -- um `str(exc)` de um SDK que ecoa o corpo
        # da requisicao (ou de um resumidor que interpola a propria entrada no
        # erro) vazaria esse texto para o log estruturado.
        #
        # `motivo` e a excecao estreita que a TEC-237 abriu: so corpo de erro
        # de protocolo do provedor, gerado pelo servidor, e `None` para todo o
        # resto -- inclusive para um resumidor que interpole a propria entrada.
        # A regra acima continua valendo; o que mudou e que "a conta acabou"
        # deixou de ser indistinguivel de "o schema quebrou".
        #
        # `teto_s` so aparece quando a degradacao FOI estouro de teto, e nao em
        # toda linha (TEC-228). A card pedia distinguir o timeout do resumo das
        # demais degradacoes, e `reason` ja fazia isso -- `APITimeoutError` tem
        # nome proprio. O que faltava era saber contra QUE teto: desde que cada
        # fatia do turno tem o seu, o mesmo `APITimeoutError` significa 25s
        # aqui e 35s no investidor, e quem le o log nao tinha como separar.
        #
        # Nao e evento novo pela mesma razao que a TEC-237 preferiu acrescentar
        # `motivo` a criar um: um nome novo obrigaria todo consumidor de
        # `contexto.degradado` a conhecer os dois, para uma distincao que um
        # campo ja faz.
        #
        # `None` quando nao foi timeout, e nao o teto sempre: um resumidor
        # injetado nos testes nao tem teto nenhum, e afirmar 25,0 numa
        # degradacao que nao foi de tempo seria o campo mentindo sobre o que
        # aconteceu.
        log.warning(
            "contexto.degradado",
            channel=channel,
            reason=type(exc).__name__,
            motivo=motivo_do_provedor(exc),
            teto_s=TETO_DO_RESUMO if isinstance(exc, APITimeoutError) else None,
        )
        return texto_do_resumo, literais, cobertas, marca, True

    nova_marca = marca
    if a_dobrar:
        ultima = a_dobrar[-1]
        nova_marca = Marca(created_at=ultima.created_at, message_id=ultima.id)
        cobertas += len(a_dobrar)

    if nova_marca is None:
        # `montar_contexto` so escolhe INSTRUCAO_COMPRIMIR quando ja existe um
        # resumo (texto_do_resumo not None implica marca not None -- os dois
        # sao atualizados juntos, so por uma dobra). DOBRAR sem `a_dobrar`
        # (a unica outra forma de chegar aqui sem marca) ja retornou antes,
        # la em cima. Chegar aqui e uma garantia quebrada, nao um caso valido
        # a degradar em silencio -- falhar alto e melhor que voltar a perder
        # uma compressao sem ninguem perceber.
        raise AssertionError("_dobrar: chamado sem marca previa e sem nada para dobrar")

    async with session_factory() as session:
        await gravar_resumo(
            session,
            channel=channel,
            conversation_key=conversation_key,
            texto=gerado.texto,
            watermark_created_at=nova_marca.created_at,
            watermark_message_id=nova_marca.message_id,
            mensagens_cobertas=cobertas,
            modelo=gerado.modelo,
        )
        # gravar_resumo empresta a sessao (Task 2): quem chama e dono da
        # fronteira. Sem este commit a marca nunca sai da memoria e todo
        # turno seguinte paga de novo o mesmo dobramento ou a mesma
        # compressao.
        await session.commit()

    return gerado.texto, a_manter, cobertas, nova_marca, False
