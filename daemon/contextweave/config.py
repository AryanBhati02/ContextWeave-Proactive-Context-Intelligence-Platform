"""Configuration management — RULE 5: one config file.

All configuration lives in ``~/.contextweave/config.toml``.  No hardcoded
ports, URLs, or model names anywhere else in the codebase.

The :class:`Config` tree is **frozen** after loading — it is never re-read
at runtime.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_DEFAULT_CONFIG_DIR: Path = Path.home() / ".contextweave"
_DEFAULT_CONFIG_PATH: Path = _DEFAULT_CONFIG_DIR / "config.toml"




_DEFAULT_TOML: str = """\
[daemon]
port = 7331
host = "127.0.0.1"
log_level = "INFO"
max_file_size_kb = 500
max_queue_size = 500
shutdown_drain_timeout_s = 10

[provider]
embed_provider = "ollama"
chat_provider = "ollama"

[provider.ollama]
base_url = "http://localhost:11434"
embed_model = "nomic-embed-text"
chat_model = "llama3.2"
timeout_s = 30

[provider.openai]
base_url = "https://api.openai.com/v1"
api_key = ""
embed_model = "text-embedding-3-small"
chat_model = "gpt-4o-mini"
timeout_s = 30

[provider.anthropic]
api_key = ""
embed_model = "voyage-3"
chat_model = "claude-3-5-haiku-20241022"
timeout_s = 30

[provider.lmstudio]
base_url = "http://localhost:1234/v1"
api_key = "lm-studio"
embed_model = "nomic-embed-text-v1.5"
chat_model = "qwen2.5-7b-instruct"
timeout_s = 30

[stuck_detector]
threshold_seconds = 600
min_change_tokens = 10

[ranker]
semantic_weight = 0.55
recency_weight = 0.30
graph_weight = 0.15
recency_half_life_hours = 4.0
candidate_pool = 30
max_context_tokens = 6000
"""





@dataclass(frozen=True, slots=True)
class DaemonConfig:
    """Settings for the HTTP daemon itself."""

    port: int = 7331
    host: str = "127.0.0.1"
    log_level: str = "INFO"
    max_file_size_kb: int = 500
    max_queue_size: int = 500
    shutdown_drain_timeout_s: int = 10


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    """Ollama-specific provider settings."""

    base_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    chat_model: str = "llama3.2"
    timeout_s: int = 30


@dataclass(frozen=True, slots=True)
class OpenAIConfig:
    """OpenAI-compatible provider settings."""

    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    embed_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"
    timeout_s: int = 30


@dataclass(frozen=True, slots=True)
class AnthropicConfig:
    """Anthropic provider settings."""

    api_key: str = ""
    embed_model: str = "voyage-3"
    chat_model: str = "claude-3-5-haiku-20241022"
    timeout_s: int = 30


@dataclass(frozen=True, slots=True)
class LMStudioConfig:
    """LM Studio provider settings."""

    base_url: str = "http://localhost:1234/v1"
    api_key: str = "lm-studio"
    embed_model: str = "nomic-embed-text-v1.5"
    chat_model: str = "qwen2.5-7b-instruct"
    timeout_s: int = 30


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Top-level provider selector and per-provider config blocks."""

    embed_provider: str = "ollama"
    chat_provider: str = "ollama"
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    lmstudio: LMStudioConfig = field(default_factory=LMStudioConfig)


@dataclass(frozen=True, slots=True)
class StuckDetectorConfig:
    """Stuck-detection thresholds."""

    threshold_seconds: int = 600
    min_change_tokens: int = 10


@dataclass(frozen=True, slots=True)
class RankerConfig:
    """Ranking weights and limits."""

    semantic_weight: float = 0.55
    recency_weight: float = 0.30
    graph_weight: float = 0.15
    recency_half_life_hours: float = 4.0
    candidate_pool: int = 30
    max_context_tokens: int = 6000


@dataclass(frozen=True, slots=True)
class Config:
    """Root configuration — frozen after creation, never re-read."""

    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    stuck_detector: StuckDetectorConfig = field(default_factory=StuckDetectorConfig)
    ranker: RankerConfig = field(default_factory=RankerConfig)






def _safe_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Filter *data* to only keys that are valid fields of *cls*."""
    valid = {f.name for f in cls.__dataclass_fields__.values()}  
    return {k: v for k, v in data.items() if k in valid}


def _build_config(raw: dict[str, Any]) -> Config:
    """Construct a :class:`Config` from a parsed TOML dictionary."""
    daemon_raw: dict[str, Any] = raw.get("daemon", {})
    provider_raw: dict[str, Any] = raw.get("provider", {})
    stuck_raw: dict[str, Any] = raw.get("stuck_detector", {})
    ranker_raw: dict[str, Any] = raw.get("ranker", {})

    provider = ProviderConfig(
        embed_provider=provider_raw.get("embed_provider", "ollama"),
        chat_provider=provider_raw.get("chat_provider", "ollama"),
        ollama=OllamaConfig(**_safe_fields(OllamaConfig, provider_raw.get("ollama", {}))),
        openai=OpenAIConfig(**_safe_fields(OpenAIConfig, provider_raw.get("openai", {}))),
        anthropic=AnthropicConfig(**_safe_fields(AnthropicConfig, provider_raw.get("anthropic", {}))),
        lmstudio=LMStudioConfig(**_safe_fields(LMStudioConfig, provider_raw.get("lmstudio", {}))),
    )

    return Config(
        daemon=DaemonConfig(**_safe_fields(DaemonConfig, daemon_raw)),
        provider=provider,
        stuck_detector=StuckDetectorConfig(**_safe_fields(StuckDetectorConfig, stuck_raw)),
        ranker=RankerConfig(**_safe_fields(RankerConfig, ranker_raw)),
    )






def load_config(path: Path | None = None) -> Config:
    """Load configuration from TOML, creating the file with defaults if absent.

    Parameters
    ----------
    path:
        Explicit path to a TOML config file.  Defaults to
        ``~/.contextweave/config.toml``.

    Returns
    -------
    Config
        A frozen, read-only configuration tree.
    """
    config_path: Path = path or _DEFAULT_CONFIG_PATH

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_DEFAULT_TOML, encoding="utf-8")
        log.info("config_created_with_defaults", path=str(config_path))
        return Config()

    with config_path.open("rb") as fh:
        raw: dict[str, Any] = tomllib.load(fh)

    log.info("config_loaded", path=str(config_path))
    return _build_config(raw)
