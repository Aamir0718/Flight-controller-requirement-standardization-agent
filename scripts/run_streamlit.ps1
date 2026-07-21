# Starts the Streamlit UI using settings from config/settings.yaml.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = "$root\src"
& "$root\.venv\Scripts\python.exe" -m streamlit run "$root\src\ui\streamlit_app.py"
