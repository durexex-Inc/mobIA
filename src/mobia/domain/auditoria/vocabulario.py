"""O vocabulario fechado da trilha de auditoria. TEC-206, D2 e D5 do desenho.

Modulo sem I/O, no molde de `handoff/vocabulario.py`. Os tres enums tem copia
literal nos CHECKs de uma migration -- a migration nao importa daqui, porque
migration aplicada nao muda quando o codigo muda --, e quem prende as duas
copias juntas e `tests/unit/test_auditoria_vocabulario.py`.

**Nem sempre a MESMA migration, desde a TEC-195.** A 0053 escreveu os tres; a
0056 acrescentou `lead` a `Entidade` e teve de RECRIAR o CHECK, porque o
Postgres nao estende CHECK; a 0057 (TEC-204) recriou os de `Acao` e
`Entidade` para `INJECAO_DETECTADA` e `mensagem`; a 0058 (TEC-198) e a 0059
(TEC-199) recriaram so o de `Acao`; a 0071 (TEC-404) o recria de novo, para
`HANDOFF_ATRIBUIDO`. Entao o vocabulario em vigor
e o da migration mais recente que escreve cada um, e e assim que aquele teste
procura.

**`detalhes` so e montado pelas funcoes deste modulo** (D5): cada valor sai de
um vocabulario fechado -- ou, nas chaves de corretor (TEC-404, D6), e um UUID --,
e texto digitado por uma pessoa nunca entra. Texto livre pode carregar dado
pessoal, e nenhum teste garante que nao carrega.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.usuarios.models import PAPEIS
from mobia.domain.usuarios.permissoes import Permissao


class AtorTipo(StrEnum):
    USUARIO = "USUARIO"
    AGENTE = "AGENTE"
    SISTEMA = "SISTEMA"


class Acao(StrEnum):
    DADO_PESSOAL_ACESSADO = "DADO_PESSOAL_ACESSADO"
    # So a edicao feita por pessoa e auditada -- a do agente se reconstroi pela
    # transcricao. O chamador e o `PATCH /leads/{leadId}/qualificacao` da
    # TEC-194, um evento por campo alterado.
    QUALIFICACAO_ALTERADA = "QUALIFICACAO_ALTERADA"
    HANDOFF_CRIADO = "HANDOFF_CRIADO"
    OPTOUT_REGISTRADO = "OPTOUT_REGISTRADO"
    OPTOUT_REATIVADO = "OPTOUT_REATIVADO"
    # TEC-199, D7. Uma versao de prompt publicada pela tela, com
    # `entidade=configuracao_agente`, o id da ATIVACAO em `entidade_id` e o
    # agente em `campo`. O texto nao vem: fica em `versoes_de_prompt`. A
    # configuracao da TEC-198 nao publica prompt -- ela grava
    # `CONFIGURACAO_ALTERADA`, abaixo, mesmo quando muda o nome ou o tom.
    PROMPT_PUBLICADO = "PROMPT_PUBLICADO"
    ACESSO_NEGADO = "ACESSO_NEGADO"
    # TEC-204, D6. A moderacao de entrada achou tentativa de mudar as
    # instrucoes do agente. Ator SISTEMA; entidade, a mensagem.
    INJECAO_DETECTADA = "INJECAO_DETECTADA"
    # TEC-198, D1. Um evento por campo da configuracao do agente que mudou,
    # com `entidade=configuracao_agente` -- que a 0053 ja previa sem chamador.
    # O valor fica na tabela de versoes, e nao aqui: a trilha diz quem mudou o
    # que, e a regra dela e nao guardar o antes e o depois.
    CONFIGURACAO_ALTERADA = "CONFIGURACAO_ALTERADA"
    # TEC-199, D7. O rollback de prompt, com a mesma forma de
    # `PROMPT_PUBLICADO`. O id da ativacao, e nao o da versao, porque o
    # rollback para o padrao (versao 0) nao tem versao. Custou a 0059.
    PROMPT_REVERTIDO = "PROMPT_REVERTIDO"
    # TEC-207, D6. O pedido chegou, pelo WhatsApp ou pelo ADMIN. Entidade
    # SOLICITACAO_DE_TITULAR, entidade_id o id da solicitacao.
    TITULAR_SOLICITOU = "TITULAR_SOLICITOU"
    # TEC-207, D6. A exportacao de `GET /leads/{leadId}/dados-pessoais`.
    DADOS_EXPORTADOS = "DADOS_EXPORTADOS"
    # TEC-207, D6. `anonimizar_lead` rodou -- pelo job da eliminacao a pedido
    # ou pelo sweep de retencao. A origem da solicitacao (D2) diz qual.
    LEAD_ANONIMIZADO = "LEAD_ANONIMIZADO"
    # TEC-207, D6. `POST /titular/solicitacoes/{id}/recusa`.
    TITULAR_RECUSADO = "TITULAR_RECUSADO"
    # TEC-404, D6. O admin troca o corretor de um handoff pela tela de pedidos
    # de interesse. Entidade HANDOFF; `detalhes` diz de quem para quem, e se um
    # aceite foi desfeito (decisao 4 da card).
    HANDOFF_ATRIBUIDO = "HANDOFF_ATRIBUIDO"


class Entidade(StrEnum):
    HANDOFF = "handoff"
    OPTOUT_EVENT = "optout_event"
    # A negativa: `entidade_id` e o template da rota, e nao o caminho com o id.
    ROTA = "rota"
    # Nasceram na 0053 sem chamador, porque o CHECK e o que custaria migration
    # depois. Hoje os dois tem: a qualificacao pela TEC-194, e a configuracao
    # pela TEC-198 e pelas versoes de prompt da TEC-199.
    LEAD_QUALIFICATION = "lead_qualification"
    CONFIGURACAO_AGENTE = "configuracao_agente"
    # TEC-195. O `entidade_id` e o apelido opaco de `referencias_de_lead`, e
    # NAO o par `(channel, conversation_key)` -- gravar o par seria gravar o
    # telefone, que e o que a D4 da TEC-206 proibiu. Quem pesquisa a trilha por
    # lead continua usando `lead_ref`. Custou a migration 0056, que recriou o
    # CHECK da 0053.
    LEAD = "lead"
    # TEC-204. O objeto da tentativa de injecao: `entidade_id` e o id da
    # mensagem, cuja linha continua existindo -- cifrada -- para quem investigar.
    MENSAGEM = "mensagem"
    # TEC-207, D2 e D6. `entidade_id` e o id de `solicitacoes_de_titular`.
    SOLICITACAO_DE_TITULAR = "solicitacao_de_titular"


# Os `campo` que a trilha nomeia. O que vai para a linha e QUAL campo foi
# lido, nunca o que ele dizia.
#
# `CAMPO_RESUMO` era o unico com chamador ate a TEC-195; `telefone` e `email`
# sao da revelacao de dado pessoal em `POST /api/v1/leads/{lead_id}/revelar` e,
# desde a TEC-404, em `POST /api/v1/interesses/{id}/revelar`,
# e `detalhe` e `transcricao` sao das leituras da TEC-193.
CAMPO_RESUMO = "resumo"
CAMPO_TELEFONE = "telefone"
# Desde a TEC-404 a fonte e `solicitacoes_de_interesse.email_cifrado`, lida por
# `POST /api/v1/interesses/{id}/revelar`. Lead de conversa continua sem e-mail:
# a rota de leads aceita o campo e devolve nulo (TEC-195, D7), para que a tela
# nao precise mudar se a coluna um dia nascer la.
CAMPO_EMAIL = "email"
# TEC-193, D3. Nao se REVELAM -- se leem, e o GET que os le e o que registra.
# `detalhe` cobre a tela inteira (resumo e qualificacao inclusos), e
# `transcricao` entra uma vez por pagina: carregar as falas anteriores e outro
# acesso, a um trecho que a primeira pagina nao mostrou.
CAMPO_DETALHE = "detalhe"
CAMPO_TRANSCRICAO = "transcricao"

# Os campos que `POST /leads/{lead_id}/revelar` e, desde a TEC-404,
# `POST /interesses/{id}/revelar` (`api/routes/interesses.py::revelar`)
# aceitam. Fora daqui e 422, e nao 500: o campo vem de quem chamou.
CAMPOS_REVELAVEIS = frozenset({CAMPO_TELEFONE, CAMPO_EMAIL})

# Os tres motivos que `api/autorizacao.py` produz. Um quarto, sem entrar aqui,
# e erro de programacao -- e nao texto que passe para a trilha.
MOTIVOS_DE_NEGATIVA = frozenset({"sem_permissao", "sem_sessao", "corretor_nao_e_o_dono"})

_METODOS_HTTP = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

# O que `detalhes` pode ter como chave. `validar_detalhes` recusa o resto.
CHAVES_DE_DETALHES = frozenset(
    {
        "gatilho",
        "permissao",
        "motivo",
        "papel",
        "metodo",
        "corretor_anterior",
        "corretor_novo",
        "aceito_desfeito",
    }
)

# TEC-404, D6. Id de corretor nao e vocabulario fechado, mas tambem nao e texto
# livre: a regra e "UUID", e um texto qualquer continua sendo ValueError. O
# booleano diz se a chave aceita nulo (so `corretor_anterior`: o handoff pode
# nunca ter tido corretor).
_CHAVES_DE_UUID: Mapping[str, bool] = {"corretor_anterior": True, "corretor_novo": False}

# O papel vem do JWT, assinado com o nosso segredo -- mas um valor fora de
# PAPEIS e anomalia, e anomalia nao vira texto na trilha.
PAPEL_DESCONHECIDO = "DESCONHECIDO"
METODO_DESCONHECIDO = "OUTRO"

# O que cada chave de `detalhes` pode valer: exatamente o que
# `detalhes_da_negativa`, `detalhes_do_handoff` e `detalhes_da_atribuicao`
# produzem, fora as chaves de `_CHAVES_DE_UUID`, que tem regra e nao conjunto.
# So `permissao` e nula aqui -- a negativa por falta de sessao nao tem
# permissao em jogo.
_VALORES_DE_DETALHES: Mapping[str, frozenset[str | None]] = {
    "gatilho": frozenset(g.value for g in Gatilho),
    "motivo": frozenset(MOTIVOS_DE_NEGATIVA),
    "permissao": frozenset({None, *(p.value for p in Permissao)}),
    "papel": frozenset({*PAPEIS, PAPEL_DESCONHECIDO}),
    "metodo": frozenset({*_METODOS_HTTP, METODO_DESCONHECIDO}),
    "aceito_desfeito": frozenset({"sim", "nao"}),
}


@dataclass(frozen=True)
class Ator:
    """Quem fez. Pessoa tem id; agente e sistema nao tem.

    O par e conferido aqui e pelo `ck_eventos_auditoria_ator_id` da 0053: um
    registro de pessoa sem identidade, ou de agente com identidade, e a
    mentira que a trilha nao pode conter.
    """

    tipo: AtorTipo
    id: str | None = None

    def __post_init__(self) -> None:
        if (self.tipo == AtorTipo.USUARIO) != (self.id is not None):
            raise ValueError(f"so USUARIO tem id; recebido tipo={self.tipo}, id={self.id!r}")


ATOR_AGENTE = Ator(AtorTipo.AGENTE)
ATOR_SISTEMA = Ator(AtorTipo.SISTEMA)


def validar_detalhes(detalhes: Mapping[str, str | None]) -> dict[str, str | None]:
    """Recusa chave fora de `CHAVES_DE_DETALHES` e valor fora do vocabulario dela.

    E a ultima barreira antes do INSERT: quem monta `detalhes` sao as funcoes
    abaixo, e esta funcao confere, chave a chave, que o valor e um dos que elas
    produzem -- `gatilho` um `Gatilho`, `motivo` um de `MOTIVOS_DE_NEGATIVA`,
    `permissao` uma `Permissao` ou nulo, `papel` um de `PAPEIS` ou
    `PAPEL_DESCONHECIDO`, `metodo` um de `_METODOS_HTTP` ou
    `METODO_DESCONHECIDO`, `aceito_desfeito` "sim" ou "nao". As duas chaves de
    corretor (TEC-404) nao tem conjunto: o valor e um UUID, e
    `corretor_anterior` aceita nulo. Um dict escrito a mao passa so se tiver
    exatamente esses valores: texto livre, em qualquer chave, e `ValueError`.
    """
    fora = sorted(set(detalhes) - CHAVES_DE_DETALHES)
    if fora:
        raise ValueError(f"detalhes com chave fora do vocabulario: {', '.join(fora)}")
    for chave, valor in detalhes.items():
        if chave in _CHAVES_DE_UUID:
            if valor is None:
                if _CHAVES_DE_UUID[chave]:
                    continue
                raise ValueError(f"detalhes.{chave} nao pode ser nulo")
            # TypeError/AttributeError: `test_valor_que_nao_e_texto_e_recusado`
            # manda int e afins, e `uuid.UUID(123)` nao levanta ValueError.
            try:
                uuid.UUID(valor)
            except (ValueError, TypeError, AttributeError) as erro:
                raise ValueError(f"detalhes.{chave} nao e UUID: {valor!r}") from erro
            continue
        if valor not in _VALORES_DE_DETALHES[chave]:
            raise ValueError(f"detalhes.{chave} fora do vocabulario: {valor!r}")
    return dict(detalhes)


def detalhes_da_negativa(
    *, permissao: str | None, motivo: str, papel: str, metodo: str
) -> dict[str, str | None]:
    """O `detalhes` de um ACESSO_NEGADO. Cada valor sai de um vocabulario fechado."""
    if motivo not in MOTIVOS_DE_NEGATIVA:
        raise ValueError(f"motivo de negativa desconhecido: {motivo}")
    if permissao is not None and permissao not in {p.value for p in Permissao}:
        raise ValueError(f"permissao desconhecida: {permissao}")
    return {
        "permissao": permissao,
        "motivo": motivo,
        "papel": papel if papel in PAPEIS else PAPEL_DESCONHECIDO,
        "metodo": metodo if metodo in _METODOS_HTTP else METODO_DESCONHECIDO,
    }


def detalhes_do_handoff(gatilho: Gatilho) -> dict[str, str | None]:
    """O `detalhes` de um HANDOFF_CRIADO: o gatilho que o criou, e nada mais."""
    return {"gatilho": gatilho.value}


def detalhes_da_atribuicao(
    *, anterior: uuid.UUID | None, novo: uuid.UUID, aceito_desfeito: bool
) -> dict[str, str | None]:
    """O `detalhes` de um HANDOFF_ATRIBUIDO (TEC-404, D6)."""
    return {
        "corretor_anterior": str(anterior) if anterior is not None else None,
        "corretor_novo": str(novo),
        "aceito_desfeito": "sim" if aceito_desfeito else "nao",
    }
