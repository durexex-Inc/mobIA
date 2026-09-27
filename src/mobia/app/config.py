import base64
import os
import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Commitada de proposito para desenvolvimento e teste. Toda comparacao com este
# valor existe para impedir que ele saia daqui.
CHAVE_DE_DESENVOLVIMENTO = "ZGV2LWtleS0zMi1ieXRlcy1mb3ItbW9iaWEtb2shISE="

# O segredo do JWT em desenvolvimento. Mesmo molde e mesmo motivo da
# CHAVE_DE_DESENVOLVIMENTO: commitado de proposito, e recusado em producao pelo
# validator. Quem o tiver emite token de ADMIN para si mesmo.
SEGREDO_DE_JWT_DE_DESENVOLVIMENTO = "dev-jwt-secret-nao-use-em-producao"

# A chave do `lead_ref` da trilha de auditoria em desenvolvimento (TEC-206,
# D4). Mesmo molde da CHAVE_DE_DESENVOLVIMENTO: commitada de proposito, e
# recusada em producao pelo validator. Quem a tiver calcula o `lead_ref` de
# qualquer telefone e descobre se ele aparece na trilha.
CHAVE_DO_LEAD_DE_DESENVOLVIMENTO = "dev-auditoria-chave-do-lead-nao-use-em-producao"

# A chave do blind index do lead em desenvolvimento (TEC-203, D2). Mesmo molde
# da CHAVE_DE_DESENVOLVIMENTO: commitada de proposito, e recusada em producao.
# Quem a tiver recalcula a chave de qualquer telefone e acha a conversa dele.
CHAVE_DO_INDICE_DE_DESENVOLVIMENTO = "dev-indice-do-lead-nao-use-em-producao"

# O piso da RFC 7518, secao 3.2: a chave de HMAC deve ter ao menos o tamanho da
# saida da funcao -- 32 bytes para SHA-256. Abaixo disso, a assinatura e mais
# facil de quebrar por forca bruta do que o algoritmo promete, e o `pyjwt` avisa
# (`InsecureKeyLengthWarning`) -- um aviso que se perde no meio do log.
#
# O default acima ja passa, com 34 bytes. Isto guarda quem CONFIGURA.
BYTES_MINIMOS_DO_JWT = 32

_AMBIENTES_DE_PRODUCAO = frozenset({"production", "producao", "prod"})

# Fracao do teto usada por `Settings.limiar_de_contagem_efetivo` quando
# `contexto_limiar_de_contagem` nao e sobrescrito. Derivada, nao um numero
# redondo -- ver o property para a conta e para o que ela nao cobre.
_FRACAO_SEGURA_DO_LIMIAR_DE_CONTAGEM = 0.6

# O formato de `tenant_slug` (TEC-344). Copia do `SLUG` de
# `frontend/src/lib/servidor/aparencia.ts`: mudar um sem o outro faz o botao
# sumir de todo site.
_FORMATO_DO_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class ConfiguracaoInsegura(RuntimeError):
    """Configuracao que rodaria, mas sem a protecao que devia ter."""


