"""Loads config/settings.yaml so no model name, host, port, or path is
hardcoded anywhere else in the application.

Usage:
    from config import get_settings
    settings = get_settings()
    model_name = settings["ollama"]["model"]
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"


def _resolve_config_path() -> Path:
    override = os.environ.get("REQAGENT_CONFIG_PATH")
    return Path(override) if override else _DEFAULT_CONFIG_PATH


@functools.lru_cache(maxsize=1)
def get_settings() -> dict[str, Any]:
    """Loads and caches config/settings.yaml as a dict."""
    config_path = _resolve_config_path()
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
