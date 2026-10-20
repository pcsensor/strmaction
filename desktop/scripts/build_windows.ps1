# Build StrmAction Desktop on Windows (PowerShell 7+).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    uv venv .venv
}
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.venv\Scripts\python.exe scripts\make_icons.py
$archKey = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "windows-arm64" } else { "windows-x64" }
if (-not (Test-Path "vendor\mpv\$archKey\mpv.exe")) {
    Write-Host "提示：未发现 vendor\mpv\$archKey\mpv.exe；构建产物将依赖用户已安装的 mpv。" -ForegroundColor Yellow
    Write-Host "如需自带 mpv，请先运行："
    Write-Host "  .venv\Scripts\python.exe scripts\prepare_mpv.py --source <mpv目录>"
}
.venv\Scripts\pyinstaller.exe packaging\strmaction-desktop.spec --noconfirm --clean

Write-Host ""
Write-Host "构建完成：desktop\dist\StrmAction\StrmAction.exe"
