<#
.SYNOPSIS
    Подписывает PDKopirka.exe и установщики код-сертификатом (signtool).

.DESCRIPTION
    Идея была «подписать установщик и программу». Для подписи нужен ЛИЧНЫЙ
    код-сертификат (обычный или EV) — его нельзя сгенерировать скриптом,
    он покупается у удостоверяющего центра. Этот скрипт делает всё остальное:
    находит signtool, проверяет сертификат и подписывает артефакты.

    Без сертификата скрипт ничего не меняет: печатает, что нечем подписывать,
    и завершается успешно — сборка остаётся рабочей (просто SmartScreen будет
    показывать «неизвестный издатель»).

    Способы задать сертификат:
      * в хранилище Windows (рекомендуется для EV/токена):
            $env:PDKO_SIGN_SHA1 = "<отпечаток сертификата>"
        либо  -Thumbprint "<отпечаток>"
      * файл .pfx:
            $env:PDKO_PFX = "C:\certs\pdko.pfx"
            $env:PDKO_PFX_PASSWORD = "пароль"
        либо  -Pfx "C:\certs\pdko.pfx" -PfxPassword "пароль"

.EXAMPLE
    pwsh -File tools\sign.ps1 -Thumbprint "A1B2C3..."
    pwsh -File tools\sign.ps1 -Pfx .\certs\pdko.pfx -PfxPassword (Read-Host -AsSecureString)
#>

param(
    [string]$Thumbprint = $env:PDKO_SIGN_SHA1,
    [string]$Pfx = $env:PDKO_PFX,
    [string]$PfxPassword = $env:PDKO_PFX_PASSWORD,
    [string]$Timestamp = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

function Find-SignTool {
    $candidates = @()
    $kits = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin", "${env:ProgramFiles}\Windows Kits\10\bin")
    foreach ($kit in $kits) {
        if (Test-Path $kit) {
            $candidates += Get-ChildItem $kit -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '\\x64\\' } |
                Sort-Object FullName -Descending |
                Select-Object -ExpandProperty FullName
        }
    }
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    return $candidates | Select-Object -First 1
}

$signtool = Find-SignTool
if (-not $signtool) {
    Write-Warning "signtool.exe не найден. Установите Windows SDK (компонент Signing Tools) — подпись пропущена."
    Pop-Location
    exit 0
}

$usePfx = $Pfx -and (Test-Path $Pfx)
if (-not $usePfx -and -not $Thumbprint) {
    Write-Host "Код-сертификат не задан — подписывать нечем." -ForegroundColor Yellow
    Write-Host "Задайте отпечаток (PDKO_SIGN_SHA1) или .pfx (PDKO_PFX) — см. комментарий в начале файла."
    Write-Host "Сборка остаётся рабочей, но SmartScreen будет показывать «неизвестный издатель»."
    Pop-Location
    exit 0
}

$version = (Get-Content "version.txt" -Raw).Trim()
$targets = @(
    "dist\PDKopirka\PDKopirka.exe",
    "installer_output\PDKopirka_Setup_$version.exe",
    "installer_output\PDKopirka_Setup_${version}_Update.exe"
) | Where-Object { Test-Path $_ }

if (-not $targets) {
    throw "Нечего подписывать: сначала соберите релиз (pwsh -File tools\build_release.ps1)"
}

$argsCommon = @("sign", "/fd", "sha256", "/td", "sha256", "/tr", $Timestamp)
if ($usePfx) {
    $argsCommon += @("/f", (Resolve-Path $Pfx).Path)
    if ($PfxPassword) { $argsCommon += @("/p", $PfxPassword) }
}
else {
    $argsCommon += @("/sha1", $Thumbprint)
}

foreach ($target in $targets) {
    Write-Host "Подпись: $target" -ForegroundColor Cyan
    & $signtool @argsCommon $target
    if ($LASTEXITCODE -ne 0) { throw "signtool вернул ошибку для $target" }
    & $signtool verify /pa /v $target | Select-Object -Last 4
}

Write-Host "Готово: подписаны $($targets.Count) файл(ов)." -ForegroundColor Green
Pop-Location
