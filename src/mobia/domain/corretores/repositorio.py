"""A escrita e a leitura do cadastro de corretores. TEC-196."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.corretores.models import Corretor
from mobia.domain.texto import dobrar

# O UNIQUE de `Corretor.__table_args__` -- a unica defesa contra corretor
# duplicado, ver `test_email_e_unico` em test_corretores_schema.py.
UNIQUE_DO_EMAIL = "uq_corretores_email"


def _e_email_duplicado(exc: IntegrityError) -> bool:
    """Distingue a colisao do e-mail de qualquer outra falha de integridade.

    Tratar todo IntegrityError como duplicata esconderia um CHECK violado
    (jornada, capacidade, especialidade fora do vocabulario) atras de um 409
    que promete "e-mail repetido" e manda quem investiga para o lado errado.
    Mesmo argumento e mesma forma de `_e_reserva_duplicada` em
    `outbound/port.py`: casa pelo NOME da constraint, nao por qualquer
    IntegrityError. `constraint_name` vem do asyncpg; a checagem no texto e o
    fallback para qualquer outro driver, que ainda cita o nome na mensagem.
    """
    original = exc.orig
    nome = getattr(original, "constraint_name", None)
    if nome is not None:
        return bool(nome == UNIQUE_DO_EMAIL)
    return UNIQUE_DO_EMAIL in str(original)


class EmailJaCadastrado(Exception):
    """Ja existe corretor com este e-mail.

    Excecao propria e nao IntegrityError cru porque a rota precisa distinguir
    este caso (409) de qualquer outra falha de integridade (500).
    """


@dataclass(frozen=True)
class DadosDoCorretor:
    """O que o administrador informa. Sem `id`, `ativo` nem carimbos."""

    nome: str
    email: str
    telefone: str
    creci: str | None
    especialidades: list[str]
    regioes_atuacao: list[str]
    horario_inicio: int
    horario_fim: int
    capacidade_diaria: int
    plantao: bool


def _email_canonico(email: str) -> str:
    """Minuscula, para o UNIQUE valer o que promete.

    Sem isto, "Paulo@x.com" e "paulo@x.com" sao duas linhas para o UNIQUE e
    um corretor so para a realidade -- e a notificacao de uma card futura
    sairia dobrada. `casefold` e nao `lower` pelo mesmo motivo de `dobrar()`:
    dobra mais que minusculas.
    """
    return email.strip().casefold()


def _regioes_dobradas(regioes: list[str]) -> list[str]:
    """A mesma dobra que produz `bairro_busca` no catalogo, sem repetir regiao.

    Sem a dobra, "Zona Sul" e "zona sul" viram duas regioes e a alocacao de
    uma card futura falha por acidente de digitacao em vez de por regra. Sem
    a deduplicacao que vem a seguir, as duas continuam sendo duas linhas --
    so que agora identicas ("zona sul", "zona sul") -- e a dobra deixa de
    cumprir o que promete. Preserva a ordem da primeira ocorrencia: nao ha
    razao para reordenar o que o administrador digitou.
    """
    vistas: set[str] = set()
    resultado: list[str] = []
    for regiao in regioes:
        dobrada = dobrar(regiao)
        if dobrada not in vistas:
            vistas.add(dobrada)
            resultado.append(dobrada)
    return resultado


# O que `atualizar_corretor` aceita mudar. Existe para a funcao nao depender
# da disciplina de quem chama: sem esta lista, um `setattr` generico
# aceitaria "id" (reatribuindo a chave primaria de uma instancia ja
# carregada -- corrompe o identity map) e absorveria em silencio qualquer
# chave sem atributo mapeado correspondente, sem gravar nada e sem avisar.
# `id`, `criado_em` (identidade e origem) e `atualizado_em` (a propria
# funcao ja carimba) ficam de fora de proposito.
CAMPOS_EDITAVEIS = frozenset(
    {
        "nome",
        "email",
        "telefone",
        "creci",
        "especialidades",
        "regioes_atuacao",
        "horario_inicio",
        "horario_fim",
        "capacidade_diaria",
        "plantao",
        "ativo",
    }
)


async def criar_corretor(session: AsyncSession, dados: DadosDoCorretor) -> Corretor:
    """Cria o corretor. **Nao commita** -- o commit e de quem chama.

    Mesma disciplina de `registrar_handoff` e de `gravar_resumo`, e pela
    mesma razao: quem chama e que sabe o que mais precisa entrar na
    transacao.
    """
    agora = datetime.now(UTC)
    corretor = Corretor(
        id=uuid.uuid4(),
        nome=dados.nome.strip(),
        email=_email_canonico(dados.email),
        telefone=dados.telefone.strip(),
        creci=dados.creci,
        especialidades=list(dados.especialidades),
        regioes_atuacao=_regioes_dobradas(dados.regioes_atuacao),
        horario_inicio=dados.horario_inicio,
        horario_fim=dados.horario_fim,
        capacidade_diaria=dados.capacidade_diaria,
        plantao=dados.plantao,
        ativo=True,
        criado_em=agora,
        atualizado_em=agora,
    )
    session.add(corretor)
    try:
        await session.flush()
    except IntegrityError as erro:
        if _e_email_duplicado(erro):
            raise EmailJaCadastrado(dados.email) from erro
        raise
    return corretor


async def obter_corretor(session: AsyncSession, *, corretor_id: uuid.UUID) -> Corretor | None:
    return (
        await session.execute(select(Corretor).where(Corretor.id == corretor_id))
    ).scalar_one_or_none()


async def listar_corretores(session: AsyncSession, *, apenas_ativos: bool) -> list[Corretor]:
    consulta = select(Corretor).order_by(Corretor.nome)
    if apenas_ativos:
        consulta = consulta.where(Corretor.ativo.is_(True))
    return list((await session.execute(consulta)).scalars().all())


async def atualizar_corretor(
    session: AsyncSession, *, corretor_id: uuid.UUID, mudancas: dict[str, Any]
) -> Corretor | None:
    """Aplica as mudancas informadas. `None` quando o corretor nao existe.

    **Desativar e uma mudanca como outra qualquer** (`{"ativo": False}`), e
    nao uma operacao propria: apagar a linha quebraria a FK que `handoffs`
    tem para `corretores`, e a RESTRICT recusaria -- um DELETE existiria so
    para devolver erro.

    Levanta `ValueError` para chave fora de `CAMPOS_EDITAVEIS`: chave
    desconhecida e erro de programacao de quem chama, e engoli-la em
    silencio reproduziria o defeito que a lista existe para evitar -- quem
    chamou acha que gravou e nao gravou.
    """
    campos_invalidos = set(mudancas) - CAMPOS_EDITAVEIS
    if campos_invalidos:
        raise ValueError(f"campo(s) nao editavel(is): {sorted(campos_invalidos)}")

    corretor = await obter_corretor(session, corretor_id=corretor_id)
    if corretor is None:
        return None

    for campo, valor in mudancas.items():
        if campo == "email":
            valor = _email_canonico(str(valor))
        elif campo == "regioes_atuacao":
            valor = _regioes_dobradas(list(valor))
        elif campo in ("nome", "telefone"):
            valor = str(valor).strip()
        setattr(corretor, campo, valor)

    corretor.atualizado_em = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as erro:
        if _e_email_duplicado(erro):
            raise EmailJaCadastrado(str(mudancas.get("email"))) from erro
        raise
    return corretor