def data_do_id(identificador: str) -> date:
    """O id de chave e a data em que ela nasceu. TEC-203, D1."""
    try:
        if len(identificador) != 8 or not identificador.isdigit():
            raise ValueError
        return date(int(identificador[:4]), int(identificador[4:6]), int(identificador[6:]))
    except ValueError:
        raise ValueError(f"id de chave {identificador!r} nao e uma data AAAAMMDD") from None


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

    # Autenticacao do dashboard (TEC-201, RNF-11).
    #
    # **Quem tem este segredo emite token de ADMIN para si mesmo**, sem senha e
    # sem MFA -- e por isso ele tem a mesma guarda de producao da chave de
    # cifra, e nao a ausencia de guarda da chave da Anthropic. A diferenca e a
    # de sempre neste arquivo: chave de API errada falha na primeira chamada,
    # segredo de assinatura errado NAO falha -- ele so deixa de proteger.
    jwt_segredo: str = SEGREDO_DE_JWT_DE_DESENVOLVIMENTO
    # Os dois numeros da RNF-11. Configuraveis porque o teste precisa de token
    # ja expirado sem esperar uma hora; a REGRA continua sendo 60 e 7.
    jwt_minutos: int = 60
    refresh_dias: int = 7

    # 32 bytes em base64. O default so serve para desenvolvimento e teste --
    # em producao vem do ambiente. A analogia com o whatsapp_app_secret que o
    # spec usou tem um furo: assinatura errada falha alto, na primeira
    # requisicao. Chave de cifra errada nao falha: o dado e gravado com uma
    # chave publicamente conhecida e nada reclama. Dai a guarda abaixo.
    content_encryption_key: str = CHAVE_DE_DESENVOLVIMENTO

    # TEC-203, D1. O keyring: id (a data de criacao, AAAAMMDD) -> chave base64.
    # Vazio, tudo continua como antes -- grava v1 com `content_encryption_key`,
    # que passa a ser a chave LEGADA e segue decifrando todo blob v1. Com
    # chaves, a gravacao sai em v2 com a ativa e as demais so decifram. O id e
    # data para que a idade da chave se leia dele sem campo a mais (ver o aviso
    # dos 90 dias em `infra/rotacao.py`).
    content_encryption_keys: dict[str, str] = {}
    content_encryption_key_ativa: str = ""

    # A chave do HMAC que produz `eventos_auditoria.lead_ref` (TEC-206, D4).
    # Mesma guarda de producao da chave de cifra, e pela mesma razao: chave
    # conhecida nao produz erro nenhum, ela so deixa de proteger. Trocada
    # sozinha, torna a trilha impesquisavel; roda so por
    # `scripts/reindexar_leads.py` com `AUDITORIA_CHAVE_DO_LEAD_ANTERIOR` --
    # ver `auditoria/referencia.py`.
    auditoria_chave_do_lead: str = CHAVE_DO_LEAD_DE_DESENVOLVIMENTO

    # TEC-203, D2. A chave do HMAC que o `conversation_key` guarda no lugar do
    # telefone. Propria, e nao a de cifra nem a do `lead_ref`: chaves com
    # funcoes diferentes nao se reaproveitam. O id e a data de criacao, para o
    # aviso dos 90 dias; trocar esta chave exige `scripts/reindexar_leads.py`
    # com o servico parado (ver `docs/seguranca/segredos.md`).
    lead_indice_chave: str = CHAVE_DO_INDICE_DE_DESENVOLVIMENTO
    lead_indice_chave_id: str = "20260926"

    # Sem default utilizavel: chave ausente falha alto na construcao do cliente.
    # Nao precisa da guarda de producao que a chave de cifra tem -- uma chave de
    # API errada falha na primeira chamada, enquanto uma chave de cifra errada
    # grava dado com valor publicamente conhecido e nao reclama.
    anthropic_api_key: str = ""

    # Dois consumidores: o resumo de conversa (`context/resumo.py`) e, desde a
    # TEC-175, o redator de resumo de handoff (`handoff/resumo.py:155`).
    # Trocado de `claude-opus-5` para `claude-sonnet-5` por custo, junto com o
    # `modelo_agente`. **A troca do resumo nao foi medida, e hoje nao ha como
    # medir**: nada em `evals/` toca `modelo_resumo`, e a unica guarda que ele
    # tem em qualquer das duas saidas e `test_todo_modelo_configurado_tem_preco_cadastrado`,
    # que confere preco e nao qualidade.
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

    # TEC-209, D1. O modelo que assume a chamada principal quando o primario
    # esgota as tentativas. Outro modelo Claude, e nao outro provedor: aceita o
    # MESMO schema estrito, as mesmas ferramentas e o mesmo prompt, e por isso
    # nao pede adaptador. Cobre throttling e sobrecarga de um modelo; a
    # Anthropic inteira fora derruba os dois juntos. O mesmo da moderacao, que
    # ja e o modelo rapido que esta conta tem preco cadastrado.
    modelo_agente_secundario: str = "claude-haiku-4-5-20251001"

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
    # de uma linha `outbound.recusado_permanente` no log -- ou, se o turno for
    # de apresentacao de fichas (TEC-162), de uma linha
    # `apresentacao.ficha_recusada` por ficha recusada (uma, duas ou tres,
    # conforme quantas o turno tinha) e nenhuma `outbound.recusado_permanente`,
    # porque aquele caminho loga por ficha e nao pelo turno. Por isso a guarda
    # mora em `mobia.workers.main.startup` (Task 6): falha antes de a primeira
    # mensagem ser consumida, em vez de deixar o 401 acontecer em producao.
    whatsapp_access_token: str = ""
    whatsapp_api_base: str = "https://graph.facebook.com/v21.0"

    # TEC-132. Onde a midia recebida do lead e guardada, ja cifrada
    # (`encrypt_bytes`) -- a porta `ArmazemDeMidia` nao sabe cifrar.
    # `local` e o default de desenvolvimento e dos testes; `s3` e producao, e
    # exige `midia_s3_bucket` (guarda abaixo). O bucket e as credenciais reais
    # sao da TEC-219 -- aqui so a escolha do adaptador.
    midia_armazem: Literal["local", "s3"] = "local"
    # Relativo ao cwd do processo, como o `.midias/` do `.gitignore`.
    midia_diretorio: str = ".midias"
    midia_s3_bucket: str = ""
    midia_s3_regiao: str = ""
    # RN de midia (TEC-132, D1): teto configuravel, com padrao de 25 MB
    # (26_214_400 bytes) -- bem abaixo dos 100 MB que a Meta aceita para
    # documento, que e o proprio motivo de o conteudo nao morar no Postgres
    # (ver o desenho). O job de download confere isto tanto antes de baixar
    # (contra o `file_size` que a Meta informa) quanto durante, em streaming,
    # abortando se o corpo passar do teto mesmo que o `file_size` tenha mentido.
    midia_teto_bytes: int = 26_214_400

    # RN-13.6 (TEC-186): os nomes dos templates da Meta APROVADOS, separados
    # por virgula. Fica em configuracao, e nao em codigo, de proposito: qual
    # template esta aprovado e fato externo -- a submissao junto a Meta esta
    # fora do escopo da card, e o RT-03 avisa que a aprovacao pode nao chegar
    # no prazo do hackathon.
    #
    # **Default VAZIO, e isso e a mitigacao do RT-03 em vigor.** Sem nenhum
    # template aprovado, todo follow-up fora da janela de 24h vira tarefa para
    # o corretor (ver `escolher_template` em `domain/followup/template.py`) --
    # o contorno que a propria RN-13.6 declara. Quando a aprovacao chegar, a
    # operacao acrescenta os nomes aqui, sem deploy de codigo. O catalogo de
    # >= 3 templates que a regra pede e codigo (`TEMPLATES`); a aprovacao e
    # este campo.
    whatsapp_templates_aprovados: str = ""

    # TEC-281. O template do aviso ao corretor, e o numero de onde ele sai.
    #
    # **Sao dois campos porque a notificacao ao corretor nao pertence a
    # conversa nenhuma.** Todo outro envio deste projeto deriva o remetente do
    # `recipient_external_id` da mensagem do lead (que, por
    # `messages/schemas.py`, e o `phone_number_id` da Meta). O corretor nao
    # tem mensagem de entrada de onde derivar isso, e escolher a de um lead
    # qualquer acoplaria o aviso a uma conversa arbitraria.
    #
    # **Os dois com default VAZIO, e o efeito e o mesmo do campo acima:** sem
    # template configurado e aprovado, `WhatsAppTemplate` falha alto e o
    # e-mail entrega sozinho. Nao ha fallback para texto livre, e nao por
    # conservadorismo -- o corretor esta sempre fora da janela de 24h, entao
    # texto livre e recusa garantida com o codigo 131047.
    #
    # O nome aqui so vale se tambem estiver em `whatsapp_templates_aprovados`:
    # este campo diz QUAL template usar, aquele diz quais a Meta aprovou.
    whatsapp_template_notificacao_corretor: str = ""
    whatsapp_phone_number_id: str = ""

    # SMTP da notificacao ao corretor (TEC-280). Provedor NENHUM esta escolhido:
    # a decisao de 19/09/2026 foi falar SMTP direto justamente para que SES,
    # Resend ou Postmark fiquem sendo configuracao e nao codigo -- a escolha de
    # vendor pode esperar a TEC-219, que decide a nuvem.
    #
    # `smtp_host` e `smtp_remetente` nascem vazios de proposito. Um default
    # como "localhost" faria o worker subir em qualquer lugar e so falhar na
    # hora de entregar, que e o descarte em silencio que esta card existe para
    # matar. Quem reprova e a guarda do `startup`.
    smtp_host: str = ""
    smtp_porta: int = 587
    smtp_usuario: str = ""
    smtp_senha: str = ""
    smtp_remetente: str = ""
    # Ligado por padrao: o caso inseguro tem de ser o escolhido a mao. O
    # Mailpit de desenvolvimento nao fala TLS, e o `.env.example` o desliga.
    smtp_starttls: bool = True

    # RN-04.7 (TEC-274). O valor da regra, e configuravel porque os testes
    # precisam injetar centesimos de segundo: tres cenarios a 4 s reais
    # custariam mais de doze segundos por execucao da suite.
    #
    # `float` e nao `int` como os `sweep_*_after_seconds` vizinhos, pela mesma
    # razao -- o teste precisa de 0.05, e um `int` o arredondaria para 0.
    #
    # Nao ha flag para desligar: a porta e o desligamento. Trocar a entrada de
    # um canal em `ctx["indicadores"]` por `IndicadorNoop`, em
    # `workers/main.py`, desliga a feature naquele canal sem tocar neste numero
    # nem no dominio -- e e assim que o web ja nasce desde a TEC-124.
    indicador_de_digitacao_apos_segundos: float = 4.0

    # RN-01.6 (TEC-128), com a emenda E-01: a janela vale para TODA mensagem
    # recebida, e nao so para a que integra uma rajada de tres em oito
    # segundos. A condicao original nao e implementavel -- a rajada so e
    # reconhecivel depois de terminada, e a essa altura a resposta a primeira
    # mensagem ja teria saido e a reserva dela em `outbound_dispatches` ja
    # estaria commitada.
    #
    # `float` e nao `int`, pela mesma razao do vizinho acima: o teste precisa
    # de centesimos de segundo, e um `int` os arredondaria para zero.
    #
    # Zero desliga o debounce. E o caminho de fuga se os seis segundos de
    # espera no caso comum -- mensagem isolada, que tambem espera -- pesarem
    # demais no piloto.
    debounce_de_rajada_segundos: float = 6.0

    # RNF-16 (TEC-205). Zero desliga, pela mesma convencao do vizinho acima.
    #
    # A janela dos dois e de um minuto e NAO e configuravel: ela nao e ajuste,
    # e a unidade em que o requisito esta escrito. Vive em
    # `infra/rate_limit.JANELA_DE_UM_MINUTO`.
    #
    # "Configuravel sem deploy" da card e atendido ate onde o repo alcanca
    # hoje: variavel de ambiente, que em container e restart e nao rebuild.
    # Alterar em runtime exigiria ler a configuracao de fora do processo, que e
    # subsistema do epico RF-19 -- a mesma lacuna que `followup/cadencia.py` e
    # `outbound/antispam.py` ja declaram. Nao a resolva aqui de passagem.
    rate_limit_mensagens_por_minuto: int = 20
    rate_limit_requisicoes_por_ip_por_minuto: int = 100

    # O atraso aplicado ao excedente por numero, no lugar da janela de
    # debounce. Fixo e nao "ate a janela abrir": a versao precisa chegaria a
    # 60s e estouraria a folga da invariante da TEC-128 -- ver
    # `test_job_timeout_cabe_dentro_da_janela_do_sweeper`, que e quem prende
    # este numero. Subi-lo sem olhar aquele teste reabre uma conta de tres
    # termos que mora em dois arquivos.
    #
    # `float` e nao `int` pela razao dos vizinhos: o teste precisa de
    # centesimos de segundo.
    atraso_de_backoff_segundos: float = 30.0

    # De onde sai o IP que o limitador conta. Desligado, e o socket
    # (`request.client.host`), que nao e forjavel. Ligado, e o ULTIMO salto de
    # `X-Forwarded-For` -- o ultimo, e nao o primeiro, porque e o unico que o
    # proxy imediato escreveu e portanto o unico que o cliente nao controla.
    #
    # Ligue quando a API estiver atras de proxy ou ingress. Sem isso, o limite
    # por IP la vira um limite global por proxy: todos os visitantes do widget
    # dividem as mesmas 100 requisicoes.
    confiar_em_forwarded_for: bool = False

    # Quantas falas a reconexao do widget devolve (TEC-124, D6). Cinquenta
    # cobre a conversa inteira no caso comum e evita decifrar um historico
    # longo a cada reconexao -- e esta tela nao e o lugar de auditar
    # transcricao, que e o painel.
    historico_do_widget_mensagens: int = 50

    # Teto de caracteres por frame de texto do widget (TEC-124, D3). Acima
    # disso o frame e recusado e a conexao CONTINUA aberta.
    tamanho_maximo_do_texto_do_widget: int = 4096

    # TEC-344, D2. O slug que o `data-tenant` do snippet do site tem de trazer
    # para o botao aparecer. `GET /widget/aparencia` o devolve, e quem compara
    # e o Next (emenda da TEC-344 ao D3). **Nulo por padrao, e nulo quer dizer
    # que nenhum slug casa**: um ambiente que esqueceu a variavel fica sem
    # botao, e nao com um botao que aceita qualquer valor. Vazio vira nulo, e
    # fora do formato do Next nao sobe -- ver `_tenant_slug_no_formato_do_next`.
    # Tenant unico na POC (PR-03); o multi-tenant troca a comparacao por uma
    # busca.
    tenant_slug: str | None = None

    # A base do dashboard (E8), para o link da RN-15.5 e para o da RN-16.2.
    # Vazia em desenvolvimento: o dashboard nao existe ainda, e o link
    # composto sobre uma base vazia continua sendo um caminho valido -- ver a
    # L4 do desenho.
    dashboard_base_url: str = ""

    # Exportacao para CRM (TEC-180, RN-16.5).
    #
    # `crm_webhook_url` vazia DESLIGA a exportacao, e o worker sobe assim --
    # divergencia deliberada da guarda de `SMTP_HOST` em `workers/main.py`, que
    # RECUSA subir. A notificacao ao corretor e `Must` e sem ela o lead espera
    # sem que ninguem saiba; a exportacao e `Should`, e a propria card declara
    # o contorno da POC ("trabalhar direto no dashboard"). Uma guarda aqui
    # tornaria uma integracao opcional pre-requisito para rodar o sistema. O
    # que substitui a guarda e um `warning` unico na subida do worker -- ver a
    # emenda E-02 a RN-16.5 e a D2 do desenho.
    crm_webhook_url: str = ""
    # Sem segredo, o POST vai sem assinatura. Assinar e do interesse de quem
    # RECEBE, que precisa ter o segredo para verificar; exigi-lo tornaria o
    # webhook mais dificil de plugar sem tornar nada mais seguro deste lado.
    crm_webhook_secret: str = ""
    # Mesmo numero e mesma razao do `TIMEOUT_SEGUNDOS` de
    # `domain/outbound/whatsapp.py`: e o teto por tentativa, e tres delas
    # precisam caber com folga no `job_timeout` do worker.
    crm_timeout_segundos: float = 10.0
    # A base do backoff exponencial: as esperas sao 30 s e 60 s (base x 2^n).
    #
    # Configuravel so porque o teste precisa injetar centesimos de segundo --
    # mesmo argumento de `indicador_de_digitacao_apos_segundos` logo acima. O
    # FATOR e a CONTAGEM nao sao configuraveis: sao a regra, e vivem em
    # `domain/crm/port.py` e no job.
    crm_backoff_base_segundos: float = 30.0
    # Ha quanto tempo um handoff sem nenhuma tentativa conta como "o enqueue se
    # perdeu" para a varredura. Maior que o backoff inteiro (30 + 60 = 90 s),
    # ou a varredura recolheria um handoff cuja primeira rodada ainda esta em
    # voo e dispararia uma segunda em paralelo.
    sweep_crm_sem_tentativa_after_seconds: int = 600

    # TEC-170, D5. O refresh token OAuth da conta Google da imobiliaria que
    # ORGANIZA os eventos e convida o corretor. Vazio DESLIGA a integracao --
    # a convencao de `crm_webhook_url` --: o worker sobe com `CalendarioNoop`
    # e um aviso. Com o token preenchido, id e segredo do cliente passam a ser
    # obrigatorios (guarda no `startup` do worker).
    google_calendar_client_id: str = ""
    google_calendar_client_secret: str = ""
    google_calendar_refresh_token: str = ""
    # A agenda da conta organizadora onde o evento nasce. `primary` e a
    # principal dela; o corretor recebe o evento por convite, nao por escrita
    # direta na agenda dele.
    google_calendar_id: str = "primary"

    # RN-02.5: teto por chamada. RN-02.2: piso de mensagens literais.
    contexto_teto_de_tokens: int = 12000
    contexto_literais_minimas: int = 20

    # Reserva subtraida do teto antes de qualquer comparacao -- ver
    # `teto_de_tokens_efetivo`. Protege contra o que o contador nao ve: a
    # contagem de `montar_contexto` mede uma mensagem plana, e a requisicao
    # real difere dela em cinco parcelas MEDIDAS (o `SISTEMA` de
    # montagem.py, que e contado e nao enviado; e o `SISTEMA_DO_AGENTE`, o
    # schema compilado, os rotulos de `montar_prompt` e a definicao da
    # ferramenta de busca em `tools=` (TEC-265), enviados e nunca contados).
    #
    # **Ha uma sexta parcela, e ela NAO entra em `_decomposicao`.** Quando o
    # laco de tool use (TEC-265) da a segunda volta, a segunda chamada ao
    # modelo tambem manda o eco do `tool_use` do assistente e o `tool_result`
    # com ate 10 candidatos -- e nenhum dos dois e contado por
    # `montar_contexto` nem pelas cinco parcelas acima. Ficou de fora de
    # proposito (fix-wave da TEC-265): medir e travar um sexto numero e
    # decisao de design, nao correcao deste comentario.
    #
    # O que importa aqui e o tamanho, em tokens REAIS -- nao no proxy `len/4`,
    # que mediria outra coisa e nao pode ser subtraido de um numero em tokens
    # (foi o erro da primeira redacao deste paragrafo, na TEC-225: fazia
    # `1600 - 793`, tokens reais menos um teto medido no proxy). A reserva de
    # 1700 cobria a subcontagem medida de 1599 (ver a entrada TEC-225 abaixo)
    # com **101 tokens reais de folga**; a TEC-204 gastou 53 deles (41 da
    # clausula de dado nao confiavel, 12 das tags `<resumo>`), e hoje sao
    # 1652 contra 1700, **48 de folga**. Medido contra `ContadorAnthropic`
    # (20/09/2026): um `tool_result` de 10 candidatos com titulo e bairro
    # TIPICOS (~45 e ~8 caracteres) custa **1.169 tokens reais**; com titulo e
    # bairro no MAXIMO da coluna (`String(160)`/`String(120)` em
    # `catalogo/models.py`), **3.709**. Os dois estouram a folga (101 na
    # TEC-225, 48 desde a TEC-204) por larga margem -- 11,6x e 36,7x,
    # respectivamente. O segundo round-trip de um turno com busca de 10
    # candidatos NAO "pode" estourar a reserva: ele a estoura, toda vez que a
    # segunda volta do laco acontece com essa contagem. Busca que volta com um
    # candidato, ou com zero, nao foi medida -- e plausivel que estoure tambem
    # (a folga e so 48), mas isto
    # nao afirma por numero que nao mediu. A sexta parcela continua fora
    # da reserva por decisao de desenho anterior a esta card (fix-wave da
    # TEC-265) -- o que muda aqui e este comentario parar de mentir sobre o
    # tamanho do que ficou de fora.
    #
    # **O valor de hoje dessa diferenca nao esta escrito aqui, de proposito**
    # (TEC-243). Ele e derivado -- muda quando alguem mexe no prompt, num
    # campo do schema ou num rotulo -- e transcrito a mao ele envelheceu
    # quatro vezes em dois dias, sempre pego tarde e por revisao humana. Ele
    # vive em `tests/unit/test_config.py`, que nao pode mentir porque roda:
    #
    #     python -m pytest -q -k margem_do_orcamento -s
    #
    # imprime as cinco parcelas, o liquido, o teto e a folga.
    #
    # O que este comentario registra e o que **nao** envelhece: por que a
    # reserva existe, por que ela ja subiu cinco vezes, e o que cada subida
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
    #
    # **880 -> 1060 na TEC-265**, que declarou a ferramenta de busca em
    # `tools=` (131,2 tokens). A alternativa sem `enum` em `operacao` custava
    # 123,8, e os 7,5 de diferenca compram o modelo traduzindo COMPRA -> VENDA
    # sozinho: os dois vocabularios discordam e `Operacao("COMPRA")`
    # levantaria em turno normal.
    #
    # 1005 (880 + 125, o aumento que so cobria o teto fixo) nao serviu: deixa
    # `headroom * 0,75` -- o teto que `test_diferenca_entre_o_contado_e_o_enviado`
    # usa -- em 753,75, abaixo do proprio liquido de 780,0. O fator 0,75
    # exige mais reserva do que o teto fixo sozinho pede; 1060 deixa esse
    # segundo teto em 795,0, com folga de 9,0 sobre o teto fixo de 786 (ver
    # `test_a_margem_do_orcamento_do_prompt_e_deliberada`). Preco desta
    # subida: **180 tokens a menos de literais e resumo por turno, de 12000
    # -- 1,5% do contexto**. E a segunda maior da historia do projeto, atras
    # dos 3,3% da primeira.
    #
    # **1060 -> 1700 na TEC-225.** As quatro subidas acima nasceram de
    # aritmetica sobre o proxy `len/4` dos dois lados da conta -- e por isso
    # `test_diferenca_entre_o_contado_e_o_enviado` e
    # `test_a_margem_do_orcamento_do_prompt_e_deliberada` passavam sem provar
    # nada sobre a reserva: a regua era a mesma dos dois lados. Esta e a
    # primeira que sai de medicao contra o contador real
    # (`ContadorAnthropic`, claude-sonnet-5), parcela a parcela, em
    # 20/09/2026:
    #
    #     parcela                                     len/4     real
    #     -montagem.SISTEMA (contado, nao enviado)    -42,0    -77,0
    #     +SISTEMA_DO_AGENTE (campo system=)          305,5    541,0
    #     +schema compilado (output_config.format)    372,8    798,0
    #     +rotulos de montar_prompt                    19,2     41,0
    #     +ferramenta de busca (tools=)                131,2    242,0
    #     = subcontagem (cinco parcelas, cinco chamadas)  786,8  1.545,0
    #
    # **A soma acima sobrecontava.** Cada parcela foi medida numa chamada
    # separada de `count_tokens`, e a sobrecarga fixa de 7 tokens por chamada
    # nao existe na requisicao real, unica -- descontada ela, as cinco
    # parcelas somam **1.524** tokens reais, nao 1.545. Falta ainda o
    # envelope estrutural do array multi-turno que `teto_de_tokens_efetivo`
    # so estimava ("100-200 tokens"): medido, **75 tokens para 40
    # mensagens** (35 para 20). Total de ponta a ponta: **1.524 + 75 =
    # 1.599** tokens reais.
    #
    # A reserva de 1060 era 539 tokens menor que essa lacuna (1599 - 1060).
    # 1700 cobria os 1599 medidos com **101 de folga real** (48 desde a
    # TEC-204) -- ver a entrada
    # da sexta parcela, acima, para o que essa folga NAO cobre. A validacao
    # desta subida e `test_o_headroom_cobre_a_subcontagem_medida` em
    # `tests/unit/test_config.py`, e nao os dois testes acima: aqueles
    # continuam medindo em `len/4` e viraram alarme contra crescimento do
    # prompt, nao prova da reserva.
    #
    # Preco desta subida: **640 tokens a menos de literais e resumo por
    # turno, de 12000 -- 5,3% do contexto**, o teto efetivo caindo de 10940
    # para 10300 -- cerca de 1.470 caracteres de conversa a menos por
    # chamada. E a maior subida da historia do projeto, e a primeira cujo
    # tamanho vem de medir, nao de arredondar sobre uma estimativa.
    contexto_headroom_de_tokens: int = 1700

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

    # TEC-290. O relogio da fase inteira de resumir/contar, e nao o teto de
    # uma chamada: os tetos por chamada vivem em `infra/anthropic.py` e nao
    # limitam um laco que faz N chamadas. Enquanto o pior caso era somado
    # requisicao a requisicao, ele crescia com `contexto_max_iteracoes` acima
    # -- e foi assim que a soma do turno chegou a 327s contra um
    # `job_timeout` de 240.
    #
    # 35s nao e medida da montagem: e o que sobra do `job_timeout` depois das
    # outras fatias do turno e da reserva de 30s do banco. O teto duro e 38s.
    # A conta inteira mora em `tests/unit/test_orcamento_do_turno.py`, que e o
    # unico lugar que enxerga os quatro clientes externos juntos.
    #
    # Estourar aqui NAO e falha: o turno segue com o contexto truncado sem
    # falar com o provedor (`_estimar_pessimista`), o lead recebe resposta, e
    # `contexto.deadline_estourado` registra. E a diferenca em relacao a um
    # teto por chamada, que vira erro tipado.
    contexto_deadline_de_montagem_segundos: float = 35.0

    log_level: str = "INFO"

    sweep_received_after_seconds: int = 30
    sweep_inflight_after_seconds: int = 300
    sweep_max_attempts: int = 5

    # TEC-261. O piso deste numero NAO vem do reagendamento do ARQ por
    # `job_timeout`. Verificado empiricamente neste venv: `job_timeout` vira
    # `CancelledError` DENTRO da corrotina, mas `asyncio.wait_for`
    # (`arq/worker.py:599`) converte o estouro em `TimeoutError` para quem
    # chama. `TimeoutError` e uma `Exception` comum, e o despacho
    # (`arq/worker.py:613-628`) cai no `else`: `finish = True`,
    # `jobs_failed += 1`. Um `importar_catalogo` que estoura o tempo e
    # TERMINAL e NUNCA e retentado -- e nada o reenfileira: a rota em
    # `imoveis.py` e o unico `enqueue_job("importar_catalogo", ...)`, e nao ha
    # `sweep_stalled` equivalente para importacao. Mesma distincao que
    # `workers/jobs/sweep_stalled.py` ja documenta: o ARQ so reagenda `Retry`,
    # `RetryJob` e `CancelledError` de verdade -- nao qualquer `Exception`.
    #
    # A sensibilidade real e outra: um cancelamento por REINICIO do worker (o
    # processo mata a corrotina em voo, sem passar pelo `wait_for`) chega como
    # `CancelledError` de verdade, e esse SIM e retentado ate `max_tries = 5`
    # vezes -- sem backoff, o job volta a fila com `incr_score=None`,
    # imediatamente. O piso pelo caminho do ARQ e uma tentativa de
    # `job_timeout = 240` mais a espera na fila, nao 20 minutos: subir
    # `max_tries` nao move nada aqui, porque o estouro de tempo em si nao e
    # retentado por essa via -- so o reinicio o e.
    #
    # 30 minutos ficam bem acima desse piso, cobrindo tambem os reinicios que
    # de fato retentam. Importacao e rara: uma linha travada esperar meia hora
    # antes de ser fechada nao custa nada, e o custo do outro lado -- fechar
    # uma que ainda esta viva -- e a mentira de relatorio que esta card existe
    # para acabar.
    #
    # **Quem subir `job_timeout` tem de reconferir este numero** -- `max_tries`
    # sozinho nao move o piso, so os reinicios de worker o fazem. Ele nao se
    # move sozinho, e nada acusa quando o piso cresce.
    #
    # O caminho da CLI (`admin/seed_catalogo.py`) chama `registrar` + `executar`
    # em processo, sem ARQ e sem `job_timeout` nenhum -- esta varredura nao
    # filtra por origem, entao uma linha `CLI` parada tambem entra. Efeito
    # bom: um seed interrompido (Ctrl+C) fica fechado, o que a card nao
    # prometia.
    sweep_importacao_travada_after_seconds: int = 1800

    # TEC-157. A chave do provedor de embedding, que NAO e a da Anthropic: a
    # API da Anthropic nao tem endpoint de embeddings, entao a indexacao usa
    # um segundo provedor e o agente segue no `infra/anthropic.py`.
    #
    # Sem valor, o `startup` do worker RECUSA subir em producao (D10) e a
    # varredura avisa uma unica vez em desenvolvimento. Nao ha default: uma
    # chave falsa faria o provedor recusar a cada lote, que e o mesmo estrago
    # com sintoma pior.
    openai_api_key: str | None = None

    # 1536 nao e ajustavel a gosto: e a dimensao da coluna `vector(1536)` da
    # `0017` e a do modelo escolhido. Mudar aqui sem migration deixa o
    # provedor devolvendo vetor que a coluna recusa.
    embedding_modelo: str = "text-embedding-3-small"
    embedding_dimensoes: int = 1536

    # Teto de candidatos por passagem e tamanho do lote por chamada. O lote e
    # MENOR que o teto de proposito: com um lote so, "comita por lote" nao
    # significaria nada -- uma falha desfaria a passagem inteira. Com dois,
    # uma falha na segunda chamada preserva os 50 primeiros.
    indexacao_limite_por_passagem: int = 100
    indexacao_tamanho_do_lote: int = 50

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

    # RN-16.1 (TEC-143): a janela em que existe gente para atender, em horas
    # locais do `followup_fuso` acima -- mesmo fuso, reaproveitado, e nao um
    # terceiro campo `atendimento_fuso`. Fora dela o handoff e criado do mesmo
    # jeito -- so o texto que o lead recebe muda (`TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO`
    # em `domain/humano/deteccao.py`), porque a card e explicita em que ele
    # nunca fica em espera silenciosa.
    #
    # Janela da imobiliaria, e nao a jornada do corretor designado: no instante
    # do pedido ninguem foi designado ainda -- a alocacao por especialidade e
    # regiao (TEC-166) escolhe corretor para o agendamento, nao para o
    # handoff. Uma janela unica responde "quando alguem te atende" sem
    # precisar saber quem.
    #
    # Mesma convencao de borda que `followup_horario_fim` documenta acima --
    # `fim` e o ultimo MINUTO em que a janela ainda vale, nao a ultima hora
    # inteira: `atendimento_horario_fim=19` inclui 19:00 e recusa 19:01. Ver
    # `dentro_da_janela_de_atendimento` para a comparacao.
    #
    # **Estas horas nao dizem a janela inteira (TEC-285).** Domingo nao e dia
    # de atendimento, e isso NAO esta aqui: e regra em codigo, na constante
    # `_DOMINGO` de `domain/humano/deteccao.py`, que explica por que os dias
    # ficaram fora da configuracao. Quem ler so estes dois campos conclui que a
    # janela e todo dia, e e por isso que esta frase existe.
    atendimento_horario_inicio: int = 9
    atendimento_horario_fim: int = 19

    @property
    def em_producao(self) -> bool:
        """O unico lugar que decide o que "producao" quer dizer.

        Os validators de producao abaixo e a guarda de `OPENAI_API_KEY` no
        `workers/main.py` (TEC-157) fazem a mesma pergunta. Uma copia de
        `environment.strip().lower() in _AMBIENTES_DE_PRODUCAO` em cada um
        divergiria no dia em que alguem aceitasse mais um nome de ambiente em
        uma delas so -- e a divergencia apareceria como guarda que nao guarda.

        Duas excecoes repetem a conta sobre `os.environ`, e nao sobre o campo:
        `get_settings`, que decide antes de existir um `Settings`, e
        `_recusar_producao_declarada_em_arquivo`, cuja pergunta e justamente se
        o ambiente veio de `os.environ`. As duas usam o mesmo
        `_AMBIENTES_DE_PRODUCAO`, que e o que as mantem iguais a esta.
        """
        return self.environment.strip().lower() in _AMBIENTES_DE_PRODUCAO

    @model_validator(mode="after")
    def _recusar_producao_declarada_em_arquivo(self) -> "Settings":
        """`ENVIRONMENT` de producao tem de vir do ambiente, nao do `.env`.

        Sem isto, `ENVIRONMENT=production` escrito so no `.env` ligaria todas
        as guardas de producao -- e o `.env` teria sido lido, que e o que
        `get_settings` existe para impedir.

        Fica antes das guardas de segredo de desenvolvimento de proposito, para
        o erro nomear a causa e nao o sintoma. Com producao declarada so no
        `.env`, os segredos quase sempre sao os de desenvolvimento -- do mesmo
        arquivo ou dos defaults --, e uma guarda deles que disparasse primeiro
        reprovaria por "chave default" -- e quem lesse iria trocar a chave, sem
        saber que o arquivo inteiro nao devia ter sido lido. Os validators
        `after` rodam na ordem em que estao definidos, e `ConfiguracaoInsegura`
        interrompe no primeiro. `test_ambiente_de_producao_vindo_do_arquivo_reprova`
        prende a ordem pela frase deste erro.
        """
        declarado = os.environ.get("ENVIRONMENT", "").strip().lower()
        if self.em_producao and declarado not in _AMBIENTES_DE_PRODUCAO:
            raise ConfiguracaoInsegura(
                f"ENVIRONMENT={self.environment} veio de arquivo, nao do ambiente. "
                "Em producao o ambiente e declarado pela plataforma, e o .env nao e lido."
            )
        return self

    @model_validator(mode="after")
    def _recusar_chave_de_desenvolvimento_em_producao(self) -> "Settings":
        """Fica no validator, e nao no `create_app`, para valer em todo processo.

        A exposicao mais afiada e a migration 0004, que importa
        `mobia.infra.crypto` e cifraria a tabela inteira com a chave de
        desenvolvimento se um job de CI/CD subisse sem o segredo -- e ela nao
        passa pelo `create_app`. Aqui a guarda pega API, worker, alembic e
        qualquer script que construa `Settings`.
        """
        if self.em_producao and self.content_encryption_key == CHAVE_DE_DESENVOLVIMENTO:
            raise ConfiguracaoInsegura(
                "CONTENT_ENCRYPTION_KEY esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Gere uma chave de 32 bytes: "
                'python -c "import base64,os;'
                'print(base64.b64encode(os.urandom(32)).decode())"'
            )
        return self

    @model_validator(mode="after")
    def _validar_keyring(self) -> "Settings":
        """Keyring errado falharia so na primeira cifra -- aqui falha na subida."""
        if not self.content_encryption_keys:
            if self.content_encryption_key_ativa:
                raise ValueError("CONTENT_ENCRYPTION_KEY_ATIVA sem CONTENT_ENCRYPTION_KEYS")
            return self
        for identificador, chave in self.content_encryption_keys.items():
            data_do_id(identificador)
            if len(base64.b64decode(chave)) != 32:
                raise ValueError(
                    f"a chave {identificador} do keyring nao tem 32 bytes apos o base64"
                )
            if self.em_producao and chave == CHAVE_DE_DESENVOLVIMENTO:
                raise ConfiguracaoInsegura(
                    f"a chave {identificador} do keyring e a de desenvolvimento e "
                    f"ENVIRONMENT={self.environment}."
                )
        if self.content_encryption_key_ativa not in self.content_encryption_keys:
            raise ValueError(
                f"a chave ativa {self.content_encryption_key_ativa!r} nao esta no keyring"
            )
        return self

    @model_validator(mode="after")
    def _recusar_segredo_de_jwt_de_desenvolvimento_em_producao(self) -> "Settings":
        """TEC-201. Mesmo molde da chave de cifra, e pela mesma razao.

        Um segredo de assinatura publicamente conhecido nao produz erro
        nenhum: o sistema autentica normalmente, e quem souber o segredo entra
        como ADMIN sem senha e sem segundo fator. E o modo de falha silencioso
        que esta guarda existe para matar.
        """
        if self.em_producao and len(self.jwt_segredo.encode("utf-8")) < BYTES_MINIMOS_DO_JWT:
            raise ConfiguracaoInsegura(
                f"JWT_SEGREDO tem menos de {BYTES_MINIMOS_DO_JWT} bytes e "
                f"ENVIRONMENT={self.environment}. A RFC 7518 pede pelo menos o "
                "tamanho da saida do HMAC (32 bytes para SHA-256); abaixo disso "
                "a assinatura fica mais facil de quebrar por forca bruta do que "
                "o algoritmo promete. Gere um: "
                'python -c "import secrets;print(secrets.token_urlsafe(48))"'
            )
        if self.em_producao and self.jwt_segredo == SEGREDO_DE_JWT_DE_DESENVOLVIMENTO:
            raise ConfiguracaoInsegura(
                "JWT_SEGREDO esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Quem o conhece emite token de "
                "ADMIN para si mesmo, sem senha e sem MFA. Gere um: "
                'python -c "import secrets;print(secrets.token_urlsafe(48))"'
            )
        return self

    @model_validator(mode="after")
    def _recusar_chave_do_lead_de_desenvolvimento_em_producao(self) -> "Settings":
        """TEC-206, D4. Mesmo molde da chave de cifra e do segredo de JWT.

        Uma chave de HMAC publicamente conhecida nao falha: a trilha grava
        normalmente, e quem souber a chave recalcula o `lead_ref` de qualquer
        telefone. No validator, e nao no `create_app`, para valer em API,
        worker, alembic e qualquer script que construa `Settings`.
        """
        if self.em_producao and self.auditoria_chave_do_lead == CHAVE_DO_LEAD_DE_DESENVOLVIMENTO:
            raise ConfiguracaoInsegura(
                "AUDITORIA_CHAVE_DO_LEAD esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Quem a conhece descobre se um "
                "telefone aparece na trilha de auditoria. Gere uma: "
                'python -c "import secrets;print(secrets.token_urlsafe(48))"'
            )
        return self

    @model_validator(mode="after")
    def _recusar_chave_de_indice_de_desenvolvimento_em_producao(self) -> "Settings":
        """TEC-203. Chave de HMAC publicamente conhecida nao falha: ela so deixa
        qualquer um recalcular a chave de um telefone e achar a conversa dele."""
        data_do_id(self.lead_indice_chave_id)
        if self.em_producao and self.lead_indice_chave == CHAVE_DO_INDICE_DE_DESENVOLVIMENTO:
            raise ConfiguracaoInsegura(
                "LEAD_INDICE_CHAVE esta com o default de desenvolvimento e "
                f"ENVIRONMENT={self.environment}. Gere uma: "
                'python -c "import secrets;print(secrets.token_urlsafe(48))"'
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

    @model_validator(mode="after")
    def _recusar_janela_de_atendimento_impossivel(self) -> "Settings":
        """Horario invertido ou vazio fecha a janela de atendimento para sempre.

        Ao contrario da cadencia de follow-up, aqui o sintoma nao e ausencia
        de alguma coisa -- e presenca da errada, sempre. `inicio >= fim` torna
        `[inicio*60, fim*60]` vazio ou invertido em `dentro_da_janela_de_atendimento`
        (`domain/humano/deteccao.py`), e nenhum minuto do dia satisfaz as duas
        pontas ao mesmo tempo: todo lead que pedir humano recebe
        `TEXTO_DO_PEDIDO_DE_HUMANO_FORA_DO_HORARIO`, nunca o outro texto, em
        qualquer hora que escreva. Nada quebra, nada loga erro -- so a
        imobiliaria aparenta nunca ter ninguem disponivel, e e essa mentira
        silenciosa que a guarda existe para recusar na subida do processo.

        **Esta guarda nao cobre o dia da semana (TEC-285).** Domingo fecha a
        janela por regra de codigo (`_DOMINGO`, em `domain/humano/deteccao.py`)
        e nao por configuracao, entao nao ha o que validar aqui -- e tambem
        nao ha como uma configuracao errada apagar um dia. O que mudou e o
        alcance da frase acima: "aparenta nunca ter ninguem disponivel" deixou
        de ser exclusividade da janela invertida, porque existe um dia inteiro
        da semana em que todo lead recebe o texto de fora do horario.
        """
        if not 0 <= self.atendimento_horario_inicio < self.atendimento_horario_fim <= 23:
            raise ValueError(
                "atendimento_horario_inicio e atendimento_horario_fim precisam satisfazer "
                f"0 <= inicio < fim <= 23; recebi inicio={self.atendimento_horario_inicio} "
                f"e fim={self.atendimento_horario_fim}. Horario invertido ou vazio faz todo "
                "lead que pedir humano receber o texto de fora do horario, sempre."
            )
        return self

    @field_validator("tenant_slug", mode="before")
    @classmethod
    def _tenant_slug_no_formato_do_next(cls, valor: object) -> object:
        """O formato e o que o Next aceita no `data-tenant` (`SLUG`, em
        `frontend/src/lib/servidor/aparencia.ts`), e as duas copias tem de
        bater.

        Sem esta guarda, `TENANT_SLUG=MinhaImob` subiria, o Next recusaria
        todo `data-tenant` antes de comparar, e nenhum site mostraria o botao
        -- sem uma linha de log em lugar nenhum. `TENANT_SLUG=` vazio no
        `.env` chega como "", e "" nao e um slug: vira nulo, que e o "nenhum
        slug casa" do default.
        """
        if valor is None or valor == "":
            return None
        if not isinstance(valor, str) or not _FORMATO_DO_SLUG.fullmatch(valor):
            raise ValueError(
                f"TENANT_SLUG fora do formato; recebi {valor!r}. Use minusculas, digitos "
                "e hifen, comecando por letra ou digito, ate 64 caracteres "
                "(^[a-z0-9][a-z0-9-]{0,63}$) -- o Next recusa qualquer outro, e o botao "
                "sumiria de todo site sem aviso."
            )
        return valor

    @model_validator(mode="after")
    def _recusar_rate_limit_impossivel(self) -> "Settings":
        """Numero negativo aqui falha em silencio ou inverte o fluxo.

        Limite negativo cai no mesmo ramo que o zero (`limite <= 0` em
        `consumir`) e desliga o limitador -- so que parecendo configurado, que
        e a pior das duas coisas. Atraso negativo vira `_defer_by` para o
        passado e o excedente seria processado ANTES da mensagem que respeitou
        o limite.

        `ValueError` e nao `ConfiguracaoInsegura` pelo criterio ja aplicado em
        `_recusar_horario_de_envio_impossivel`: isto nao roda sem a protecao
        que devia ter, isto deixa de operar.

        **Nao fecha a conta inteira.** A invariante de quatro termos --
        `max(debounce_de_rajada_segundos, atraso_de_backoff_segundos) +
        job_timeout < sweep_inflight_after_seconds` -- continua so no teste
        (`test_job_timeout_cabe_dentro_da_janela_do_sweeper`), porque
        `job_timeout` mora em `WorkerSettings` e trazer isso para ca abriria
        um ciclo de import. O que esta guarda pega, sem precisar de
        `job_timeout`, e o caso onde `atraso_de_backoff_segundos` sozinho ja
        estoura `sweep_inflight_after_seconds` -- os dois campos vivem no
        MESMO `Settings` -- e o operador que sobe
        `ATRASO_DE_BACKOFF_SEGUNDOS` no `.env` sem saber da invariante faz o
        sweeper reenfileirar um turno ainda em voo antes mesmo de o backoff
        acabar.
        """
        if self.rate_limit_mensagens_por_minuto < 0:
            raise ValueError(
                "rate_limit_mensagens_por_minuto nao pode ser negativo; recebi "
                f"{self.rate_limit_mensagens_por_minuto}. Use 0 para desligar o limite."
            )
        if self.rate_limit_requisicoes_por_ip_por_minuto < 0:
            raise ValueError(
                "rate_limit_requisicoes_por_ip_por_minuto nao pode ser negativo; recebi "
                f"{self.rate_limit_requisicoes_por_ip_por_minuto}. Use 0 para desligar."
            )
        if self.atraso_de_backoff_segundos < 0:
            raise ValueError(
                "atraso_de_backoff_segundos nao pode ser negativo; recebi "
                f"{self.atraso_de_backoff_segundos}. Um defer negativo agendaria o "
                "excedente para antes de quem respeitou o limite."
            )
        if self.atraso_de_backoff_segundos >= self.sweep_inflight_after_seconds:
            raise ValueError(
                "atraso_de_backoff_segundos "
                f"({self.atraso_de_backoff_segundos}) precisa ser menor que "
                f"sweep_inflight_after_seconds ({self.sweep_inflight_after_seconds}); "
                "do contrario o excedente do rate limit por numero fica em voo por mais "
                "tempo do que o sweeper espera antes de reenfileirar, e a mesma conversa "
                "roda duas vezes em paralelo. Isto nao fecha a conta inteira -- "
                "`job_timeout` tambem entra, ver "
                "`test_job_timeout_cabe_dentro_da_janela_do_sweeper` -- mas pega o caso "
                "que nao depende dele."
            )
        return self

    @model_validator(mode="after")
    def _recusar_s3_sem_bucket(self) -> "Settings":
        """`midia_armazem="s3"` sem bucket sobe limpo e so falha dentro do job.

        `armazem_da_config` (`domain/midia/armazem.py`) constroi `ArmazemS3`
        com o que estiver aqui, sem olhar se e vazio -- o primeiro sintoma
        seria um erro do boto3 no meio do job `baixar_midia` (Task 5), longe
        de onde a configuracao foi escrita. `ValueError`, e nao
        `ConfiguracaoInsegura`: o caso desta ultima e configuracao que roda
        sem a protecao que devia ter (a chave de cifra, o token de catalogo);
        aqui nao ha protecao perdida, ha escolha incompleta que deixa de
        operar.
        """
        if self.midia_armazem == "s3" and not self.midia_s3_bucket:
            raise ValueError(
                "midia_armazem='s3' exige midia_s3_bucket preenchido; recebi "
                f"midia_s3_bucket={self.midia_s3_bucket!r}."
            )
        return self

    @property
    def templates_aprovados(self) -> frozenset[str]:
        """Os nomes de template aprovados, ja separados e sem vazios. TEC-186.

        Property e nao um `frozenset` no campo: a fonte e uma variavel de
        ambiente (uma string), e derivar aqui evita um parser de env que
        falharia alto por causa de um espaco a mais. `frozenset` para bater
        com a assinatura de `escolher_template` e para ser imutavel.
        """
        return frozenset(
            nome.strip() for nome in self.whatsapp_templates_aprovados.split(",") if nome.strip()
        )

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
        requisicao real que a TEC-134 monta e um system prompt mais um array
        multi-turno, e cada turno carrega overhead estrutural que o contador
        nunca ve -- medido na TEC-225 (`ContadorAnthropic`) em **35 tokens
        para uma janela de vinte mensagens e 75 para quarenta**, nao mais os
        "100-200" que esta docstring estimava antes de alguem medir. Some a
        isso que `_texto_do_estado` e explicitamente uma representacao para
        medir, nao o renderizador que a TEC-134 usa.

        A reserva nasceu porque contar a forma exata exigiria conhecer a forma
        exata, e na epoca o consumidor que a define ainda nao existia:
        construir para um palpite e pior que reservar margem. Hoje ele existe,
        e a reserva continua -- o que a substituiu nao foi contar a forma
        exata, e sim a medicao registrada abaixo. O valor e
        `contexto_headroom_de_tokens`, e o comentario da propria constante
        registra por que ele ja subiu cinco vezes e o que cada subida custou.

        **Medido na TEC-134, com a requisicao real ja montada.** A conta usa
        um proxy `len/4` proprio do orcamento -- **nao** o mesmo da TEC-225
        (`montagem.py` mede densidade de conteudo, isto mede peso de prompt e
        schema) --, e nao uma chamada de `count_tokens`: medir contra a API
        de verdade custaria uma chamada paga por execucao e nao pode entrar
        na suite, que nao toca a rede. E estimativa honesta, nao medida
        exata, e e por isso que o resultado vira um teste
        (`test_diferenca_entre_o_contado_e_o_enviado`) em vez de um numero
        solto num comentario. Desde a TEC-225 esse teste, e o irmao
        `test_a_margem_do_orcamento_do_prompt_e_deliberada`, nao validam mais
        a reserva -- quem faz isso e `test_o_headroom_cobre_a_subcontagem_medida`,
        medido contra o contador real. Os dois continuam de pe como alarme
        contra crescimento do prompt, em unidades deste proxy proprio.

        Sao cinco as parcelas em que a contagem difere do que se envia:

        - `-` `montagem.SISTEMA` entra na contagem mas **nao** e enviado --
          o classificador chama `montar_prompt(omitir_sistema=True)`.
        - `+` `classificador.SISTEMA_DO_AGENTE` vai no campo `system=` e
          nunca passa pelo contador.
        - `+` o schema compilado em `output_config.format`, idem.
        - `+` os rotulos de secao que `montar_prompt` intercala.
        - `+` a definicao da ferramenta de busca em `tools=` (TEC-265), idem.

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
        abaixo, confia na estimativa ciente de densidade de `_estimar`
        (TEC-225).

        0.6 do teto efetivo por padrao (`teto_de_tokens_efetivo`, ja com a
        reserva descontada), nao um numero redondo -- e a mesma fracao de
        antes da TEC-225, porque o que precisava de conserto era a
        estimativa que ela compara, nao a fracao.

        A estimativa antiga (`len//4`, um proxy do ingles) so protegia
        texto que rodasse a `4*0.6 = 2.4` caracteres por token ou mais --
        abaixo disso ela podia dizer "cabe" com o real ja estourado. O
        portugues, lingua principal do produto, mede 2,34 sem acento e 2,38
        acentuado: **a folga real era de 2,6%**, nao a margem confortavel
        que esta docstring chegou a afirmar citando o intervalo do ingles
        (~3.2-3.7 chars/token, medido em 3,15) como se fosse o do
        portugues.

        A TEC-225 trocou a estimativa por uma ciente de densidade: ASCII a
        2,3 caracteres por token, nao-ASCII a 3 tokens por caractere. Contra
        essa formula o portugues passa a superestimar -- 1,02 a 1,23 do
        real, medido -- e o mesmo vale para emoji (1,06 do real, contra
        0,09 antes) e para uma duzia de URLs (0,80, contra 0,46 antes): os
        tres deixam de escapar da contagem real.

        O que sobra descoberto: base64, em 0,43 do real. Nao por descuido
        -- cobri-lo exigiria detectar "sequencia longa sem espaco", e esse
        detector tem falso-positivo proprio: uma URL longa e exatamente
        isso tambem (a D4 do desenho da TEC-225). Um turno dominado por
        base64 pode escapar da contagem real e sair medido para menos
        tokens do que de fato tem. Ate existir uma forma de distinguir os
        dois sem penalizar URL, isto e um risco aceito e documentado, nao
        um bug escondido.
        """
        if self.contexto_limiar_de_contagem is not None:
            return self.contexto_limiar_de_contagem
        return round(self.teto_de_tokens_efetivo * _FRACAO_SEGURA_DO_LIMIAR_DE_CONTAGEM)


@lru_cache
def get_settings() -> Settings:
    """Monta `Settings` com as fontes que o ambiente permite. TEC-203, D5.

    **Em producao o `.env` nao e lido.** Segredo em producao vem do secret
    manager da plataforma, que o entrega como variavel de ambiente ou arquivo
    montado; um `.env` no servidor e justamente o segredo em arquivo que a
    RNF-14 proibe. A decisao olha `os.environ` e nao `Settings`, porque e ela
    que decide se o arquivo entra -- ler o arquivo para descobrir se pode le-lo
    seria circular. Quem pusesse `ENVIRONMENT=production` so no `.env` escapa
    daqui; o validator `_recusar_producao_declarada_em_arquivo` o pega.

    `MOBIA_SECRETS_DIR` aponta o diretorio de arquivos montados (um arquivo por
    segredo, nome do campo em minusculas), no formato de Docker, K8s e ECS.
    """
    em_producao = os.environ.get("ENVIRONMENT", "").strip().lower() in _AMBIENTES_DE_PRODUCAO
    # `# type: ignore[call-arg]`: `BaseModel` e `@dataclass_transform`, e o
    # mypy sintetiza o construtor so a partir dos campos anotados -- ele nunca
    # olha o `__init__` de verdade que `pydantic_settings.BaseSettings`
    # escreve a mao (`main.py`), que e onde `_env_file` e `_secrets_dir`
    # existem. Em runtime os dois chegam la; so o checador nao os enxerga.
    return Settings(  # type: ignore[call-arg]
        _env_file=None if em_producao else ".env",
        _secrets_dir=os.environ.get("MOBIA_SECRETS_DIR") or None,
    )


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
