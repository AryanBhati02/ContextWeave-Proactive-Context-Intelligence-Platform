"""Anthropic / Voyage LLM provider.

* Embeddings go to the **Voyage AI** API (``voyage-3``).
* Chat completions go to the **Anthropic Messages** API.

* ``POST https://api.voyageai.com/v1/embeddings``      → :meth:`embed`
* ``POST https://api.anthropic.com/v1/messages``        → :meth:`chat`
"""

from __future__ import annotations

import os

import httpx
import structlog

from contextweave.config import AnthropicConfig
from contextweave.providers.base import (
    ChatResult,
    EmbedResult,
    LLMProvider,
    ProviderError,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_PROVIDER_NAME: str = "anthropic"
_VOYAGE_BASE: str = "https://api.voyageai.com/v1"
_ANTHROPIC_BASE: str = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION: str = "2023-06-01"


class AnthropicProvider(LLMProvider):
    """Anthropic (chat) + Voyage (embed) provider."""

    def __init__(self, config: AnthropicConfig) -> None:
        self._config: AnthropicConfig = config
        api_key: str = config.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._api_key: str = api_key

        self._voyage_client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=_VOYAGE_BASE,
            timeout=httpx.Timeout(config.timeout_s),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self._anthropic_client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=_ANTHROPIC_BASE,
            timeout=httpx.Timeout(config.timeout_s),
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )

    async def embed(self, text: str) -> EmbedResult:
        """Generate an embedding via the Voyage ``/embeddings`` endpoint."""
        try:
            resp: httpx.Response = await self._voyage_client.post(
                "/embeddings",
                json={
                    "model": self._config.embed_model,
                    "input": [text],
                    "input_type": "document",
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc)) from exc

        data: dict = resp.json()
        embedding: list[float] = data["data"][0]["embedding"]
        prompt_tokens: int = data.get("usage", {}).get("total_tokens", len(text.split()))

        return EmbedResult(
            embedding=embedding,
            model=self._config.embed_model,
            prompt_tokens=prompt_tokens,
        )

    async def chat(self, system: str, user: str) -> ChatResult:
        """Generate a chat completion via the Anthropic Messages API."""
        try:
            resp: httpx.Response = await self._anthropic_client.post(
                "/messages",
                json={
                    "model": self._config.chat_model,
                    "max_tokens": 1024,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc)) from exc

        data: dict = resp.json()
        content: str = data["content"][0]["text"]
        usage: dict = data.get("usage", {})

        return ChatResult(
            content=content,
            model=self._config.chat_model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    async def health_check(self) -> bool:
        """Ping Anthropic Messages API with a minimal request.  Never raises."""
        try:
            resp: httpx.Response = await self._anthropic_client.post(
                "/messages",
                json={
                    "model": self._config.chat_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )
            return resp.status_code in (200, 400)
        except Exception:
            return False
