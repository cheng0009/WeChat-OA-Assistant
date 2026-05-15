@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Activate virtual environment and start server
echo [启动] 激活虚拟环境...
call venv\Scripts\activate.bat

if errorlevel 1 (
    echo [错误] 无法激活虚拟环境，请确保 venv 目录存在
    echo         运行: python -m venv venv
    echo         然后: pip install -r requirements.txt
    pause
    exit /b 1
)

echo [启动] 虚拟环境已激活，启动服务...
"%~dp0venv\Scripts\python.exe" run.py

if errorlevel 1 (
    echo [错误] 服务异常退出，请检查日志
    pause
)