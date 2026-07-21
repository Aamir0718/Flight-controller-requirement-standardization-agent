# Runs the test suite using the project virtual environment.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
& "$root\.venv\Scripts\python.exe" -m pytest "$root\tests" @args
