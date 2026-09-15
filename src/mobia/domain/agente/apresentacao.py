"""A ficha do imovel e a legenda que o lead recebe. TEC-162.

Puro de proposito: nenhum I/O e **nenhum import de `domain/catalogo`**. Quem
traduz `Imovel` em `Ficha` e `ferramenta_de_busca.fichas_do_catalogo`, que e
o unico arquivo em que `domain/agente` toca `domain/catalogo` -- a invariante
esta no docstring dele, e quebra-la aqui a tornaria invisivel.

Todo texto daqui sai para o lead e por isso leva acento (TEC-267), com a
excecao de `m2`: nao ha vogal ali para acentuar, e trocar por `m²`
sobrescrito e mudanca de outra natureza. E a mesma disciplina de
`TEXTO_DA_BUSCA_INCONCLUSIVA` em `turno.py`, tambem acentuado desde a
TEC-267.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

# RN-04.2. O mesmo numero de `evals/metricas.MAX_CARACTERES_DA_RESPOSTA`, que
# mede a regra nas evals; este e o primeiro lugar de `src/` que a respeita por
# construcao. Nao e limite da Meta -- a legenda dela cabe 1024.
MAX_CARACTERES_DA_LEGENDA = 600

# Duas e nao quatro porque cinco linhas de ficha e o limite do que se le numa
# legenda de foto.
CARACTERISTICAS_NO_DESTAQUE = 2

# Publico pelo mesmo motivo de `prosa_que_cabe`, abaixo: `legenda_de` e o
# followup (TEC-184) montam a mesma juncao prosa+corpo e precisam do mesmo
# separador, sem duplicar o literal.
SEPARADOR_DA_PROSA = "\n\n"
_RETICENCIA = "..."


@dataclass(frozen=True, slots=True)
class Rentabilidade:
    """Os indicadores da RN-07.3, e so para a trilha do investidor. TEC-154.

    Objeto proprio, e nao tres campos soltos em `Ficha`: a docstring de la
    promete "os oito campos da RN-10.1", e este repo trata comentario
    desatualizado como defeito. `Ficha.rentabilidade is None` significa
    trilha PADRAO -- o que distingue "nao e investidor" de "e investidor e o
    catalogo nao tem o dado", dois estados que a mesma ficha precisa
    diferenciar porque o segundo imprime uma linha e o primeiro nao imprime
    nada.

    Os tres campos sao independentes, com UMA invariante: `yield_pct` nao
    nulo implica `aluguel_centavos` nao nulo. As combinacoes que existem:

    | aluguel | preco de venda | linha do aluguel   | ressalva |
    |---------|----------------|--------------------|----------|
    | tem     | tem            | valor E yield      | sim      |
    | tem     | nulo           | valor, sem yield   | sim      |
    | nulo    | qualquer       | `não informado`    | nao      |

    `custos_centavos` nao entra na tabela porque nao depende de nenhum dos
    dois: condominio e IPTU sao fato do catalogo, nao estimativa, e saem
    mesmo sem aluguel.
    """

    aluguel_centavos: int | None
    yield_pct: Decimal | None
    custos_centavos: int | None


@dataclass(frozen=True, slots=True)
class Ficha:
    """Os oito campos da RN-10.1, resolvidos e agnosticos de canal -- mais
    tres campos fora dessa contagem: `id`, `foto` e `rentabilidade`.
    `dataclasses.fields(Ficha)` devolve onze ao todo, nao dez.

    `id` existe para quem opera, nao para o lead: fix wave da TEC-162
    (Minor). Sem ele, `turno.py` nao tinha como dizer QUAL imovel sumiu do
    catalogo entre a busca e a apresentacao -- so quantos. `foto` e a
    RN-10.2, uma regra sobre midia e canal, nao um dos oito campos
    descritivos da RN-10.1 -- por isso tambem fica de fora da contagem.

    `rentabilidade` fica de fora da contagem "os oito" de proposito: e o
    bloco do investidor da RN-07.3, uma regra diferente da RN-10.1, e so
    existe (nao-`None`) na trilha do investidor -- ver a docstring de
    `Rentabilidade`. Omiti-lo aqui pareceria descuido a quem conta os campos
    e encontra onze; a conta fecha porque `id` e `foto` tambem estao de fora
    dos oito, cada um pela sua propria razao.

    Dois dos oito campos sao opcionais -- `condominio_centavos` e
    `diferencial` -- porque o catalogo os tem vazios de verdade:
    `diferencial` fica `None` em 117 dos 520 imoveis do seed, que nao tem
    caracteristica nenhuma. Ausencia omite a linha e nunca esconde o imovel,
    que e a regra da propria RN-10.2 sobre foto.
    """

    id: uuid.UUID
    titulo: str
    bairro: str
    preco_centavos: int
    quartos: int
    vagas: int
    area_util_m2: int
    condominio_centavos: int | None
    diferencial: str | None
    foto: str | None
    # TEC-154. `None` e a trilha PADRAO, e nao "investidor sem dado" -- ver a
    # docstring de `Rentabilidade`. Com default e no fim de proposito: `Ficha`
    # e `slots=True` e toda construcao existente tem de seguir valida.
    rentabilidade: Rentabilidade | None = None


def reais_de(centavos: int) -> str:
    """`R$ 516.464` a partir de 51646430.

    Trunca os centavos para BAIXO e nunca arredonda: arredondar para cima
    cota ao lead um preco acima do real, e e essa a direcao que vira
    reclamacao na visita. O seed tem preco com centavos de verdade
    (`516464.30`), entao isto nao e hipotese.
    """
    return f"R$ {centavos // 100:,}".replace(",", ".")


def yield_bruto_anual(
    aluguel_centavos: int | None, preco_venda_centavos: int | None
) -> Decimal | None:
    """O yield bruto anual em pontos percentuais, ou `None` sem os dois precos.

    `aluguel * 12 / preco_venda`, que e a RN-07.3 literal.

    **Trunca para BAIXO, como `reais_de` faz com centavos, e pelo argumento
    invertido:** arredondar preco para cima cota ao lead acima do real;
    arredondar yield para cima PROMETE retorno acima do real. 4,3479% sai
    como 4,3, nunca 4,4.

    **Zero entra pela mesma porta que `None`.** Preco de venda zero daria
    ZeroDivisionError e derrubaria a apresentacao inteira por causa de um
    imovel -- `ck_imoveis_ao_menos_um_preco` recusa NULL nos dois, nao zero
    num deles. Aluguel zero nao e indicador de rentabilidade, e omitir e mais
    honesto que exibir "0,0% ao ano".

    **Quem passa o preco de venda e `fichas_do_catalogo`, lendo
    `Imovel.preco_venda` -- nunca `Ficha.preco_centavos`**, que e o preco da
    operacao BUSCADA: num investidor que buscasse ALUGUEL ele e o aluguel, e
    a conta daria 1200% ao ano numa ficha que o lead le como fato.
    """
    if not aluguel_centavos or not preco_venda_centavos:
        return None
    bruto = Decimal(aluguel_centavos) * 12 * 100 / Decimal(preco_venda_centavos)
    return bruto.quantize(Decimal("0.1"), rounding=ROUND_DOWN)


def custos_recorrentes(condominio_centavos: int | None, iptu_centavos: int | None) -> int | None:
    """Condominio somado ao IPTU, ou `None` quando os DOIS faltam.

    Um so ausente nao zera o outro: somar apenas o que existe e o que mantem
    a linha verdadeira. `None` nos dois omite a linha, como `condominio` ja
    faz na ficha padrao.
    """
    if condominio_centavos is None and iptu_centavos is None:
        return None
    return (condominio_centavos or 0) + (iptu_centavos or 0)


def diferencial_de(caracteristicas: Sequence[str]) -> str | None:
    """As duas primeiras caracteristicas, na ordem em que o catalogo as guarda.

    Ordem armazenada e nao ranking: quem quiser priorizar muda o CSV. `None`
    quando nao ha nenhuma, e `legenda_de` omite a linha.
    """
    escolhidas = tuple(caracteristicas)[:CARACTERISTICAS_NO_DESTAQUE]
    if not escolhidas:
        return None
    return " e ".join(escolhidas)


def _pluralizado(quantidade: int, singular: str, plural: str) -> str:
    """`singular` quando `quantidade == 1`, `plural` em qualquer outro caso.

    Zero fica com o plural de proposito ("0 quartos", "0 vagas") -- e a forma
    que um TERRENO usa de verdade, e se aquela linha deveria sumir inteira
    quando os dois campos sao zero e questao de produto que esta correcao nao
    resolve. So o "1" tem forma propria em portugues.
    """
    return singular if quantidade == 1 else plural


# RN-07.5 e RN-04.4 na mesma frase: "estimativa" cobre a ressalva de que o
# numero e estimado, e "nao e garantia" cobre a proibicao de apresentar
# rentabilidade como garantida. Texto do CODIGO, nao do modelo -- precedente
# do aviso de ampliacao (TEC-160) e do motivo de match (TEC-163): texto de
# modelo some num turno e muda de palavra no outro, e aqui o que sumiria e
# justamente a ressalva.
RESSALVA_DE_ESTIMATIVA = "Estimativa, não é garantia de retorno."

# Cenario 3 do Gherkin. NAO e silencio: medido no seed, 375 dos 520 imoveis
# caem aqui -- os que nao tem `preco_aluguel` --, e uma linha ausente
# pareceria esquecimento nosso em vez de lacuna do catalogo. Os outros 92 que
# tambem nao mostram yield (tem aluguel, mas nao tem `preco_venda`) NAO caem
# aqui: eles tem o dado, entram no `else` abaixo e saem com o valor do
# aluguel, so sem o sufixo do yield.
_ALUGUEL_AUSENTE = "Aluguel estimado: não informado"


def _linhas_da_rentabilidade(rentabilidade: Rentabilidade) -> list[str]:
    """As ate tres linhas do bloco do investidor, na ordem em que saem.

    A ressalva acompanha QUALQUER numero estimado -- o aluguel sozinho ja e
    um --, e nao so o yield. Sem numero nenhum ela nao sai.
    """
    linhas: list[str] = []
    # Falsy e nao `is None`: `yield_bruto_anual` ja trata aluguel zero como
    # ausente ("omitir e mais honesto que exibir 0,0% ao ano", na docstring
    # dela) e o `CHECK` do banco nao proibe zero -- so NULL. Duas regras
    # diferentes para o mesmo valor no mesmo modulo seriam a inconsistencia,
    # e aqui as duas checagens de `aluguel_centavos` (esta e a da ressalva,
    # abaixo) tem de concordar com aquela.
    if not rentabilidade.aluguel_centavos:
        linhas.append(_ALUGUEL_AUSENTE)
    else:
        linha = f"Aluguel estimado {reais_de(rentabilidade.aluguel_centavos)}"
        if rentabilidade.yield_pct is not None:
            # Virgula decimal porque o lead e brasileiro, e `:.1f` para o zero
            # a direita: "6%" e "6,0%" dizem coisas diferentes sobre precisao.
            percentual = f"{rentabilidade.yield_pct:.1f}".replace(".", ",")
            linha += f" - yield bruto {percentual}% ao ano"
        linhas.append(linha)
    if rentabilidade.custos_centavos is not None:
        # O rotulo nomeia dois componentes (condominio e IPTU) mas reporta um
        # numero so: se `iptu_mensal` for NULL, `custos_recorrentes` cai para
        # so o condominio e esta linha repete o valor da linha `Condomínio`
        # acima -- o lead le isso como "IPTU = 0". Inalcancavel no seed (as
        # 520 linhas tem os dois campos preenchidos), mas o schema permite, e
        # decidimos nao desdobrar o rotulo em dois so por essa lacuna hoje
        # hipotetica.
        linhas.append(f"Condomínio + IPTU {reais_de(rentabilidade.custos_centavos)}/mês")
    if rentabilidade.aluguel_centavos:
        linhas.append(RESSALVA_DE_ESTIMATIVA)
    return linhas


def legenda_de(ficha: Ficha, *, prefixo: str | None = None) -> str:
    """A legenda de uma ficha, com a prosa do modelo opcionalmente na frente.

    Estourado o teto, o que se corta e o PREFIXO -- nunca a ficha. A ficha
    carrega o que a RN-10.1 exige e, na trilha do investidor, o bloco da
    RN-07.3 tambem: os dois sao conteudo e nenhum dos dois cede espaco, so a
    prosa e ornamento -- essa ordem de prioridade e a D14 do desenho.
    """
    quartos = _pluralizado(ficha.quartos, "quarto", "quartos")
    vagas = _pluralizado(ficha.vagas, "vaga", "vagas")
    linhas = [
        ficha.titulo,
        f"{ficha.bairro} - {reais_de(ficha.preco_centavos)}",
        f"{ficha.quartos} {quartos} - {ficha.vagas} {vagas} - {ficha.area_util_m2} m2",
    ]
    if ficha.condominio_centavos is not None:
        linhas.append(f"Condomínio {reais_de(ficha.condominio_centavos)}")
    if ficha.diferencial is not None:
        linhas.append(f"Destaque: {ficha.diferencial}")
    if ficha.rentabilidade is not None:
        # No CORPO, e nao no prefixo: e o que faz `prosa_que_cabe` proteger o
        # bloco de graca quando o teto de 600 aperta. A prioridade da D14
        # (corta-se a prosa, nunca a ficha) segue valendo sem mudanca.
        linhas.extend(_linhas_da_rentabilidade(ficha.rentabilidade))
    corpo = "\n".join(linhas)

    prosa = prosa_que_cabe(prefixo, len(corpo)) if prefixo else ""
    if not prosa:
        return corpo
    return f"{prosa}{SEPARADOR_DA_PROSA}{corpo}"


def prosa_que_cabe(prefixo: str, tamanho_do_corpo: int) -> str:
    """O prefixo truncado na ultima fronteira de palavra que couber.

    Devolve string vazia quando nao sobra espaco nem para a reticencia --
    prosa cortada no meio de uma palavra sem marca nenhuma pareceria bug ao
    lead, e a ficha nunca cede espaco para evitar isso.

    Publica porque tem dois consumidores: `legenda_de` acima e
    `mensagem.texto_do_followup` (TEC-184), que aplica o mesmo teto de 600
    caracteres ao prefixo do follow-up. A aritmetica do corte -- separador,
    fronteira de palavra, reticencia -- mora so aqui.
    """
    disponivel = MAX_CARACTERES_DA_LEGENDA - tamanho_do_corpo - len(SEPARADOR_DA_PROSA)
    if len(prefixo) <= disponivel:
        return prefixo
    if disponivel <= len(_RETICENCIA):
        return ""
    return prefixo[: disponivel - len(_RETICENCIA)].rsplit(" ", 1)[0] + _RETICENCIA
