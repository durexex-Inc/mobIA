"""Os 20 ataques de prompt injection pelo turno de verdade. Chamada real, dinheiro real.

TEC-204, D5. Roda no job "Avaliacoes de IA", separado da metrica agregada de
intencao: um ataque que funciona reprova sozinho, sem se diluir numa taxa.
**Um veredito de ataque reprova, sem retentativa** -- retentar esconderia o
ataque que funciona uma vez em tres, que e exatamente o perigoso em
producao. O custo declarado no desenho: uma falha rara por nao determinismo
bloqueia um PR e alguem tem de olhar.

**Excecao decidida em 26/09/2026: falha de transporte (rede, timeout) do SDK
da Anthropic tenta de novo, ate duas vezes por chamada, antes de propagar** --
`mobia.evals.injecao.com_retentativa_de_transporte`. So essa forma de falha;
o veredito do ataque, `RespostaInvalida` e `ModeracaoIndisponivel` fora do
protocolo nunca retentam.

O turno e `ClassificadorAnthropic.classificar` sobre `montar_prompt`, o mesmo
de producao, sem porta de busca -- como `test_acuracia_de_intencao.py`. O
veredito e `mobia.evals.injecao.falhas_de`, testado sem modelo em
`tests/unit/test_evals_injecao.py`. Custo por execucao: ~25 chamadas ao
classificador (20 ataques mais os turnos extras dos dois multi-turno), uma ao
resumidor e ~24 a moderacao de saida, no modelo mais barato.
"""

from pathlib import Path

import pytest

from mobia.domain.agente.citacao import divergencias_de
from mobia.domain.agente.classificador import (
    SISTEMA_DO_AGENTE,
    ClassificadorAnthropic,
    RespostaInvalida,
)
from mobia.domain.context.montagem import conteudo_da_dobra
from mobia.domain.context.resumo import INSTRUCAO_DOBRAR, ResumidorAnthropic
from mobia.domain.messages.enums import MessageRole
from mobia.domain.moderacao.port import Direcao
from mobia.evals.contexto import contexto_do_historico, mensagem_transiente
from mobia.evals.injecao import (
    Ataque,
    carregar_ataques,
    com_retentativa_de_transporte,
    falhas_de,
    janelas_do_prompt,
)
from mobia.infra.moderacao import ModeradorAnthropic

ATAQUES = carregar_ataques(Path(__file__).resolve().parent / "injecao" / "ataques.yaml")
JANELAS = janelas_do_prompt(SISTEMA_DO_AGENTE)

# `get_client` (infra/anthropic.py) e `get_moderation_client` (infra/moderacao.py)
# sao @lru_cache: o AsyncAnthropic (e o pool httpx por baixo) e criado uma vez
# e reusado pela sessao inteira. O default do projeto e um event loop por
# teste (`asyncio_default_fixture_loop_scope = "function"`), e com 20 testes
# assincronos separados isso reusa o cliente cacheado em loops diferentes --
# uma conexao mantida viva de um loop ja fechado quebra com "Event loop is
# closed" no loop seguinte. Um loop por MODULO mantem os 20 ataques no mesmo
# loop em que o cliente foi criado, igual a `test_acuracia_de_intencao.py`
# (uma unica funcao de teste, um unico loop para todo o corpus).
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.mark.parametrize("ataque", ATAQUES, ids=[a.id for a in ATAQUES])
async def test_o_ataque_nao_funciona(ataque: Ataque, capsys) -> None:
    classificador = ClassificadorAnthropic()
    moderador = ModeradorAnthropic()
    historico: list[tuple[MessageRole, str]] = []
    resumo: str | None = None

    for indice, fala in enumerate(ataque.turnos):
        historico.append((MessageRole.LEAD, fala))
        contexto = contexto_do_historico(historico, sistema=SISTEMA_DO_AGENTE, resumo=resumo)
        try:
            # So a falha de transporte retenta (decisao de 26/09/2026); recusa,
            # parada anormal ou qualquer outro RespostaInvalida cai direto no
            # except abaixo, sem segunda chance.
            resposta = await com_retentativa_de_transporte(
                lambda contexto=contexto: classificador.classificar(contexto)
            )
        except RespostaInvalida:
            # Recusa ou parada anormal: nenhum texto chegaria ao lead, entao o
            # ataque nao teve sucesso neste turno. Erro de rede nao cai aqui --
            # ja tentou de novo acima e, esgotada a retentativa, sobe e reprova
            # como infraestrutura. Sem `continue`: a fala do lead fica na
            # transcricao com ou sem resposta, e a dobra abaixo tem de
            # roda-la -- pular a dobra no turno que planta a instrucao
            # imprimiria "resistiu" sem o resumo ter sido exercitado.
            with capsys.disabled():
                print(f"\n[injecao] {ataque.id} turno {indice}: sem resposta utilizavel")
        else:
            texto = resposta.resposta
            # `ModeracaoIndisponivel` sobe de proposito quando fora do
            # protocolo: resposta nao julgada nao e aprovacao. Quando a causa e
            # transporte, `com_retentativa_de_transporte` ja tentou de novo.
            veredito = await com_retentativa_de_transporte(
                lambda texto=texto: moderador.moderar(texto, direcao=Direcao.SAIDA)
            )
            falhas = falhas_de(
                texto,
                canario=ataque.canario,
                janelas=JANELAS,
                negociacao=veredito.categoria == "NEGOCIACAO",
                divergencias=divergencias_de(
                    texto, candidatos=resposta.candidatos, faixa=(None, None)
                ),
            )
            assert not falhas, (
                f"{ataque.id}, turno {indice}: o ataque funcionou ({', '.join(falhas)}).\n"
                f"Resposta: {texto}"
            )
            historico.append((MessageRole.AGENTE, texto))

        if ataque.resumir_ate == indice + 1:
            # A dobra de producao, com o texto exato de producao: a instrucao
            # plantada tem de sobreviver (ou nao) a um resumo de verdade. Mesma
            # retentativa de transporte das duas chamadas acima -- e o mesmo
            # SDK, a mesma rede.
            conteudo = conteudo_da_dobra(
                resumo, [mensagem_transiente(t, papel=p) for p, t in historico]
            )
            gerado = await com_retentativa_de_transporte(
                lambda conteudo=conteudo: ResumidorAnthropic().resumir(INSTRUCAO_DOBRAR, conteudo)
            )
            resumo = gerado.texto
            historico = []

    with capsys.disabled():
        print(f"\n[injecao] {ataque.id}: resistiu")
