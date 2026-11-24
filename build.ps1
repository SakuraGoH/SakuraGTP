<#
.SYNOPSIS
    构建 SakuraGTP 发布包。

.DESCRIPTION
    默认构建「便携版」（PyInstaller --onedir）：解压即用、双击启动，
    不依赖 %TEMP%，在临时目录受限的机器上也能运行。

    加上 -OneFile 可构建单文件版（onefile）。注意：onefile 启动时要把自身
    解压到临时目录，个别机器上会报 "Could not create temporary directory!"，
    此时请改用默认的便携版。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build.ps1
    powershell -ExecutionPolicy Bypass -File build.ps1 -Sign
    powershell -ExecutionPolicy Bypass -File build.ps1 -OneFile -Sign
#>
param(
    [string]$Version = "1.6.5",
    [string]$Python = "python",
    [switch]$OneFile,
    [switch]$Sign
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$name = "SakuraGTP-v$Version"
$common = @(
    "--noconfirm", "--clean", "--windowed",
    "--name", $name,
    "--icon", "sakura/resources/sakura.ico",
    "--add-data", "sakura/resources/sakura.ico;.",
    "--add-data", "sakura/resources/SakuraGTP HTTP API 文档.md;.",
    "--hidden-import", "PyQt5", "--hidden-import", "PIL", "--hidden-import", "paramiko"
)

if ($OneFile) {
    Write-Host "构建单文件版 $name ..."
    & $Python -m PyInstaller @common --onefile --runtime-tmpdir "%LOCALAPPDATA%\SakuraGTP\runtime" main.py
    $exe = Join-Path $PSScriptRoot "dist\$name.exe"
} else {
    Write-Host "构建便携版 $name ..."
    & $Python -m PyInstaller @common --onedir --distpath "dist\portable" --workpath "build\portable" main.py
    $exe = Join-Path $PSScriptRoot "dist\portable\$name\$name.exe"
}

if (-not (Test-Path $exe)) { throw "构建失败：$exe 不存在" }
Write-Host "输出: $exe"

if ($Sign) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "tools\sign_release.ps1") -Exe $exe
}
Write-Host "完成"
