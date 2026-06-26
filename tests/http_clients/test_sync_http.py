from unittest.mock import Mock, patch

import requests
import pytest

from src.http_clients.client_pool import ClientPurpose
from src.http_clients.errors import HttpConnectError
from src.http_clients.sync_http import sync_fetch_response, sync_req


def test_sync_get_uses_verified_pooled_session_without_proxy():
    response = Mock(text="ok", url="https://example.test/final")
    session = Mock()
    session.get.return_value = response

    with patch("src.http_clients.sync_http.get_sync_session", return_value=session) as factory:
        assert sync_req("https://example.test") == "ok"

    factory.assert_called_once_with(
        purpose=ClientPurpose.DIRECT,
        proxy_addr=None,
        trust_env=False,
    )
    session.get.assert_called_once_with(
        "https://example.test",
        headers={},
        timeout=20,
        verify=True,
    )


def test_sync_request_selects_proxy_and_abroad_purposes():
    response = Mock(text="ok", url="https://example.test")
    session = Mock()
    session.get.return_value = response

    with patch("src.http_clients.sync_http.get_sync_session", return_value=session) as factory:
        sync_req("https://example.test", proxy_addr="127.0.0.1:8080")
        assert factory.call_args.kwargs["purpose"] is ClientPurpose.PROXY
        assert factory.call_args.kwargs["proxy_addr"] == "http://127.0.0.1:8080"

        sync_req("https://example.test", abroad=True)
        assert factory.call_args.kwargs["purpose"] is ClientPurpose.ABROAD


def test_sync_post_preserves_data_and_redirect_shape():
    response = Mock(text="created", url="https://example.test/final")
    session = Mock()
    session.post.return_value = response

    with patch("src.http_clients.sync_http.get_sync_session", return_value=session):
        assert (
            sync_req(
                "https://example.test",
                data={"key": "value"},
                redirect_url=True,
            )
            == "https://example.test/final"
        )

    session.post.assert_called_once_with(
        "https://example.test",
        data={"key": "value"},
        json=None,
        headers={},
        timeout=20,
        verify=True,
    )


def test_sync_request_returns_response_body_for_http_error_status():
    response = Mock(text="bad request", status_code=400)
    session = Mock()
    session.get.return_value = response

    with patch("src.http_clients.sync_http.get_sync_session", return_value=session):
        assert sync_req("https://example.test") == "bad request"


def test_sync_req_raises_classified_error_with_root_cause():
    session = Mock()
    session.get.side_effect = requests.ConnectionError("connection refused")

    with patch("src.http_clients.sync_http.get_sync_session", return_value=session):
        with pytest.raises(HttpConnectError) as caught:
            sync_req("https://example.test")

    assert caught.value.category == "connect"
    assert "connection refused" in str(caught.value)


def test_sync_fetch_response_raises_classified_error():
    session = Mock()
    session.get.side_effect = requests.ConnectionError("connection refused")

    with patch("src.http_clients.sync_http.get_sync_session", return_value=session):
        try:
            sync_fetch_response("GET", "https://example.test")
        except HttpConnectError as error:
            assert error.category == "connect"
            assert isinstance(error.cause, requests.ConnectionError)
        else:
            raise AssertionError("expected HttpConnectError")
