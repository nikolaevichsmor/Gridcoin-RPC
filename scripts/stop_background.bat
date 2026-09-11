@echo off
echo Stopping Gridcoin Discord RPC daemon...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_background.ps1"
echo Done.
