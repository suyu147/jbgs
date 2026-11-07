@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1"
if errorlevel 1 (
  echo.
  echo 启动失败，请检查应用数据\logs 下的日志和部署说明。
  pause
  exit /b 1
)
start "" "http://127.0.0.1:5175/"
