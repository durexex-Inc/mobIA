import base64
import json

import pytest
from pydantic import ValidationError

from mobia.app.config import (
    CHAVE_DE_DESENVOLVIMENTO,
    TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO,
    ConfiguracaoInsegura,
    Settings,
    get_settings,
)
from mobia.domain.agente.classificador import _SCHEMA_COMPILADO, SISTEMA_DO_AGENTE
from mobia.domain.agente.ferramenta_de_busca import FERRAMENTA_DE_BUSCA
from mobia.domain.context.montagem import SISTEMA
from mobia.domain.messages.recorder import custo_em_dolar
from mobia.infra.anthropic import get_client

# Rotulos que `montar_prompt` intercala entre resumo, mensagens recentes e
# estado -- hardcoded aqui, acoplado a `montagem.py`, porque copiar o texto
# exato e mais barato que importar o modulo so para reconstrui-lo. O
# acoplamento e pre-existente (nao nasceu deste helper); o helper so o
# concentra num unico ponto em vez de deixa-lo duplicado entre os dois testes
# que o usavam.
_ROTULOS_DE_MONTAR_PROMPT = (
    "Resumo da conversa ate aqui:\nMensagens recentes:\nEstado de qualificacao:\n" + "\n\n" * 2
)


def _linha(rotulo: str, valor: float) -> None:
    """Uma linha do relatorio de `_subcontagem`, alinhada pelo rotulo mais
    longo das parcelas para que os testes possam acrescentar teto e folga
    embaixo da tabela sem desalinha-la.

    A largura e derivada dos proprios nomes, e nao um numero escrito aqui:
    seria estranho a card que tira valores derivados da prosa deixar um para
    tras no proprio relatorio que ela criou.
    """
    largura = max(len(nome) for nome in _decomposicao())
    print(f"  {rotulo:<{largura}}  {valor:>8.1f}")


def _decomposicao() -> dict[str, float]:
    """As cinco parcelas da subcontagem, em tokens do proxy `len/4`.

    Sao cinco porque cinco coisas diferem entre o que `montar_contexto` conta
    e o que a requisicao do classificador de fato manda. Os *nomes* das
    parcelas nao envelhecem -- os *valores* envelhecem a cada mudanca de
    prompt ou de schema, e e por isso que eles vivem aqui, calculados, e nao
    transcritos em prosa (TEC-243).
    """

    def em_tokens(texto: str) -> float:
        return len(texto) / 4

    return {
        # Contado e nao enviado: o classificador usa omitir_sistema=True.
        "-montagem.SISTEMA (contado, nao enviado)": -em_tokens(SISTEMA),
        # Enviados e nunca contados: campo `system=`, o schema de saida e os
        # rotulos que `montar_prompt` intercala.
        "+classificador.SISTEMA_DO_AGENTE (campo system=)": em_tokens(SISTEMA_DO_AGENTE),
        "+schema compilado (output_config.format)": em_tokens(json.dumps(_SCHEMA_COMPILADO)),
        "+rotulos de montar_prompt": em_tokens(_ROTULOS_DE_MONTAR_PROMPT),
        # TEC-265: enviada em toda chamada do classificador e nunca contada por
        # `montar_contexto`, exatamente como o schema de saida.
        "+ferramenta de busca (tools=)": em_tokens(json.dumps(FERRAMENTA_DE_BUSCA)),
    }


def _subcontagem() -> float:
    """A mesma conta que `test_diferenca_entre_o_contado_e_o_enviado` e
    `test_a_margem_do_orcamento_do_prompt_e_deliberada` travam contra tetos
    diferentes. Extraida para um so lugar porque as duas copias verbatim
    divergirem em silencio era exatamente o risco que a duplicacao corria: se
    `montar_prompt` ganhar um quarto rotulo, so um dos dois testes seria
    atualizado, e os dois continuariam verdes medindo coisas diferentes.

    Imprime a decomposicao. O `print` nao e depuracao esquecida: e o entregavel
    da TEC-243. Os valores derivados -- subcontagem, folga, margem -- estavam
    transcritos a mao em quatro textos de prosa e envelheceram quatro vezes em
    dois dias, sempre do mesmo jeito: alguem mexe numa parcela e o valor
    derivado fica velho em tres lugares de uma vez. Agora a prosa explica o
    mecanismo e manda rodar isto:

        python -m pytest -q -k margem_do_orcamento -s

    Sem `-s` o pytest engole a saida quando o teste passa -- e a mostra quando
    ele falha, que e justamente quando alguem precisa dela.
    """
    parcelas = _decomposicao()
    liquido = sum(parcelas.values())

    largura = max(len(nome) for nome in parcelas)
    print("\nSubcontagem do orcamento de contexto (tokens do proxy len/4):")
    for nome, valor in parcelas.items():
        print(f"  {nome:<{largura}}  {valor:>8.1f}")
    print(f"  {'= liquido':<{largura}}  {liquido:>8.1f}")

    return liquido


