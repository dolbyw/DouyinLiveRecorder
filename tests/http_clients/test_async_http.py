from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.http_clients.async_http import async_fetch_response, async_req
from src.http_clients.client_pool import ClientPurpose
from src.http_clients.errors import HttpConnectError, HttpStatusError


@pytest.mark.asyncio
async def test_async_fetch_uses_verified_direct_client_by_default():
    response = httpx.Response(200, text="ok")
    client = AsyncMock()
    client.request.return_value = response

    with patch("src.http_clients.async_http.get_async_client", return_value=client) as factory:
        assert await async_fetch_response("GET", "https://example.test") is response

    factory.assert_called_once_with(
        purpose=ClientPurpose.DIRECT,
        proxy_addr=None,
        verify=True,
        http2=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("proxy_addr", "abroad", "purpose"),
    [
        ("http://127.0.0.1:8080", False, ClientPurpose.PROXY),
        (None, True, ClientPurpose.ABROAD),
    ],
)
async def test_async_fetch_selects_client_purpose(proxy_addr, abroad, purpose):
    client = AsyncMock()
    client.request.return_value = httpx.Response(200, text="ok")

    with patch("src.http_clients.async_http.utils.handle_proxy_addr", return_value=proxy_addr):
        with patch("src.http_clients.async_http.get_async_client", return_value=client) as factory:
            await async_fetch_response(
                "GET",
                "https://example.test",
                proxy_addr=proxy_addr,
                abroad=abroad,
            )

    assert factory.call_args.kwargs["purpose"] is purpose


@pytest.mark.asyncio
async def test_async_req_preserves_text_and_cookie_return_shapes():
    response = httpx.Response(
        200,
        text="payload",
        headers={"set-cookie": "session=abc; Path=/"},
        request=httpx.Request("GET", "https://example.test"),
    )
    with patch("src.http_clients.async_http.async_fetch_response", new=AsyncMock(return_value=response)):
        assert await async_req("https://example.test") == "payload"
        assert await async_req("https://example.test", return_cookies=True) == {"session": "abc"}
        assert await async_req(
            "https://example.test",
            return_cookies=True,
            include_cookies=True,
        ) == ("payload", {"session": "abc"})


@pytest.mark.asyncio
async def test_async_req_raises_classified_error_with_root_cause():
    source = httpx.ConnectError("connection refused")
    with patch(
        "src.http_clients.async_http.async_fetch_response",
        new=AsyncMock(
            side_effect=HttpConnectError(
                "GET",
                "https://example.test",
                str(source),
                cause=source,
            )
        ),
    ):
        with pytest.raises(HttpConnectError) as caught:
            await async_req("https://example.test")

    assert caught.value.category == "connect"
    assert "connection refused" in str(caught.value)


@pytest.mark.asyncio
async def test_async_fetch_can_raise_classified_status_error():
    request = httpx.Request("GET", "https://example.test")
    response = httpx.Response(503, request=request)
    client = AsyncMock()
    client.request.return_value = response

    with patch("src.http_clients.async_http.get_async_client", return_value=client):
        with pytest.raises(HttpStatusError) as caught:
            await async_fetch_response(
                "GET",
                "https://example.test",
                raise_for_status=True,
            )

    assert caught.value.status_code == 503
