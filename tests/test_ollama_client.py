import json
from io import BytesIO

from mailassist.llm.ollama import GENERATE_TIMEOUT_SECONDS, OllamaClient


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = BytesIO(body)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)


def test_compose_reply_disables_thinking_and_uses_slow_model_timeout(monkeypatch) -> None:
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req, timeout))
        return FakeResponse(json.dumps({"response": "ready"}).encode("utf-8"))

    monkeypatch.setattr("mailassist.llm.ollama.request.urlopen", fake_urlopen)

    result = OllamaClient("http://localhost:11434", "gemma4:31b").compose_reply("hello")

    assert result == "ready"
    assert calls[0][1] == GENERATE_TIMEOUT_SECONDS
    payload = json.loads(calls[0][0].data.decode("utf-8"))
    assert payload["model"] == "gemma4:31b"
    assert payload["stream"] is False
    assert payload["think"] is False


def test_compose_reply_stream_disables_thinking(monkeypatch) -> None:
    body = b'{"response":"re","done":false}\n{"response":"ady","done":true}\n'
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req, timeout))
        return FakeResponse(body)

    monkeypatch.setattr("mailassist.llm.ollama.request.urlopen", fake_urlopen)

    result = "".join(OllamaClient("http://localhost:11434", "gemma4:31b").compose_reply_stream("hello"))

    assert result == "ready"
    assert calls[0][1] == GENERATE_TIMEOUT_SECONDS
    payload = json.loads(calls[0][0].data.decode("utf-8"))
    assert payload["stream"] is True
    assert payload["think"] is False