def test_settings_le_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "segredo-do-teste")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6390/1")
    settings = Settings(_env_file=None)
    assert settings.whatsapp_app_secret == "segredo-do-teste"
    assert settings.redis_url == "redis://localhost:6390/1"


def test_get_settings_e_cacheada() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()


def test_limiares_do_sweeper_tem_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.sweep_received_after_seconds == 30
    assert settings.sweep_inflight_after_seconds == 300
    assert settings.sweep_max_attempts == 5


def test_producao_com_a_chave_de_desenvolvimento_nao_sobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chave de cifra errada nao falha alto como assinatura errada falha.

    Ela grava o dado com uma chave publicamente conhecida e nada reclama. A
    exposicao mais afiada e a migration 0004, que cifraria a tabela inteira num
    job de CI/CD que subiu sem o segredo.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ConfiguracaoInsegura) as erro:
        Settings(_env_file=None)

    assert "CONTENT_ENCRYPTION_KEY" in str(erro.value)
    assert CHAVE_DE_DESENVOLVIMENTO not in str(erro.value)


def test_producao_com_chave_propria_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    chave = base64.b64encode(b"x" * 32).decode()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", chave)
    settings = Settings(_env_file=None)
    assert settings.content_encryption_key == chave


def test_desenvolvimento_segue_com_o_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A guarda nao pode travar a maquina de ninguem nem o CI."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.content_encryption_key == CHAVE_DE_DESENVOLVIMENTO


