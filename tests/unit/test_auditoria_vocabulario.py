"""O vocabulario da trilha de auditoria e o `lead_ref`. TEC-206, D2, D4 e D5.

Sem banco: o que se verifica aqui e a forma do que vai para a linha -- o par
ator/id, o `detalhes` so com metadado fechado, e a referencia ao lead que nao
contem o telefone. A garantia no banco esta em
`tests/integration/test_trilha_de_auditoria.py`.
"""

import ast
import pathlib

import pytest

from mobia.domain.auditoria.referencia import lead_ref
from mobia.domain.auditoria.vocabulario import (
    ATOR_AGENTE,
    ATOR_SISTEMA,
    CHAVES_DE_DETALHES,
    METODO_DESCONHECIDO,
    MOTIVOS_DE_NEGATIVA,
    PAPEL_DESCONHECIDO,
    Acao,
    Ator,
    AtorTipo,
    Entidade,
    detalhes_da_negativa,
    detalhes_do_handoff,
    validar_detalhes,
)
from mobia.domain.handoff.vocabulario import Gatilho
from mobia.domain.usuarios.models import PAPEIS
from mobia.domain.usuarios.permissoes import Permissao

CHAVE = "chave-de-teste"
TELEFONE = "5511911112222"


class TestLeadRef:
    def test_e_estavel(self) -> None:
        assert lead_ref("whatsapp", TELEFONE, chave=CHAVE) == lead_ref(
            "whatsapp", TELEFONE, chave=CHAVE
        )

    def test_tem_64_caracteres_hexadecimais(self) -> None:
        ref = lead_ref("whatsapp", TELEFONE, chave=CHAVE)
        assert len(ref) == 64
        int(ref, 16)

    def test_muda_com_o_canal(self) -> None:
        assert lead_ref("whatsapp", TELEFONE, chave=CHAVE) != lead_ref("web", TELEFONE, chave=CHAVE)

    def test_nao_contem_o_telefone(self) -> None:
        ref = lead_ref("whatsapp", TELEFONE, chave=CHAVE)
        assert TELEFONE not in ref
        assert TELEFONE[-8:] not in ref

    def test_depende_da_chave(self) -> None:
        """Sem a chave nao se recalcula -- e por isso ela nao pode ser o default em producao."""
        assert lead_ref("whatsapp", TELEFONE, chave=CHAVE) != lead_ref(
            "whatsapp", TELEFONE, chave="outra-chave"
        )


class TestAtor:
    def test_usuario_exige_id(self) -> None:
        with pytest.raises(ValueError, match="USUARIO"):
            Ator(AtorTipo.USUARIO)

    def test_agente_e_sistema_nao_tem_id(self) -> None:
        with pytest.raises(ValueError):
            Ator(AtorTipo.AGENTE, "alguem")
        assert ATOR_AGENTE.id is None
        assert ATOR_SISTEMA.id is None

    def test_usuario_com_id_passa(self) -> None:
        assert Ator(AtorTipo.USUARIO, "token-compartilhado").id == "token-compartilhado"


class TestDetalhes:
    def test_negativa_so_leva_valores_de_vocabulario_fechado(self) -> None:
        detalhes = detalhes_da_negativa(
            permissao=Permissao.VER_AUDITORIA.value,
            motivo="sem_permissao",
            papel="GERENTE",
            metodo="GET",
        )
        assert set(detalhes) <= CHAVES_DE_DETALHES
        assert detalhes["permissao"] in {p.value for p in Permissao}
        assert detalhes["motivo"] in MOTIVOS_DE_NEGATIVA
        assert detalhes["papel"] in PAPEIS
        assert detalhes["metodo"] == "GET"

    def test_papel_fora_da_lista_nao_e_copiado(self) -> None:
        """O papel vem do JWT; um valor fora de PAPEIS nao entra como texto."""
        detalhes = detalhes_da_negativa(
            permissao=None, motivo="sem_sessao", papel="SUPERVISOR do Paulo", metodo="GET"
        )
        assert detalhes["papel"] == PAPEL_DESCONHECIDO

    def test_metodo_fora_da_lista_nao_e_copiado(self) -> None:
        detalhes = detalhes_da_negativa(
            permissao=None, motivo="sem_sessao", papel="ADMIN", metodo="PROPFIND"
        )
        assert detalhes["metodo"] == METODO_DESCONHECIDO

    def test_motivo_desconhecido_e_erro_de_programacao(self) -> None:
        with pytest.raises(ValueError, match="motivo"):
            detalhes_da_negativa(
                permissao=None, motivo="o usuario xingou", papel="ADMIN", metodo="GET"
            )

    def test_permissao_desconhecida_e_erro_de_programacao(self) -> None:
        with pytest.raises(ValueError, match="permissao"):
            detalhes_da_negativa(
                permissao="QUALQUER", motivo="sem_permissao", papel="ADMIN", metodo="GET"
            )

    def test_handoff_leva_so_o_gatilho(self) -> None:
        assert detalhes_do_handoff(Gatilho.LEAD_QUENTE) == {"gatilho": "LEAD_QUENTE"}

    def test_chave_fora_do_vocabulario_e_recusada(self) -> None:
        with pytest.raises(ValueError, match="motivo_livre"):
            validar_detalhes({"motivo_livre": "lead pediu por telefone"})

    def test_valor_que_nao_e_texto_e_recusado(self) -> None:
        with pytest.raises(ValueError):
            validar_detalhes({"gatilho": 3})


