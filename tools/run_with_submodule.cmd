@echo off
setlocal
if not exist "%~dp0..\third_party\everquest1-mcp\package.json" (
  call "%~dp0setup_mcp_submodule.cmd"
  if errorlevel 1 exit /b %errorlevel%
)
py "%~dp0..\EverQuestie.py"