def test_producao_com_o_token_de_catalogo_de_desenvolvimento_nao_sobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token de catalogo de dev em producao deixa o catalogo gravavel por quem o leu.

    Mesmo molde da guarda da chave de cifra: o valor de desenvolvimento esta
    no `.env.example`, versionado, e por isso conhecido de qualquer um que
    clonou o repo.
    """
    # CONTENT_ENCRYPTION_KEY precisa de um valor proprio aqui -- sem isso a
    # guarda da chave de cifra (que roda antes desta) dispara primeiro, e o
    # teste acabaria verificando a mensagem errada.
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO)
    with pytest.raises(ConfiguracaoInsegura) as erro:
        Settings(_env_file=None)

    assert "CATALOGO_ADMIN_TOKEN" in str(erro.value)
    assert TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO not in str(erro.value)


def test_producao_com_token_de_catalogo_proprio_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "token-de-producao-gerado-com-secrets"
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", token)
    settings = Settings(_env_file=None)
    assert settings.catalogo_admin_token == token


def test_desenvolvimento_segue_com_o_token_de_catalogo_de_desenvolvimento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guarda nao pode travar a maquina de ninguem nem o CI."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("CATALOGO_ADMIN_TOKEN", TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO)
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.catalogo_admin_token == TOKEN_DE_CATALOGO_DE_DESENVOLVIMENTO


def test_s3_sem_bucket_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """`midia_armazem='s3'` sem bucket falharia dentro do job de download, longe
    de onde a configuracao foi escrita -- ver `_recusar_s3_sem_bucket`.
    """
    monkeypatch.setenv("MIDIA_ARMAZEM", "s3")
    with pytest.raises(ValidationError, match="midia_s3_bucket"):
        Settings(_env_file=None)


def test_s3_com_bucket_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIDIA_ARMAZEM", "s3")
    monkeypatch.setenv("MIDIA_S3_BUCKET", "meu-bucket")
    settings = Settings(_env_file=None)
    assert settings.midia_armazem == "s3"
    assert settings.midia_s3_bucket == "meu-bucket"


def test_local_e_o_default_e_nao_exige_bucket() -> None:
    settings = Settings(_env_file=None)
    assert settings.midia_armazem == "local"
    assert settings.midia_diretorio == ".midias"
    assert settings.midia_teto_bytes == 26_214_400


def test_defaults_da_janela_de_contexto(settings) -> None:
    """Os numeros da RN-02.2 e RN-02.5 vivem em configuracao, nao espalhados no codigo.

    `modelo_resumo` esta aqui pelo mesmo motivo que `modelo_agente` esta em
    `test_defaults_do_agente`: travar o default para a troca ser deliberada.
    Ele fez o trabalho -- reprovou quando o resumo passou para `claude-sonnet-5`
    sem esta linha ser atualizada.

    A diferenca entre os dois e o que vem DEPOIS do assert. Trocar o agente tem
    gate pago que mede a consequencia; trocar o resumo nao tem nada. Este
    assert e a unica coisa que torna a troca do resumo visivel, e o que ele
    garante e que ela foi escolhida -- nao que ela foi boa.
    """
    assert settings.modelo_resumo == "claude-sonnet-5"
    assert settings.contexto_teto_de_tokens == 12000
    assert settings.contexto_literais_minimas == 20
    assert settings.contexto_gatilho_de_regeneracao == 40


def test_gatilho_deixa_o_piso_de_literais(settings) -> None:
    """Dobrar `gatilho - minimas` deixa exatamente `minimas` literais.

    Quem garante o piso e `dividir`, nao esta relacao: com `piso_pode_ceder`
    desligado ela nunca dobra abaixo de `minimas`, seja qual for o gatilho. O
    que esta relacao controla e a *frequencia* -- com um gatilho menor que
    `2 * minimas` a dobra sobra pouco a dobrar e a conversa paga uma chamada de
    modelo com muito mais frequencia, cada uma absorvendo pouquissima mensagem.
    Com `gatilho >= 2 * minimas` cada regeneracao dobra pelo menos `minimas`
    mensagens de uma vez, que e o custo por mensagem que o spec orcou.
    """
    assert settings.contexto_gatilho_de_regeneracao >= 2 * settings.contexto_literais_minimas


def test_headroom_desconta_do_teto(settings) -> None:
    """O teto comparado nao e o teto nominal.

    A contagem mede um proxy menor do que a TEC-134 vai de fato enviar: uma
    mensagem plana, sem system e sem o overhead estrutural de cada turno do
    array. A reserva e o que impede o modulo aceitar um contexto que so estoura
    na requisicao real.
    """
    assert settings.contexto_headroom_de_tokens > 0
    assert settings.teto_de_tokens_efetivo == (
        settings.contexto_teto_de_tokens - settings.contexto_headroom_de_tokens
    )
    assert settings.teto_de_tokens_efetivo < settings.contexto_teto_de_tokens


def test_limiar_deriva_do_teto_efetivo(settings) -> None:
    """Mexer no teto ou na reserva move o limiar junto, sem descasar em silencio."""
    assert settings.limiar_de_contagem_efetivo < settings.teto_de_tokens_efetivo


def test_o_headroom_cobre_a_subcontagem_medida() -> None:
    """A reserva tem de cobrir a diferenca MEDIDA, nao a do proxy.

    Ate a TEC-225 dois testes validavam o headroom com `len/4` dos dois lados
    da conta, entao passavam sem dizer nada sobre a reserva. Medido com
    `ContadorAnthropic` em 20/09/2026, parcela a parcela, as cinco parcelas
    somam 1545 tokens reais -- mas isso sobrecontava: cada parcela foi medida
    numa chamada separada de `count_tokens`, e a sobrecarga fixa de 7 tokens
    por chamada nao existe na requisicao real, unica. Descontada ela, as
    parcelas somam 1524. Falta ainda o envelope estrutural do array
    multi-turno (system separado mais varios turnos), medido em 75 tokens
    para uma janela de 40 mensagens -- nao os "100-200" que
    `teto_de_tokens_efetivo` chegou a estimar antes de alguem medir. Total de
    ponta a ponta: 1524 + 75 = 1599 -- contra uma reserva que era 1060.

    O numero abaixo e essa medicao, transcrita aqui porque medi-la no teste
    exigiria chamar a API a cada execucao. Se alguem mexer no prompt do
    agente, no schema ou na ferramenta de busca, ele envelhece -- e o teste
    vizinho de margem do orcamento e quem avisa, porque conta crescimento do
    prompt em unidades do proxy.
    """
    SUBCONTAGEM_REAL_MEDIDA = 1599
    assert get_settings().contexto_headroom_de_tokens >= SUBCONTAGEM_REAL_MEDIDA


def test_cliente_recusa_subir_sem_chave(monkeypatch, caches_de_cliente_limpos: None) -> None:
    """Chave ausente falha aqui, com mensagem util, e nao no meio de um turno."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    with pytest.raises(ConfiguracaoInsegura, match="ANTHROPIC_API_KEY"):
        get_client()


