"""Leitura e escrita do ciclo de vida da conversa. TEC-138.

Nenhuma escritora commita -- a sessao e emprestada e o dono da transacao e
quem chama, como em `gravar_estado` e `registrar_recalculo`.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.identificacao import DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA
from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status


async def encerrar_conversa(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    motivo: str,
    agora: datetime,
) -> None:
    """Marca a conversa como encerrada, com o motivo e o carimbo.

    Upsert e nao INSERT: a conversa pode ja ter linha de um encerramento
    anterior que a janela dos 30 dias ja reabriu. Encerrar de novo e
    idempotente de proposito -- `deve_encerrar` usa `>=` pela mesma razao.
    """
    valores = {
        "channel": channel,
        "conversation_key": conversation_key,
        # `Status` e StrEnum e esta funcao grava `str(...)`, entao a coluna
        # guarda o literal, no mesmo molde de `gravar_intencao`
        # (`agente/repositorio.py`) com `Intencao`.
        "status": str(Status.ENCERRADA),
        "motivo_do_encerramento": motivo,
        "encerrada_em": agora,
    }
    statement = pg_insert(Conversa).values(valores)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["channel", "conversation_key"],
            set_={
                "status": statement.excluded.status,
                "motivo_do_encerramento": statement.excluded.motivo_do_encerramento,
                "encerrada_em": statement.excluded.encerrada_em,
            },
        )
    )


@dataclass(frozen=True)
class SituacaoDaConversa:
    """As tres coisas que uma leitura so de `conversas` responde.

    Existe porque o turno precisa de mais de uma (TEC-138, Task 4):
    `silencia_o_agente` decide se ele cala, e `marcada_como_encerrada` decide se
    ele reabre a linha antes de seguir. Sem este conjunto o turno so tinha o
    booleano de `esta_encerrada`, que responde False tanto para "nunca houve
    encerramento" quanto para "houve e a janela venceu" -- e a unica forma de
    separar os dois era chamar `reabrir_conversa` incondicionalmente, pagando um
    `UPDATE` e um commit em TODO turno de toda conversa ja reaberta, para
    sempre.
    """

    marcada_como_encerrada: bool
    dentro_da_janela: bool
    motivo_do_encerramento: str | None

    @property
    def silencia_o_agente(self) -> bool:
        """A politica dos 30 dias de silencio se aplica a esta conversa AGORA?

        **Duas condicoes, e o motivo e a que existe por causa da TEC-130** (fix
        da revisao final, Important 1). Calar por 30 dias e politica da RN-03.5,
        do encerramento por FORA_DE_ESCOPO -- nao e propriedade do `status`.
        A Emenda E-02 da RN-02.3 manda a TEC-130 acrescentar `INATIVIDADE` a
        `MotivoDoEncerramento` e o escritor que fecha a conversa por
        inatividade; uma versao desta propriedade que olhasse so o `status`
        transformaria isso, sem ninguem pedir, em 30 dias de silencio para TODA
        conversa fechada por inatividade -- destruindo exatamente o
        reengajamento que a RN-02.3 existe para ter.

        Motivo novo, portanto, **entra no silencio se optar por ele**, e nao
        por omissao: quem acrescentar um membro ao vocabulario ganha a
        escrituracao do encerramento e nada mais, ate acrescentar o motivo
        aqui.

        `dentro_da_janela` fica separado de proposito, e nao dobrado aqui
        dentro: ele responde sobre o TEMPO e continua verdadeiro para qualquer
        motivo. Quem quer a politica le esta propriedade; quem quer a janela le
        aquele campo.
        """
        return (
            self.dentro_da_janela
            and self.motivo_do_encerramento == MotivoDoEncerramento.FORA_DE_ESCOPO
        )


async def situacao_da_conversa(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    agora: datetime,
) -> SituacaoDaConversa:
    """Le a linha UMA vez e devolve a situacao. **A regra da janela mora aqui.**

    `marcada_como_encerrada` olha so a coluna; `dentro_da_janela` olha a coluna
    E o relogio; `motivo_do_encerramento` e o literal gravado, que
    `silencia_o_agente` usa para separar a politica da RN-03.5 dos outros
    motivos. Uma conversa com `marcada_como_encerrada=True` e
    `dentro_da_janela=False` e exatamente a que o turno reabre.

    Um `status` ENCERRADA com `encerrada_em` nulo -- estado que o modelo diz
    nao existir, porque "os dois andam juntos" -- conta como marcada e fora da
    janela: sem carimbo nao ha janela para medir, e reabrir e o conserto certo.

    **A resposta e do tempo, e nao so do status.** Um encerramento mais velho
    que a janela devolve `dentro_da_janela=False` com a coluna ainda dizendo
    ENCERRADA: quem reabre e o turno, e ele so roda quando chega mensagem. Ate
    la a linha fica como estava, e esta funcao ja conta a verdade.

    `agora` entra por parametro, e nao de `datetime.now()` aqui dentro, pelo
    mesmo motivo que `e_conversa_nova` o recebe: e o que torna a janela
    testavel sem congelar relogio.

    **Empate em exatamente 30 dias resolvido para o lado fechado**, com `<=`
    e nao `<`: exatamente 30 dias ainda esta encerrada, e reabre so depois
    disso. E o mesmo lado que `e_conversa_nova` escolhe para o empate dela --
    "exatamente 30 dias ainda nao abre conversa nova" -- e tem de ser, porque
    as duas funcoes compartilham `DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA`: se
    esta reabrisse no instante exato em que `e_conversa_nova` ainda considera
    silencio, a reabertura e a identificacao de conversa nova deixariam de
    coincidir, que e o motivo de as duas usarem a mesma constante. Deixar o
    empate ao acaso e o defeito que a TEC-229 documentou.
    """
    linha = (
        await session.execute(
            select(Conversa.status, Conversa.encerrada_em, Conversa.motivo_do_encerramento).where(
                Conversa.channel == channel,
                Conversa.conversation_key == conversation_key,
            )
        )
    ).one_or_none()
    if linha is None or linha.status != Status.ENCERRADA:
        return SituacaoDaConversa(
            marcada_como_encerrada=False, dentro_da_janela=False, motivo_do_encerramento=None
        )
    if linha.encerrada_em is None:
        return SituacaoDaConversa(
            marcada_como_encerrada=True,
            dentro_da_janela=False,
            motivo_do_encerramento=linha.motivo_do_encerramento,
        )
    return SituacaoDaConversa(
        marcada_como_encerrada=True,
        dentro_da_janela=(
            agora - linha.encerrada_em <= timedelta(days=DIAS_DE_SILENCIO_PARA_CONVERSA_NOVA)
        ),
        motivo_do_encerramento=linha.motivo_do_encerramento,
    )


async def esta_encerrada(
    session: AsyncSession,
    *,
    channel: str,
    conversation_key: str,
    agora: datetime,
) -> bool:
    """A conversa esta encerrada AGORA? **Ver `situacao_da_conversa` para a
    regra da janela** -- ela mora uma vez so, la, e esta funcao apenas devolve
    metade do que aquela le.

    Duas copias da regra seriam duas coisas para manter em sincronia, e o
    ponteiro aponta para cima e nao para baixo de proposito (fix da revisao
    final, Minor 6): quem o turno chama em producao e `situacao_da_conversa`
    direto, entao e la que a regra tem de estar escrita, e nao pendurada na
    funcao que ninguem chama fora de teste.

    **Quem o turno chama nao e esta funcao**: ele precisa de mais de um campo
    de `SituacaoDaConversa` para decidir se cala e se reabre, e esta devolve so
    `dentro_da_janela`. Esta funcao e para quem so precisa da resposta booleana
    simples -- hoje, os testes de repositorio.

    **E ela responde sobre a JANELA, nao sobre a politica de silencio.**
    `dentro_da_janela` ignora o motivo; quem decide calar e
    `silencia_o_agente`, que exige `FORA_DE_ESCOPO`. As duas coisas divergem a
    partir do primeiro motivo novo -- ver a docstring daquela propriedade.

    Sem linha, nao esta -- o estado default e "pode receber", igual ao de
    `esta_em_optout`.
    """
    return (
        await situacao_da_conversa(
            session, channel=channel, conversation_key=conversation_key, agora=agora
        )
    ).dentro_da_janela


async def reabrir_conversa(session: AsyncSession, *, channel: str, conversation_key: str) -> None:
    """Volta a conversa para ATIVA e limpa motivo e carimbo.

    Nao zera o contador de fora de escopo: no caminho normal ele ja esta em
    zero desde o encerramento, e essa e a razao de o encerramento o zerar. Ver
    o comentario da coluna em `agente/models.py`.

    **"Normal" nao e "sempre", e a excecao esta medida** (fix da revisao,
    Minor 8): dois turnos concorrentes da mesma conversa, ambos fora de
    escopo, podem deixar o contador em 1 depois do zero -- o segundo espera o
    cadeado de linha que `gravar_intencao` tomou, le o zero e grava 1. Zerar
    aqui tambem nao consertaria isso -- entre o encerramento e a reabertura,
    seja pela janela de 30 dias vencida, seja pelo pedido de humano que reabre
    em minutos (`agente/turno.py`), nada escreve o contador -- e
    acrescentaria a esta funcao uma escrita numa tabela de outro modulo. O
    custo do caso raro e o lead ter duas tentativas em vez de tres; o
    comentario do encerramento em `agente/turno.py` guarda a conta.
    """
    await session.execute(
        update(Conversa)
        .where(Conversa.channel == channel, Conversa.conversation_key == conversation_key)
        # `str(...)` pela mesma razao do `valores` de `encerrar_conversa`
        # acima: `Status` e StrEnum, e gravar o literal mantem a coluna no
        # mesmo formato dos dois lados.
        .values(status=str(Status.ATIVA), motivo_do_encerramento=None, encerrada_em=None)
    )
