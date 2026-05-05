"""OpenAI-compatible LLM provider.

Works with **OpenAI**, **LM Studio**, and any other service that exposes the
standard ``/embeddings`` and ``/chat/completions`` endpoints.

* ``POST {base_url}/embeddings``        → :meth:`embed`
* ``POST {base_url}/chat/completions``  → :meth:`chat`
* ``GET  {base_url}/models``            → :meth:`health_check`
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from contextweave.providers.base import (
    ChatResult,
    EmbedResult,
    LLMProvider,
    ProviderError,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_PROVIDER_NAME: str = "openai_compat"


@dataclass(frozen=True, slots=True)
class OpenAICompatConfig:
    """Minimal config contract expected by this provider."""

    base_url: str
    api_key: str
    embed_model: str
    chat_model: str
    timeout_s: int


class OpenAICompatProvider(LLMProvider):
    """Provider for any OpenAI-compatible API (OpenAI, LM Studio, etc.)."""

    def __init__(self, config: OpenAICompatConfig) -> None:
        self._config: OpenAICompatConfig = config
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(config.timeout_s),
            headers=headers,
        )

    async def embed(self, text: str) -> EmbedResult:
        """Generate an embedding via the ``/embeddings`` endpoint."""
        try:
            resp: httpx.Response = await self._client.post(
                "/embeddings",
                json={"model": self._config.embed_model, "input": text},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc)) from exc

        data: dict = resp.json()
        embedding: list[float] = data["data"][0]["embedding"]
        prompt_tokens: int = data.get("usage", {}).get("prompt_tokens", len(text.split()))

        return EmbedResult(
            embedding=embedding,
            model=self._config.embed_model,
            prompt_tokens=prompt_tokens,
        )

    async def chat(self, system: str, user: str) -> ChatResult:
        """Generate a chat completion via ``/chat/completions``."""
        try:
            resp: httpx.Response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._config.chat_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc)) from exc

        data: dict = resp.json()
        content: str = data["choices"][0]["message"]["content"]
        usage: dict = data.get("usage", {})

        return ChatResult(
            content=content,
            model=self._config.chat_model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    async def health_check(self) -> bool:
        """Ping ``/models`` to verify connectivity.  Never raises."""
        try:
            resp: httpx.Response = await self._client.get("/models")
            return resp.status_code == 200
        except Exception:
            return False
