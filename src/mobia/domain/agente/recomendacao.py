"""As regras puras da recomendacao e da reacao do lead.

TEC-163. Sem I/O e sem banco: o que precisa de sessao mora em
`repositorio.py`, e o que precisa do modelo mora em `classificador.py`. Aqui
ficam as decisoes que se testam sem nada de pe.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from mobia.domain.agente.schemas import CategoriaDescarte, ReacaoDoImovel

_SEM_CRITERIO = "sem filtro: o lead nao restringiu a busca"


def motivo_do_match(criterios: Sequence[str]) -> str:
    """A frase de explicabilidade da RN-10.3, montada dos criterios da busca.

    **Derivada, nunca escrita pelo modelo (D5).** Um motivo inventado ficaria
    gravado no banco como se fosse fato, e explicabilidade falsa e pior que
    explicabilidade pobre: a pobre se reconhece, a falsa nao.

    **E por BUSCA e nao por imovel (D4).** Todos os candidatos de uma busca
    casaram o mesmo filtro; o que os distingue e o `score_match`, que tem
    coluna propria. Um motivo por candidato seria a mesma frase repetida tres
    vezes, paga em tokens no `tool_result` de todo turno que busca.

    Lista vazia devolve uma frase e nao string vazia: a coluna e NOT NULL, e
    um campo de explicabilidade em branco deixa quem le a linha meses depois
    sem saber se nao houve filtro ou se alguem esqueceu de gravar.
    """
    return ", ".join(criterios) if criterios else _SEM_CRITERIO


def resolver_ordinais(
    reacoes: Sequence[ReacaoDoImovel], apresentados: Sequence[uuid.UUID]
) -> tuple[tuple[uuid.UUID, ReacaoDoImovel], ...]:
    """Casa cada reacao com o imovel daquela posicao. D7.

    **Ordinal fora de 1..N sai, e os outros ficam.** Um ordinal inventado nao
    pode invalidar as reacoes que o modelo acertou: o lead perderia a opiniao
    correta junto com a errada, e o turno nao tem como perguntar de novo.

    A guarda e `1 <= ordinal <= len(apresentados)` e nao um `try/except
    IndexError`, porque `apresentados[-1]` em Python devolve o ULTIMO item em
    vez de levantar -- um ordinal negativo marcaria o imovel errado, em
    silencio, e o lead veria a reacao dele aplicada a outro imovel.
    """
    return tuple(
        (apresentados[reacao.ordinal - 1], reacao)
        for reacao in reacoes
        if 1 <= reacao.ordinal <= len(apresentados)
    )


@dataclass(frozen=True, slots=True)
class DescartePorBairro:
    """Um descarte lido do banco, com o bairro (dobrado) e a categoria dele. TEC-163.

    **`bairro` chega SEMPRE dobrado.** Vem de `Imovel.bairro_busca`
    (`repositorio.ler_descartes_por_distancia`), a mesma coluna que
    `FiltroDeBusca.bairros_excluidos` compara -- ver o docstring daquele
    campo em `catalogo/schemas.py`. Dobrar de novo aqui seria custo sem
    efeito, mas dobrar SO deste lado e nao do outro foi exatamente o defeito
    que a TEC-160 pagou com um Critical: a metade de bairros da RN-09.3 saiu
    desligada, calada, com 1534 testes verdes, porque so um lado do
    `in`/`not in` estava dobrado.

    `categoria` e `None` quando o lead descartou sem dizer por que --
    `ReacaoDoImovel.categoria` e opcional, e um descarte sem motivo nao pode
    contar para nenhuma contagem (ver `bairros_a_excluir`).
    """

    bairro: str
    categoria: CategoriaDescarte | None


# RN-10.4. Um descarte pode ser sobre a foto, o andar ou o condominio -- so
# dois na MESMA direcao viram sinal. Nomeado e nao literal porque
# `bairros_a_excluir` o cita duas vezes (a comparacao e o motivo na
# docstring), e um numero repetido nos dois lugares diverge no dia em que
# alguem mudar um so.
LIMIAR_DE_DESCARTES = 2


def bairros_a_excluir(descartes: Sequence[DescartePorBairro]) -> tuple[str, ...]:
    """Os bairros que RN-10.4 tira das buscas seguintes desta conversa.

    **So conta descarte de categoria `DISTANCIA`.** Um descarte por preco ou
    por tamanho nao diz nada sobre o BAIRRO -- conta-lo estreitaria a busca
    por um motivo que o lead nunca deu. Pelo mesmo raciocinio, um descarte
    SEM categoria (`None`) tambem nao conta: sem motivo registrado nao ha
    como saber que foi sobre distancia, e contar mesmo assim estreitaria a
    busca pelo motivo errado.

    **O filtro de categoria mora aqui, nao na consulta.** `repositorio.
    ler_descartes_por_distancia` le TODO descarte da conversa, de qualquer
    categoria -- e esta funcao, que se testa sem banco nenhum, quem decide o
    que conta. A regra fica no unico lugar de onde `test_recomendacao_
    regras.py` a exercita.

    O limiar e `>=` e nao `>`: dois descartes JA e o sinal, o terceiro nao
    adiciona nada de novo a decisao.
    """
    contagem: dict[str, int] = {}
    for descarte in descartes:
        if descarte.categoria is not CategoriaDescarte.DISTANCIA:
            continue
        contagem[descarte.bairro] = contagem.get(descarte.bairro, 0) + 1
    return tuple(bairro for bairro, total in contagem.items() if total >= LIMIAR_DE_DESCARTES)
