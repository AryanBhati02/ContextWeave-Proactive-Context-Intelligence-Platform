"""LLM provider abstractions and factory — no vendor lock-in (RULE 2).

Use :func:`create_provider` to get a provider instance based on config.
Switching providers is a one-line change in ``config.toml``.
"""

from __future__ import annotations

import structlog

from contextweave.config import Config
from contextweave.providers.base import (
    ChatResult,
    EmbedResult,
    LLMProvider,
    ProviderError,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger()

__all__: list[str] = [
    "LLMProvider",
    "EmbedResult",
    "ChatResult",
    "ProviderError",
    "create_provider",
]


def create_provider(config: Config) -> LLMProvider:
    """Instantiate the correct :class:`LLMProvider` from *config*.

    The ``config.provider.embed_provider`` value selects the backend:

    * ``"ollama"``    → :class:`OllamaProvider`
    * ``"openai"``    → :class:`OpenAICompatProvider` (OpenAI keys)
    * ``"lmstudio"``  → :class:`OpenAICompatProvider` (LM Studio keys)
    * ``"anthropic"`` → :class:`AnthropicProvider`
    """
    name: str = config.provider.embed_provider

    if name == "ollama":
        from contextweave.providers.ollama import OllamaProvider

        log.info("provider_created", provider="ollama")
        return OllamaProvider(config.provider.ollama)

    if name == "openai":
        from contextweave.providers.openai_compat import (
            OpenAICompatConfig,
            OpenAICompatProvider,
        )

        oc = config.provider.openai
        log.info("provider_created", provider="openai")
        return OpenAICompatProvider(
            OpenAICompatConfig(
                base_url=oc.base_url,
                api_key=oc.api_key,
                embed_model=oc.embed_model,
                chat_model=oc.chat_model,
                timeout_s=oc.timeout_s,
            )
        )

    if name == "lmstudio":
        from contextweave.providers.openai_compat import (
            OpenAICompatConfig,
            OpenAICompatProvider,
        )

        lc = config.provider.lmstudio
        log.info("provider_created", provider="lmstudio")
        return OpenAICompatProvider(
            OpenAICompatConfig(
                base_url=lc.base_url,
                api_key=lc.api_key,
                embed_model=lc.embed_model,
                chat_model=lc.chat_model,
                timeout_s=lc.timeout_s,
            )
        )

    if name == "anthropic":
        from contextweave.providers.anthropic import AnthropicProvider

        log.info("provider_created", provider="anthropic")
        return AnthropicProvider(config.provider.anthropic)

    raise ValueError(f"Unknown embed_provider: {name!r}")
