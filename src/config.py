"""Loads config/settings.yaml so no model name, host, port, or path is
hardcoded anywhere else in the application.

Usage:
    from config import get_settings
    settings = get_settings()
    model_name = settings["ollama"]["model"]
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"

# Cache keyed by the file's last-modified time, not a plain @lru_cache --
# the configured Ollama model (settings.yaml's ollama.model) gets swapped
# often during offline development (gemma3:4b, gemma3:1b, qwen3:6b, ...),
# and a plain cache would keep serving the model name/config the backend
# process happened to start with until it was restarted. Re-stat()ing a
# few-KB YAML file is negligible next to an LLM call, so there's no real
# cost to just checking every time.
_cached_settings: dict[str, Any] | None = None
_cached_mtime: float | None = None
_cached_path: Path | None = None


def _resolve_config_path() -> Path:
    override = os.environ.get("REQAGENT_CONFIG_PATH")
    return Path(override) if override else _DEFAULT_CONFIG_PATH


def get_settings() -> dict[str, Any]:
    """Loads config/settings.yaml as a dict, re-reading it whenever the
    file's mtime has changed since the last call -- so editing e.g. the
    configured model takes effect immediately, no backend restart needed.
    """
    global _cached_settings, _cached_mtime, _cached_path
    config_path = _resolve_config_path()
    mtime = config_path.stat().st_mtime
    if _cached_settings is None or _cached_path != config_path or _cached_mtime != mtime:
        with config_path.open("r", encoding="utf-8") as f:
            _cached_settings = yaml.safe_load(f)
        _cached_mtime = mtime
        _cached_path = config_path
    return _cached_settings
