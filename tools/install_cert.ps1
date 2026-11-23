<#
.SYNOPSIS
    在目标机器上安装 SakuraGTP 的代码签名证书，让 Windows 认得「发布者」。

.DESCRIPTION
    把 certs\SakuraGTP-CodeSigning.cer 导入：
      * 当前用户的「受信任的根证书颁发机构」
      * 当前用户的「受信任的发布者」
    有管理员权限时同时导入本机存储（对所有用户生效）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\install_cert.ps1
    powershell -ExecutionPolicy Bypass -File tools\install_cert.ps1 -Machine
#>
param(
    [string]$Cer = "",
    [switch]$Machine
)

$ErrorActionPreference = "Stop"

if (-not $Cer) {
    $Cer = Join-Path $PSScriptRoot "..\certs\SakuraGTP-CodeSigning.cer"
}
$Cer = (Resolve-Path $Cer).Path

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Host "证书: $Cer"
Write-Host "管理员: $isAdmin"

# 当前用户：无需管理员，静默导入
& certutil -user -addstore -f Root $Cer | Out-Null
& certutil -user -addstore -f TrustedPublisher $Cer | Out-Null
Write-Host "已导入当前用户（Root / TrustedPublisher）"

if ($Machine -or $isAdmin) {
    if (-not $isAdmin) {
        Write-Warning "指定了 -Machine 但不是管理员，跳过本机存储导入"
    } else {
        & certutil -addstore -f Root $Cer | Out-Null
        & certutil -addstore -f TrustedPublisher $Cer | Out-Null
        Write-Host "已导入本机存储（Root / TrustedPublisher）"
    }
}

# 验证
$thumb = (New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $Cer).Thumbprint
$root = Get-ChildItem Cert:\CurrentUser\Root | Where-Object { $_.Thumbprint -eq $thumb }
if ($root) {
    Write-Host "验证通过：证书已在本机受信任根存储中（$thumb）"
    exit 0
}
Write-Warning "证书未出现在受信任根存储中，请重试或手动双击 .cer 安装"
exit 1
