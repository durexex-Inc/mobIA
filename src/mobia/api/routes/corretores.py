"""O CRUD de corretores. TEC-196, RF-19 e RN-19.2.

**Guardado pelo `exigir_admin`, o mesmo token do catalogo -- e isso estende a
um DADO PESSOAL uma guarda que foi aceita por nao haver dado pessoal.** A
emenda E-01 da TEC-156 escreveu, sobre o catalogo: "aceito porque o objeto e
o catalogo de imoveis e nao dado pessoal, ao contrario da reativacao de
opt-out da TEC-182, que por isso ficou sem rota HTTP". Aqui o objeto E dado
pessoal: nome, e-mail e telefone de pessoas reais. Decisao consciente de
12/09/2026, declarada na emenda E-01 da RN-19.5 e no comentario da card.
**Consequencia: quem tem o token le o contato de todos os corretores.** Ver a
D8 do desenho.

Nao ha rota DELETE de proposito: desativar e `ativo = false` (D6).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mobia.api.deps import exigir_admin
from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.repositorio import (
    DadosDoCorretor,
    EmailJaCadastrado,
    atualizar_corretor,
    criar_corretor,
    listar_corretores,
    obter_corretor,
)
from mobia.domain.corretores.vocabulario import (
    CAPACIDADE_MINIMA,
    HORA_MAXIMA,
    HORA_MINIMA,
    Especialidade,
    jornada_valida,
)
from mobia.infra.db import get_sessionmaker

router = APIRouter(prefix="/api/v1/corretores", tags=["corretores"])


class CorretorNovo(BaseModel):
    """O corpo do cadastro, no camelCase da secao 6 do SRS.

    `alias` e nao atributos em camelCase: o corpo HTTP fala camelCase e o
    Python deste repo fala snake_case -- mesmo molde de `FiltrosDaBusca` em
    `imoveis.py`.
    """

    model_config = ConfigDict(populate_by_name=True)

    nome: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=160)
    telefone: str = Field(min_length=8, max_length=20)
    creci: str | None = Field(default=None, max_length=20)
    especialidades: list[Especialidade] = Field(min_length=1)
    regioes_atuacao: list[str] = Field(alias="regioesAtuacao", min_length=1)
    horario_inicio: int = Field(alias="horarioInicio", ge=HORA_MINIMA, le=HORA_MAXIMA)
    horario_fim: int = Field(alias="horarioFim", ge=HORA_MINIMA, le=HORA_MAXIMA)
    capacidade_diaria: int = Field(alias="capacidadeDiaria", ge=CAPACIDADE_MINIMA)
    plantao: bool = False

    @field_validator("horario_fim")
    @classmethod
    def _jornada_coerente(cls, fim: int, info: object) -> int:
        # A jornada e recusada na borda, com 422, em vez de deixar o CHECK do
        # banco devolver 500. O CHECK continua existindo: e ele que protege a
        # tabela de quem escrever por fora desta rota.
        inicio = info.data.get("horario_inicio")  # type: ignore[attr-defined]
        if inicio is not None and not jornada_valida(inicio, fim):
            raise ValueError("jornada invalida: o inicio tem de vir antes do fim")
        return fim


class CorretorEditado(BaseModel):
    """As mudancas do PATCH. So o que vier explicitamente muda.

    A rota le isto com `model_dump(exclude_unset=True)`, nao
    `exclude_none=True`: `exclude_none` nao distingue "nao informei este
    campo" de "informei que e nulo", e isso tornaria impossivel limpar o
    `creci` de volta para nulo. `exclude_unset` distingue os dois casos, que e
    o comportamento certo para um PATCH parcial.
    """

    model_config = ConfigDict(populate_by_name=True)

    nome: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, min_length=3, max_length=160)
    telefone: str | None = Field(default=None, min_length=8, max_length=20)
    creci: str | None = Field(default=None, max_length=20)
    especialidades: list[Especialidade] | None = Field(default=None, min_length=1)
    regioes_atuacao: list[str] | None = Field(default=None, alias="regioesAtuacao", min_length=1)
    horario_inicio: int | None = Field(
        default=None, alias="horarioInicio", ge=HORA_MINIMA, le=HORA_MAXIMA
    )
    horario_fim: int | None = Field(
        default=None, alias="horarioFim", ge=HORA_MINIMA, le=HORA_MAXIMA
    )
    capacidade_diaria: int | None = Field(
        default=None, alias="capacidadeDiaria", ge=CAPACIDADE_MINIMA
    )
    plantao: bool | None = None
    ativo: bool | None = None

    @model_validator(mode="after")
    def _jornada_se_edita_em_par(self) -> "CorretorEditado":
        # Mandar so um dos dois nao da para validar sem ler a linha atual do
        # banco -- um novo inicio pode ficar incoerente com o fim antigo, e
        # vice-versa. Por isso o modelo exige os dois juntos ou nenhum, e usa
        # `model_fields_set` (nao a checagem por `is None`) porque o que
        # importa e o campo ter vindo no corpo, nao o valor dele.
        veio_inicio = "horario_inicio" in self.model_fields_set
        veio_fim = "horario_fim" in self.model_fields_set
        if veio_inicio != veio_fim:
            raise ValueError(
                "jornada se edita em par: horarioInicio e horarioFim vem juntos ou nenhum"
            )
        if veio_inicio and veio_fim:
            if self.horario_inicio is None or self.horario_fim is None:
                raise ValueError(
                    "jornada nao aceita nulo: horarioInicio e horarioFim tem de vir preenchidos"
                )
            if not jornada_valida(self.horario_inicio, self.horario_fim):
                raise ValueError("jornada invalida: o inicio tem de vir antes do fim")
        return self


def _resposta(corretor: Corretor) -> dict[str, object]:
    return {
        "id": str(corretor.id),
        "nome": corretor.nome,
        "email": corretor.email,
        "telefone": corretor.telefone,
        "creci": corretor.creci,
        "especialidades": corretor.especialidades,
        "regioesAtuacao": corretor.regioes_atuacao,
        "horarioInicio": corretor.horario_inicio,
        "horarioFim": corretor.horario_fim,
        "capacidadeDiaria": corretor.capacidade_diaria,
        "plantao": corretor.plantao,
        "ativo": corretor.ativo,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def cadastrar(pedido: CorretorNovo, _: None = Depends(exigir_admin)) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        try:
            corretor = await criar_corretor(
                session,
                DadosDoCorretor(
                    nome=pedido.nome,
                    email=pedido.email,
                    telefone=pedido.telefone,
                    creci=pedido.creci,
                    especialidades=[e.value for e in pedido.especialidades],
                    regioes_atuacao=pedido.regioes_atuacao,
                    horario_inicio=pedido.horario_inicio,
                    horario_fim=pedido.horario_fim,
                    capacidade_diaria=pedido.capacidade_diaria,
                    plantao=pedido.plantao,
                ),
            )
        except EmailJaCadastrado as erro:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="e-mail ja cadastrado"
            ) from erro
        await session.commit()
        return _resposta(corretor)


@router.get("")
async def listar(
    ativos: Annotated[bool, Query()] = False, _: None = Depends(exigir_admin)
) -> list[dict[str, object]]:
    async with get_sessionmaker()() as session:
        return [_resposta(c) for c in await listar_corretores(session, apenas_ativos=ativos)]


@router.get("/{corretor_id}")
async def obter(corretor_id: uuid.UUID, _: None = Depends(exigir_admin)) -> dict[str, object]:
    async with get_sessionmaker()() as session:
        corretor = await obter_corretor(session, corretor_id=corretor_id)
    if corretor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="corretor nao existe")
    return _resposta(corretor)


@router.patch("/{corretor_id}")
async def editar(
    corretor_id: uuid.UUID, pedido: CorretorEditado, _: None = Depends(exigir_admin)
) -> dict[str, object]:
    # `exclude_unset`, nao `exclude_none`: ver a docstring de `CorretorEditado`.
    mudancas = pedido.model_dump(exclude_unset=True)
    if "especialidades" in mudancas:
        mudancas["especialidades"] = [str(e) for e in mudancas["especialidades"]]

    async with get_sessionmaker()() as session:
        try:
            corretor = await atualizar_corretor(session, corretor_id=corretor_id, mudancas=mudancas)
        except EmailJaCadastrado as erro:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="e-mail ja cadastrado"
            ) from erro
        if corretor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="corretor nao existe")
        await session.commit()
        return _resposta(corretor)
