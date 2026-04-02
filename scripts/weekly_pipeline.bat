@echo off
cd /d C:\Users\rstra\Chief_of_Staff\Chief-of-Staff\fermato-dev
echo [%date% %time%] Creative Intelligence Weekly Pipeline >> data\pipeline.log

python -m creative_intelligence run --days 7 2>> data\pipeline.log
if errorlevel 1 echo [%date% %time%] ERROR: run failed >> data\pipeline.log

python -m creative_intelligence decompose --days 7 --limit 10 2>> data\pipeline.log
if errorlevel 1 echo [%date% %time%] ERROR: decompose failed >> data\pipeline.log

python -m creative_intelligence recommend 2>> data\pipeline.log
if errorlevel 1 echo [%date% %time%] ERROR: recommend failed >> data\pipeline.log

cd /d C:\Users\rstra\Chief_of_Staff\Chief-of-Staff\fermato-dev
git add data\ 2>> data\pipeline.log
git commit -m "creative-intelligence: %date:~6,4%-%date:~3,2%-%date:~0,2% weekly pipeline" 2>> data\pipeline.log
git push 2>> data\pipeline.log

echo [%date% %time%] Pipeline complete >> data\pipeline.log
