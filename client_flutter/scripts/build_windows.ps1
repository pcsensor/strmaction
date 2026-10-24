param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
        throw "未找到 flutter，请先安装 Flutter SDK 并加入 PATH。"
    }

    # flutter_inappwebview_windows uses NuGet to fetch WebView2 packages.
    if (-not (Get-Command nuget -ErrorAction SilentlyContinue)) {
        $nugetDir = Join-Path $env:TEMP "strmaction-nuget"
        $nugetExe = Join-Path $nugetDir "nuget.exe"
        New-Item -ItemType Directory -Force $nugetDir | Out-Null
        if (-not (Test-Path $nugetExe)) {
            Write-Host "未找到 NuGet，下载到 $nugetExe ..."
            Invoke-WebRequest -Uri "https://dist.nuget.org/win-x86-commandline/latest/nuget.exe" `
                -OutFile $nugetExe -UseBasicParsing
        }
        $env:PATH = "$nugetDir;$env:PATH"
    }

    flutter pub get
    flutter analyze
    if (-not $SkipTests) {
        flutter test
    }
    flutter build windows --release

    $source = Join-Path $root "build\windows\x64\runner\Release"
    $target = Join-Path $root "dist\StrmAction-Windows"
    if (Test-Path $target) {
        Remove-Item -Recurse -Force $target
    }
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Copy-Item $source $target -Recurse

    $oldExe = Join-Path $target "strmaction_desktop.exe"
    $newExe = Join-Path $target "StrmAction.exe"
    if (Test-Path $oldExe) {
        Move-Item $oldExe $newExe
    }

    $zip = Join-Path $root "dist\StrmAction-Windows.zip"
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Compress-Archive -Path $target -DestinationPath $zip

    Write-Host ""
    Write-Host "构建完成：$newExe"
    Write-Host "压缩包：$zip"
    Write-Host "目标机需要 WebView2 Runtime（Windows 10/11 通常已自带）。"
} finally {
    Pop-Location
}
