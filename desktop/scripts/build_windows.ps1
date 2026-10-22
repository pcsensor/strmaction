# Build StrmAction Desktop on Windows (PowerShell 7+).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    uv venv .venv
}
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.venv\Scripts\python.exe scripts\make_icons.py
.venv\Scripts\pyinstaller.exe packaging\strmaction-desktop.spec --noconfirm --clean

Write-Host ""
Write-Host "构建完成：desktop\dist\StrmAction\StrmAction.exe"