def test_cliente_e_construido_uma_vez(monkeypatch, caches_de_cliente_limpos: None) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")

    assert get_client() is get_client()


def test_defaults_do_agente(settings) -> None:
    """O modelo do agente e configuravel separado do modelo do resumo.

    Sao trabalhos diferentes: a TEC-210 vai querer afinar a acuracia de
    intencao sem mexer na qualidade do resumo, e vice-versa.

    O default e `claude-sonnet-5` desde a troca por custo. Esta asercao existe
    para a troca ser deliberada: mudar o modelo do agente muda o sistema que o
    gate mede, e `config.py` nao esta no filtro de `evals.yml` -- entao sem
    este assert a troca passaria sem nada acusar, nem teste nem CI.
    """
    assert settings.modelo_agente == "claude-sonnet-5"
    assert settings.whatsapp_api_base.startswith("https://")


def test_token_da_meta_nao_tem_default_utilizavel(settings) -> None:
    """Sem default utilizavel: quem sobe sem configurar tem de decidir.

    Ao contrario da ANTHROPIC_API_KEY, a ausencia nao falha alto sozinha --
    vira 401 da Meta, tratado como falha permanente. A guarda que impede isso
    de chegar a producao fica em `mobia.workers.main.startup`, testada em
    `tests/integration/test_worker_startup.py`.
    """
    assert settings.whatsapp_access_token == ""


def test_cliente_falha_tipado_antes_de_o_arq_cancelar(
    monkeypatch, caches_de_cliente_limpos: None
) -> None:
    """O teto por requisicao tem de caber no `job_timeout` do worker.

    O default do SDK (10 min, com retentativa interna) e maior que o job
    inteiro: uma chamada lenta nunca falharia, seria cancelada pelo ARQ. E
    `CancelledError` e BaseException -- o `except Exception` de
    `process_message` nao pega, a linha nao vira FAILED e a reserva de envio
    fica presa. Erro tipado e recuperavel; cancelamento nao e.
    """
    from mobia.infra.anthropic import MAX_TENTATIVAS, TIMEOUT_SEGUNDOS

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    cliente = get_client()

    assert cliente.timeout == TIMEOUT_SEGUNDOS
    assert cliente.max_retries == MAX_TENTATIVAS
    # O par (timeout, retentativas) contra o `job_timeout` do worker esta em
    # `tests/integration/test_worker_startup.py`: importar `workers.main` aqui
    # construiria `Settings` antes do monkeypatch da chave.


def test_diferenca_entre_o_contado_e_o_enviado(settings) -> None:
    """Discharge da re-verificacao que a TEC-127 deixou marcada para a TEC-134.

    A contagem de `montar_contexto` mede um proxy do que a requisicao do
    classificador de fato manda. Este teste refaz a conta com um `len/4`
    proprio do orcamento -- ja nao e mais o mesmo da TEC-225, que trocou a
    formula de `montagem.py` por uma ciente de densidade -- e nao com
    `count_tokens`, que custaria uma chamada paga e rede, que a suite nao
    toca.

    Fica como teste, e nao como numero num comentario, porque cada parcela
    vive num modulo diferente: crescer `SISTEMA_DO_AGENTE` ou acrescentar um
    campo ao schema muda a conta sem tocar em `config.py`, e sem isto ninguem
    ficaria sabendo ate a primeira chamada estourar o limite de verdade.

    Desde a TEC-225 este teste e o irmao
    `test_a_margem_do_orcamento_do_prompt_e_deliberada` nao validam mais a
    reserva -- os dois medem no proxy `len/4`, o mesmo que a TEC-225 derrubou
    do lado da montagem, entao a regua era igual dos dois lados da conta. O
    que valida a reserva agora e `test_o_headroom_cobre_a_subcontagem_medida`,
    medido contra o contador real. Estes dois continuam de pe como alarme
    contra **crescimento do prompt**, em unidades do proxy proprio do
    orcamento.
    """
    subcontagem = _subcontagem()
    teto = settings.contexto_headroom_de_tokens * 0.75
    _linha("teto desta assercao (headroom * 0,75)", teto)
    _linha("folga", teto - subcontagem)

    assert subcontagem > 0, "se virar negativo, a conta abaixo perdeu o sentido"
    assert subcontagem < settings.contexto_headroom_de_tokens, (
        "a reserva parou de cobrir o que a contagem nao ve -- suba "
        "CONTEXTO_HEADROOM_DE_TOKENS ou encolha o que e enviado sem ser contado"
    )
    # Folga, nao empate: o overhead estrutural da requisicao (envelope do
    # turno de usuario) tambem sai daqui, e ele nao esta na conta acima.
    assert subcontagem < teto


