from decimal import Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Commitada de proposito para desenvolvimento e teste. Toda comparacao com este
# valor existe para impedir que ele saia daqui.
CHAVE_DE_DESENVOLVIMENTO = "ZGV2LWtleS0zMi1ieXRlcy1mb3ItbW9iaWEtb2shISE="

# O default de desenvolvimento, recusado em producao pelo validator abaixo.
# Mesmo molde da CHAVE_DE_DESENVOLVIMENTO.
TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO = "dev-catalogo-token"

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

    # Vazio DESLIGA o endpoint de importacao: o router nem e registrado. Nao e
    # 401 -- rota que nao existe nao pode ser exposta por engano de
    # configuracao, e este projeto ainda nao tem camada de autenticacao (JWT,
    # OIDC e papeis sao a TEC-201). Ver D1 do desenho da TEC-156.
    catalogo_admin_token: str = ""

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

    # Trocado de `claude-opus-5` para `claude-sonnet-5` por custo, junto com o
    # `modelo_agente`. **A troca do resumo nao foi medida, e hoje nao ha como
    # medir**: nada em `evals/` toca `modelo_resumo`, e a unica guarda que ele
    # tem e `test_todo_modelo_configurado_tem_preco_cadastrado`, que confere
    # preco e nao qualidade.
    #
    # A diferenca com o agente e essa, e importa: o agente trocou com gate --
    # 91,8% VERDE medido depois, contra 85,4% antes --, e o resumo trocou sem
    # instrumento. O argumento "sonnet-5 aguentou" vale para a acuracia de
    # intencao e para a precisao da extracao, que foram medidas, e NAO
    # transfere para a qualidade do resumo, que nao foi.
    #
    # Fica registrado em vez de escondido: se a qualidade do resumo regrediu,
    # nada neste projeto acusaria. Medir exigiria corpus e criterio proprios,
    # que nao existem -- e a TEC-140, que seria o lugar disso, tambem nao.
    modelo_resumo: str = "claude-sonnet-5"

    # Separado do modelo_resumo de proposito: a acuracia de intencao e a
    # qualidade do resumo sao metricas distintas e a TEC-210 vai afinar uma
    # sem tocar na outra. Os dois rodam em sonnet-5 hoje, e continuam campos
    # separados: e a possibilidade de divergir que a separacao guarda, nao o
    # fato de divergirem agora.
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
    # `teto_de_tokens_efetivo`. Protege contra o que o contador nao ve: a
    # contagem de `montar_contexto` mede uma mensagem plana, e a requisicao
    # real difere dela em quatro parcelas (o `SISTEMA` de montagem.py, que e
    # contado e nao enviado; e o `SISTEMA_DO_AGENTE`, o schema compilado e os
    # rotulos de `montar_prompt`, enviados e nunca contados).
    #
    # **O valor de hoje dessa diferenca nao esta escrito aqui, de proposito**
    # (TEC-243). Ele e derivado -- muda quando alguem mexe no prompt, num
    # campo do schema ou num rotulo -- e transcrito a mao ele envelheceu
    # quatro vezes em dois dias, sempre pego tarde e por revisao humana. Ele
    # vive em `tests/unit/test_config.py`, que nao pode mentir porque roda:
    #
    #     python -m pytest -q -k margem_do_orcamento -s
    #
    # imprime as quatro parcelas, o liquido, o teto e a folga.
    #
    # O que este comentario registra e o que **nao** envelhece: por que a
    # reserva existe, por que ela ja subiu duas vezes, e o que cada subida
    # custou por turno.
    #
    # **400 -> 800 na TEC-145**, que acrescentou o objeto `extracao` ao
    # `SCHEMA_DA_RESPOSTA` -- ~263 tokens (medidos naquela card) enviados em
    # toda chamada e nunca contados. Com 400 a reserva deixava de cobrir o que
    # a contagem nao ve. Preco: 400 tokens a menos de literais e resumo por
    # turno, de um teto de 12000 -- 3,3% do contexto, em troca de extracao
    # estruturada.
    #
    # A licao da TEC-145, que vale para toda subida futura: o minimo que
    # passava a segunda assercao passava **por meio token**, e por isso nao
    # foi adotado. O fator 0,75 existe para haver folga; empatar com o teto o
    # derrota. Escolher o minimo e escolher que a proxima card estoure.
    #
    # **800 -> 850 na TEC-250**, que acrescentou tres regras ao
    # `SISTEMA_DO_AGENTE` e levou a subcontagem acima do teto real.
    # **A alternativa foi procurada primeiro**, porque o proprio
    # `test_a_margem_do_orcamento_do_prompt_e_deliberada` manda perguntar
    # "o que sai do prompt?" antes de "quanto subo o numero?". Nao havia corte
    # de ~92 caracteres que nao tocasse algo medido: a enumeracao das tres
    # tarefas foi acrescentada pela TEC-240 justamente para nomear a extracao,
    # os parenteses das intencoes separam COMPRA de INVESTIMENTO (distincao
    # que o gate mede), a guarda de alucinacao e a unica que existe, e a frase
    # da confianca e o unico lugar onde ela e definida -- nenhum campo do
    # schema tem `description`.
    #
    # 830 nao serviu, e o meio token importou: reprovava por uma fracao de
    # token contra a subcontagem daquele dia. 850 deixou margem visivel, do
    # mesmo tamanho da que a TEC-240 tinha deixado de proposito. Os numeros
    # daquela medicao estao na secao TEC-250 do README, que e o registro
    # datado dela -- aqui eles so envelheceriam de novo. Preco desta subida: **50 tokens a menos de
    # literais e resumo por turno, de 12000 -- 0,4% do contexto**. Muito menor
    # que o da subida anterior (400 tokens, 3,3%), e a decisao foi tomada com
    # o numero na mao, nao por reflexo.
    #
    # **850 -> 880 na TEC-257**, que gastou ~18,5 tokens no campo `perguntou`
    # do `SCHEMA_DA_RESPOSTA` -- lista de strings livre em vez de enum dos
    # nove campos, que custaria +56,0 -- e ~0,75 na clausula da memoria de
    # `SISTEMA_DO_AGENTE` (classificador.py), ~19,25 no total. A clausula foi
    # **encurtada, e nao acrescentada**: "nao repergunte o que ja esta
    # preenchido" virou "nao repergunte o preenchido nem o ignorado", e foi o
    # corte na forma existente que pagou quase toda a clausula nova -- +0,75
    # em vez dos +6,25 que so acrescentar teria custado.
    # Preco desta subida: **30 tokens a menos de literais e resumo por turno,
    # de 12000 -- 0,25% do contexto**. Menor que as duas anteriores (3,3% e
    # 0,4%).
    contexto_headroom_de_tokens: int = 880

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

    # RN-13.3 (TEC-185): o horario de envio automatico, em horas locais do
    # `followup_fuso`. `fim` nomeia o ultimo MINUTO em que um envio pode
    # comecar -- `fim=20` autoriza 20:00 e recusa 20:01 --, e nao a ultima hora
    # inteira. A borda inclusiva nao e escolha estetica: os dois primeiros
    # criterios de aceite da card caem exatamente em 20:00, porque um lead que
    # parou de falar as 18h vence a primeira tentativa do QUENTE (+2h) as 20h
    # em ponto.
    #
    # O validator abaixo exige `fim <= 23`, e a comparacao e contra
    # `fim * 60`: entao os minutos 23:01-23:59 NUNCA podem ser autorizados,
    # em nenhuma configuracao, e uma janela de 24 horas e inexpressivel --
    # nao existe `fim` que signifique "meia-noite". A D10 do desenho depende
    # deste fato: uma janela "sempre aberta" nao existe, so uma que recusa
    # 59 minutos por dia.
    followup_horario_inicio: int = 9
    followup_horario_fim: int = 20

    # Fuso UNICO da POC (PR-04), e nao o fuso do lead: a deteccao pelo numero
    # esta declarada fora do escopo da TEC-185. Nome e nao offset de proposito
    # -- o Brasil aboliu o horario de verao em 2019, e gravar `-3` faria a
    # volta dele virar um erro silencioso de uma hora em todo disparo.
    followup_fuso: str = "America/Sao_Paulo"

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

    @model_validator(mode="after")
    def _recusar_token_de_catalogo_de_desenvolvimento_em_producao(self) -> "Settings":
        """O token de dev em producao deixa o catalogo gravavel por quem o leu.

        Ele esta no `.env.example`, versionado: qualquer um que clonou o repo o
        conhece. Diferente da chave de cifra, aqui o estrago nao e silencioso
        -- e por isso a guarda nao precisa existir para o token VAZIO, que
        apenas desliga a rota.
        """
        if (
            self.environment.strip().lower() in _AMBIENTES_DE_PRODUCAO
            and self.catalogo_admin_token == TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO
        ):
            raise ConfiguracaoInsegura(
                "CATALOGO_ADMIN_TOKEN esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Gere um token: "
                'python -c "import secrets;print(secrets.token_urlsafe(32))"'
            )
        return self

    @model_validator(mode="after")
    def _recusar_horario_de_envio_impossivel(self) -> "Settings":
        """Horario invertido ou vazio desligaria a cadencia em silencio.

        A varredura devolveria 0 para sempre, e o unico sintoma seria a
        ausencia de `followup.devido` -- indistinguivel de "nenhum lead
        devido". Um `followup_fuso` invalido, sem esta guarda, explodiria
        dentro da varredura a cada 5 minutos em vez de aqui.

        `ValueError` e nao `ConfiguracaoInsegura`: o docstring daquela excecao
        fala de configuracao que roda "sem a protecao que devia ter", e o caso
        dela e a chave de cifra de desenvolvimento em producao. Um horario
        invertido nao perde protecao -- ele deixa de operar. O pydantic
        embrulha este ValueError em ValidationError, que falha igualmente alto
        e em todo processo.
        """
        if not 0 <= self.followup_horario_inicio < self.followup_horario_fim <= 23:
            raise ValueError(
                "followup_horario_inicio e followup_horario_fim precisam satisfazer "
                f"0 <= inicio < fim <= 23; recebi inicio={self.followup_horario_inicio} "
                f"e fim={self.followup_horario_fim}. Horario invertido ou vazio desliga "
                "a cadencia de follow-up sem nenhum sintoma."
            )
        try:
            ZoneInfo(self.followup_fuso)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"followup_fuso={self.followup_fuso!r} nao e um fuso conhecido. "
                "Se o nome estiver certo, confira a dependencia `tzdata` no "
                "pyproject.toml -- o Windows nao tem base de fusos do sistema."
            ) from exc
        return self

    @property
    def fuso_de_envio(self) -> ZoneInfo:
        """O fuso do horario da RN-13.3, ja validado na construcao.

        Construido a cada acesso em vez de guardado: o `ZoneInfo` e cacheado
        pelo proprio modulo `zoneinfo`, e um atributo aqui teria de ser
        excluido do modelo do pydantic.
        """
        return ZoneInfo(self.followup_fuso)

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
        palpite e pior que reservar margem. O valor e
        `contexto_headroom_de_tokens`, e o comentario da propria constante
        registra por que ele ja subiu duas vezes e o que cada subida custou.

        **Medido na TEC-134, com a requisicao real ja montada.** A conta usa o
        mesmo proxy `len/4` do modulo de montagem, e nao uma chamada de
        `count_tokens` -- medir contra a API de verdade custaria uma chamada
        paga por execucao e nao pode entrar na suite, que nao toca a rede. E
        estimativa honesta, nao medida exata, e e por isso que o resultado
        vira um teste (`test_diferenca_entre_o_contado_e_o_enviado`) em vez de
        um numero solto num comentario.

        Sao quatro as parcelas em que a contagem difere do que se envia:

        - `-` `montagem.SISTEMA` entra na contagem mas **nao** e enviado --
          o classificador chama `montar_prompt(omitir_sistema=True)`.
        - `+` `classificador.SISTEMA_DO_AGENTE` vai no campo `system=` e
          nunca passa pelo contador.
        - `+` o schema compilado em `output_config.format`, idem.
        - `+` os rotulos de secao que `montar_prompt` intercala.

        **Quanto cada uma pesa hoje nao esta escrito aqui** (TEC-243). Os
        nomes das parcelas nao envelhecem; os valores envelhecem a cada
        mudanca de prompt ou de schema. Para ve-los:

            python -m pytest -q -k margem_do_orcamento -s

        **Por que esta regra existe:** este texto ja ficou desatualizado uma
        vez por uma card inteira. A TEC-145 acrescentou o objeto `extracao` ao
        `SCHEMA_DA_RESPOSTA` e subiu a reserva de 400 para 800, mas so
        atualizou o comentario da constante logo acima -- esta docstring
        continuou afirmando o peso do schema e o liquido de antes da mudanca,
        e a reserva de 400 em tres lugares. Depois disso o mesmo defeito
        reapareceu mais tres vezes (TEC-238 a TEC-241), sempre pego por
        revisao humana e nunca por teste, porque a prosa fica verde mentindo.
        A conta vive num lugar so agora: o teste, que nao pode mentir porque
        roda.
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
