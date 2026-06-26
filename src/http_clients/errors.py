from __future__ import annotations

import httpx
import requests


class HttpClientError(Exception):
    category = "request"

    def __init__(self, method: str, url: str, detail: str, *, cause: Exception | None = None) -> None:
        self.method = method.upper()
        self.url = url
        self.detail = detail
        self.cause = cause
        super().__init__(f"{self.method} {self.url} failed [{self.category}]: {detail}")


class HttpConnectError(HttpClientError):
    category = "connect"


class HttpTimeoutError(HttpClientError):
    category = "timeout"


class HttpProxyError(HttpClientError):
    category = "proxy"


class HttpStatusError(HttpClientError):
    category = "status"

    def __init__(
        self,
        method: str,
        url: str,
        status_code: int,
        detail: str = "unexpected status",
        *,
        cause: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        super().__init__(method, url, f"{detail} (status={status_code})", cause=cause)


class HttpDecodeError(HttpClientError):
    category = "decode"


class HttpJsonError(HttpClientError):
    category = "json"


class HttpRequestConfigError(HttpClientError):
    category = "config"


# Backward-compatible name retained for existing imports.
HttpClientStatusError = HttpStatusError


def wrap_httpx_error(method: str, url: str, error: httpx.HTTPError) -> HttpClientError:
    if isinstance(error, httpx.TimeoutException):
        return HttpTimeoutError(method, url, str(error), cause=error)
    if isinstance(error, httpx.ProxyError):
        return HttpProxyError(method, url, str(error), cause=error)
    if isinstance(error, httpx.ConnectError):
        return HttpConnectError(method, url, str(error), cause=error)
    if isinstance(error, httpx.InvalidURL):
        return HttpRequestConfigError(method, url, str(error), cause=error)
    if isinstance(error, httpx.HTTPStatusError):
        return HttpStatusError(
            method,
            url,
            error.response.status_code,
            str(error),
            cause=error,
        )
    return HttpClientError(method, url, str(error), cause=error)


def wrap_requests_error(method: str, url: str, error: requests.exceptions.RequestException) -> HttpClientError:
    if isinstance(error, requests.exceptions.Timeout):
        return HttpTimeoutError(method, url, str(error), cause=error)
    if isinstance(error, requests.exceptions.ProxyError):
        return HttpProxyError(method, url, str(error), cause=error)
    if isinstance(error, requests.exceptions.ConnectionError):
        return HttpConnectError(method, url, str(error), cause=error)
    if isinstance(
        error,
        (
            requests.exceptions.InvalidURL,
            requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema,
        ),
    ):
        return HttpRequestConfigError(method, url, str(error), cause=error)
    return HttpClientError(method, url, str(error), cause=error)
