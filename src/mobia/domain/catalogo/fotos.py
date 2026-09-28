"""Validacao de foto de imovel por assinatura de bytes. TEC-335, D3.

Confiar no `Content-Type` que o navegador manda no upload, ou na extensao do
nome do arquivo, aceitaria um GIF renomeado para `.jpg` ou um HTML disfarcado
de imagem -- e como a rota de leitura (D2) serve esse mesmo arquivo de volta
com o `Content-Type` que esta validacao decidiu, um arquivo mal identificado
na entrada sairia mal identificado na saida, na cara do navegador de um admin.

Os quatro primeiros bytes (ou mais, para WebP) sao conferidos contra a
assinatura real de cada formato -- sem trazer uma dependencia nova (Pillow,
python-magic): as tres assinaturas sao curtas e a checagem e codigo puro, no
espirito de `parser.py` (que ja valida a mao em vez de trazer uma lib de CSV).
"""

FOTO_TETO_DE_BYTES = 5 * 1024 * 1024
FOTO_LIMITE_POR_IMOVEL = 15

# fotos-de-imoveis/, e nao o prefixo que a midia de WhatsApp usa: as duas
# nunca colidem no mesmo diretorio/bucket (D1).
PREFIXO_DO_ARMAZEM = "fotos-de-imoveis"

_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_RIFF = b"RIFF"
_WEBP = b"WEBP"

# formato -> (mime, extensao). A extensao entra na chave do armazem; o mime e
# o Content-Type da resposta de leitura (D2) -- nunca o que o cliente declarou.
_MIME_E_EXTENSAO: dict[str, tuple[str, str]] = {
    "jpeg": ("image/jpeg", "jpg"),
    "png": ("image/png", "png"),
    "webp": ("image/webp", "webp"),
}


def detectar_formato(dados: bytes) -> str | None:
    """`"jpeg"`/`"png"`/`"webp"`, ou `None` se nenhuma assinatura bater.

    WebP nao e assinatura contigua: `RIFF` nos 4 primeiros bytes, um campo de
    tamanho de 4 bytes, e so entao `WEBP` nos bytes 8-11.
    """
    if dados.startswith(_JPEG):
        return "jpeg"
    if dados.startswith(_PNG):
        return "png"
    if dados[:4] == _RIFF and dados[8:12] == _WEBP:
        return "webp"
    return None


def mime_e_extensao_de(formato: str) -> tuple[str, str]:
    return _MIME_E_EXTENSAO[formato]


def mime_da_extensao(extensao: str) -> str | None:
    """O caminho inverso de `mime_e_extensao_de`, para a rota de leitura (D2):
    o formato nao e guardado a parte, entao o Content-Type de servir de volta
    vem da extensao que a chave do armazem carrega."""
    for mime, ext in _MIME_E_EXTENSAO.values():
        if ext == extensao:
            return mime
    return None


def chave_do_armazem(imovel_id: str, foto_id: str, extensao: str) -> str:
    return f"{PREFIXO_DO_ARMAZEM}/{imovel_id}/{foto_id}.{extensao}"
