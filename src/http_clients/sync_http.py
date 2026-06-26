from __future__ import annotations

import requests

from .. import utils
from .client_pool import ClientPurpose, get_sync_session
from .errors import wrap_requests_error

OptionalStr = str | None
OptionalDict = dict | None


def sync_fetch_response(
    method: str,
    url: str,
    proxy_addr: OptionalStr = None,
    headers: OptionalDict = None,
    data: dict | bytes | None = None,
    json_data: dict | list | None = None,
    timeout: int = 20,
    abroad: bool = False,
    verify: bool = True,
) -> requests.Response:
    if headers is None:
        headers = {}
    normalized_proxy_addr = utils.handle_proxy_addr(proxy_addr)
    if abroad:
        purpose = ClientPurpose.ABROAD
    elif normalized_proxy_addr:
        purpose = ClientPurpose.PROXY
    else:
        purpose = ClientPurpose.DIRECT

    session = get_sync_session(
        purpose=purpose,
        proxy_addr=normalized_proxy_addr,
        trust_env=False,
    )
    try:
        if method.upper() == "POST":
            return session.post(
                url,
                data=data,
                json=json_data,
                headers=headers,
                timeout=timeout,
                verify=verify,
            )
        return session.get(
            url,
            headers=headers,
            timeout=timeout,
            verify=verify,
        )
    except requests.exceptions.RequestException as error:
        raise wrap_requests_error(method, url, error) from error


def sync_req(
    url: str,
    proxy_addr: OptionalStr = None,
    headers: OptionalDict = None,
    data: dict | bytes | None = None,
    json_data: dict | list | None = None,
    timeout: int = 20,
    redirect_url: bool = False,
    abroad: bool = False,
    content_conding: str = "utf-8",
    verify: bool = True,
) -> str:
    method = "POST" if data is not None or json_data is not None else "GET"
    response = sync_fetch_response(
        method,
        url,
        proxy_addr=proxy_addr,
        headers=headers,
        data=data,
        json_data=json_data,
        timeout=timeout,
        abroad=abroad,
        verify=verify,
    )
    if redirect_url:
        return str(response.url)
    response.encoding = content_conding
    return response.text
