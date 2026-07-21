# Starts the FastAPI backend using settings from config/settings.yaml.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
& "$root\.venv\Scripts\python.exe" -m uvicorn ui.api:app --reload --app-dir "$root\src"
