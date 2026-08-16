@echo off
setlocal
py "%~dp0verify_mcp_builder_source.py" %*
exit /b %ERRORLEVEL%
