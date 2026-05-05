"""Tests for contextweave.config — frozen config, TOML loading, defaults."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from contextweave.config import Config, DaemonConfig, load_config


class TestConfigDefaults:
    """Config loading when no file exists on disk."""

    def test_config_loads_defaults_when_no_file_exists(self, tmp_path: Path) -> None:
        """When the TOML is absent the returned Config uses all defaults."""
        config_path: Path = tmp_path / "config.toml"
        config: Config = load_config(path=config_path)

        assert config.daemon.port == 7331
        assert config.daemon.host == "127.0.0.1"
        assert config.daemon.log_level == "INFO"
        assert config.provider.embed_provider == "ollama"
        assert config.stuck_detector.threshold_seconds == 600
        
        assert config.ranker.semantic_weight == 0.55
        assert config.ranker.recency_weight == 0.30
        assert config.ranker.graph_weight == 0.15

    def test_config_creates_file_if_not_exists(self, tmp_path: Path) -> None:
        """load_config creates the TOML file with defaults when absent."""
        config_path: Path = tmp_path / "subdir" / "config.toml"
        assert not config_path.exists()

        load_config(path=config_path)

        assert config_path.exists()
        content: str = config_path.read_text(encoding="utf-8")
        assert "[daemon]" in content
        assert "port = 7331" in content


class TestConfigFrozen:
    """Config immutability after loading."""

    def test_config_is_frozen_after_load(self, tmp_path: Path) -> None:
        """Mutating a frozen Config field raises FrozenInstanceError."""
        config: Config = load_config(path=tmp_path / "config.toml")

        with pytest.raises(dataclasses.FrozenInstanceError):
            config.daemon = DaemonConfig(port=9999)  

    def test_nested_config_is_frozen(self, tmp_path: Path) -> None:
        """Nested dataclass fields are also frozen."""
        config: Config = load_config(path=tmp_path / "config.toml")

        with pytest.raises(dataclasses.FrozenInstanceError):
            config.daemon.port = 9999  


class TestConfigFromToml:
    """Config loading from an existing TOML file."""

    def test_config_reads_port_from_toml(self, tmp_path: Path) -> None:
        """A custom port in the TOML is reflected in the loaded Config."""
        config_path: Path = tmp_path / "config.toml"
        config_path.write_text(
            '[daemon]\nport = 8080\nhost = "0.0.0.0"\n',
            encoding="utf-8",
        )

        config: Config = load_config(path=config_path)

        assert config.daemon.port == 8080
        assert config.daemon.host == "0.0.0.0"

    def test_config_reads_provider_from_toml(self, tmp_path: Path) -> None:
        """Provider selection is read from the TOML file."""
        config_path: Path = tmp_path / "config.toml"
        config_path.write_text(
            '[provider]\nembed_provider = "openai"\nchat_provider = "anthropic"\n',
            encoding="utf-8",
        )

        config: Config = load_config(path=config_path)

        assert config.provider.embed_provider == "openai"
        assert config.provider.chat_provider == "anthropic"

    def test_config_partial_toml_fills_defaults(self, tmp_path: Path) -> None:
        """Fields omitted from the TOML fall back to defaults."""
        config_path: Path = tmp_path / "config.toml"
        config_path.write_text("[daemon]\nport = 5555\n", encoding="utf-8")

        config: Config = load_config(path=config_path)

        assert config.daemon.port == 5555
        
        assert config.daemon.max_file_size_kb == 500
        assert config.ranker.candidate_pool == 30

    def test_config_provider_subsection(self, tmp_path: Path) -> None:
        """Nested provider sub-sections (e.g. ollama) are parsed correctly."""
        config_path: Path = tmp_path / "config.toml"
        config_path.write_text(
            '[provider.ollama]\nembed_model = "custom-embed"\n',
            encoding="utf-8",
        )

        config: Config = load_config(path=config_path)

        assert config.provider.ollama.embed_model == "custom-embed"
        
        assert config.provider.ollama.timeout_s == 30
