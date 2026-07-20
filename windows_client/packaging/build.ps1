# Default-Build: --onedir via sprichblitz.spec
#
# Voraussetzungen (siehe BUILD.md):
#   - Windows 10/11
#   - Python 3.12 (NICHT 3.13/3.14 wegen pinned deps)
#   - uv 0.11.29
#   - uv sync --frozen --extra build
#
# Ergebnis: dist\Sprichblitz\Sprichblitz.exe (+ Lib-Verzeichnisse)

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Split-Path -Parent $here
function Stop-RunningSprichblitz {
    # PyInstaller --noconfirm scheitert mit PermissionError, wenn die
    # alte .exe noch läuft (numpy.dll & co. in Memory).
    $proc = Get-Process -Name "Sprichblitz" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "==> Sprichblitz läuft noch – wird beendet" -ForegroundColor Yellow
        Stop-Process -Name "Sprichblitz" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
}

Push-Location $project
try {
    Stop-RunningSprichblitz

    Write-Host "==> PyInstaller --onedir (Spec: packaging\sprichblitz.spec)" -ForegroundColor Cyan
    uv run pyinstaller "packaging\sprichblitz.spec" --noconfirm --clean
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "==> Build fehlgeschlagen (pyinstaller exit $LASTEXITCODE)" -ForegroundColor Red
        Write-Host "    Mögliche Ursachen:" -ForegroundColor Yellow
        Write-Host "    - Eine alte Sprichblitz-Instanz hält dist\Sprichblitz\* offen"
        Write-Host "    - Defender / Indexierungsdienst hält Dateien offen"
        Write-Host "    - Manueller Fix: dist\ und build\ löschen, ggf. Reboot"
        throw "pyinstaller exit $LASTEXITCODE"
    }
    Write-Host ""
    Write-Host "==> Fertig. Build liegt in dist\Sprichblitz\" -ForegroundColor Green
    Write-Host "    Start: dist\Sprichblitz\Sprichblitz.exe"
} finally {
    Pop-Location
}
