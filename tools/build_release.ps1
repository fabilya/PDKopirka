<#
.SYNOPSIS
    Полная сборка релиза PDKopirka: exe, полный установщик и облегчённый пакет обновления.

.DESCRIPTION
    Делает три шага и печатает итоговые пути и SHA-256:

      1. PyInstaller  -> dist\PDKopirka\PDKopirka.exe
      2. ISCC         -> installer_output\PDKopirka_Setup_<версия>.exe
                         (полный, со встроенным LibreOffice из vendor\libreoffice)
      3. ISCC /DNoLO
                      -> installer_output\PDKopirka_Setup_<версия>_Update.exe
                         (облегчённый: только файлы программы, для автообновления
                          на машинах, где LibreOffice уже установлен)

    Версия берётся из version.txt. Перед шагом 2 нужна папка vendor\libreoffice —
    её готовит tools\fetch_libreoffice.ps1.

.EXAMPLE
    pwsh -File tools\build_release.ps1
    pwsh -File tools\build_release.ps1 -SkipExe
#>

param(
    [switch]$SkipExe,
    [string]$Iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

$version = (Get-Content "version.txt" -Raw).Trim()
if (-not $version) { throw "Не удалось прочитать version.txt" }
Write-Host "Версия: $version" -ForegroundColor Cyan

if (-not (Test-Path $Iscc)) { throw "Не найден ISCC.exe: $Iscc" }

if (-not $SkipExe) {
    Write-Host "Сборка exe (PyInstaller)..." -ForegroundColor Cyan
    & python -m PyInstaller PDKopirka.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }
}

$hasLO = Test-Path "vendor\libreoffice\program\soffice.com"
if (-not $hasLO) {
    Write-Warning "Нет vendor\libreoffice — полный установщик соберётся без встроенного LibreOffice."
}

Write-Host "Полный установщик..." -ForegroundColor Cyan
& $Iscc PDKopirka.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC (полный) завершился с ошибкой" }

Write-Host "Облегчённый пакет обновления..." -ForegroundColor Cyan
& $Iscc "/DNoLO" "/DOutputSuffix=_Update" PDKopirka.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC (обновление) завершился с ошибкой" }

$artifacts = @(
    "installer_output\PDKopirka_Setup_$version.exe",
    "installer_output\PDKopirka_Setup_${version}_Update.exe"
) | ForEach-Object {
    if (-not (Test-Path $_)) { throw "Не найден результат сборки: $_" }
    $item = Get-Item $_
    [pscustomobject]@{
        Файл   = $item.Name
        МБ     = [math]::Round($item.Length / 1MB, 1)
        SHA256 = (Get-FileHash $item.FullName -Algorithm SHA256).Hash
    }
}

Write-Host ""
$artifacts | Format-Table -AutoSize | Out-String -Width 200 | Write-Host

Write-Host "Не забудьте:" -ForegroundColor Yellow
Write-Host "  1) подписать артефакты:  pwsh -File tools\sign.ps1"
Write-Host "  2) загрузить оба файла в GitHub Release $version"
Write-Host "  3) в latest.json проверить version / url / url_lite"

Pop-Location
