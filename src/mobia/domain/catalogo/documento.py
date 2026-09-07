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


def hash_do_documento(texto: str, modelo: str, dimensoes: int) -> str:
    """Impressao digital do documento E do provedor que o vetorizou.

    Nao e escolha criptografica: e deteccao de mudanca. `sha256` custa o
    mesmo que `md5` nesta escala e nao deixa ninguem ler a escolha como
    decisao de seguranca que ela nao e.

    **A identidade do provedor entra no HASH, e nao no documento.** O texto
    que vai para a API continua sendo `documento_de(imovel)` e nada mais --
    prefixar o nome do modelo no que se embeda mudaria o vetor de todo imovel
    por um motivo que nao e semantico. Quem ganha o prefixo e o material
    hasheado, porque ele responde outra pergunta: "o vetor guardado ainda
    vale?".

    Sem isso, trocar `text-embedding-3-small` por `text-embedding-3-large` na
    MESMA dimensao (`dimensions=1536` e uma opcao do provedor) nao mudaria
    hash nenhum: nenhuma linha viraria candidata, e o catalogo passaria a
    guardar vetores de dois espacos incompativeis. Cosseno entre eles e
    ruido, sem erro e sem caminho de reindexacao -- a mesma classe de falha
    que a D3 recusou o hash em SQL para evitar, alcancada pela configuracao
    do provedor em vez da lista de campos. Com o prefixo, a troca faz todo
    hash diferir e a varredura reindexa o catalogo sozinha.

    A dimensao entra junto por completude. Sozinha ela ja falha alto -- a
    coluna `vector(1536)` recusa vetor de outro tamanho --, mas deixa-la fora
    faria o hash descrever pela metade o que produziu o vetor.

    A composicao mora AQUI, e nao na varredura, pelo mesmo motivo que a
    definicao do documento mora aqui: quem grava `documento_hash` e quem o
    compara tem de derivar o valor da mesma funcao, e duas expressoes
    equivalentes em arquivos diferentes divergem no dia em que uma delas
    muda. A funcao segue pura: recebe modelo e dimensao, nao le `Settings`.
    """
    material = f"{modelo}\n{dimensoes}\n{texto}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
