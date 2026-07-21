# Creates (if missing) and updates the project virtual environment,
# then installs the package in editable mode plus pinned dependencies.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$root\.venv")) {
    python -m venv "$root\.venv"
}

& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install -r "$root\requirements.txt"
& "$root\.venv\Scripts\python.exe" -m pip install -e "$root"

Write-Host "Environment ready. Activate with: $root\.venv\Scripts\Activate.ps1"
