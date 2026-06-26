from typing import Any

import httpx

from .. import utils
from .client_pool import ClientPurpose, get_async_client
from .errors import HttpClientError, wrap_httpx_error

OptionalStr = str | None
OptionalDict = dict[str, Any] | None


async def async_fetch_response(
    method: str,
    url: str,
    proxy_addr: OptionalStr = None,
    headers: OptionalDict = None,
    data: dict | bytes | None = None,
    json_data: dict | list | None = None,
    timeout: int = 20,
    follow_redirects: bool = False,
    verify: bool = True,
    http2: bool = True,
    abroad: bool = False,
    raise_for_status: bool = False,
) -> httpx.Response:
    if headers is None:
        headers = {}

    normalized_proxy_addr = utils.handle_proxy_addr(proxy_addr)
    if abroad:
        purpose = ClientPurpose.ABROAD
    elif normalized_proxy_addr:
        purpose = ClientPurpose.PROXY
    else:
        purpose = ClientPurpose.DIRECT
    client = get_async_client(
        purpose=purpose,
        proxy_addr=normalized_proxy_addr,
        verify=verify,
        http2=http2,
    )

    try:
        response = await client.request(
            method=method.upper(),
            url=url,
            headers=headers,
            data=data,
            json=json_data,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )
        if raise_for_status:
            response.raise_for_status()
        return response
    except httpx.HTTPError as e:
        raise wrap_httpx_error(method=method, url=url, error=e) from e


async def async_req(
    url: str,
    proxy_addr: OptionalStr = None,
    headers: OptionalDict = None,
    data: dict | bytes | None = None,
    json_data: dict | list | None = None,
    timeout: int = 20,
    redirect_url: bool = False,
    return_cookies: bool = False,
    include_cookies: bool = False,
    abroad: bool = False,
    content_conding: str = "utf-8",
    verify: bool = True,
    http2: bool = True,
) -> OptionalDict | OptionalStr | tuple:
    if headers is None:
        headers = {}
    method = "POST" if data is not None or json_data is not None else "GET"
    response = await async_fetch_response(
        method=method,
        url=url,
        proxy_addr=proxy_addr,
        headers=headers,
        data=data,
        json_data=json_data,
        timeout=timeout,
        follow_redirects=not (data is not None or json_data is not None),
        verify=verify,
        http2=http2,
        abroad=abroad,
    )

    if redirect_url:
        return str(response.url)
    if return_cookies:
        cookies_dict = {name: value for name, value in response.cookies.items()}
        return (response.text, cookies_dict) if include_cookies else cookies_dict
    return response.text


async def get_response_status(
    url: str,
    proxy_addr: OptionalStr = None,
    headers: OptionalDict = None,
    timeout: int = 10,
    abroad: bool = False,
    verify: bool = True,
    http2=False,
) -> bool:
    try:
        response = await async_fetch_response(
            method="HEAD",
            url=url,
            proxy_addr=proxy_addr,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            verify=verify,
            http2=http2,
            abroad=abroad,
        )
        return response.status_code == 200
    except HttpClientError as e:
        print(e)
    return False
