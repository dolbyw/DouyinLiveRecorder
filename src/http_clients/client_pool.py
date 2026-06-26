from __future__ import annotations

import asyncio
import atexit
from enum import Enum
from threading import Lock

import httpx
import requests


class ClientPurpose(str, Enum):
    DIRECT = "direct"
    PROXY = "proxy"
    ABROAD = "abroad"


_ASYNC_CLIENTS: dict[
    tuple[asyncio.AbstractEventLoop, ClientPurpose, str | None, bool, bool],
    httpx.AsyncClient,
] = {}
_SYNC_SESSIONS: dict[tuple[ClientPurpose, str | None, bool], requests.Session] = {}
_POOL_LOCK = Lock()


def _build_async_client(proxy_addr: str | None, verify: bool, http2: bool) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=50,
        max_keepalive_connections=20,
        keepalive_expiry=30.0,
    )
    return httpx.AsyncClient(
        proxy=proxy_addr,
        verify=verify,
        http2=http2,
        limits=limits,
    )


def get_async_client(
    purpose: ClientPurpose = ClientPurpose.DIRECT,
    proxy_addr: str | None = None,
    verify: bool = True,
    http2: bool = True,
) -> httpx.AsyncClient:
    client_key = (asyncio.get_running_loop(), purpose, proxy_addr, verify, http2)
    with _POOL_LOCK:
        client = _ASYNC_CLIENTS.get(client_key)
        if client is None:
            client = _build_async_client(proxy_addr=proxy_addr, verify=verify, http2=http2)
            _ASYNC_CLIENTS[client_key] = client
        return client


def _build_sync_session(proxy_addr: str | None, trust_env: bool) -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_env
    if proxy_addr:
        session.proxies.update(
            {
                "http": proxy_addr,
                "https": proxy_addr,
            }
        )
    return session


def get_sync_session(
    purpose: ClientPurpose = ClientPurpose.DIRECT,
    proxy_addr: str | None = None,
    trust_env: bool = False,
) -> requests.Session:
    session_key = (purpose, proxy_addr, trust_env)
    with _POOL_LOCK:
        session = _SYNC_SESSIONS.get(session_key)
        if session is None:
            session = _build_sync_session(proxy_addr=proxy_addr, trust_env=trust_env)
            _SYNC_SESSIONS[session_key] = session
        return session


def close_sync_sessions() -> None:
    with _POOL_LOCK:
        sessions = list(_SYNC_SESSIONS.values())
        _SYNC_SESSIONS.clear()
    for session in sessions:
        session.close()


async def close_async_clients_for_current_loop() -> None:
    current_loop = asyncio.get_running_loop()
    with _POOL_LOCK:
        keys = [key for key in _ASYNC_CLIENTS if key[0] is current_loop]
        clients = [_ASYNC_CLIENTS.pop(key) for key in keys]
    for client in clients:
        await client.aclose()


async def close_async_clients() -> None:
    with _POOL_LOCK:
        clients = list(_ASYNC_CLIENTS.values())
        _ASYNC_CLIENTS.clear()
    for client in clients:
        await client.aclose()


atexit.register(close_sync_sessions)
