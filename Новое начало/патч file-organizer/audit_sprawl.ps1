#Requires -Version 5.1
<#
.SYNOPSIS
    Аудит расползания проекта: одни и те же материалы в разных корнях и средах.
    Только чтение. Ничего не перемещает, не переименовывает и не удаляет.

.DESCRIPTION
    Дополняет audit_duplicates.ps1: тот ищет дубли ВНУТРИ одного корня,
    этот — МЕЖДУ корнями и средами (рабочий стол, загрузки, клоны репозиториев,
    синхронизируемые облачные папки, распакованные архивы).

    Выдаёт «светофор»:
      КРАСНЫЙ  — расползание: один и тот же файл лежит в 2+ корнях;
                 чувствительные материалы в синхронизируемой/публикуемой папке.
      ЖЁЛТЫЙ   — разошедшиеся версии (имя совпадает, содержимое разное);
                 следы среды (клон репозитория, «(1)»-копии из браузера,
                 распакованные архивы, временные файлы).
      ЗЕЛЁНЫЙ  — чисто.

.PARAMETER Roots
    Один или несколько корней для сравнения.

.PARAMETER SensitiveMarker
    Имя файла-маркера, помечающего папку как чувствительную (по умолчанию
    .sensitive). Достаточно положить пустой файл с таким именем в корень проекта.

.PARAMETER CsvPath
    Необязательный путь для выгрузки подробной таблицы.

.EXAMPLE
    .\audit_sprawl.ps1 -Roots "$env:USERPROFILE\Desktop","$env:USERPROFILE\Downloads"

.EXAMPLE
    .\audit_sprawl.ps1 -Roots "D:\Проекты","$env:USERPROFILE\Desktop" -CsvPath .\sprawl.csv
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]]$Roots,

    [string]$SensitiveMarker = '.sensitive',

    [string]$CsvPath,

    [int]$MaxFileMB = 200
)

$ErrorActionPreference = 'Stop'

# Пути, попадание в которые означает синхронизацию или публикацию содержимого
$SyncPatterns = @('OneDrive', 'Dropbox', 'Google Drive', 'GoogleDrive',
                  'Яндекс.Диск', 'YandexDisk', 'iCloudDrive', 'Creative Cloud Files')

function Get-LongPath([string]$p) {
    if ($p -like '\\?\*') { return $p }
    if ($p -like '\\*')   { return '\\?\UNC\' + $p.Substring(2) }
    return '\\?\' + $p
}

function Test-Skip([string]$rel) {
    return ($rel -match '(^|\\)(\.git|node_modules|__pycache__|\.venv|venv|obj|bin)(\\|$)')
}

Write-Host ''
Write-Host '=== АУДИТ РАСПОЛЗАНИЯ (только чтение) ===' -ForegroundColor Cyan

$inventory = New-Object System.Collections.Generic.List[object]
$envNotes  = New-Object System.Collections.Generic.List[object]

foreach ($root in $Roots) {
    if (-not (Test-Path -LiteralPath $root)) {
        Write-Warning "Корень не найден, пропущен: $root"
        continue
    }
    $resolved = (Resolve-Path -LiteralPath $root).Path
    Write-Host "  сканирую: $resolved" -ForegroundColor DarkGray

    # --- следы среды на уровне папок ---
    Get-ChildItem -LiteralPath (Get-LongPath $resolved) -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            $d = $_
            if (Test-Path -LiteralPath (Join-Path $d.FullName '.git')) {
                $remote = ''
                try {
                    $cfg = Get-Content -LiteralPath (Join-Path $d.FullName '.git\config') -ErrorAction Stop
                    $remote = ($cfg | Select-String -Pattern 'url\s*=\s*(.+)' |
                               Select-Object -First 1).Matches.Groups[1].Value.Trim()
                } catch { }
                $envNotes.Add([pscustomobject]@{
                    Тип = 'Клон репозитория'; Путь = $d.FullName; Деталь = $remote
                })
            }
            if ($d.Name -match '-(main|master|dev|claude)[-\w]*$' -and $d.Name -match '^\w+-') {
                $envNotes.Add([pscustomobject]@{
                    Тип = 'Похоже на распакованный архив ветки'; Путь = $d.FullName; Деталь = ''
                })
            }
        }

    # --- инвентаризация файлов ---
    Get-ChildItem -LiteralPath (Get-LongPath $resolved) -File -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            $f = $_
            $rel = $f.FullName -replace [regex]::Escape($resolved), '' -replace '^\\', ''
            if (Test-Skip $rel) { return }
            if ($f.Length -gt ($MaxFileMB * 1MB)) { $hash = 'ПРОПУЩЕН-РАЗМЕР' }
            else {
                try { $hash = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash }
                catch { $hash = 'ОШИБКА-ЧТЕНИЯ' }
            }
            $inventory.Add([pscustomobject]@{
                Корень       = $resolved
                Имя          = $f.Name
                ОтносПуть    = $rel
                ПолныйПуть   = $f.FullName
                Размер       = $f.Length
                Изменён      = $f.LastWriteTime
                SHA256       = $hash
            })

            if ($f.Name -match '\s\(\d+\)\.[^.]+$') {
                $envNotes.Add([pscustomobject]@{
                    Тип = 'Копия из браузера/чата'; Путь = $f.FullName; Деталь = ''
                })
            }
            if ($f.Extension -in '.tmp', '.crdownload', '.part' -or $f.Name -like '~$*') {
                $envNotes.Add([pscustomobject]@{
                    Тип = 'Временный/служебный файл'; Путь = $f.FullName; Деталь = ''
                })
            }
        }
}

