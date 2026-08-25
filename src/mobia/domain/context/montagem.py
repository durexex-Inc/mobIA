from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.context.janela import Marca, dividir, literais_apos, marca_de
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
from mobia.domain.messages.models import Message
from mobia.infra.crypto import aad_de, decrypt

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


@dataclass(frozen=True)
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


def _texto_da(linha: Message) -> str:
    """Decifra o corpo para montar o prompt.

    O conteudo real e obrigatorio aqui por dois motivos: o resumo so e util se
    resumir o que foi dito, e a contagem de tokens tem de medir o que vai de
    fato ser enviado. Este texto nunca entra num `log.*`.
    """
    corpo = decrypt(linha.text_body, aad_de(linha.id, "text_body")) or ""
    return f"[{linha.role}] {corpo}"


def _texto_das(literais: list[Message]) -> str:
    return "\n".join(_texto_da(linha) for linha in literais)


def _texto_do_estado(estado: LeadQualification | None) -> str:
    """Representa o estado de qualificacao para fins de medicao.

    Nao e o renderizador do prompt -- isso e da TEC-134 -- mas a contagem tem
    de medir algo perto do que sera de fato enviado. Ignorar o estado aqui
    faria a medida ficar sistematicamente menor que a real, e o campo so
    cresce a partir da TEC-145.
    """
    if estado is None:
        return ""
    campos = {
        "intencao": estado.intencao,
        "faixa_preco_min": estado.faixa_preco_min,
        "faixa_preco_max": estado.faixa_preco_max,
        "regiao": estado.regiao,
        "tipo_imovel": estado.tipo_imovel,
        "quartos": estado.quartos,
        "vagas": estado.vagas,
        "urgencia": estado.urgencia,
        "forma_pagamento": estado.forma_pagamento,
        "tem_imovel_para_vender": estado.tem_imovel_para_vender,
    }
    return "\n".join(f"{chave}: {valor}" for chave, valor in campos.items() if valor is not None)


def _estimar(resumo: str | None, literais: list[Message], estado: LeadQualification | None) -> int:
    bruto = (
        len(SISTEMA) + len(resumo or "") + len(_texto_das(literais)) + len(_texto_do_estado(estado))
    )
    return bruto // 4


