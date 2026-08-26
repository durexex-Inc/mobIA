from decimal import Decimal
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Commitada de proposito para desenvolvimento e teste. Toda comparacao com este
# valor existe para impedir que ele saia daqui.
CHAVE_DE_DESENVOLVIMENTO = "ZGV2LWtleS0zMi1ieXRlcy1mb3ItbW9iaWEtb2shISE="

_AMBIENTES_DE_PRODUCAO = frozenset({"production", "producao", "prod"})

# Fracao do teto usada por `Settings.limiar_de_contagem_efetivo` quando
# `contexto_limiar_de_contagem` nao e sobrescrito. Derivada, nao um numero
# redondo -- ver o property para a conta e para o que ela nao cobre.
_FRACAO_SEGURA_DO_LIMIAR_DE_CONTAGEM = 0.6


class ConfiguracaoInsegura(RuntimeError):
    """Configuracao que rodaria, mas sem a protecao que devia ter."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Governa a guarda abaixo. `development` por default porque errar para o
    # lado de nao bloquear a maquina de ninguem e o certo aqui: em producao a
    # variavel e obrigatoria e a ausencia dela ja e o bug que a guarda pega.
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://mobia:mobia@localhost:5433/mobia"
    redis_url: str = "redis://localhost:6380/0"

    whatsapp_app_secret: str = "dev-app-secret"
    whatsapp_verify_token: str = "dev-verify-token"

    # 32 bytes em base64. O default so serve para desenvolvimento e teste --
    # em producao vem do ambiente. A analogia com o whatsapp_app_secret que o
    # spec usou tem um furo: assinatura errada falha alto, na primeira
    # requisicao. Chave de cifra errada nao falha: o dado e gravado com uma
    # chave publicamente conhecida e nada reclama. Dai a guarda abaixo.
    content_encryption_key: str = CHAVE_DE_DESENVOLVIMENTO

    # Sem default utilizavel: chave ausente falha alto na construcao do cliente.
    # Nao precisa da guarda de producao que a chave de cifra tem -- uma chave de
    # API errada falha na primeira chamada, enquanto uma chave de cifra errada
    # grava dado com valor publicamente conhecido e nao reclama.
    anthropic_api_key: str = ""

    modelo_resumo: str = "claude-opus-5"

    # Separado do modelo_resumo de proposito: a acuracia de intencao e a
    # qualidade do resumo sao metricas distintas e a TEC-210 vai afinar uma
    # sem tocar na outra.
    modelo_agente: str = "claude-opus-5"

    # Sem default utilizavel de proposito. Mas ao contrario da
    # ANTHROPIC_API_KEY, esta ausencia **nao** falha alto na primeira chamada:
    # a Meta devolve 401, o outbound (Task 4) classifica como EnvioRecusado
    # (permanente), o turno devolve "sem_resposta" e a linha vira PROCESSED --
    # terminal, o sweeper nunca reenfileira. Cada lead que escrever durante a
    # janela de misconfiguracao perde a resposta pra sempre, sem alarme alem
    # de uma linha `outbound.recusado_permanente` no log. Por isso a guarda
    # mora em `mobia.workers.main.startup` (Task 6): falha antes de a primeira
    # mensagem ser consumida, em vez de deixar o 401 acontecer em producao.
    whatsapp_access_token: str = ""
    whatsapp_api_base: str = "https://graph.facebook.com/v21.0"

    # RN-02.5: teto por chamada. RN-02.2: piso de mensagens literais.
    contexto_teto_de_tokens: int = 12000
    contexto_literais_minimas: int = 20

    # Reserva subtraida do teto antes de qualquer comparacao -- ver
    # `teto_de_tokens_efetivo`. Protege contra o que o contador nao ve.
    contexto_headroom_de_tokens: int = 400

    # Dobrar `gatilho - minimas` mensagens deixa exatamente `minimas` literais.
    # Manter gatilho >= 2 * minimas e o que garante o piso depois da regeneracao.
    contexto_gatilho_de_regeneracao: int = 40

    # None -> derivado do teto, ver `limiar_de_contagem_efetivo`. Um valor
    # explicito aqui -- ou via env `CONTEXTO_LIMIAR_DE_CONTAGEM` -- sobrescreve
    # a derivacao; e o que a fixture `sempre_contar` dos testes usa para forcar
    # a contagem real em todo turno.
    contexto_limiar_de_contagem: int | None = None

    # Teto de iteracoes do laco do estouro. Um `while` aqui e um caminho para
    # gastar dinheiro em circulo com um resumo que nao encolhe.
    contexto_max_iteracoes: int = 3

    log_level: str = "INFO"

    sweep_received_after_seconds: int = 30
    sweep_inflight_after_seconds: int = 300
    sweep_max_attempts: int = 5

    @model_validator(mode="after")
    def _recusar_chave_de_desenvolvimento_em_producao(self) -> "Settings":
        """Fica no validator, e nao no `create_app`, para valer em todo processo.

        A exposicao mais afiada e a migration 0004, que importa
        `mobia.infra.crypto` e cifraria a tabela inteira com a chave de
        desenvolvimento se um job de CI/CD subisse sem o segredo -- e ela nao
        passa pelo `create_app`. Aqui a guarda pega API, worker, alembic e
        qualquer script que construa `Settings`.
        """
        if (
            self.environment.strip().lower() in _AMBIENTES_DE_PRODUCAO
            and self.content_encryption_key == CHAVE_DE_DESENVOLVIMENTO
        ):
            raise ConfiguracaoInsegura(
                "CONTENT_ENCRYPTION_KEY esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Gere uma chave de 32 bytes: "
                'python -c "import base64,os;'
                'print(base64.b64encode(os.urandom(32)).decode())"'
            )
        return self

    @property
    def teto_de_tokens_efetivo(self) -> int:
        """O teto contra o qual a montagem (TEC-127) de fato compara.

        A contagem mede um proxy menor do que vai ser enviado. `_contar_se_valer`
        monta uma unica mensagem de usuario plana e `ContadorAnthropic.contar` a
        manda como `messages=[{"role": "user", ...}]`, sem `system=`. A
        requisicao real que a TEC-134 vai montar e um system prompt mais um array
        multi-turno, e cada turno carrega overhead estrutural que o contador
        nunca ve -- da ordem de 100-200 tokens numa janela de vinte a quarenta
        mensagens. Some a isso que `_texto_do_estado` e explicitamente uma
        representacao para medir, nao o renderizador que a TEC-134 vai usar.

        A reserva existe porque contar a forma exata exigiria conhecer a forma
        exata, e o consumidor que a define ainda nao existe: construir para um
        palpite e pior que reservar margem. 400 cobre ~5 tokens por turno numa
        janela de quarenta (200) com o dobro de folga para o system prompt e para
        o renderizador do estado.

        **Medido na TEC-134, com a requisicao real ja montada.** A conta usa o
        mesmo proxy `len/4` do modulo de montagem, e nao uma chamada de
        `count_tokens` -- medir contra a API de verdade custaria uma chamada
        paga por execucao e nao pode entrar na suite, que nao toca a rede. E
        estimativa honesta, nao medida exata, e e por isso que o resultado
        vira um teste (`test_diferenca_entre_o_contado_e_o_enviado`) em vez de
        um numero solto num comentario.

        O que a contagem ve a mais e a menos, em tokens de proxy:

        - `-42`  `montagem.SISTEMA` entra na contagem mas **nao** e enviado --
          o classificador chama `montar_prompt(omitir_sistema=True)`.
        - `+193` `classificador.SISTEMA_DO_AGENTE` vai no campo `system=` e
          nunca passa pelo contador.
        - `+93`  o schema compilado em `output_config.format`, idem.
        - `+19`  os rotulos de secao que `montar_prompt` intercala.

        Liquido: **~263 tokens contados a menos do que se envia**, contra uma
        reserva de 400. Sobram ~137 para o overhead estrutural da requisicao,
        que hoje e um unico turno de usuario -- ordem de dezenas de tokens, nao
        centenas, porque a TEC-134 nao montou o array multi-turno que este
        texto previa. Por isso a reserva **fica em 400**: cobre o medido com
        folga de mais de 50%, e derruba-la para perto de 263 trocaria uma
        margem barata (2,2% do teto) por risco de estourar o limite real da
        chamada.
        """
        return self.contexto_teto_de_tokens - self.contexto_headroom_de_tokens

    @property
    def limiar_de_contagem_efetivo(self) -> int:
        """Acima disto, `_contar_se_valer` (TEC-127) paga a contagem real;
        abaixo, confia na estimativa de `len/4`.

        0.6 do teto efetivo por padrao (`teto_de_tokens_efetivo`, ja com a
        reserva descontada), nao um numero redondo: um limiar T implica um
        texto de aproximadamente `4*T` caracteres (a estimativa e `len//4`).
        Para a estimativa enganar -- dizer "cabe" quando na verdade estoura --
        o texto precisaria rodar a menos de `4*T/teto` caracteres por token.
        Com T = 0.6 * teto essa razao e 2.4, e portugues acentuado (~3.2-3.7
        chars/token) fica coberto com folga.

        O que este limiar **nao** cobre: emoji (~0.3-0.5 chars/token -- cada
        emoji e 1 caractere Python e 2-4 tokens) e blobs base64/URL (~2). Um
        turno dominado por qualquer um dos dois pode escapar da contagem real
        e sair medido para menos tokens do que de fato tem. Nao existe fracao
        razoavel do teto que cubra emoji sem eliminar o beneficio da
        estimativa barata para o trafego normal -- cobrir 0.3 exigiria um
        limiar por volta de 7.5% do teto, baixo demais para qualquer conversa
        real ficar abaixo dele. Ate existir um estimador que leve densidade de
        caracteres nao-ASCII em conta, isto e um risco aceito e documentado,
        nao um bug escondido.
        """
        if self.contexto_limiar_de_contagem is not None:
            return self.contexto_limiar_de_contagem
        return round(self.teto_de_tokens_efetivo * _FRACAO_SEGURA_DO_LIMIAR_DE_CONTAGEM)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Preco em dolar por 1 milhao de tokens, (entrada, saida). O custo e calculado e
# **materializado** no momento do registro: mudar um preco aqui amanha nao pode
# reescrever o que ja foi gasto.
#
# claude-sonnet-5 esta com tarifa promocional de 2.00/10.00 ate 2026-08-31.
# Fica a tarifa cheia de proposito: precificacao com vigencia por data exigiria
# intervalos de data na tabela, que o spec rejeitou ao descartar a opcao de
# calcular custo em query. Superestimar num painel de custo e mais seguro que
# subestimar.
PRECOS_POR_MODELO: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
}
