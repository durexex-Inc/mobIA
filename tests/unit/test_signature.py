from mobia.infra.signature import SIGNATURE_HEADER, compute_signature, is_valid_signature

SECRET = "segredo-do-app"
BODY = b'{"object":"whatsapp_business_account"}'


def test_nome_do_header() -> None:
    assert SIGNATURE_HEADER == "X-Hub-Signature-256"


def test_assinatura_tem_prefixo_sha256() -> None:
    assinatura = compute_signature(SECRET, BODY)
    assert assinatura.startswith("sha256=")
    assert len(assinatura) == len("sha256=") + 64


def test_assinatura_valida_e_aceita() -> None:
    assert is_valid_signature(SECRET, BODY, compute_signature(SECRET, BODY)) is True


def test_assinatura_forjada_e_recusada() -> None:
    assert is_valid_signature(SECRET, BODY, "sha256=" + "0" * 64) is False


def test_assinatura_ausente_e_recusada() -> None:
    assert is_valid_signature(SECRET, BODY, None) is False
    assert is_valid_signature(SECRET, BODY, "") is False


def test_assinatura_sem_prefixo_e_recusada() -> None:
    sem_prefixo = compute_signature(SECRET, BODY).removeprefix("sha256=")
    assert is_valid_signature(SECRET, BODY, sem_prefixo) is False


def test_corpo_alterado_invalida_a_assinatura() -> None:
    assinatura = compute_signature(SECRET, BODY)
    assert is_valid_signature(SECRET, BODY + b" ", assinatura) is False


def test_segredo_errado_invalida_a_assinatura() -> None:
    assinatura = compute_signature("outro-segredo", BODY)
    assert is_valid_signature(SECRET, BODY, assinatura) is False
