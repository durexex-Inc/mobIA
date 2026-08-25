from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.app.config import get_settings
from mobia.domain.context.janela import dividir, literais_apos, marca_de
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


def _estimar(resumo: str | None, literais: list[Message]) -> int:
    bruto = len(SISTEMA) + len(resumo or "") + len(_texto_das(literais))
    return bruto // 4


async def _contar_se_valer(
    contador: ContadorPort, resumo: str | None, literais: list[Message]
) -> int:
    """Estimativa barata decide se vale pagar o round trip da contagem real.

    Turno normal nao paga nada; turno perto do limite paga um e acerta. A
    estimativa nunca decide sozinha se cabe -- so decide se vale medir.
    """
    estimativa = _estimar(resumo, literais)
    if estimativa < get_settings().contexto_limiar_de_contagem:
        return estimativa
    return await contador.contar(f"{SISTEMA}\n{resumo or ''}\n{_texto_das(literais)}")


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
    degradado = False

    # Gatilho por acumulo: quarenta literais dobram as vinte mais antigas e
    # deixam vinte. Por proximidade, a marca colaria no presente.
    if len(literais) >= settings.contexto_gatilho_de_regeneracao:
        texto_do_resumo, literais, cobertas, falhou = await _dobrar(
            session_factory,
            channel,
            conversation_key,
            resumidor,
            texto_do_resumo,
            literais,
            cobertas,
            INSTRUCAO_DOBRAR,
        )
        degradado = degradado or falhou

    tokens = await _contar_se_valer(contador, texto_do_resumo, literais)

    iteracao = 0
    while tokens > settings.contexto_teto_de_tokens:
        if iteracao >= settings.contexto_max_iteracoes:
            # Ultimo recurso: o teto e limite fisico da chamada, o piso e
            # preferencia de qualidade. Quando se contradizem, o teto vence.
            descartadas = len(literais) - 1
            literais = literais[-1:]
            degradado = True
            log.warning(
                "contexto.truncado",
                channel=channel,
                descartadas=descartadas,
                tokens=tokens,
            )
            tokens = await _contar_se_valer(contador, texto_do_resumo, literais)
            break

        if len(literais) > settings.contexto_literais_minimas:
            instrucao = INSTRUCAO_DOBRAR
        else:
            # Nao ha mais mensagem a dobrar sem violar o piso; agora a cascata.
            instrucao = INSTRUCAO_COMPRIMIR
            log.warning("contexto.piso_violado", channel=channel, tokens=tokens)

        texto_do_resumo, literais, cobertas, falhou = await _dobrar(
            session_factory,
            channel,
            conversation_key,
            resumidor,
            texto_do_resumo,
            literais,
            cobertas,
            instrucao,
        )
        degradado = degradado or falhou
        if falhou:
            break
        tokens = await _contar_se_valer(contador, texto_do_resumo, literais)
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
    instrucao: str,
) -> tuple[str | None, list[Message], int, bool]:
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
            return texto_do_resumo, literais, cobertas, False
        conteudo = (
            f"Resumo atual:\n{texto_do_resumo or '(vazio)'}\n\n"
            f"Novas mensagens:\n{_texto_das(a_dobrar)}"
        )

    try:
        gerado = await resumidor.resumir(instrucao, conteudo)
    except Exception as exc:
        log.warning(
            "contexto.degradado",
            channel=channel,
            reason=type(exc).__name__,
            detail=str(exc),
        )
        return texto_do_resumo, literais, cobertas, True

    if a_dobrar:
        ultima = a_dobrar[-1]
        async with session_factory() as session:
            await gravar_resumo(
                session,
                channel=channel,
                conversation_key=conversation_key,
                texto=gerado.texto,
                watermark_created_at=ultima.created_at,
                watermark_message_id=ultima.id,
                mensagens_cobertas=cobertas + len(a_dobrar),
                modelo=gerado.modelo,
            )
            # gravar_resumo empresta a sessao (Task 2): quem chama e dono da
            # fronteira. Sem este commit a marca nunca sai da memoria e todo
            # turno seguinte paga de novo o mesmo dobramento.
            await session.commit()
        cobertas += len(a_dobrar)

    return gerado.texto, a_manter, cobertas, False
