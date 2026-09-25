"""O vocabulario fechado da trilha de auditoria. TEC-206, D2 e D5 do desenho.

Modulo sem I/O, no molde de `handoff/vocabulario.py`. Os tres enums tem copia
literal nos CHECKs da migration 0053 -- a migration nao importa daqui, porque
migration aplicada nao muda quando o codigo muda --, e quem prende as duas
copias juntas e `tests/unit/test_auditoria_vocabulario.py`.

**`detalhes` so e montado pelas funcoes deste modulo** (D5): cada valor sai de
um vocabulario fechado, e texto digitado por uma pessoa nunca entra. Texto
livre pode carregar dado pessoal, e nenhum teste garante que nao carrega.
"""

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
    # Sem chamador: a edicao de qualificacao pelo dashboard e a TEC-194, e so a
    # feita por pessoa sera auditada -- a do agente se reconstroi pela
    # transcricao.
    QUALIFICACAO_ALTERADA = "QUALIFICACAO_ALTERADA"
    HANDOFF_CRIADO = "HANDOFF_CRIADO"
    OPTOUT_REGISTRADO = "OPTOUT_REGISTRADO"
    OPTOUT_REATIVADO = "OPTOUT_REATIVADO"
    # Sem chamador: `ConfiguracaoAgente` nao existe (TEC-198/199).
    PROMPT_PUBLICADO = "PROMPT_PUBLICADO"
    ACESSO_NEGADO = "ACESSO_NEGADO"


class Entidade(StrEnum):
    HANDOFF = "handoff"
    OPTOUT_EVENT = "optout_event"
    # A negativa: `entidade_id` e o template da rota, e nao o caminho com o id.
    ROTA = "rota"
    # As entidades das duas acoes sem chamador. Entram agora porque o CHECK da
    # 0053 e o que custaria migration depois, e o chamador nao custa nada.
    LEAD_QUALIFICATION = "lead_qualification"
    CONFIGURACAO_AGENTE = "configuracao_agente"
    # TEC-195. O `entidade_id` e o apelido opaco de `referencias_de_lead`, e
    # NAO o par `(channel, conversation_key)` -- gravar o par seria gravar o
    # telefone, que e o que a D4 da TEC-206 proibiu. Quem pesquisa a trilha por
    # lead continua usando `lead_ref`. Custou a migration 0056, que recriou o
    # CHECK da 0053.
    LEAD = "lead"


# Os `campo` que a trilha nomeia. O que vai para a linha e QUAL campo foi
# lido, nunca o que ele dizia.
#
# `CAMPO_RESUMO` era o unico com chamador ate a TEC-195; os outros dois sao da
# revelacao de dado pessoal em `POST /api/v1/leads/{lead_id}/revelar`.
CAMPO_RESUMO = "resumo"
CAMPO_TELEFONE = "telefone"
# Sem fonte: nenhuma tabela deste sistema guarda e-mail de lead (TEC-195, D7).
# A rota o aceita e devolve nulo, para que a tela nao precise mudar quando a
# coluna nascer.
CAMPO_EMAIL = "email"

# Os campos que `POST /leads/{lead_id}/revelar` aceita. Fora daqui e 422, e
# nao 500: o campo vem de quem chamou.
CAMPOS_REVELAVEIS = frozenset({CAMPO_TELEFONE, CAMPO_EMAIL})

# Os tres motivos que `api/autorizacao.py` produz. Um quarto, sem entrar aqui,
# e erro de programacao -- e nao texto que passe para a trilha.
MOTIVOS_DE_NEGATIVA = frozenset({"sem_permissao", "sem_sessao", "corretor_nao_e_o_dono"})

_METODOS_HTTP = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

# O que `detalhes` pode ter como chave. `validar_detalhes` recusa o resto.
CHAVES_DE_DETALHES = frozenset({"gatilho", "permissao", "motivo", "papel", "metodo"})

# O papel vem do JWT, assinado com o nosso segredo -- mas um valor fora de
# PAPEIS e anomalia, e anomalia nao vira texto na trilha.
PAPEL_DESCONHECIDO = "DESCONHECIDO"
METODO_DESCONHECIDO = "OUTRO"

# O que cada chave de `detalhes` pode valer: exatamente o que
# `detalhes_da_negativa` e `detalhes_do_handoff` produzem. So `permissao` e
# nula -- a negativa por falta de sessao nao tem permissao em jogo.
_VALORES_DE_DETALHES: Mapping[str, frozenset[str | None]] = {
    "gatilho": frozenset(g.value for g in Gatilho),
    "motivo": frozenset(MOTIVOS_DE_NEGATIVA),
    "permissao": frozenset({None, *(p.value for p in Permissao)}),
    "papel": frozenset({*PAPEIS, PAPEL_DESCONHECIDO}),
    "metodo": frozenset({*_METODOS_HTTP, METODO_DESCONHECIDO}),
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
    `METODO_DESCONHECIDO`. Um dict escrito a mao passa so se tiver exatamente
    esses valores: texto livre, em qualquer chave, e `ValueError`.
    """
    fora = sorted(set(detalhes) - CHAVES_DE_DETALHES)
    if fora:
        raise ValueError(f"detalhes com chave fora do vocabulario: {', '.join(fora)}")
    for chave, valor in detalhes.items():
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