class TestValidarDetalhesPorValor:
    """`validar_detalhes` confere o VALOR de cada chave, e nao so o nome.

    Um dict escrito a mao com a chave certa e texto livre no valor e o caminho
    por onde dado pessoal entraria na trilha sem passar pelas duas funcoes.
    """

    @pytest.mark.parametrize("chave", sorted(CHAVES_DE_DETALHES))
    def test_texto_livre_em_cada_chave_e_recusado(self, chave: str) -> None:
        with pytest.raises(ValueError, match=f"detalhes.{chave}"):
            validar_detalhes({chave: "lead pediu pelo 5511911112222"})

    @pytest.mark.parametrize("gatilho", list(Gatilho))
    def test_todo_detalhe_de_handoff_passa(self, gatilho: Gatilho) -> None:
        detalhes = detalhes_do_handoff(gatilho)
        assert validar_detalhes(detalhes) == detalhes

    @pytest.mark.parametrize("permissao", [None, *(p.value for p in Permissao)])
    @pytest.mark.parametrize("motivo", sorted(MOTIVOS_DE_NEGATIVA))
    @pytest.mark.parametrize("papel", [*PAPEIS, "SUPERVISOR do Paulo"])
    @pytest.mark.parametrize("metodo", ["GET", "POST", "PUT", "PATCH", "DELETE", "PROPFIND"])
    def test_todo_detalhe_de_negativa_passa(
        self, permissao: str | None, motivo: str, papel: str, metodo: str
    ) -> None:
        detalhes = detalhes_da_negativa(
            permissao=permissao, motivo=motivo, papel=papel, metodo=metodo
        )
        assert validar_detalhes(detalhes) == detalhes

    def test_os_sentinelas_passam(self) -> None:
        detalhes = {"papel": PAPEL_DESCONHECIDO, "metodo": METODO_DESCONHECIDO}
        assert validar_detalhes(detalhes) == detalhes

    @pytest.mark.parametrize("chave", ["gatilho", "motivo", "papel", "metodo"])
    def test_nulo_so_vale_para_permissao(self, chave: str) -> None:
        with pytest.raises(ValueError, match=f"detalhes.{chave}"):
            validar_detalhes({chave: None})

    def test_permissao_nula_passa(self) -> None:
        assert validar_detalhes({"permissao": None}) == {"permissao": None}

    def test_toda_chave_tem_vocabulario_de_valor(self) -> None:
        """Chave nova em `CHAVES_DE_DETALHES` sem vocabulario viraria `KeyError`."""
        from mobia.domain.auditoria.vocabulario import _VALORES_DE_DETALHES

        assert set(_VALORES_DE_DETALHES) == CHAVES_DE_DETALHES


VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _tupla_da_migracao(nome: str) -> tuple[str, ...]:
    """O valor literal de `nome = ("...", ...)` na ULTIMA migration que o define.

    Le os ARQUIVOS com `ast`, como `test_uma_cabeca_de_migration.py`: nao
    precisa de banco, e nao importa a migration -- importa-la rodaria o
    `from alembic import op` fora de um contexto de migracao.

    **Era a `0053` fixa ate a TEC-195**, que acrescentou `lead` a `Entidade` e
    recriou o CHECK na `0056` -- o Postgres nao estende CHECK, entao o
    vocabulario em vigor passou a ser o da migration mais recente que o
    escreve. Ordenar por nome de arquivo basta porque as revisoes sao `NNNN_`,
    e o que interessa e a ultima a tocar no assunto. A TEC-204 redefine
    `_ACOES` e `_ENTIDADES` de novo, na migration da injecao. So conta
    migration que fala de `eventos_auditoria`, porque o nome da tupla poderia
    ser reusado para outra tabela.

    **A varredura NAO afrouxa a asserta.** Ela continua comparando o enum com
    uma copia literal escrita a mao num arquivo de migration; o que mudou e
    qual arquivo responde.
    """
    for arquivo in sorted(VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"), reverse=True):
        fonte = arquivo.read_text(encoding="utf-8")
        if "eventos_auditoria" not in fonte:
            continue
        for no in ast.parse(fonte).body:
            if isinstance(no, ast.Assign) and any(
                isinstance(alvo, ast.Name) and alvo.id == nome for alvo in no.targets
            ):
                valor = ast.literal_eval(no.value)
                assert isinstance(valor, tuple)
                return valor
    raise AssertionError(f"{nome} nao encontrado em nenhuma migration de eventos_auditoria")


@pytest.mark.parametrize(
    ("constante", "enum"),
    [("_ATORES", AtorTipo), ("_ACOES", Acao), ("_ENTIDADES", Entidade)],
)
def test_o_vocabulario_bate_com_o_check_da_migration(constante: str, enum: type) -> None:
    """Valor novo no enum sem migration seria recusado pelo banco no primeiro INSERT."""
    assert set(_tupla_da_migracao(constante)) == {membro.value for membro in enum}


def test_a_tupla_vem_da_migration_mais_recente() -> None:
    """A 0056 redefine as acoes; a 0053 continua sendo a unica dos atores."""
    assert "INJECAO_DETECTADA" in _tupla_da_migracao("_ACOES")
    assert "mensagem" in _tupla_da_migracao("_ENTIDADES")
    assert _tupla_da_migracao("_ATORES") == ("USUARIO", "AGENTE", "SISTEMA")
