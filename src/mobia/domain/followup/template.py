"""A janela de 24h, o catalogo de templates e a escolha por contexto.

TEC-186, RN-13.6. Puro de proposito -- sem I/O, sem banco, sem chamada ao
modelo --, como `cadencia.py`, `mensagem.py` e `prosa.py`. Quem consulta o
banco, decide o canal e entrega e a varredura (`sweep_followups`).

**A janela e decidida A PARTIR DA ANCORA** (a ultima fala do lead), e nao do
relogio no adaptador do WhatsApp: fora dela nenhuma mensagem livre pode ser
tentada (CA-13.3), entao a decisao e tomada antes do envio. Ver a D1 do
desenho. Isto NAO contradiz a TEC-134, que decidiu nao pre-checar o relogio no
`_deliver`: aquilo e sobre o caminho de resposta normal, e aqui a ancora ja e
o fato que governa a cadencia inteira -- e a fonte, nao uma segunda copia dela.

**Qual template esta aprovado pela Meta e fato EXTERNO** (RT-03) e entra por
configuracao (`Settings.templates_aprovados`), nunca hard-coded: a card poe a
submissao dos templates fora de escopo, e o RT-03 avisa que a aprovacao pode
nao chegar no prazo do hackathon. O catalogo abaixo mantem os >= 3 templates
que a RN-13.6 pede; a aprovacao e injetada.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from mobia.domain.agente.apresentacao import Ficha, reais_de
from mobia.domain.followup.mensagem import QuedaDePreco

# A Meta so aceita mensagem livre dentro de 24h da ultima fala do lead; fora
# disso, so template aprovado. E a mesma janela que `outbound/whatsapp.py`
# nomeia pelo codigo 131047 -- la ela e o gatilho da recusa, aqui e a duracao.
JANELA_DE_SERVICO = timedelta(hours=24)

# Os tres contextos do follow-up (RN-13.2/13.6). Sao os mesmos tres que a
# TEC-184 ja escolhe como novidade -- queda de preco, imovel novo, convite.
CATEGORIA_QUEDA = "queda_de_preco"
CATEGORIA_IMOVEL_NOVO = "imovel_novo"
CATEGORIA_CONVITE = "convite"


def dentro_da_janela(*, ancora_em: datetime, agora: datetime) -> bool:
    """True quando ainda cabe mensagem livre. TEC-186, RN-13.6.

    **A borda e estrita (`<`).** Aos 24h exatos a janela ja fechou -- e a regra
    da Meta, e o cenario 4 do Gherkin cai exatamente nesse limite. Um `<=` aqui
    deixaria passar um envio livre que a Meta recusaria.

    **`ancora_em`, e nao a ultima mensagem da conversa.** A ancora e a ultima
    fala do LEAD (`candidatos_a_followup`), entao uma resposta do agente no
    meio nao move a janela -- e o cenario 4 do Gherkin exige exatamente isso.

    Tudo keyword-only: `ancora_em` e `agora` sao dois `datetime` adjacentes, e
    trocar a ordem devolveria o resultado errado em silencio, sem erro de tipo
    -- mesma razao de `tentativa_devida` (`cadencia.py`).
    """
    return agora - ancora_em < JANELA_DE_SERVICO


@dataclass(frozen=True, slots=True)
class TemplateAprovado:
    """Um template do catalogo. TEC-186, RN-13.6.

    `nome` e o nome do template na Meta -- a chave que
    `Settings.templates_aprovados` lista quando (e se) a aprovacao chega.
    `categoria` e o contexto do follow-up que ele serve. O TEXTO aprovado NAO
    vive aqui: ele mora na Meta, e a submissao esta fora do escopo desta card
    (L5). O codigo so monta `name` + `language` + os parametros que preenchem
    os placeholders.
    """

    nome: str
    categoria: str
    idioma: str


# Um template por contexto -- os tres da RN-13.2/13.6. O piso de tres da
# RN-13.6 e afirmado por `test_o_catalogo_mantem_no_minimo_tres_e_uma_por_contexto`.
# Os nomes sao os que serao submetidos a Meta (fora de escopo); `pt_BR` e o
# idioma de todos.
TEMPLATES: tuple[TemplateAprovado, ...] = (
    TemplateAprovado(nome="followup_queda_de_preco", categoria=CATEGORIA_QUEDA, idioma="pt_BR"),
    TemplateAprovado(nome="followup_imovel_novo", categoria=CATEGORIA_IMOVEL_NOVO, idioma="pt_BR"),
    TemplateAprovado(nome="followup_convite", categoria=CATEGORIA_CONVITE, idioma="pt_BR"),
)


def categoria_da_novidade(*, ficha: Ficha | None, queda: QuedaDePreco | None) -> str:
    """O contexto do follow-up, na MESMA precedencia de `texto_do_followup`.

    Queda vence imovel novo, que vence o convite -- derivado do MESMO par
    `(ficha, queda)` que a TEC-184 ja escolhe, e nao uma segunda fonte. Se esta
    precedencia divergir daquela funcao, a categoria do template deixa de bater
    com o texto que o caminho de mensagem livre montaria para o mesmo lead.
    """
    if queda is not None:
        return CATEGORIA_QUEDA
    if ficha is not None:
        return CATEGORIA_IMOVEL_NOVO
    return CATEGORIA_CONVITE


def escolher_template(*, categoria: str, aprovados: frozenset[str]) -> TemplateAprovado | None:
    """O template do catalogo para `categoria`, SE aprovado pela Meta.

    `None` quando nenhum template do catalogo para aquela categoria esta em
    `aprovados` -- e o gatilho da tarefa para o corretor (cenario 3). Com
    `aprovados` vazio (o default, e a realidade do RT-03 durante o hackathon),
    devolve `None` para todo contexto, e todo follow-up fora da janela vira
    tarefa: e a mitigacao do RT-03 em vigor por padrao, nao um buraco.
    """
    for template in TEMPLATES:
        if template.categoria == categoria and template.nome in aprovados:
            return template
    return None


def parametros_do_template(
    *, template: TemplateAprovado, ficha: Ficha | None, queda: QuedaDePreco | None
) -> list[str]:
    """Os parametros que preenchem os placeholders do template aprovado.

    Ordem por categoria; os valores vem de `ficha`/`queda`, nunca do modelo.
    **Numero nenhum passa pelo modelo** -- os precos saem de `reais_de`, como
    na apresentacao e no texto livre (D5). Texto que chega ao lead, entao
    acentuado (TEC-267): `ficha.titulo`/`ficha.bairro` ja vem assim, e
    `reais_de` e ASCII por natureza.

    O par que chega aqui e o mesmo que definiu a categoria em
    `categoria_da_novidade`, entao os guards abaixo (`queda is not None`,
    `ficha is not None`) sao verdadeiros no caminho normal; eles existem para
    que um par incoerente caia em `[]` em vez de levantar dentro do envio.
    """
    if template.categoria == CATEGORIA_QUEDA and queda is not None and ficha is not None:
        return [
            ficha.titulo,
            reais_de(queda.preco_antes_centavos),
            reais_de(queda.preco_agora_centavos),
        ]
    if template.categoria == CATEGORIA_IMOVEL_NOVO and ficha is not None:
        return [ficha.titulo, ficha.bairro]
    return []
