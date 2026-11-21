# 打包脚本：生成 dist/FoxGTP-Py.exe
# 用法（PowerShell）：  .\build.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$python = "C:\Users\10632\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "== 生成图标 =="
& $python tools\make_icon.py

Write-Host "== 单元测试 =="
& $python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw "单元测试失败，停止打包" }

Write-Host "== PyInstaller =="
& $python -m PyInstaller --noconfirm --clean FoxGTP-Py.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }

$exe = Join-Path $here "dist\FoxGTP-Py.exe"
if (-not (Test-Path $exe)) { throw "没有生成 $exe" }
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "== 完成: $exe ($size MB) =="
