import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from mobia.domain.messages.models import Base
from mobia.infra.crypto import aad_de


def aad_do_resumo(channel: str, conversation_key: str) -> str:
    """Amarra o resumo a sua propria conversa.

    Nao ha `message_id` aqui -- o resumo cobre muitas mensagens -- entao a
    identidade da linha e o par (channel, conversation_key). Prefixado por
    tamanho porque `channel` e `String(32)` sem whitelist de caracteres: sem o
    prefixo, `("a:b", "c")` e `("a", "b:c")` colapsariam no mesmo AAD e um
    resumo poderia decifrar sob a chave de outra conversa. Com o tamanho na
    frente de cada parte, o ponto onde ela termina deixa de depender do
    conteudo, entao dois pares diferentes nunca produzem a mesma string.
    """
    identidade = f"{len(channel)}:{channel}:{len(conversation_key)}:{conversation_key}"
    return aad_de(identidade, "resumo")


class ConversationSummary(Base):
    """Resumo do que veio antes da marca d'agua.

    Uma linha por conversa: e estado corrente, nao historico. A marca e um par
    ordenavel `(created_at, id)` e nao uma contagem, porque contagem quebra
    quando uma linha e apagada ou quando duas mensagens chegam fora de ordem.
    """

    __tablename__ = "conversation_summaries"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Cifrado com AES-GCM, AAD de `aad_do_resumo` (formato em detalhe la). Um
    # resumo destila as mesmas frases que `messages.text_body` guarda --
    # deixa-lo em claro ao lado de uma coluna cifrada seria manter a
    # fechadura e tirar a porta.
    resumo: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    watermark_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    watermark_message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mensagens_cobertas: Mapped[int] = mapped_column(Integer, nullable=False)
    modelo: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @validates("resumo")
    def _recusar_texto_claro(self, coluna: str, valor: object) -> object:
        """Mesma guarda de `Message`: str aqui vira vazamento no texto do erro.

        O driver embute o argumento recusado na propria mensagem de excecao,
        antes de o SQLAlchemy ver qualquer coisa, e essa mensagem chega ao log.
        """
        if valor is not None and not isinstance(valor, bytes | bytearray | memoryview):
            raise TypeError(
                f"{coluna} aceita apenas bytes cifrados, recebeu {type(valor).__name__}"
            )
        return valor


