@echo off
setlocal
echo WARNING: run_with_submodule.cmd is a compatibility alias. EverQuestie runtime does not require MCP or Node.js. 1>&2
call "%~dp0run_source_app.cmd" %*
exit /b %ERRORLEVEL%
