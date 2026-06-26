import httpx
import pytest
import requests

from src.http_clients.errors import (
    HttpConnectError,
    HttpProxyError,
    HttpRequestConfigError,
    HttpTimeoutError,
    wrap_httpx_error,
    wrap_requests_error,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (httpx.ConnectError("refused"), HttpConnectError),
        (httpx.ProxyError("bad proxy"), HttpProxyError),
        (httpx.ReadTimeout("slow"), HttpTimeoutError),
        (httpx.InvalidURL("bad url"), HttpRequestConfigError),
    ],
)
def test_httpx_errors_are_classified_and_keep_cause(source, expected):
    error = wrap_httpx_error("GET", "https://example.test", source)

    assert isinstance(error, expected)
    assert error.cause is source
    assert error.category in str(error)
    assert "example.test" in str(error)
    assert str(source) in str(error)


def test_error_text_does_not_contain_headers_that_were_never_part_of_context():
    source = httpx.ConnectError("refused")

    error = wrap_httpx_error("GET", "https://example.test", source)

    assert "Authorization" not in str(error)
    assert "Cookie" not in str(error)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (requests.exceptions.ConnectionError("refused"), HttpConnectError),
        (requests.exceptions.ProxyError("bad proxy"), HttpProxyError),
        (requests.exceptions.Timeout("slow"), HttpTimeoutError),
        (requests.exceptions.InvalidURL("bad url"), HttpRequestConfigError),
    ],
)
def test_requests_errors_are_classified_and_keep_cause(source, expected):
    error = wrap_requests_error("GET", "https://example.test", source)

    assert isinstance(error, expected)
    assert error.cause is source
    assert str(source) in str(error)
