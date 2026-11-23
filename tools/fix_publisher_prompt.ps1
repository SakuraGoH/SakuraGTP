<#
.SYNOPSIS
    一键处理「发布者未知」提示：解除文件锁定 + 安装信任证书 + 校验签名。

.DESCRIPTION
    适用于把 SakuraGTP 的 exe 拷贝/下载到本机后，双击时出现
    「未知发布者」或「Windows 已保护你的电脑」的情况。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\fix_publisher_prompt.ps1
    powershell -ExecutionPolicy Bypass -File tools\fix_publisher_prompt.ps1 -Exe "D:\Tools\SakuraGTP-v1.6.3.exe"
#>
param(
    [string]$Exe = ""
)

$ErrorActionPreference = "Continue"

if (-not $Exe) {
    $candidate = Get-ChildItem -Path (Join-Path $PSScriptRoot "..\dist") -Filter "SakuraGTP-*.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($candidate) { $Exe = $candidate.FullName }
}

if ($Exe) {
    $Exe = (Resolve-Path $Exe).Path
    Write-Host "目标 exe: $Exe"
    # 1) 去掉「来自 Internet」的标记（Zone.Identifier）
    try { Unblock-File -Path $Exe; Write-Host "已解除文件锁定" } catch { Write-Warning "解除锁定失败: $($_.Exception.Message)" }
} else {
    Write-Warning "没有指定 exe，也未在 dist 下找到 SakuraGTP-*.exe；只安装证书。"
}

# 2) 安装信任证书（当前用户）
& (Join-Path $PSScriptRoot "install_cert.ps1")

# 3) 校验签名
if ($Exe) {
    $sig = Get-AuthenticodeSignature $Exe
    Write-Host "签名状态: $($sig.Status) - $($sig.StatusMessage)"
    if ($sig.SignerCertificate) {
        Write-Host "发布者: $($sig.SignerCertificate.Subject)"
    } else {
        Write-Warning "该 exe 未签名。请用 tools\sign_release.ps1 重新签名后再分发。"
    }
}
