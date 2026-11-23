<#
.SYNOPSIS
    生成 SakuraGTP 的代码签名证书（自签名），并导出 .cer / .pfx。

.DESCRIPTION
    只在本机执行一次即可。证书会装在当前用户的「个人」存储里，
    tools\sign_release.ps1 通过主题 CN=SakuraGTP 找到它。
    导出的：
      certs\SakuraGTP-CodeSigning.cer  —— 公钥证书，给其他机器安装信任
      certs\SakuraGTP-CodeSigning.pfx  —— 含私钥，仅限本机保存，禁止提交/外发

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\make_signing_cert.ps1
#>
param(
    [string]$Subject = "CN=SakuraGTP, O=SakuraGTP Project, C=CN",
    [int]$Years = 10,
    [string]$PfxPassword = "SakuraGTP-Signing-2026",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$certDir = Join-Path $PSScriptRoot "..\certs"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

$existing = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -eq $Subject } | Select-Object -First 1
if ($existing -and -not $Force) {
    $cert = $existing
    Write-Host "已存在证书，直接复用: $($cert.Thumbprint)"
} else {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Subject `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears($Years) `
        -KeyUsage DigitalSignature `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3")
    Write-Host "已生成证书: $($cert.Thumbprint)"
}

$cerPath = Join-Path $certDir "SakuraGTP-CodeSigning.cer"
$pfxPath = Join-Path $certDir "SakuraGTP-CodeSigning.pfx"
Export-Certificate -Cert $cert -FilePath $cerPath -Type CERT | Out-Null
$secure = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $secure | Out-Null

Write-Host "公钥证书: $((Resolve-Path $cerPath).Path)"
Write-Host "私钥备份: $((Resolve-Path $pfxPath).Path)（请妥善保管，不要提交到版本库）"
Write-Host ""
Write-Host "下一步："
Write-Host "  1) 给发布包签名:   powershell -ExecutionPolicy Bypass -File tools\sign_release.ps1"
Write-Host "  2) 在本机装信任:   powershell -ExecutionPolicy Bypass -File tools\install_cert.ps1"
exit 0
