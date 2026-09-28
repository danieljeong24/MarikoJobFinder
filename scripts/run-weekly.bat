@echo off
rem Weekly job-watch run for Windows Task Scheduler (see README).
cd /d "%~dp0.."
"%USERPROFILE%\.local\bin\uv.exe" run job-watch run --email >> job-watch.log 2>&1
