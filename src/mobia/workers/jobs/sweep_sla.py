"""O job que escala o handoff vencido e recupera o handoff perdido sem prazo. TEC-178, TEC-279."""

from typing import Any

from mobia.domain.handoff.escalada import escalar_vencidos
from mobia.domain.handoff.recuperacao import recuperar_sem_prazo

SWEEP_SLA_JOB = "sweep_sla"


async def sweep_sla(ctx: dict[str, Any], limite: int = 100) -> int:
    """Escala os vencidos e recupera os perdidos. Devolve quantos ao todo.

    **Duas varreduras, nao uma.** `escalar_vencidos` (TEC-178) pega o handoff
    que TEM prazo e o estourou; `recuperar_sem_prazo` (TEC-279) pega o que
    nunca ganhou prazo porque o enfileiramento da notificacao falhou. Os
    conjuntos sao disjuntos por construcao -- um exige `sla_limite_em IS NOT
    NULL` e o outro `IS NULL` --, entao **a ordem e indiferente para a
    SELECAO**: nenhuma das duas seleciona o que a outra pegaria. Nao e
    indiferente para a FALHA -- as duas chamadas sao sequenciais e sem
    isolamento entre si, entao `escalar_vencidos` levantando uma excecao mata
    a recuperacao desta mesma passagem.

    O retorno e a soma porque o numero do job e "quantos handoffs esta
    passagem tocou". Nenhuma das duas funcoes loga um numero: cada uma loga
    uma linha por handoff (`handoff.escalado`/`handoff.escalado_sem_gerente`
    e `handoff.recuperado_sem_prazo`), entao a informacao continua ali, so
    que como contagem de linhas, nao como um campo no log.

    Tudo vem do `ctx`, no mesmo molde de `notificar_corretor`: e o `startup`
    do worker que decide a implementacao, e o teste troca a decisao sem tocar
    neste job.
    """
    escalados = await escalar_vencidos(
        ctx["session_factory"], canais=ctx["canais_de_notificacao"], limite=limite
    )
    recuperados = await recuperar_sem_prazo(
        ctx["session_factory"], reenfileirador=ctx["reenfileirador"], limite=limite
    )
    return escalados + recuperados
