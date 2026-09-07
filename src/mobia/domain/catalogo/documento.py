"""O documento textual que vira embedding, e sua impressao digital.

TEC-157, RN-08.2. Funcao pura: sem banco, sem rede, sem `Settings`.

**A definicao do documento mora AQUI e em nenhum outro lugar.** A alternativa
era calcular o hash em SQL -- `md5(titulo || descricao || ...)` -- para que a
varredura resolvesse tudo numa consulta. Foi recusada: a lista de campos
passaria a existir em dois lugares, e o dia em que divergissem o sintoma
seria embedding silenciosamente velho, sem erro nenhum. A varredura paga um
pre-filtro barato em SQL e a comparacao exata aqui.

**Por que estes seis campos, e por que quatro textuais ficam fora.** A secao
4.4 do SRS manda embedar descricao, bairro, tipologia e diferenciais, e
manter os numericos fora, "evitando o erro classico de pedir ao vetor que
entenda 'ate 600 mil'". `operacao`, `status`, `zona` e `uf` saem pelo mesmo
principio: sao dimensoes de filtro por igualdade, resolvidas no WHERE da
RN-09.1. `titulo` e `cidade` entram alem dos quatro do SRS -- o titulo por
ser texto livre descritivo, a cidade porque bairro homonimo em cidades
diferentes colide. Ver a Emenda E-01 a RN-08.2.
"""

import hashlib

from mobia.domain.catalogo.models import Imovel


def documento_de(imovel: Imovel) -> str:
    """O texto normalizado de um imovel, um documento por imovel.

    Nao fragmenta em chunks: o registro ja e curto e coeso, e fragmentar
    destruiria a associacao entre caracteristica e imovel (secao 4.4).
    """
    partes = [
        imovel.titulo,
        imovel.descricao,
        imovel.tipo,
        imovel.bairro,
        imovel.cidade,
        *imovel.caracteristicas,
    ]
    return "\n".join(parte.strip() for parte in partes if parte and parte.strip())


def hash_do_documento(texto: str) -> str:
    """Impressao digital do documento, para detectar mudanca.

    Nao e escolha criptografica: e deteccao de mudanca. `sha256` custa o
    mesmo que `md5` nesta escala e nao deixa ninguem ler a escolha como
    decisao de seguranca que ela nao e.
    """
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
