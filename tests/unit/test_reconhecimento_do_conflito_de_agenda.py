"""O que conta como colisao da exclusao de horario, e o que nao conta. TEC-168.

`_e_sobreposicao` decide se um `IntegrityError` e "horario ja ocupado" ou
outra coisa qualquer, e errar para o lado do "ja ocupado" esconderia um CHECK
quebrado atras de uma mensagem que manda quem investiga para o lado errado.

`tests/integration/test_agendamento_repositorio.py` ja cobre o caminho fim-a-
fim contra o Postgres de verdade -- mas so por ele so um ramo desta funcao
roda: o do texto, porque `exc.orig` (o `IntegrityError` que o SQLAlchemy
adapta) nao tem `constraint_name` com asyncpg. Aqui os ramos sao exercitados
direto, com dubles, no mesmo molde de
`tests/unit/test_reconhecimento_da_reserva.py` (TEC-230, que achou o mesmo
defeito em `_e_reserva_duplicada`, em `outbound/port.py`): antes desta
correcao, o nome estruturado vivia em `exc.orig.__cause__`, nao em `exc.orig`,
e o ramo "nomeado" nunca rodava -- quem decidia tudo era o fallback por
substring, sem que nenhum teste mostrasse isso.
"""

from sqlalchemy.exc import IntegrityError

from mobia.domain.agendamento.models import EXCLUSAO_DE_SOBREPOSICAO
from mobia.domain.agendamento.repositorio import _e_sobreposicao


class _ErroDoAsyncpg(Exception):
    """Duble do `asyncpg.exceptions.ExclusionViolationError`.

    O que importa dele e carregar `constraint_name` -- o campo estruturado que
    o Postgres manda e que o asyncpg preserva.
    """

    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


class _ErroDoDialeto(Exception):
    """Duble do que o dialeto asyncpg do SQLAlchemy poe em `IntegrityError.orig`.

    Nao tem `constraint_name` -- o erro do driver, que tem, fica em `__cause__`.
    """

    def __init__(self, texto: str, causa: Exception | None = None) -> None:
        super().__init__(texto)
        self.__cause__ = causa


def _integridade(texto: str, causa: Exception | None = None) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, _ErroDoDialeto(texto, causa))


def test_o_nome_estruturado_no_cause_decide() -> None:
    """O caminho normal com asyncpg: o texto NAO contem o nome, so o __cause__ tem.

    E o teste que reprova a versao anterior da funcao: ela lia
    `constraint_name` direto de `exc.orig`, que no dialeto asyncpg nunca tem
    esse atributo, e so o `__cause__` tem -- entao caia sempre no fallback por
    substring, que aqui nao encontraria nada.
    """
    erro = _integridade(
        "conflicting key value violates exclusion constraint",
        _ErroDoAsyncpg(EXCLUSAO_DE_SOBREPOSICAO),
    )

    assert _e_sobreposicao(erro) is True


def test_outro_constraint_no_cause_nao_e_sobreposicao() -> None:
    """A FK ou o CHECK que o docstring promete nao esconder atras do conflito."""
    erro = _integridade(
        'violates check constraint "ck_agendamentos_tipo"',
        _ErroDoAsyncpg("ck_agendamentos_tipo"),
    )

    assert _e_sobreposicao(erro) is False


def test_nome_estruturado_direto_em_orig_sem_cause_tambem_decide() -> None:
    """O ramo intermediario: um driver que exponha `constraint_name` sem o nivel do `__cause__`.

    E o que a funcao ja fazia antes desta correcao -- continua valendo para
    quem nao empacota o erro estruturado dentro de outro, como o asyncpg faz.
    """
    erro = IntegrityError("INSERT ...", {}, _ErroDoAsyncpg(EXCLUSAO_DE_SOBREPOSICAO))

    assert _e_sobreposicao(erro) is True


def test_sem_nome_estruturado_cai_para_o_texto() -> None:
    """O fallback continua existindo, para o driver que nao expoe nada estruturado."""
    erro = _integridade(
        f'conflicting key value violates exclusion constraint "{EXCLUSAO_DE_SOBREPOSICAO}"'
    )

    assert _e_sobreposicao(erro) is True


def test_sem_nome_estruturado_e_sem_o_nome_no_texto_nao_e_sobreposicao() -> None:
    erro = _integridade("null value in column violates not-null constraint")

    assert _e_sobreposicao(erro) is False
