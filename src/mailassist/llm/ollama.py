from __future__ import annotations

import json
from typing import Iterator, List
from urllib import error, request


GENERATE_TIMEOUT_SECONDS = 300
LIST_MODELS_TIMEOUT_SECONDS = 30


class OllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def compose_reply(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "think": False,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=GENERATE_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except error.URLError as exc:
            raise RuntimeError(
                f"Unable to reach Ollama at {self.base_url}. Is the server running?"
            ) from exc

        data = json.loads(body)
        return data.get("response", "").strip()

    def compose_reply_stream(self, prompt: str) -> Iterator[str]:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "think": False,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=GENERATE_TIMEOUT_SECONDS) as response:
                pending = b""
                reader = getattr(response, "read1", None)
                if reader is None and getattr(response, "fp", None) is not None:
                    reader = getattr(response.fp, "read1", None)
                if reader is None:
                    reader = lambda size: response.read(size)
                while True:
                    raw_chunk = reader(1)
                    if not raw_chunk:
                        break
                    pending += raw_chunk
                    while b"\n" in pending:
                        raw_line, pending = pending.split(b"\n", 1)
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("error"):
                            raise RuntimeError(str(data["error"]))
                        chunk = data.get("response", "")
                        if chunk:
                            yield chunk
                        if data.get("done"):
                            return
                if pending.strip():
                    data = json.loads(pending.decode("utf-8").strip())
                    if data.get("error"):
                        raise RuntimeError(str(data["error"]))
                    chunk = data.get("response", "")
                    if chunk:
                        yield chunk
        except error.URLError as exc:
            raise RuntimeError(
                f"Unable to reach Ollama at {self.base_url}. Is the server running?"
            ) from exc

    def list_models(self) -> List[str]:
        req = request.Request(
            f"{self.base_url}/api/tags",
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=LIST_MODELS_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except error.URLError as exc:
            raise RuntimeError(
                f"Unable to reach Ollama at {self.base_url}. Is the server running?"
            ) from exc

        data = json.loads(body)
        return [item["name"] for item in data.get("models", []) if item.get("name")]
