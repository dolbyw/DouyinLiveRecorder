from pathlib import Path


def test_source_has_no_global_tls_verification_disablement():
    source_root = Path("src")
    python_sources = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))

    assert "ssl.CERT_NONE" not in python_sources
    assert "check_hostname = False" not in python_sources


def test_http_client_public_defaults_do_not_disable_verification():
    client_root = Path("src/http_clients")
    client_sources = "\n".join(path.read_text(encoding="utf-8") for path in client_root.rglob("*.py"))

    assert "verify: bool = False" not in client_sources
