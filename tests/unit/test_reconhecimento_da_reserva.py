"""O que conta como colisao da UNIQUE da reserva, e o que nao conta. TEC-230.

`_e_reserva_duplicada` decide se um `IntegrityError` e "ja reservei este envio"
ou outra coisa qualquer, e errar para o lado do "ja reservei" e caro: `send()`
devolve False, o turno vira `reentrega_suprimida`, a linha fecha em PROCESSED
-- terminal -- e o lead nunca recebe nada, com um log de duplicata que manda
quem investiga para o lado errado.

`tests/integration/test_outbound_guard.py` ja cobre o caminho fim-a-fim com o
banco de verdade. Aqui a funcao e exercitada direto, com dubles, porque os dois
ramos dela nao sao alcancaveis pelo mesmo driver: contra o Postgres do repo so
o primeiro roda, e o segundo -- que serve quem nao expoe o nome estruturado --
nao tem como ser alcancado sem trocar de driver.

Foi essa impossibilidade que escondeu o defeito que a TEC-230 achou: ate ela,
a funcao lia o nome do lugar errado, o primeiro ramo NUNCA rodava, e quem
decidia tudo era o fallback por substring, sem que nenhum teste mostrasse isso.
"""

from sqlalchemy.exc import IntegrityError

from mobia.domain.outbound.port import UNIQUE_DA_RESERVA, _e_reserva_duplicada


class _ErroDoAsyncpg(Exception):
    """Duble do `asyncpg.exceptions.IntegrityConstraintViolationError`.

    O que importa dele e carregar `constraint_name` -- o campo estruturado que
    o Postgres manda e que o asyncpg preserva.
    """

    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


class _ErroDoDialeto(Exception):
    """Duble do que o dialeto asyncpg do SQLAlchemy poe em `IntegrityError.orig`.

    Sondado na TEC-230 contra o banco real: o tipo e
    `sqlalchemy.dialects.postgresql.asyncpg.IntegrityError`, ele **nao** tem
    `constraint_name`, e o erro do driver -- que tem -- fica em `__cause__`.
    """

    def __init__(self, texto: str, causa: Exception | None = None) -> None:
        super().__init__(texto)
        self.__cause__ = causa


def _integridade(texto: str, causa: Exception | None = None) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, _ErroDoDialeto(texto, causa))


def test_o_nome_estruturado_do_constraint_decide() -> None:
    """O caminho normal: o asyncpg diz qual constraint estourou, e e a nossa."""
    erro = _integridade(
        f'duplicate key value violates unique constraint "{UNIQUE_DA_RESERVA}"',
        _ErroDoAsyncpg(UNIQUE_DA_RESERVA),
    )

    assert _e_reserva_duplicada(erro) is True


def test_outro_constraint_nao_e_a_reserva() -> None:
    """A FK quebrada do teste irmao de integracao, vista pelo lado da funcao."""
    erro = _integridade(
        'violates foreign key constraint "outbound_dispatches_message_id_fkey"',
        _ErroDoAsyncpg("outbound_dispatches_message_id_fkey"),
    )

    assert _e_reserva_duplicada(erro) is False


def test_um_constraint_com_a_nossa_unique_no_nome_nao_e_a_nossa() -> None:
    """O motivo de haver comparacao exata, e nao so a busca no texto.

    Um constraint futuro chamado `uq_outbound_message_kind_v2` CONTEM o nome do
    nosso. A busca por substring no texto do erro casa com ele e responde
    "duplicata" para uma violacao que nao tem nada a ver com a reserva -- o
    exato desfecho que o docstring da funcao existe para evitar, chegando pela
    porta que ele nao vigiava.

    Este e o teste que reprova a versao anterior da funcao: ela lia
    `constraint_name` de `exc.orig`, que no dialeto asyncpg nunca tem esse
    atributo, entao caia SEMPRE no fallback por substring.
    """
    vizinho = f"{UNIQUE_DA_RESERVA}_v2"
    erro = _integridade(
        f'duplicate key value violates unique constraint "{vizinho}"',
        _ErroDoAsyncpg(vizinho),
    )

    assert _e_reserva_duplicada(erro) is False


def test_sem_nome_estruturado_cai_para_o_texto() -> None:
    """O fallback continua existindo, e nao e decorativo.

    Ele serve o driver que nao expoe o campo estruturado -- psycopg, um driver
    novo, um erro que chegue sem `__cause__`. A TEC-230 corrigiu o ramo de cima
    em vez de apagar este, porque apagar deixaria esses casos sem cobertura
    nenhuma.
    """
    erro = _integridade(f'duplicate key value violates unique constraint "{UNIQUE_DA_RESERVA}"')

    assert _e_reserva_duplicada(erro) is True


def test_sem_nome_estruturado_e_sem_o_nome_no_texto_nao_e_duplicata() -> None:
    erro = _integridade("null value in column violates not-null constraint")

    assert _e_reserva_duplicada(erro) is False
