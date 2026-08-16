# Copies the current backend code into this deploy snapshot folder.
# Run this after any backend change, before committing/pushing to the
# Hugging Face Space remote.
#
# Usage (from repo root or from here, doesn't matter):
#   powershell -File deploy\hf-space\sync_backend.ps1

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $here)

Write-Host "Syncing backend into $here ..."

robocopy "$repoRoot\src" "$here\src" /MIR /XD __pycache__ *.egg-info /NFL /NDL /NJH /NJS
robocopy "$repoRoot\config" "$here\config" /NFL /NDL /NJH /NJS
Copy-Item "$repoRoot\requirements.txt" "$here\requirements.txt" -Force

Write-Host "Done. Review 'git status' in this folder, then commit and push to the Space remote."
