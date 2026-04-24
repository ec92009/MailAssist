from __future__ import annotations

import json
from typing import List
from urllib import error, request


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
            }
        ).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=120) as response:
                body = response.read().decode("utf-8")
        except error.URLError as exc:
            raise RuntimeError(
                f"Unable to reach Ollama at {self.base_url}. Is the server running?"
            ) from exc

        data = json.loads(body)
        return data.get("response", "").strip()

    def list_models(self) -> List[str]:
        req = request.Request(
            f"{self.base_url}/api/tags",
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
        except error.URLError as exc:
            raise RuntimeError(
                f"Unable to reach Ollama at {self.base_url}. Is the server running?"
            ) from exc

        data = json.loads(body)
        return [item["name"] for item in data.get("models", []) if item.get("name")]
