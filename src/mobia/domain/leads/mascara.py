"""Como telefone e e-mail do lead aparecem para quem nao os revelou. TEC-195.

Modulo sem I/O, no molde de `leads/consulta.py` e `metricas/vocabulario.py`:
e o que deixa a forma da mascara ser testada em `tests/unit/` sem Postgres de
pe.

**A mascara e o que TODO chamador recebe, e nao o que alguns recebem** (D4 do
desenho). A resposta da lista nunca contem dado pessoal, para papel nenhum --
o unico lugar do sistema que devolve o valor cheio e
`POST /leads/{leadId}/revelar`, que registra na trilha antes de responder.

**A regra so erra para o lado de esconder.** Entrada que nao cabe na forma
canonica sai `None`, e entrada curta demais para a regra de e-mail e mascarada
quase por inteiro -- nunca ha caminho em que a mascara revele MAIS do que a
regra descreve.
"""

from mobia.domain.identidade.telefone import normalizar

# O caractere da mascara. Um so, e nao um por digito escondido: a TEC-330
# escreve `+55 48 9****-**21` por extenso, e esse e o contrato com a tela.
_OCULTO = "*"


def mascarar_telefone(bruto: str) -> str | None:
    """`5511999990021` vira `+55 11 9****-**21`. Nao-telefone vira `None`.

    **Pais e DDD ficam**: nao identificam ninguem e sao o que da a tela alguma
    utilidade. Do numero do assinante sobram o primeiro digito -- que e sempre
    9 em celular, e portanto nao diz nada -- e os dois ultimos.

    **`None` e "isto nao e telefone", e nao "este lead nao tem telefone".**
    Quem chama passa o telefone ja revelado por `identidade/indice.py::telefones_de`
    -- nunca a `conversation_key`, que desde a TEC-203 e um HMAC. Lead sem
    telefone conhecido (sessao web sem vinculo) nem chega aqui: `telefones_de`
    devolve `None` para ele e quem chama nao mascara nada.
    """
    canonico = normalizar(bruto)
    if canonico is None:
        return None

    ddd, assinante = canonico[2:4], canonico[4:]
    # `assinante` tem 8 ou 9 digitos -- `normalizar` garante. Os visiveis sao o
    # primeiro e os dois ultimos; o resto vira `_OCULTO`, com o hifen na
    # posicao em que a tela o espera.
    escondidos = len(assinante) - 3
    antes = _OCULTO * (escondidos - 2)
    return f"+55 {ddd} {assinante[0]}{antes}-{_OCULTO * 2}{assinante[-2:]}"


def mascarar_email(bruto: str) -> str | None:
    """`marina@exemplo.com` vira `m****a@e*****o.com`. Sem `@` vira `None`.

    **Esta funcao NAO TEM CHAMADOR, e isso e deliberado** (D7 do desenho):
    nenhuma tabela deste sistema guarda e-mail de lead -- `corretores.email` e
    `usuarios.email` sao de gente da operacao. A card pede telefone E e-mail, e
    a metade que nao tem fonte entra como regra escrita e verificada em vez de
    entrar como nada.

    E o mesmo estado em que `agendamento/ciclo.py::marcar_realizado` esperou a
    TEC-374: quando a coluna nascer, o mascaramento ja esta decidido e testado,
    em vez de ser improvisado por quem estiver criando a coluna.

    Primeiro e ultimo caractere do local, primeiro e ultimo do dominio antes do
    TLD, TLD inteiro. O que e curto demais para isso e mascarado por inteiro
    menos o ultimo caractere -- ver `_miolo`.
    """
    local, arroba, dominio = bruto.partition("@")
    if not arroba or not local or not dominio:
        return None

    nome, ponto, tld = dominio.rpartition(".")
    if not ponto:
        # Dominio sem ponto nao tem TLD a preservar; mascara o dominio inteiro
        # pela mesma regra do local.
        return f"{_miolo(local)}@{_miolo(dominio)}"
    return f"{_miolo(local)}@{_miolo(nome)}.{tld}"


def _miolo(parte: str) -> str:
    """Primeiro e ultimo caractere visiveis, o resto oculto.

    **Com menos de tres caracteres nao ha miolo a esconder**, e mostrar o
    primeiro E o ultimo mostraria a parte inteira. Nesses casos sobra so o
    ultimo, precedido de um `_OCULTO` -- o degrau e sempre para o lado de
    esconder, nunca para o de revelar.
    """
    if len(parte) < 3:
        return f"{_OCULTO}{parte[-1:]}"
    return f"{parte[0]}{_OCULTO * (len(parte) - 2)}{parte[-1]}"