def test_a_margem_do_orcamento_do_prompt_e_deliberada(settings) -> None:
    """A margem existe para ser vista antes de ser gasta, nao depois.

    O teto de 793 e mais apertado que o `headroom * 0,75` usado pelo teste
    irmao, e e o proposito deste teste: se voce esta lendo isto porque ele
    reprovou, a pergunta e "o que sai do prompt para o novo texto entrar?",
    nao "quanto subo o numero?". Subir e resposta legitima -- mas so depois da
    primeira pergunta, e com o preco por turno escrito no comentario de
    `contexto_headroom_de_tokens`.

    O 793 e o unico numero desta conta escrito a mao em qualquer lugar, e e
    escrito aqui de proposito: um limite so trava se estiver fixo. Todo o
    resto -- subcontagem, folga, margem -- e derivado e sai impresso por
    `_subcontagem`, para ninguem precisar transcrever (TEC-243):

        python -m pytest -q -k margem_do_orcamento -s

    Historico das duas vezes em que este numero se mexeu: a TEC-240 gastou 61
    dos 74 tokens de folga que a TEC-145 tinha deixado e parou com 13 de
    proposito; a TEC-250 gastou esses 13 e mais 35,8, e subiu a reserva de 800
    para 850 depois de procurar o que cortar e nao achar. Sao numeros daquelas
    cards, nao os de hoje -- os de hoje estao na saida acima.

    A TEC-257 gastou os 4,2 que restavam e mais ~15, subindo o teto para 655
    e a reserva para 880: o campo `perguntou` do schema custou ~18,5 e a
    clausula da memoria em `SISTEMA_DO_AGENTE` custou ~0,75, ~19,25 no total.
    A clausula foi encurtada, nao acrescentada -- "nao repergunte o que ja
    esta preenchido" virou "nao repergunte o preenchido nem o ignorado" -- e
    foi o corte na forma existente que pagou quase toda a clausula nova,
    +0,75 em vez dos +6,25 que so acrescentar teria custado.

    A TEC-148 gastou 17,6 dos 23,8 que a TEC-257 havia deixado, e o teto NAO
    se mexeu: o liquido foi de 631,2 para 648,8 e a margem ficou em 6,2.
    Todo o custo foi o campo `recusou` no schema -- o prompt nao ganhou
    texto, porque a clausula "nao repergunte o preenchido nem o ignorado" da
    TEC-257 ja cobre recusa, e o campo recusado ja vem marcado
    "(perguntado, sem resposta)" do turno em que foi perguntado.

    A TEC-265 gastou os 6,2 que restavam: a definicao da ferramenta de busca
    em `tools=` custou 131,2, levando o liquido a exatamente 780,0. A
    alternativa mais barata foi recusada por defeito e nao por preco -- um
    schema com so `consulta_texto` (73,8) buscaria com o estado do turno
    anterior, porque a extracao do turno atual so volta no JSON final. Dentro
    da propria ferramenta houve corte: `tipo` como string livre em vez de
    `enum` economizou ~40, e `operacao` ficou `enum` (+7,5) porque e a unica
    dimensao que nao pode ser descartada -- ver a D5 e a D11 do desenho.

    O teto subiu para 786, nao para 780: com o liquido medido em exatamente
    780,0, um teto igual a ele zerava a margem e reprovava esta assercao, que
    e estrita (`<`, nao `<=`). 786 deixa 6,0 de margem, do mesmo tamanho da
    que a TEC-148 tinha deixado. A reserva precisou subir mais do que o
    aumento do teto: 1005 (780 + 125, o primeiro numero cogitado) faz
    `headroom * 0,75` cair para 753,75, abaixo do proprio liquido de 780,0 --
    o fator 0,75 do teste irmao exige folga adicional que o aumento do teto
    sozinho nao cobre. 1060 deixa `headroom * 0,75` em 795,0, 9,0 acima do
    teto fixo de 786. Preco: 180 tokens a menos de literais e resumo por
    turno, de 12000 -- 1,5% do contexto, a segunda maior subida da historia
    do projeto, atras dos 3,3% da primeira.

    O calculo de custo desta card errou duas vezes antes de bater com o
    numero real, e as duas ficam registradas para ninguem repetir a conta
    por fora do teste. A entrada nova em `properties`
    (`{"recusou": {"type": "array", "items": {"type": "string"}}}`) sozinha
    e 14,75 tokens -- mas `_ORDEM_DOS_CAMPOS` tambem alimenta
    `SCHEMA_DA_RESPOSTA["required"]` (a guarda de import em
    `classificador.py` exige que as duas listas tenham as mesmas chaves), e
    `required` cresceu junto com `properties`. Simular so a entrada de
    `properties` e esquecer que `required` cresce e o primeiro erro. Medir
    essa simulacao com `json.dumps(separators=(",", ":"))`, e nao com os
    separadores default que o teste usa, e o segundo -- subestima de novo,
    13,25 em vez de 14,75 so na entrada de `properties`. Os dois juntos
    ficam 4,35 tokens abaixo do real. Por isso o numero que conta e sempre
    o impresso por

        python -m pytest -q -k margem_do_orcamento -s

    nunca uma simulacao do schema por fora dele.

    A TEC-141 gastou 9,25 e devolveu 2,50, subindo o teto para 793: a
    clausula `Nao negocie valor: e com o corretor.` custou 9,25, e saiu o
    `, de 0 a 1` da confianca -- o schema compilado carrega essa faixa
    dentro de `description`, nao em `minimum`/`maximum` soltos
    (`transform_schema` dobra as duas chaves para la, porque o compilador
    de schema do lado do servidor nao as suporta para `number`), entao
    dizer a faixa tambem em prosa repetia o que a description ja carregava.

    O teto fixo passou de 9,0 abaixo do teto derivado (795,0) para 2,0
    abaixo dele: qualquer alta acima de +2 no fixo exigiria subir
    `contexto_headroom_de_tokens` junto -- margem apertada que ficou para a
    TEC-225 herdar, e que a TEC-225 de fato gastou ao medir a reserva contra
    o contador real. Hoje o derivado e `1700 * 0,75 = 1275` (a reserva subiu
    para 1700 -- ver o comentario de `contexto_headroom_de_tokens`), 482
    acima do fixo: a margem apertada nao existe mais. O acoplamento que o
    CLAUDE.md descreve continua de pe -- o fixo segue sendo o mais apertado
    dos dois --, so que a distancia entre eles parou de ser o risco imediato
    que era.

    O teto fixo NAO foi para 800. As duas redacoes mais longas cabem, em
    tokens brutos, no teto derivado de 795,0: `nem desconto` fica em 790,00
    (5,0 de folga) e `nem prometa desconto` em 793,25 (1,75 de folga) --
    nenhuma das duas fura o teto derivado por aritmetica. O que elas nao
    deixam e a margem de ~6 tokens que esta card mantem por convencao (a
    curta fica em 786,75 liquido contra 793, folga de 6,25). O argumento
    real para a clausula curta e semantico, nao aritmetico: pedir desconto
    ja e negociar valor (desenho, D2), entao a forma curta cobre o mesmo
    cenario do Gherkin sem apertar a margem. A palavra `desconto` ficou com
    o moderador de saida, onde nao custa orcamento.
    """
    subcontagem = _subcontagem()
    _linha("teto desta assercao (fixo)", 793)
    _linha("margem", 793 - subcontagem)

    assert subcontagem < 793, (
        f"subcontagem {subcontagem}: a margem sobre o teto de 793 foi "
        f"consumida. Encolha o texto enviado, ou suba a reserva registrando "
        f"o preco por turno."
    )