class LeadQualification(Base):
    """Estado estruturado de qualificacao. Esta historia le; TEC-145 escreve.

    Fica **em claro**, ao contrario do resumo, e a assimetria e deliberada:
    TEC-150 e TEC-158 consultam faixa de preco e regiao em SQL, e cifrar
    forcaria carregar a tabela inteira para filtrar em memoria. A cifra da
    TEC-126 protege o que o lead escreveu; isto e o que o sistema concluiu.

    A TEC-147 **nao** consulta: `esta_qualificado` e funcao pura sobre a linha
    ja carregada, e nao ha consulta que filtre por qualificado (e uma lacuna
    declarada no desenho dela). Ela estava nesta lista por engano.
    """

    __tablename__ = "lead_qualification"

    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    intencao: Mapped[str | None] = mapped_column(String(16), nullable=True)
    faixa_preco_min_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    faixa_preco_max_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    regiao: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tipo_imovel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quartos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vagas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urgencia: Mapped[str | None] = mapped_column(String(32), nullable=True)
    forma_pagamento: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tem_imovel_para_vender: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # TEC-257. Os campos que o agente perguntou e o lead nao respondeu.
    #
    # `NULL` e `{}` nao sao sinonimos: `NULL` e "linha anterior a esta card,
    # ninguem marcava", `{}` e "marcava, e nao havia nada". Quem le tem de
    # tratar os dois iguais **na leitura** (`or ()`), e nunca gravar `NULL`
    # querendo dizer vazio.
    #
    # Em claro, como o resto desta tabela: e o que o sistema concluiu, nao o
    # que o lead escreveu.
    perguntados_sem_resposta: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(32)), nullable=True
    )

    # TEC-148, RN-05.7. Os campos que o lead se negou a informar.
    #
    # O nome vem do modelo de dados do SRS (`campos_recusados text[]`), e nao
    # de `recusados`, que e o nome do PARAMETRO que `esta_qualificado` expoe
    # desde a TEC-147. Coluna e parametro nao precisam coincidir.
    #
    # Coluna propria e nao reuso de `perguntados_sem_resposta`: silencio e
    # recusa sao fatos diferentes. Silencio e "pode ser que ele responda
    # depois"; recusa e "ele disse que nao". Colapsa-los tornaria
    # inqualificavel para sempre todo lead que apenas ainda nao respondeu.
    #
    # `NULL` e `{}` nao sao sinonimos, como na coluna vizinha: `NULL` e
    # "linha anterior a esta card, ninguem registrava", `{}` e "registrava, e
    # nao havia recusa". Quem le trata os dois iguais (`or ()`), e nunca grava
    # `NULL` querendo dizer vazio.
    #
    # Em claro, como o resto desta tabela: e o que o sistema concluiu, nao o
    # que o lead escreveu.
    campos_recusados: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)), nullable=True)

    # TEC-149, RN-05.5. Quantas perguntas de qualificacao ja foram FEITAS E
    # ENTREGUES a este lead. Cresce so no commit pos-entrega do turno -- ver
    # `contar_perguntas` no repositorio, e o porque no comentario que chama
    # `marcar_perguntados` em `turno.py`.
    #
    # `NOT NULL DEFAULT 0`, ao contrario das colunas acima: ali o `NULL`
    # distingue "linha anterior a card" de "nao havia nada", e para um
    # contador isso nao paga. Zero numa linha antiga significa "ninguem
    # contava", e o lead antigo recomeca com orcamento cheio.
    #
    # Conta CAMPO perguntado, nao turno: a Emenda E-01 da RN-05.4 permite
    # duas perguntas por turno desde a TEC-255, e contar turnos daria dezesseis
    # perguntas sob um teto que diz oito.
    perguntas_feitas: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")

    # TEC-153, RN-05.2. Os campos que o subagente do investidor pergunta, e
    # que a trilha padrao nao tem onde guardar. Nulaveis pela mesma razao das
    # vizinhas: qualificacao e progressiva.
    ticket_investimento_centavos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Centavos como todo dinheiro deste schema (RN-05.6), e `Numeric` para o
    # percentual porque ele e taxa, nao dinheiro: `numeric(4,2)` vem do
    # dicionario de dados do SRS.
    retorno_esperado_pct: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    # O campo QUALITATIVO que a RN-07.2 pressupoe sem nomear. O percentual
    # acima nao separa renda de valorizacao -- e este que separa, e e ele que
    # `perfil_de` le. Ver a Emenda E-01 da RN-07.2.
    retorno_esperado_tipo: Mapped[str | None] = mapped_column(String(16), nullable=True)
    horizonte: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tolerancia_reforma: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ja_investe_em_imoveis: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # DERIVADO de `horizonte` + `retorno_esperado_tipo` por `perfil_de`, e
    # gravado em vez de recalculado na leitura: a TEC-154 le o perfil direto.
    #
    # **NULL nao e MISTO.** NULL e "falta um dos dois campos, ainda nao sei";
    # MISTO e "sei, e os sinais se contradizem". Colapsar os dois faria a
    # TEC-154 exibir indicador de perfil para quem nunca respondeu.
    perfil_investidor: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # TEC-151, RN-06.2. A temperatura corrente do lead.
    #
    # Materializada, e nao derivada na leitura: e contra ela que a borda da
    # RN-06.5 compara para saber se o lead ACABOU de esquentar. Derivar na
    # leitura daria a temperatura de agora e nao a de antes, e a notificacao
    # dispararia em todo turno quente em vez de na travessia.
    #
    # `NULL` significa "linha anterior a esta card, nunca recalculada", e nao
    # "FRIO": um lead cuja primeira travessia cai em QUENTE tem de emitir, e
    # com NULL colapsado em FRIO ele emitiria igual -- mas um lead que JA era
    # quente antes desta card reemitiria, e a distincao existe para isso.
    #
    # Denormalizacao declarada: ao contrario do `total_novo` da 0012, que a
    # soma dos cinco fatores prende num CHECK, esta coluna guarda uma
    # conclusao que ninguem pode reconferir contra o banco. Se os pesos
    # virarem configuracao (RF-19), ela passa a guardar uma conclusao
    # calculada com os pesos de ontem.
    temperatura: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # TEC-151, RN-06.3. Quando o lead foi forcado a QUENTE por gatilho.
    #
    # `NULL` = nao forcada. Nao nulo = QUENTE ate intervencao humana, e
    # nenhum recalculo de score rebaixa -- e a leitura desta coluna que
    # alimenta o `forcada` de `temperatura_de`, entao a regra de "nao
    # rebaixa" mora no mesmo lugar que a regra de "qual e a temperatura".
    #
    # O carimbo e o do PRIMEIRO forcamento, nao do ultimo: quem grava usa
    # `COALESCE`. E o que "permanece ate intervencao humana" torna
    # interessante -- quando esquentou, e ha quanto tempo ninguem interveio.
    #
    # **A intervencao humana (TEC-192) nao existe hoje, e nada nesta base
    # limpa esta coluna.** Quando ela for construida, limpar SO este carimbo
    # nao basta e passa despercebido pelos dois CHECK: `NULL` aqui com
    # `temperatura_forcada_motivos` ainda preenchido e `temperatura` ainda
    # "QUENTE" satisfaz os dois (com o carimbo NULL, nenhum dos dois chega a
    # olhar para a coluna vizinha) e deixa a linha MENTINDO -- forcada por
    # motivos que a coluna de carimbo diz que nao existem mais, e a
    # temperatura travada em QUENTE sem nenhum dos tres campos concordando
    # entre si. A intervencao tem de limpar as TRES colunas juntas
    # (`temperatura_forcada_em`, `temperatura_forcada_motivos` e recalcular
    # `temperatura` a partir do score puro, via `temperatura_de` com
    # `forcada=False`) na mesma transacao, nunca so esta.
    temperatura_forcada_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # TEC-151, RN-06.3. Quais gatilhos forcaram, acumulados.
    #
    # Uniao entre turnos e nao sobrescrita, no molde de `campos_recusados`:
    # "primeiro vence" esconde o que veio depois, "ultimo vence" perde
    # justamente o motivo que forcou, e a uniao nao tem esse lado. Duplicata
    # e possivel (o lead pede visita duas vezes) e nao incomoda, mesma razao
    # das duas colunas de array acima: quem le testa pertinencia, nao conta.
    #
    # `NULL` = nao forcada, mas nao e o unico estado que o CHECK admite
    # junto de carimbo nulo: com o carimbo NULL, o CHECK nem chega a olhar
    # para esta coluna, entao qualquer valor passaria aqui. Array vazio com
    # carimbo nao nulo e que fica inalcancavel, proibido pelo mesmo CHECK.
    # Quem le trata NULL e vazio iguais (`or ()`).
    temperatura_forcada_motivos: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(16)), nullable=True
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LeadScoreAudit(Base):
    """Um registro por recalculo que mudou o score. Append-only e imutavel.

    TEC-152, RN-06.4. Mesmo molde de `optout_events`: uma linha por evento,
    carimbo pelo relogio do servidor, e sem FK para `messages` nem para
    `lead_qualification` -- a retencao da trilha (12 meses, RNF-18) nao pode
    ser encurtada por cascata da limpeza de outra tabela.

    **So os fatores do score NOVO sao gravados.** Como o registro so entra
    quando o resultado muda, o registro anterior da mesma conversa **e** o
    score anterior; guardar os dois criaria duas fontes para o mesmo fato, que
    e o defeito que a TEC-146 gastou uma card inteira consertando.
    `total_anterior` fica mesmo assim porque e o que a card nomeia e poupa a
    segunda leitura de quem so quer o delta.
    """

    __tablename__ = "lead_score_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    # O par que identifica o lead, o mesmo de `lead_qualification`.
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # Nulo no primeiro registro do lead, e nao zero. O `score.py` ja faz essa
    # distincao: "o zero e a ausencia de sujeito, nao uma nota sobre ele". Um
    # lead cujo primeiro calculo deu 51 nunca teve score 0, e dizer que teve
    # inventaria uma subida de 51 pontos que nao aconteceu.
    total_anterior: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_novo: Mapped[int] = mapped_column(Integer, nullable=False)

    completude: Mapped[int] = mapped_column(Integer, nullable=False)
    urgencia: Mapped[int] = mapped_column(Integer, nullable=False)
    catalogo: Mapped[int] = mapped_column(Integer, nullable=False)
    engajamento: Mapped[int] = mapped_column(Integer, nullable=False)
    capacidade: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nunca NULL e nunca vazio: tupla vazia e o sinal de nao gravar, entao uma
    # linha sem causa nao deveria ter chegado ao INSERT. O vocabulario mora em
    # `context/auditoria.py`.
    causas: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)

    # So na edicao manual pelo dashboard (TEC-192), que ainda nao existe --
    # hoje e sempre nulo. Mesma forma de `optout_events.autor`, nulo no
    # opt-out pela mesma razao: o ato e do lead, nao de um humano nosso.
    autor: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # `server_default` e nao valor vindo do cliente, pela razao do
    # `optout_events`: `registrar_recalculo` le `ORDER BY created_at DESC LIMIT
    # 1` sem desempate, e com o relogio de cada worker escrevendo a coluna um
    # skew entre duas maquinas inverteria dois registros do mesmo lead.
    #
    # E `clock_timestamp()` e nao `now()`: `now()` e
    # `transaction_timestamp()`, congelado no PRIMEIRO statement da transacao,
    # e este INSERT acontece no fim de um turno longo -- varios statements
    # depois dele. Dois turnos concorrentes da mesma conversa seriam entao
    # ordenados por quando COMECARAM, e nao por quando gravaram, invertendo a
    # trilha em relacao a ordem que o `SELECT ... FOR UPDATE` de
    # `registrar_recalculo` serializa. Como o INSERT ocorre com aquele lock na
    # mao, `clock_timestamp()` produz uma ordem total igual a ordem do lock.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )

    __table_args__ = (
        # A consulta quente e "qual o ultimo registro deste lead?", uma vez por
        # turno. DESC no indice para o LIMIT 1 nao ordenar em memoria. Mesmo
        # formato do `ix_optout_events_lead` e do `ix_messages_timeline`.
        Index(
            "ix_lead_score_audit_lead",
            "channel",
            "conversation_key",
            text("created_at DESC"),
        ),
    )
