<#
.SYNOPSIS
    Готовит встроенный портативный LibreOffice 7.3.7.2 для установщика PDKopirka.

.DESCRIPTION
    Почему именно 7.3.7.2 и именно портативно:

    * DOCX — это описание вёрстки, итог зависит от конвертера. Штамп ГОСТ в этих
      документах нарисован повёрнутыми текстовыми блоками внутри группы фигур
      в колонтитуле. Word их рендерит правильно, а LibreOffice начиная с 7.4 —
      нет (tdf#149395, дубль tdf#164868), текст штампа рассыпается по буквам.
      7.3.x — последняя ветка, где поворот ещё работал.
    * MSI распаковывается административной установкой (msiexec /a) в папку
      vendor\libreoffice. Прав администратора не нужно, в систему ничего не
      ставится, версия зафиксирована и одинакова на всех машинах.

    Скрипт запускается один раз на сборочной машине, до сборки установщика.
    Папка vendor\libreoffice в git не попадает (см. .gitignore).

.EXAMPLE
    pwsh -File tools\fetch_libreoffice.ps1
#>

param(
    [string]$Version = "7.3.7.2",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$vendorDir = Join-Path $repoRoot "vendor\libreoffice"
$sofficeRel = "program\soffice.exe"

if ((Test-Path (Join-Path $vendorDir $sofficeRel)) -and -not $Force) {
    Write-Host "LibreOffice уже подготовлен: $vendorDir" -ForegroundColor Green
    & (Join-Path $vendorDir $sofficeRel) --version
    exit 0
}

$url = "https://downloadarchive.documentfoundation.org/libreoffice/old/$Version/win/x86_64/LibreOffice_${Version}_Win_x64.msi"
$msiPath = Join-Path $env:TEMP "LibreOffice_${Version}_Win_x64.msi"
$extractDir = Join-Path $env:TEMP "PDKopirka_LO_$Version"

if (-not (Test-Path $msiPath)) {
    Write-Host "Скачивание $url" -ForegroundColor Cyan
    Write-Host "(около 330 МБ, один раз)" -ForegroundColor DarkGray
    Invoke-WebRequest -Uri $url -OutFile $msiPath -UseBasicParsing
    if (-not (Test-Path $msiPath)) { throw "Не удалось скачать $url" }
}
else {
    Write-Host "Использую уже скачанный архив: $msiPath" -ForegroundColor DarkGray
}

if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null

Write-Host "Распаковка MSI (административная установка в папку)..." -ForegroundColor Cyan
$proc = Start-Process msiexec.exe -ArgumentList @(
    "/a", "`"$msiPath`"", "/qn", "TARGETDIR=`"$extractDir`""
) -Wait -PassThru
if ($proc.ExitCode -ne 0) { throw "msiexec /a завершился с кодом $($proc.ExitCode)" }

$soffice = Get-ChildItem -Path $extractDir -Recurse -Filter soffice.exe |
    Select-Object -First 1
if (-not $soffice) { throw "soffice.exe не найден в распакованном архиве" }

$programDir = $soffice.Directory
$loRoot = $programDir.Parent

if (Test-Path $vendorDir) { Remove-Item $vendorDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Split-Path $vendorDir) | Out-Null
Copy-Item -Path $loRoot.FullName -Destination $vendorDir -Recurse
Remove-Item $extractDir -Recurse -Force

# Чистим лишнее: словари всех языков кроме русского и английского, справку,
# readme и ресурсы интерфейса. Для headless-конвертации они не нужны, а вес
# встроенного LibreOffice уменьшается почти вдвое (1.4 ГБ -> ~750 МБ).
$keepDicts = @("dict-ru", "dict-en")
$dictDir = Join-Path $vendorDir "share\extensions"
if (Test-Path $dictDir) {
    Get-ChildItem $dictDir -Directory -Filter "dict-*" -ErrorAction SilentlyContinue |
        Where-Object { $keepDicts -notcontains $_.Name } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
foreach ($extra in @("help", "readmes")) {
    $path = Join-Path $vendorDir $extra
    if (Test-Path $path) { Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue }
}
# program\resource — иконки и картинки интерфейса LibreOffice. Конвертация идёт
# в headless-режиме и их не использует (проверено на документах с картинками).
$uiRes = Join-Path $vendorDir "program\resource"
if (Test-Path $uiRes) { Remove-Item $uiRes -Recurse -Force -ErrorAction SilentlyContinue }
Get-ChildItem $vendorDir -Filter "*.msi" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

$target = Join-Path $vendorDir $sofficeRel
if (-not (Test-Path $target)) { throw "После копирования не найден $target" }

Write-Host "Готово: $target" -ForegroundColor Green
& $target --version

$sizeMb = [math]::Round(
    ((Get-ChildItem $vendorDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 0)
Write-Host "Размер папки: $sizeMb МБ (войдёт в установщик)" -ForegroundColor DarkGray
