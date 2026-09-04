"""Smoke test: every package in src/ should be importable, and config
should load config/settings.yaml without any hardcoded values leaking in.
"""

import importlib

import pytest

PACKAGES = ["ingestion", "rules", "llm", "pipeline", "storage", "ui", "data_prep"]


@pytest.mark.parametrize("package_name", PACKAGES)
def test_package_imports(package_name):
    importlib.import_module(package_name)


def test_settings_load():
    from config import get_settings

    settings = get_settings()
    assert "llm" in settings
    assert "model" in settings["llm"]
    assert "base_url" in settings["llm"]