def test_todo_modelo_configurado_tem_preco_cadastrado(settings) -> None:
    """A guarda que teria pego o buraco da moderacao no dia em que ele entrou.

    `modelo_moderacao` e um ID datado (`claude-haiku-4-5-20251001`) e a tabela
    so tinha a chave sem data, entao `custo_em_dolar` devolvia None para ele.
    Ficou latente porque a moderacao nao tinha telemetria nenhuma -- ninguem
    consultava o preco --, e teria virado custo nulo em producao no dia em que
    alguem instrumentasse. Foi o que a TEC-249 fez.

    Este teste amarra as duas pontas: toda `modelo_*` de `Settings` tem de ter
    preco, e o proximo modelo configurado sem entrada reprova aqui em vez de
    somar zero num painel.
    """
    configurados = {
        nome: getattr(settings, nome)
        for nome in type(settings).model_fields
        if nome.startswith("modelo_")
    }
    assert configurados, "nenhuma `modelo_*` encontrada: o teste perdeu o alvo"
    sem_preco = {
        nome: valor
        for nome, valor in configurados.items()
        if custo_em_dolar(valor, 1000, 100) is None
    }
    assert not sem_preco, f"modelos configurados sem preco em PRECOS_POR_MODELO: {sem_preco}"


def test_o_horario_de_envio_invertido_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Horario invertido desligaria a cadencia sem nenhum sintoma.

    A varredura devolveria 0 para sempre, e a ausencia de `followup.devido` e
    indistinguivel de "nenhum lead devido" -- exatamente a falha silenciosa que
    este repo trata como pior que a alta.
    """
    monkeypatch.setenv("FOLLOWUP_HORARIO_INICIO", "20")
    monkeypatch.setenv("FOLLOWUP_HORARIO_FIM", "9")

    with pytest.raises(ValidationError, match="followup_horario"):
        Settings(_env_file=None)


def test_o_horario_de_envio_vazio_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """9-9 nao e um horario de um instante: e a cadencia desligada."""
    monkeypatch.setenv("FOLLOWUP_HORARIO_INICIO", "9")
    monkeypatch.setenv("FOLLOWUP_HORARIO_FIM", "9")

    with pytest.raises(ValidationError, match="followup_horario"):
        Settings(_env_file=None)


def test_o_horario_de_envio_alem_das_23_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ceiling `fim <= 23`: 24 pareceria "meia-noite" para quem le o
    validator de fora, mas a comparacao interna e contra `fim * 60` em
    minuto do dia, e 24 estouraria o dia sem recusar nada dentro dele."""
    monkeypatch.setenv("FOLLOWUP_HORARIO_FIM", "24")

    with pytest.raises(ValidationError, match="followup_horario"):
        Settings(_env_file=None)


