<#
.SYNOPSIS
    用 SakuraGTP 的代码签名证书给发布用的 exe 签名，并校验结果。

.DESCRIPTION
    证书默认从当前用户的「个人」证书存储里按主题 CN=SakuraGTP 查找。
    如果证书不存在，请先运行 tools\make_signing_cert.ps1（只在本机生成一次）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\sign_release.ps1
    powershell -ExecutionPolicy Bypass -File tools\sign_release.ps1 -Exe dist\SakuraGTP-v1.6.3.exe
#>
param(
    [string]$Exe = "",
    [string]$Subject = "CN=SakuraGTP",
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not $Exe) {
    $candidate = Get-ChildItem -Path (Join-Path $PSScriptRoot "..\dist") -Filter "SakuraGTP-*.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $candidate) { throw "dist 目录里没有找到 SakuraGTP-*.exe，请先打包或指定 -Exe" }
    $Exe = $candidate.FullName
}
$Exe = (Resolve-Path $Exe).Path

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -like "*$Subject*" } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) {
    throw "没有找到代码签名证书（$Subject）。请先运行 tools\make_signing_cert.ps1 生成，或导入已有的 .pfx。"
}

Write-Host "证书: $($cert.Subject)"
Write-Host "指纹: $($cert.Thumbprint)"
Write-Host "目标: $Exe"

$sig = $null
try {
    $sig = Set-AuthenticodeSignature -FilePath $Exe -Certificate $cert -HashAlgorithm SHA256 `
        -TimestampServer $TimestampServer -ErrorAction Stop
    Write-Host "已签名（含时间戳）"
} catch {
    Write-Warning "时间戳服务器不可用（$($_.Exception.Message)），改为不带时间戳签名"
    $sig = Set-AuthenticodeSignature -FilePath $Exe -Certificate $cert -HashAlgorithm SHA256
    Write-Host "已签名（无时间戳）"
}

# 去掉「来自 Internet」的标记，避免打开时出现安全警告
Unblock-File -Path $Exe

$check = Get-AuthenticodeSignature $Exe
Write-Host "校验结果: $($check.Status) - $($check.StatusMessage)"
if ($check.Status -ne "Valid") {
    Write-Warning "签名链未通过校验。请在目标机器上运行 tools\install_cert.ps1 安装信任证书。"
    exit 1
}
exit 0