if ($inventory.Count -eq 0) { Write-Host 'Файлов не найдено.' -ForegroundColor Yellow; return }

# --- КРАСНЫЙ: один файл в нескольких корнях ---
$sprawl = $inventory |
    Where-Object { $_.SHA256 -notmatch 'ПРОПУЩЕН|ОШИБКА' } |
    Group-Object SHA256 |
    Where-Object { ($_.Group | Select-Object -ExpandProperty Корень -Unique).Count -gt 1 }

# --- ЖЁЛТЫЙ: имя совпадает, содержимое разошлось ---
$diverged = $inventory |
    Where-Object { $_.SHA256 -notmatch 'ПРОПУЩЕН|ОШИБКА' } |
    Group-Object Имя |
    Where-Object {
        ($_.Group | Select-Object -ExpandProperty SHA256 -Unique).Count -gt 1 -and
        ($_.Group | Select-Object -ExpandProperty Корень -Unique).Count -gt 1
    }

# --- КРАСНЫЙ: чувствительное в синхронизируемом пути ---
$sensitiveRoots = $inventory |
    Where-Object { $_.Имя -eq $SensitiveMarker } |
    ForEach-Object { Split-Path -Parent $_.ПолныйПуть } |
    Select-Object -Unique

$exposed = foreach ($sr in $sensitiveRoots) {
    $hit = $SyncPatterns | Where-Object { $sr -like "*$_*" }
    if ($hit) { [pscustomobject]@{ Папка = $sr; Причина = "синхронизируемый путь ($hit)" } }
    if (Test-Path -LiteralPath (Join-Path $sr '.git')) {
        [pscustomobject]@{ Папка = $sr; Причина = 'внутри клона репозитория (уходит на сервер)' }
    }
}

# ================= ОТЧЁТ =================
Write-Host ''
Write-Host ('Просканировано файлов: {0}, корней: {1}' -f $inventory.Count, $Roots.Count)
Write-Host ''

$red = $false

if ($exposed) {
    $red = $true
    Write-Host 'КРАСНЫЙ — чувствительные материалы в среде, которая их распространяет:' -ForegroundColor Red
    $exposed | ForEach-Object { Write-Host ("  • {0}`n    причина: {1}" -f $_.Папка, $_.Причина) }
    Write-Host ''
}

if ($sprawl) {
    $red = $true
    Write-Host ('КРАСНЫЙ — расползание: {0} файл(ов) лежат в нескольких корнях' -f $sprawl.Count) -ForegroundColor Red
    $sprawl | Select-Object -First 15 | ForEach-Object {
        $g = $_.Group | Sort-Object Изменён -Descending
        Write-Host ("  • {0}" -f $g[0].Имя)
        $g | ForEach-Object { Write-Host ("      {0}   [{1:yyyy-MM-dd}]" -f $_.ПолныйПуть, $_.Изменён) -ForegroundColor DarkGray }
    }
    if ($sprawl.Count -gt 15) { Write-Host ('      … и ещё {0}' -f ($sprawl.Count - 15)) -ForegroundColor DarkGray }
    Write-Host ''
}

if ($diverged) {
    Write-Host ('ЖЁЛТЫЙ — разошедшиеся версии: {0} имя(имён) с разным содержимым в разных корнях' -f $diverged.Count) -ForegroundColor Yellow
    $diverged | Select-Object -First 10 | ForEach-Object {
        Write-Host ("  • {0}" -f $_.Name)
        $_.Group | Sort-Object Изменён -Descending | ForEach-Object {
            Write-Host ("      {0}   [{1:yyyy-MM-dd}, {2} б]" -f $_.ПолныйПуть, $_.Изменён, $_.Размер) -ForegroundColor DarkGray
        }
    }
    Write-Host ''
}

if ($envNotes.Count -gt 0) {
    Write-Host 'ЖЁЛТЫЙ — следы сред и мусор:' -ForegroundColor Yellow
    $envNotes | Group-Object Тип | ForEach-Object {
        Write-Host ("  {0}: {1}" -f $_.Name, $_.Count)
        $_.Group | Select-Object -First 5 | ForEach-Object {
            $d = if ($_.Деталь) { "  <- $($_.Деталь)" } else { '' }
            Write-Host ("      {0}{1}" -f $_.Путь, $d) -ForegroundColor DarkGray
        }
    }
    Write-Host ''
}

if (-not $red -and -not $diverged -and $envNotes.Count -eq 0) {
    Write-Host 'ЗЕЛЁНЫЙ — расползания, разошедшихся версий и следов сред не найдено.' -ForegroundColor Green
    Write-Host ''
}

Write-Host 'Ничего не изменено. Решение по каждому пункту принимает владелец.' -ForegroundColor Cyan

if ($CsvPath) {
    $inventory | Export-Csv -LiteralPath $CsvPath -NoTypeInformation -Encoding UTF8
    Write-Host ("Подробная таблица: {0}" -f $CsvPath)
}
