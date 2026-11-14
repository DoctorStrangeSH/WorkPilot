@echo off
start "Malenia Browser Setup" powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0setup_browser_bridge.ps1"
