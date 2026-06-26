import main


class FakeResponse:
    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def iter_bytes(self, _chunk_size):
        yield b"live"
        yield b"data"


class FakeClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.entered = False
        self.exited = False
        self.stream_calls = []
        FakeClient.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True
        return False

    def stream(self, method, url, **kwargs):
        self.stream_calls.append((method, url, kwargs))
        return FakeResponse()


def test_direct_download_closes_http_client(monkeypatch, tmp_path):
    FakeClient.instances.clear()
    output = tmp_path / "download.flv"

    monkeypatch.setattr(main.httpx, "Client", FakeClient)
    monkeypatch.setattr(main, "url_comments", [])
    monkeypatch.setattr(main, "exit_recording", False)

    result = main.direct_download_stream(
        "https://stream.example/live.flv",
        str(output),
        "room",
        "https://live.example/room",
        "Other",
    )

    assert result is True
    assert output.read_bytes() == b"livedata"
    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].entered is True
    assert FakeClient.instances[0].exited is True
