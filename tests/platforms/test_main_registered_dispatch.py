import main
from src.platforms import DispatchResult


class FakeGate:
    def __init__(self):
        self.entered = False

    def __enter__(self):
        self.entered = True

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_registered_platform_helper_builds_dispatch_context(monkeypatch):
    gate = FakeGate()
    captured = {}
    sentinel = object()

    def fake_try_resolve(registry, url, quality, **kwargs):
        captured["registry"] = registry
        captured["url"] = url
        captured["quality"] = quality
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(main, "semaphore", gate, raising=False)
    monkeypatch.setattr(main, "dy_cookie", "dy", raising=False)
    monkeypatch.setattr(main, "tiktok_cookie", "tt", raising=False)
    monkeypatch.setattr(main, "bili_cookie", "bili", raising=False)
    monkeypatch.setattr(main, "hy_cookie", "hy", raising=False)
    monkeypatch.setattr(main, "global_proxy", True)
    monkeypatch.setattr(main, "try_resolve", fake_try_resolve)
    monkeypatch.setattr(main, "run_async_batch", lambda factory: (factory(),))

    result = main.resolve_registered_platform_once("https://live.douyin.com/1", "HD", "proxy")

    assert result is sentinel
    assert gate.entered is True
    assert captured == {
        "registry": main.default_registry,
        "url": "https://live.douyin.com/1",
        "quality": "HD",
        "kwargs": {
            "proxy_addr": "proxy",
            "cookies_by_platform": {
                "douyin": "dy",
                "tiktok": "tt",
                "bilibili": "bili",
                "huya": "hy",
            },
            "network_available": True,
        },
    }


def test_registered_platform_helper_skips_async_runner_for_unregistered_url(monkeypatch):
    gate = FakeGate()

    def fail_run_async_batch(_factory):
        raise AssertionError("unregistered URLs must fall through to legacy branches without async dispatch")

    monkeypatch.setattr(main, "semaphore", gate, raising=False)
    monkeypatch.setattr(main, "run_async_batch", fail_run_async_batch)

    result = main.resolve_registered_platform_once("https://live.kuaishou.com/u/example", "HD", None)

    assert result == DispatchResult(handled=False)
    assert gate.entered is False
