@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo  WeChat OA 构建脚本 (onefile)
echo ========================================
echo.

REM ---- Step 1: 生成内嵌密钥 ----
echo [1/3] 生成 _secret.py（内嵌密钥）...
python build_embed_key.py
if %ERRORLEVEL% neq 0 (
    echo [ERROR] 密钥生成失败，终止构建
    pause
    exit /b 1
)
echo.

REM ---- Step 2: 打包 exe ----
echo [2/3] 运行 PyInstaller...
if exist dist rmdir /s /q dist
pyinstaller build.spec
if %ERRORLEVEL% neq 0 (
    echo [ERROR] PyInstaller 打包失败
    pause
    exit /b 1
)
echo.

REM ---- Step 3: 后处理（复制 Chromium 等） ----
echo [3/3] 后处理...
call post_build.bat

echo.
echo ===== 构建完成 =====
pause
