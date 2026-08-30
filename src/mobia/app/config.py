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
    # Trocado de `claude-opus-5` para `claude-sonnet-5` por custo: $2/$10 por
    # MTok contra $5/$25, ou ~60% mais barato dos dois lados. Uma execucao do
    # gate custava US$ 3,05 medidos (146 chamadas, 282k tokens de entrada e
    # 66k de saida), e passa a custar da ordem de US$ 1,20.
    #
    # **A troca nao foi medida quando entrou, e o risco esta assimetrico entre
    # as duas metricas do gate.** A baseline de 30/08/2026 (TEC-247, medida em
    # opus-5) tinha acuracia de intencao com folga larga -- 97,3% crua e 96,6%
    # efetiva, contra alvo 90 e piso 84 --, mas `precisao_da_extracao` em
    # 79,2%, ja **abaixo** do piso de 85. Nao ha margem daquele lado para
    # gastar com modelo mais barato, e as duas metricas saem da MESMA chamada:
    # nao da para tierizar uma sem a outra sem dobrar o custo por turno.
    #
    # Quem re-medir tem de olhar `precisao_da_extracao` primeiro, e nao a
    # acuracia: e ela que decide se esta troca se paga ou se custa o gate.
    #
    # Este arquivo NAO entra no filtro de `.github/workflows/evals.yml` (esta
    # escrito la, e de proposito -- ele carrega config alheia ao agente).
    # Entao trocar esta linha **nao dispara o gate pago**: a re-medicao e
    # manual, por `workflow_dispatch` ou `pytest evals`.
    modelo_agente: str = "claude-sonnet-5"

    # Separado do `modelo_agente` de proposito, e por dois motivos. Moderar e
    # classificacao binaria sobre texto curto: nao precisa do modelo que
    # escreve a resposta, e o teto de 5s do cliente da moderacao (ver
    # `infra/moderacao.py`) so fecha com modelo rapido. E amarrar os dois faria
    # uma troca de `modelo_agente` mudar em silencio o custo e a latencia da
    # moderacao de **todo** turno -- num arquivo que o filtro do gate da
    # TEC-210 nao cobre, entao a troca passaria sem re-medir.
    modelo_moderacao: str = "claude-haiku-4-5-20251001"

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
    # 800 e nao 400 desde a TEC-145: o objeto `extracao` do
    # `SCHEMA_DA_RESPOSTA` custa 263 tokens que sao enviados em toda chamada e
    # nunca entram na contagem de `montar_contexto`. Com 400 a conta de
    # `test_diferenca_entre_o_contado_e_o_enviado` chegava a 526 e a reserva
    # deixava de cobrir o que a contagem nao ve. Na TEC-145, 800 deixava a
    # subcontagem em 526 contra os 600 que a segunda assercao de
    # test_config.py exige (headroom * 0,75) -- 74 tokens de folga. O minimo
    # que passava era 702, e foi o primeiro escolhido -- mas 702 satisfazia a
    # assercao por 0,5 token e derrotava o proposito do fator 0,75, que e
    # existir folga.
    #
    # A TEC-240 alongou o prompt do agente e a subcontagem subiu para 587 --
    # a folga caiu para 13 tokens (test_a_margem_do_orcamento_do_prompt_e_deliberada,
    # em test_config.py, trava nesse numero). O minimo que passaria hoje ja
    # nao e 702; nao o recalculamos aqui de proposito. Esta conta vive em
    # tres lugares -- este comentario, a docstring de `teto_de_tokens_efetivo`
    # e o teste -- e so o teste nao pode mentir, porque ele roda a cada
    # execucao; os outros dois sao prosa que alguem tem de lembrar de
    # atualizar quando a conta muda, e nem sempre lembra.
    #
    # O preco: 400 tokens menos de literais e resumo por turno, de um teto de
    # 12000 -- 3,3% do contexto, em troca de extracao estruturada.
    contexto_headroom_de_tokens: int = 800

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
        palpite e pior que reservar margem. O valor atual e `contexto_headroom_de_tokens`
        (800, nao os 400 originais -- ver o comentario da propria constante e o
        "por que" no fim desta docstring); a decomposicao abaixo e o que
        justifica esse numero, medido, em vez de um segundo palpite escrito aqui.

        **Medido na TEC-134, com a requisicao real ja montada.** A conta usa o
        mesmo proxy `len/4` do modulo de montagem, e nao uma chamada de
        `count_tokens` -- medir contra a API de verdade custaria uma chamada
        paga por execucao e nao pode entrar na suite, que nao toca a rede. E
        estimativa honesta, nao medida exata, e e por isso que o resultado
        vira um teste (`test_diferenca_entre_o_contado_e_o_enviado`) em vez de
        um numero solto num comentario.

        O que a contagem ve a mais e a menos, em tokens de proxy:

        - `-42`   `montagem.SISTEMA` entra na contagem mas **nao** e enviado --
          o classificador chama `montar_prompt(omitir_sistema=True)`.
        - `+254`  `classificador.SISTEMA_DO_AGENTE` vai no campo `system=` e
          nunca passa pelo contador.
        - `+356`  o schema compilado em `output_config.format`, idem.
        - `+19`   os rotulos de secao que `montar_prompt` intercala.

        Liquido: **~587 tokens contados a menos do que se envia**, contra uma
        reserva de 800. A reserva **fica em 800**: o fator 0,75 sobre o
        headroom existe para haver folga. Na TEC-145, quando a subcontagem
        era 526, o minimo que passava a segunda assercao de
        `test_diferenca_entre_o_contado_e_o_enviado` era 702 -- e passava por
        meio token, o que derrotava o proposito do fator 0,75. Com a
        subcontagem de hoje em 587 (esta card alongou `SISTEMA_DO_AGENTE`),
        esse minimo historico ja nao vale -- subiu junto. Nao o recalculamos
        aqui de proposito: ver o teste, que e o unico dos tres lugares onde
        esta conta vive que nao pode mentir, porque ele roda.

        **Por que este texto ficou desatualizado antes de ser corrigido
        agora:** a TEC-145 acrescentou o objeto `extracao` ao
        `SCHEMA_DA_RESPOSTA` (de onde vem o `+356` acima, que era `+93`) e
        subiu a reserva de 400 para 800 -- mas so atualizou o comentario da
        propria constante `contexto_headroom_de_tokens` logo acima, nao esta
        docstring, que ficou com os numeros de antes por uma card inteira. A
        mesma conta vive em dois lugares neste arquivo -- e um terceiro fora
        dele, o teste citado acima. Quando ela muda, os tres precisam mudar
        juntos, ou algum envelhece em silencio ate a proxima pessoa confiar
        nele; so o teste nao tem esse risco, porque ele roda.
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
#
# `MODELO_SEM_CHAMADA` nao e modelo: e a ausencia de chamada, com nome. Um
# turno pode entregar texto constante sem falar com provedor nenhum -- e o que
# `_entregar_texto_fixo` faz quando a moderacao de entrada bloqueia --, e a
# telemetria dessa entrega precisa de algum valor em `model`. Com "" (ou
# qualquer string fora desta tabela) `custo_em_dolar` devolve None e o recorder
# emite `telemetry.unknown_model`, cujo proposito declarado e "None aparece
# como lacuna e alguem conserta": toda entrada bloqueada abriria um chamado
# para uma lacuna que nao existe. Zero aqui tambem nao e a mentira que aquele
# docstring teme -- ele fala de chamada real com preco desconhecido somando
# como zero; aqui nao houve chamada, e zero e o custo exato.
MODELO_SEM_CHAMADA = "sem-chamada"

PRECOS_POR_MODELO: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    # $2/$10, e nao $3/$15 -- aqueles sao os precos do `claude-sonnet-4-6`, e
    # estavam nesta linha sob o nome do sonnet-5. Corrigido quando o
    # `modelo_agente` passou a ser sonnet-5: com a tabela errada, a telemetria
    # de custo de TODO turno sairia 50% acima do real, e o painel que deveria
    # confirmar a economia da troca e justamente o que estaria mentindo.
    "claude-sonnet-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    MODELO_SEM_CHAMADA: (Decimal("0"), Decimal("0")),
}
