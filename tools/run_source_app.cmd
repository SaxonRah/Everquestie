@echo off
setlocal
py "%~dp0..\EverQuestie.py" %*
exit /b %ERRORLEVEL%
