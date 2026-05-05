"""Ollama LLM provider.

Communicates with a local Ollama instance via its REST API.

* ``POST /api/embeddings``  → :meth:`embed`
* ``POST /api/chat``        → :meth:`chat`
* ``GET  /api/tags``        → :meth:`health_check`
"""

from __future__ import annotations

import httpx
import structlog

from contextweave.config import OllamaConfig
from contextweave.providers.base import (
    ChatResult,
    EmbedResult,
    LLMProvider,
    ProviderError,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_PROVIDER_NAME: str = "ollama"


class OllamaProvider(LLMProvider):
    """Ollama REST API provider."""

    def __init__(self, config: OllamaConfig) -> None:
        self._config: OllamaConfig = config
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(config.timeout_s),
        )

    async def embed(self, text: str) -> EmbedResult:
        """Generate an embedding via Ollama ``/api/embeddings``."""
        try:
            resp: httpx.Response = await self._client.post(
                "/api/embeddings",
                json={"model": self._config.embed_model, "prompt": text},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc)) from exc

        data: dict = resp.json()
        embedding: list[float] = data["embedding"]

        return EmbedResult(
            embedding=embedding,
            model=self._config.embed_model,
            prompt_tokens=len(text.split()),
        )

    async def chat(self, system: str, user: str) -> ChatResult:
        """Generate a chat completion via Ollama ``/api/chat``."""
        try:
            resp: httpx.Response = await self._client.post(
                "/api/chat",
                json={
                    "model": self._config.chat_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc)) from exc

        data: dict = resp.json()
        content: str = data.get("message", {}).get("content", "")
        prompt_tokens: int = data.get("prompt_eval_count", 0)
        completion_tokens: int = data.get("eval_count", 0)

        return ChatResult(
            content=content,
            model=self._config.chat_model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )

    async def health_check(self) -> bool:
        """Check Ollama reachability via ``GET /api/tags``.  Never raises."""
        try:
            resp: httpx.Response = await self._client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False