def test_o_horario_de_envio_com_inicio_negativo_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOLLOWUP_HORARIO_INICIO", "-1")

    with pytest.raises(ValidationError, match="followup_horario"):
        Settings(_env_file=None)


def test_o_horario_de_envio_no_limite_das_bordas_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """`inicio=0, fim=23` e o extremo permitido dos dois lados ao mesmo
    tempo, e o validator tem de aceitar em vez de recusar por engano."""
    monkeypatch.setenv("FOLLOWUP_HORARIO_INICIO", "0")
    monkeypatch.setenv("FOLLOWUP_HORARIO_FIM", "23")

    settings = Settings(_env_file=None)

    assert settings.followup_horario_inicio == 0
    assert settings.followup_horario_fim == 23


def test_a_janela_de_atendimento_invertida_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Par de `test_o_horario_de_envio_invertido_nao_sobe`, mas para a janela de atendimento.

    Invertida, `dentro_da_janela_de_atendimento` nunca reconheceria nenhum
    minuto do dia como dentro -- todo lead que pedir humano receberia o
    texto de fora do horario, sempre, sem nenhum sintoma alem desse.
    """
    monkeypatch.setenv("ATENDIMENTO_HORARIO_INICIO", "18")
    monkeypatch.setenv("ATENDIMENTO_HORARIO_FIM", "9")

    with pytest.raises(ValidationError, match="atendimento_horario"):
        Settings(_env_file=None)


def test_a_janela_de_atendimento_no_limite_das_bordas_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """`inicio=0, fim=23` e o extremo permitido dos dois lados ao mesmo tempo."""
    monkeypatch.setenv("ATENDIMENTO_HORARIO_INICIO", "0")
    monkeypatch.setenv("ATENDIMENTO_HORARIO_FIM", "23")

    settings = Settings(_env_file=None)

    assert settings.atendimento_horario_inicio == 0
    assert settings.atendimento_horario_fim == 23


def test_o_fuso_de_envio_invalido_nao_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem esta guarda, o typo explodiria dentro da varredura a cada 5 minutos
    em vez de na subida do worker."""
    monkeypatch.setenv("FOLLOWUP_FUSO", "America/Sao_Paolo")

    with pytest.raises(ValidationError, match="followup_fuso"):
        Settings(_env_file=None)


