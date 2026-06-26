from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, Callable


NativeHandler = Callable[..., Any]


def _taobao_sign(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _laixiu_sign(*_args: Any) -> dict[str, Any]:
    timestamp = int(time.time() * 1000)
    imei = uuid.uuid4().hex
    secret = "kk792f28d6ff1f34ec702c08626d454b39pro"
    input_str = f"web{imei}{timestamp}{secret}"
    request_id = hashlib.md5(input_str.encode("utf-8")).hexdigest()
    return {
        "timestamp": timestamp,
        "imei": imei,
        "requestId": request_id,
        "inputString": input_str,
    }


_NATIVE_SCRIPT_HANDLERS: dict[tuple[str, str], NativeHandler] = {
    ("taobao-sign.js", "sign"): _taobao_sign,
    ("laixiu.js", "sign"): _laixiu_sign,
}


def try_call_native_script(script_name: str, function_name: str, *args: Any) -> tuple[bool, Any]:
    handler = _NATIVE_SCRIPT_HANDLERS.get((script_name, function_name))
    if handler is None:
        return False, None
    return True, handler(*args)