async def _contar_se_valer(
    contador: ContadorPort,
    resumo: str | None,
    literais: list[Message],
    estado: LeadQualification | None,
) -> int:
    """Estimativa barata decide se vale pagar o round trip da contagem real.

    Turno normal nao paga nada; turno perto do limite paga um e acerta. A
    estimativa nunca decide sozinha se cabe -- so decide se vale medir.

    `len/4` supoe 4 caracteres por token, mas portugues acentuado e emoji --
    comuns no trafego do WhatsApp -- rodam perto de 3.2. No pior caso a
    estimativa erra por um fator de ate 4/3.2 = 1.25, entao qualquer limiar
    acima de 0.8 do teto deixaria passar, sem medir de verdade, estimativas
    que na contagem real ja estourariam. `contexto_limiar_de_contagem` fica
    abaixo dessa fronteira com folga (ver comentario no `Settings`).
    """
    estimativa = _estimar(resumo, literais, estado)
    if estimativa < get_settings().contexto_limiar_de_contagem:
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
) -> tuple[str | None, list[Message], int]:
    """Ultimo recurso: o teto e limite fisico da chamada, o piso e preferencia
    de qualidade. Quando se contradizem, o teto vence -- ate o fim, nao so na
    primeira tentativa.

    Primeiro corta para a mensagem literal mais recente. Se ainda estourar,
    descarta o resumo tambem -- uma unica mensagem sem memoria nenhuma e pior
    que uma unica mensagem com memoria, mas ainda e melhor que nada. Se nem
    isso bastar, quem chama nao tem contexto nenhum que caiba: a excecao
    tipada avisa em vez de devolver algo acima do teto.
    """
    descartadas = max(len(literais) - 1, 0)
    literais = literais[-1:] if literais else literais
    log.warning("contexto.truncado", channel=channel, descartadas=descartadas, tokens=tokens)
    tokens = await _contar_se_valer(contador, texto_do_resumo, literais, estado)

    if tokens > teto and texto_do_resumo is not None:
        texto_do_resumo = None
        log.warning("contexto.resumo_descartado", channel=channel, tokens=tokens)
        tokens = await _contar_se_valer(contador, texto_do_resumo, literais, estado)

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
) -> ContextoMontado:
    settings = get_settings()

    async with session_factory() as session:
        resumo_atual: ResumoDaConversa | None = await ler_resumo(session, channel, conversation_key)
        literais = await literais_apos(session, channel, conversation_key, marca_de(resumo_atual))
        estado = await ler_estado(session, channel, conversation_key)

    texto_do_resumo = resumo_atual.texto if resumo_atual else None
    cobertas = resumo_atual.mensagens_cobertas if resumo_atual else 0
    marca_atual = marca_de(resumo_atual)
    degradado = False

    # Gatilho por acumulo: quarenta literais dobram as vinte mais antigas e
    # deixam vinte. Por proximidade, a marca colaria no presente.
    if len(literais) >= settings.contexto_gatilho_de_regeneracao:
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
        )
        degradado = degradado or falhou

    tokens = await _contar_se_valer(contador, texto_do_resumo, literais, estado)

    iteracao = 0
    while tokens > settings.contexto_teto_de_tokens:
        if iteracao >= settings.contexto_max_iteracoes:
            degradado = True
            texto_do_resumo, literais, tokens = await _truncar_ate_caber(
                contador,
                channel,
                texto_do_resumo,
                literais,
                estado,
                tokens,
                settings.contexto_teto_de_tokens,
            )
            break

        if len(literais) > settings.contexto_literais_minimas:
            instrucao = INSTRUCAO_DOBRAR
        else:
            # Nao ha mais mensagem a dobrar sem violar o piso; agora a cascata.
            instrucao = INSTRUCAO_COMPRIMIR
            log.warning("contexto.piso_violado", channel=channel, tokens=tokens)

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
        )
        degradado = degradado or falhou
        if falhou:
            # O teto nao negocia: se o provedor falhou e nao da pra dobrar ou
            # comprimir, o mesmo corte de emergencia do teto de iteracoes entra
            # em cena agora -- nunca devolver contexto acima do teto so porque
            # o provedor caiu no meio do laco.
            texto_do_resumo, literais, tokens = await _truncar_ate_caber(
                contador,
                channel,
                texto_do_resumo,
                literais,
                estado,
                tokens,
                settings.contexto_teto_de_tokens,
            )
            break
        tokens = await _contar_se_valer(contador, texto_do_resumo, literais, estado)
        iteracao += 1

    return ContextoMontado(
        sistema=SISTEMA,
        resumo=texto_do_resumo,
        literais=literais,
        estado=estado,
        tokens=tokens,
        degradado=degradado,
    )


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
        a_dobrar, a_manter = dividir(literais, settings.contexto_literais_minimas)
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
        log.warning(
            "contexto.degradado",
            channel=channel,
            reason=type(exc).__name__,
        )
        return texto_do_resumo, literais, cobertas, marca, True

    nova_marca = marca
    if a_dobrar:
        ultima = a_dobrar[-1]
        nova_marca = Marca(created_at=ultima.created_at, message_id=ultima.id)
        cobertas += len(a_dobrar)

    if nova_marca is not None:
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
    else:
        # COMPRIMIR sem nenhuma marca previa (nunca houve uma dobra) nao tem
        # watermark para amarrar a linha -- watermark_* e NOT NULL no esquema.
        # Sem watermark nao ha upsert seguro; o texto comprimido so vive na
        # memoria deste turno.
        log.warning("contexto.compressao_sem_marca", channel=channel)

    return gerado.texto, a_manter, cobertas, nova_marca, False
