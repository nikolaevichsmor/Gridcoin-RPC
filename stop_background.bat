@echo off
echo Stopping Gridcoin Discord RPC daemon...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host 'Stopped PID' $_.ProcessId }"
echo Done.