def test_o_fuso_de_envio_default_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A guarda do tzdata: sem a dependencia isto levanta no Windows, onde o
    `zoneinfo` nao tem base de fusos do sistema. Passaria no Linux do CI e
    falharia na maquina de quem desenvolve."""
    monkeypatch.delenv("FOLLOWUP_HORARIO_INICIO", raising=False)
    monkeypatch.delenv("FOLLOWUP_HORARIO_FIM", raising=False)
    monkeypatch.delenv("FOLLOWUP_FUSO", raising=False)

    settings = Settings(_env_file=None)

    assert settings.fuso_de_envio.key == "America/Sao_Paulo"
    assert settings.followup_horario_inicio == 9
    assert settings.followup_horario_fim == 20


def test_os_limites_da_rnf_16_sao_os_defaults() -> None:
    settings = Settings()
    assert settings.rate_limit_mensagens_por_minuto == 20
    assert settings.rate_limit_requisicoes_por_ip_por_minuto == 100


def test_o_backoff_tem_default_e_e_float() -> None:
    settings = Settings()
    assert settings.atraso_de_backoff_segundos == 30.0


def test_confiar_em_forwarded_for_vem_desligado() -> None:
    """O default e o inseguro-contra-proxy, nao o inseguro-contra-spoof.

    Atras de proxy sem a chave ligada o limite fica mais apertado do que se
    quer e alguem reclama; com a confianca ligada por omissao e sem proxy o
    limite simplesmente nao existe e ninguem reclama. Falha que se anuncia e
    melhor que falha silenciosa. Ver D7 do desenho.
    """
    assert Settings().confiar_em_forwarded_for is False


def test_limite_negativo_e_recusado() -> None:
    with pytest.raises(ValidationError):
        Settings(rate_limit_mensagens_por_minuto=-1)
    with pytest.raises(ValidationError):
        Settings(rate_limit_requisicoes_por_ip_por_minuto=-1)


def test_backoff_negativo_e_recusado() -> None:
    """`_defer_by` negativo agendaria para o passado, e o excedente seria
    processado ANTES da mensagem que respeitou o limite.
    """
    with pytest.raises(ValidationError):
        Settings(atraso_de_backoff_segundos=-1.0)


def test_backoff_maior_que_a_janela_do_sweeper_e_recusado() -> None:
    """O caso absurdo que nao precisa de `job_timeout` para ser pego: os dois
    campos vivem no mesmo `Settings`, entao a guarda nao fecha ciclo de
    import nenhum -- so nao fecha a conta inteira (essa continua so no
    teste do worker).
    """
    with pytest.raises(ValidationError, match="atraso_de_backoff_segundos"):
        Settings(atraso_de_backoff_segundos=300.0, sweep_inflight_after_seconds=300)


def test_backoff_igual_a_janela_do_sweeper_e_recusado() -> None:
    """`>=`, nao `>`: igualdade ainda deixa o sweeper reenfileirar no mesmo
    instante em que o backoff terminaria, sem folga nenhuma.
    """
    with pytest.raises(ValidationError, match="atraso_de_backoff_segundos"):
        Settings(atraso_de_backoff_segundos=90.0, sweep_inflight_after_seconds=90)


def test_templates_aprovados_default_e_vazio() -> None:
    """RN-13.6 (TEC-186): sem operar a config, nada esta aprovado -- e a
    mitigacao do RT-03, todo follow-up fora da janela vira tarefa."""
    assert Settings(_env_file=None).templates_aprovados == frozenset()


def test_templates_aprovados_parseia_lista_por_virgula_sem_vazios() -> None:
    s = Settings(
        _env_file=None,
        whatsapp_templates_aprovados=" followup_queda_de_preco , followup_convite ,",
    )
    assert s.templates_aprovados == frozenset({"followup_queda_de_preco", "followup_convite"})
