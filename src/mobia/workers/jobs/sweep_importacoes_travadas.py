"""A varredura que encerra importacao de catalogo parada em PROCESSANDO. TEC-261."""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text

from mobia.app.config import Settings, get_settings

log = structlog.get_logger(__name__)

# Nao nomeia a causa -- worker caido, fila perdida, tempo estourado sao
# indistinguiveis daqui, e afirmar uma seria inventar. Diz o que aconteceu e o
# que fazer, porque quem le o relatorio e o administrador, nao quem opera.
MOTIVO_DA_VARREDURA = (
    "O processamento nao terminou e a importacao foi encerrada pela varredura. Reimporte o arquivo."
)

# **Um statement, e nao as duas fases da `sweep_stalled`.** La o SELECT e
# commitado antes do enqueue porque ha I/O de rede no meio, e o docstring dela
# explica o preco de segurar lock de linha enquanto se fala com o Redis. Aqui
# nao ha I/O nenhum: le e escreve a mesma tabela.
#
# Com um statement, o quarto cenario do Gherkin -- duas varreduras concorrentes
# nao encerram a mesma linha duas vezes -- sai por construcao. Copiar as duas
# fases faria o oposto: abriria uma janela entre o commit do SELECT e o UPDATE
# em que a segunda varredura ainda leria `PROCESSANDO`.
#
# `CAST(:erro AS jsonb)` e nao o parametro cru: `erros` e JSONB, e um `text()`
# com parametro nao converte lista Python por este caminho.
_ENCERRAR_TRAVADAS = text(
    """
    UPDATE importacoes
       SET status = 'FALHOU',
           concluida_em = now(),
           erros = CAST(:erro AS jsonb)
     WHERE id IN (
             SELECT id
               FROM importacoes
              WHERE status = 'PROCESSANDO'
                AND criada_em < now() - make_interval(secs => :travada_after)
              ORDER BY criada_em
              LIMIT :limite
                FOR UPDATE SKIP LOCKED
           )
    RETURNING id
    """
)


async def sweep_importacoes_travadas(ctx: dict[str, Any], limite: int = 100) -> int:
    """Encerra em FALHOU a importacao que parou de andar. Devolve quantas.

    `PROCESSANDO` tem dois significados e nada os distingue: "o worker esta
    trabalhando nisso" e "o worker morreu e ninguem vai voltar". A TEC-156
    fechou o caso do enqueue que FALHA (`_marcar_falha`, em
    `api/routes/imoveis.py`); fica este, o do enqueue que deu certo e do
    processamento que nao terminou -- worker caido, fila perdida, tempo
    estourado sem retry.

    **Marca FALHOU, nao reenfileira.** Reenfileirar exigiria uma coluna de
    tentativas que `importacoes` nao tem: a `sweep_stalled` depende de
    `messages.attempts` para nao entrar em laco, e aqui nao ha equivalente.
    Marcar e mais honesto -- o relatorio passa a dizer "nao terminou" em vez de
    mentir "processando".

    **Grava o mesmo formato de `_marcar_falha`**: `FALHOU`, `concluida_em` e um
    erro na linha 0. A convencao da linha 0 e da TEC-156, para falha de arquivo
    inteiro, e ja existia antes desta card.

    **Substituir `erros` em vez de anexar e seguro**, e a razao e verificavel:
    `catalogo/importacao.py` grava o relatorio de uma vez so, no fim. Uma linha
    travada nunca chegou la, entao `erros` esta vazio.

    **A corrida que fica.** Se algo exceder o limite e o job ainda estiver vivo
    quando esta varredura fechar a linha, o job sobrescreve com o resultado
    verdadeiro no fim -- `catalogo/importacao.py` grava sem olhar o estado atual
    da linha. O sistema se cura e o desfecho final e o certo; esta escrito aqui
    para ninguem descobrir isso num incidente e achar que e defeito.

    **NAO limpa `importacoes.arquivo`.** A retencao dos bytes esta fora do
    escopo da card, entao a linha encerrada continua segurando ate 10 MB. E
    lacuna conhecida, nao esquecimento.
    """
    session_factory = ctx["session_factory"]
    settings: Settings = ctx.get("settings") or get_settings()

    async with session_factory() as session:
        resultado = await session.execute(
            _ENCERRAR_TRAVADAS,
            {
                "erro": json.dumps([{"linha": 0, "motivo": MOTIVO_DA_VARREDURA}]),
                "travada_after": settings.sweep_importacao_travada_after_seconds,
                "limite": limite,
            },
        )
        ids: list[uuid.UUID] = [linha[0] for linha in resultado.fetchall()]
        await session.commit()

    if ids:
        # `error`, e nao `info` como o `sweep.requeued` da `sweep_stalled`: la o
        # desfecho e recuperacao (a mensagem volta para a fila), aqui e
        # terminal. O administrador perdeu o trabalho e vai precisar reimportar.
        # Mesmo nivel que `catalogo.importacao_nao_enfileirada`, que e o irmao
        # deste caso na TEC-156.
        log.error(
            "catalogo.importacoes_travadas_encerradas",
            count=len(ids),
            importacao_ids=[str(i) for i in ids],
        )
    return len(ids)
