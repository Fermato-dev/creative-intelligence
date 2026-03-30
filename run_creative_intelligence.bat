@echo off
REM Fermato Creative Intelligence — Weekly Runner
REM Scheduled via Windows Task Scheduler (1x tydne, napr. pondeli 7:03 CET)
REM Stahne Meta data za 7 dni, posle tydenni Pumble report, spusti AI analyzu

cd /d "C:\Users\rstra\Chief_of_Staff\Chief-of-Staff"

REM Load env vars from .env (each line: KEY=VALUE)
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "%%a=%%b"
)

REM Run weekly pipeline with vision analysis
python projects\cmo\rust-a-akvizice\scripts\creative_weekly_runner.py >> projects\cmo\rust-a-akvizice\outputs\cron.log 2>&1

echo [%date% %time%] Creative Intelligence Weekly completed >> projects\cmo\rust-a-akvizice\outputs\cron.log
