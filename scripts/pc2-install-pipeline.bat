@echo off
REM ============================================================
REM PC2 Setup — registruje Creative Intelligence Weekly Pipeline
REM Spust JEDNOU na PC2: pravym klikem → Spustit jako spravce
REM ============================================================

echo [setup] Registruji FermatoCreativeIntelligence task...

schtasks /delete /tn "FermatoCreativeIntelligence" /f >nul 2>&1

schtasks /create ^
    /tn "FermatoCreativeIntelligence" ^
    /tr "\"%~dp0weekly_pipeline.bat\"" ^
    /sc weekly ^
    /d MON ^
    /st 07:13 ^
    /ru "%USERNAME%" ^
    /rl HIGHEST ^
    /f

if %ERRORLEVEL% equ 0 (
    echo [setup] Task zaregistrovan uspesne!
    echo [setup] Bezi kazde pondeli v 7:13.
    echo [setup] Kontrola: schtasks /query /tn "FermatoCreativeIntelligence"
) else (
    echo [setup] CHYBA: Registrace selhala. Spust jako administrator.
)

pause
