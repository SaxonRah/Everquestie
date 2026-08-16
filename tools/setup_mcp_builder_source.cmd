@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_mcp_builder_source.ps1" %*
exit /b %ERRORLEVEL%
