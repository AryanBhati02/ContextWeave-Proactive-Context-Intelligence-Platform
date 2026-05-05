"""Abstract base class for all LLM providers.

Every provider (Ollama, OpenAI, Anthropic, LM Studio) implements this
interface.  Switching providers is a one-line config change (RULE 2).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmbedResult:
    """Result of an embedding call."""

    embedding: list[float]
    model: str
    prompt_tokens: int


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Result of a chat completion call."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int


class ProviderError(Exception):
    """All providers raise this on failure.  Always catchable at the caller."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider: str = provider
        super().__init__(f"[{provider}] {message}")


class LLMProvider(abc.ABC):
    """Abstract base for LLM providers — RULE 2: no vendor lock-in."""

    @abc.abstractmethod
    async def embed(self, text: str) -> EmbedResult:
        """Return an embedding vector for *text*."""

    @abc.abstractmethod
    async def chat(self, system: str, user: str) -> ChatResult:
        """Return a chat completion given system and user prompts."""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return ``True`` if the provider is reachable and healthy.

        Must **never** raise — catch all exceptions and return ``False``.
        """
