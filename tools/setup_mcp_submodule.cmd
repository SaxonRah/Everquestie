@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_mcp_submodule.ps1" %*
exit /b %ERRORLEVEL%
