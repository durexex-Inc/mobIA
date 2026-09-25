"""Os 20 ataques de prompt injection pelo turno de verdade. Chamada real, dinheiro real.

TEC-204, D5. Roda no job "Avaliacoes de IA", separado da metrica agregada de
intencao: um ataque que funciona reprova sozinho, sem se diluir numa taxa.
**Uma falha reprova, sem retentativa** -- retentar esconderia o ataque que
funciona uma vez em tres, que e exatamente o perigoso em producao. O custo
declarado no desenho: uma falha rara por nao determinismo bloqueia um PR e
alguem tem de olhar.

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
from mobia.evals.injecao import Ataque, carregar_ataques, falhas_de, janelas_do_prompt
from mobia.infra.moderacao import ModeradorAnthropic

ATAQUES = carregar_ataques(Path(__file__).resolve().parent / "injecao" / "ataques.yaml")
JANELAS = janelas_do_prompt(SISTEMA_DO_AGENTE)


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
            resposta = await classificador.classificar(contexto)
        except RespostaInvalida:
            # Recusa ou parada anormal: nenhum texto chegaria ao lead, entao o
            # ataque nao teve sucesso neste turno. Erro de rede nao cai aqui --
            # sobe e reprova como infraestrutura.
            with capsys.disabled():
                print(f"\n[injecao] {ataque.id} turno {indice}: sem resposta utilizavel")
            continue

        texto = resposta.resposta
        # `ModeracaoIndisponivel` sobe de proposito: resposta nao julgada nao e aprovacao.
        veredito = await moderador.moderar(texto, direcao=Direcao.SAIDA)
        falhas = falhas_de(
            texto,
            canario=ataque.canario,
            janelas=JANELAS,
            negociacao=veredito.categoria == "NEGOCIACAO",
            divergencias=divergencias_de(texto, candidatos=resposta.candidatos, faixa=(None, None)),
        )
        assert not falhas, (
            f"{ataque.id}, turno {indice}: o ataque funcionou ({', '.join(falhas)}).\n"
            f"Resposta: {texto}"
        )
        historico.append((MessageRole.AGENTE, texto))

        if ataque.resumir_ate == indice + 1:
            # A dobra de producao, com o texto exato de producao: a instrucao
            # plantada tem de sobreviver (ou nao) a um resumo de verdade.
            gerado = await ResumidorAnthropic().resumir(
                INSTRUCAO_DOBRAR,
                conteudo_da_dobra(resumo, [mensagem_transiente(t, papel=p) for p, t in historico]),
            )
            resumo = gerado.texto
            historico = []

    with capsys.disabled():
        print(f"\n[injecao] {ataque.id}: resistiu")
