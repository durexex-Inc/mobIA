"""O que se pede a lista de leads, e onde a pagina seguinte comeca. TEC-192.

Modulo sem I/O, no molde de `metricas/filtros.py`: e o que deixa a forma do
cursor e a validacao do filtro serem testadas em `tests/unit/`, sem Postgres de
pe. Quem toca o banco e `repositorio.py`, ao lado.
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

# Teto de itens por pagina. O SRS escreve `limite=25` no exemplo da secao 6.2;
# o teto existe para que `?limite=100000` nao vire uma consulta que agrega
# `messages` inteira e devolve tudo numa resposta so.
LIMITE_PADRAO = 25
LIMITE_MAXIMO = 100


class FiltroInvalido(ValueError):
    """Pedido que a borda recusa com 422, e nao lista vazia.

    Mesma decisao de `metricas/filtros.py`: uma lista vazia se leria como "nao
    ha lead assim", que e afirmacao sobre o negocio -- e o erro e de quem
    chamou.
    """


class Ordem(StrEnum):
    """As ordens da lista. TEC-321, D4, e o `ordenar` da secao 6.2 do SRS.

    Os valores sao os nomes que o SRS ja escreve (`?ordenar=score_desc`). Nas
    duas ordens o desempate e o par, pela razao da D5 da TEC-192: empate
    tambem acontece no instante, porque duas falas podem cair no mesmo
    microssegundo.
    """

    SCORE = "score_desc"
    ULTIMA_INTERACAO = "ultima_interacao_desc"


@dataclass(frozen=True)
class Cursor:
    """Onde a pagina seguinte comeca: o ULTIMO item da pagina atual.

    **Os dois campos juntos, e nao so o score** (D5 do desenho). Score e
    inteiro de 0 a 100 numa base de milhares: empate e o caso comum, nao a
    borda. Sem um desempate estavel, duas paginas trazem a mesma linha -- que e
    exatamente o que o quarto cenario do Gherkin verifica.

    **O desempate viajava como o par `(channel, conversation_key)` ate a
    TEC-195**, e o par era o telefone do lead no WhatsApp (ate a TEC-203, que
    o trocou pelo HMAC do telefone). `codificar` e base64,
    que qualquer um decodifica, entao `proximoCursor` entregava o telefone a
    quem nao pode le-lo -- o mesmo vazamento do `conversationKey` no item, por
    um campo em que ninguem olhava. Agora viaja o apelido opaco de
    `referencias_de_lead`, e quem volta ao par e o servidor.

    `score` nulavel porque lead sem pontuacao entra na lista (D4), e a pagina
    pode terminar num deles.

    **O cursor carrega a ordem em que nasceu** (TEC-321, D4). Na ordem por
    ultima interacao, o que se compara e `ultima_interacao_em`, e `score` fica
    nulo. Um cursor usado na outra ordem e recusado em `montar_filtro`.
    """

    score: int | None
    lead_id: uuid.UUID
    ordem: Ordem = Ordem.SCORE
    ultima_interacao_em: datetime | None = None

    def codificar(self) -> str:
        """base64 de um JSON. **Opaco de proposito.**

        Opaco nao e seguranca -- qualquer um decodifica base64 -- e sim
        contrato: um cursor legivel vira um cursor que alguem monta a mao, e a
        partir dai a forma interna dele nao pode mais mudar sem quebrar
        cliente. O SRS ja o descreve assim ("proximoCursor": "opaco").

        **Desde a TEC-195 isso BASTA**, e antes nao bastava: o que trafega aqui
        ja nao e dado pessoal, entao a fragilidade do base64 deixou de ter
        consequencia. Um `lead_id` decodificado nao diz nada sobre o lead.
        """
        # O cursor de score continua com a forma `{"s","l"}` da TEC-195: a
        # TEC-321 acrescentou a segunda ordem sem invalidar cursor em uso.
        campos: dict[str, object]
        if self.ordem is Ordem.ULTIMA_INTERACAO and self.ultima_interacao_em is not None:
            campos = {"o": "u", "u": self.ultima_interacao_em.isoformat(), "l": str(self.lead_id)}
        else:
            campos = {"s": self.score, "l": str(self.lead_id)}
        corpo = json.dumps(campos, separators=(",", ":"))
        return base64.urlsafe_b64encode(corpo.encode("utf-8")).decode("ascii")


def decodificar_cursor(texto: str) -> Cursor:
    """O cursor que `codificar` produziu. Levanta `FiltroInvalido` para o resto.

    **Recusa, e nao volta para a primeira pagina.** Cursor corrompido significa
    que quem chamou perdeu o lugar; devolver a primeira pagina em silencio
    faria a tela mostrar o comeco da lista como se fosse a continuacao dela, e
    o defeito so apareceria como "a rolagem pulou para o topo sozinha".

    **`ValueError` no lugar dos tres nomes que estavam aqui.** `binascii.Error`,
    `UnicodeDecodeError` e `json.JSONDecodeError` sao todos subclasses dele, e
    a TEC-195 acrescentou um quarto caso com a mesma base -- `uuid.UUID` de um
    texto que nao e UUID. Listar os quatro daria a impressao de que a lista e
    exaustiva quando ela nunca foi. `KeyError` cobre o JSON bem formado com as
    chaves erradas, que e o caso de um cursor de uma VERSAO anterior deste
    formato -- inclusive o `{"s","c","k"}` de antes da TEC-195, que passa a ser
    recusado com 422.
    """
    try:
        corpo = json.loads(base64.urlsafe_b64decode(texto.encode("ascii")))
        if corpo.get("o") == "u":
            return Cursor(
                score=None,
                lead_id=uuid.UUID(corpo["l"]),
                ordem=Ordem.ULTIMA_INTERACAO,
                ultima_interacao_em=datetime.fromisoformat(corpo["u"]),
            )
        return Cursor(score=corpo["s"], lead_id=uuid.UUID(corpo["l"]))
    except (ValueError, KeyError, TypeError) as erro:
        raise FiltroInvalido("cursor invalido") from erro


@dataclass(frozen=True)
class RecorteDoPapel:
    """O que o PAPEL de quem chama impoe, por cima do que ele pediu. D7.

    **Objeto proprio, e nao um `corretor_id | None` solto**, porque os dois
    estados que um nulo teria de representar sao opostos: "nao ha recorte de
    papel" (um GERENTE, que ve tudo) e "ha recorte e o vinculo esta vazio" (um
    CORRETOR sem cadastro completo, que nao pode ver nada). Colapsados num
    nulo so, o segundo vira o primeiro -- que e fail-OPEN, e foi exatamente o
    defeito que `test_corretor_sem_vinculo_ve_lista_vazia` pegou na primeira
    implementacao desta card.
    """

    e_corretor: bool = False
    corretor_id: uuid.UUID | None = None

    @property
    def nao_ve_nada(self) -> bool:
        """CORRETOR sem vinculo. Cadastro incompleto nao e passe livre.

        Mesmo argumento da D4 da TEC-202: a diferenca entre "nao tem dono" e
        "e dono de tudo" e o erro que aquela card existe para nao cometer.
        """
        return self.e_corretor and self.corretor_id is None


# O recorte de quem nao e CORRETOR: nenhum. Constante de modulo e nao
# `RecorteDoPapel()` no default de `listar_leads`, porque a B008 recusa chamada
# em default de argumento -- e aqui ela tem razao, ja que a instancia seria
# criada uma vez no import de qualquer jeito.
SEM_RECORTE = RecorteDoPapel()


@dataclass(frozen=True)
class Filtro:
    """O recorte pedido. `corretor_id` aqui e o da QUERY, nao o do papel.

    **A distincao importa e esta na D7:** o recorte do papel `CORRETOR` e
    aplicado depois, pelo repositorio, sobre o que vier aqui -- mandar
    `corretorId=<outro>` na query nao alarga nada. Se os dois morassem no mesmo
    campo, o ultimo a escrever venceria, e qual seria o ultimo dependeria da
    ordem em que a rota monta o objeto.
    """

    busca: str | None = None
    status: str | None = None
    temperatura: str | None = None
    canal: str | None = None
    corretor_id: uuid.UUID | None = None
    limite: int = LIMITE_PADRAO
    cursor: Cursor | None = None
    ordem: Ordem = Ordem.SCORE


def montar_filtro(
    *,
    busca: str | None = None,
    status: str | None = None,
    temperatura: str | None = None,
    canal: str | None = None,
    corretor_id: uuid.UUID | None = None,
    limite: int = LIMITE_PADRAO,
    cursor: str | None = None,
    ordenar: str | None = None,
) -> Filtro:
    """Valida na borda o que o SQL nao valida sozinho.

    `status` e conferido contra o vocabulario porque um valor fora dele
    devolveria lista vazia -- que se leria como "nao ha lead ativo", e a razao
    de recusar em vez de devolver vazio e a mesma de `FiltroInvalido`.

    `temperatura` e `canal` NAO sao conferidos, e a assimetria e deliberada:
    `temperatura` tem vocabulario proprio em `context/temperatura.py`, mas a
    coluna aceita nulo e valores antigos, e `canal` cresce a cada integracao
    nova -- fixar a lista aqui obrigaria a mexer neste arquivo toda vez que um
    canal nascesse, para nao ganhar nada que a lista vazia nao diga.

    `ordenar` e conferido, e o cursor tem de ser da mesma ordem (TEC-321, D4):
    a ordem padrao em silencio, ou um cursor de score continuado por instante,
    devolveriam uma pagina plausivel e errada.
    """
    from mobia.domain.conversa.vocabulario import Status

    if not 1 <= limite <= LIMITE_MAXIMO:
        raise FiltroInvalido(f"limite fora da faixa 1..{LIMITE_MAXIMO}: {limite}")

    if status is not None and status not in {s.value for s in Status}:
        raise FiltroInvalido(f"status desconhecido: {status}")

    try:
        ordem = Ordem(ordenar) if ordenar is not None else Ordem.SCORE
    except ValueError as erro:
        raise FiltroInvalido(f"ordenacao desconhecida: {ordenar}") from erro

    posicao = decodificar_cursor(cursor) if cursor else None
    if posicao is not None and posicao.ordem is not ordem:
        raise FiltroInvalido("cursor de outra ordenacao")

    # `strip()` e depois "vazio vira None": uma busca de espacos em branco
    # filtraria por `%   %` e devolveria quase nada, o que pareceria base vazia.
    limpa = busca.strip() if busca is not None else None

    return Filtro(
        busca=limpa or None,
        status=status,
        temperatura=temperatura,
        canal=canal,
        corretor_id=corretor_id,
        limite=limite,
        cursor=posicao,
        ordem=ordem,
    )
