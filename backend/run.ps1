# Convenience script for Windows PowerShell: seeds the database (if needed)
# and starts the API server. Equivalent to run.sh, but for PowerShell.
#
# Usage:  .\run.ps1
# (If PowerShell blocks script execution, run this once first:
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser )

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "niyamguard.db")) {
    Write-Host "No database found - seeding sample data..."
    python -m app.seed_data
}

Write-Host "Starting NiyamGuard AI backend on http://localhost:8000  (docs at /docs)"
uvicorn app.main:app --reload --port 8000