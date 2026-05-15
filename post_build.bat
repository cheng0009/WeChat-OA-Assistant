@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ===== WeChat OA 构建后处理 (onefile) =====

set DIST_DIR=dist
set CHROMIUM_SRC=%USERPROFILE%\AppData\Local\ms-playwright\chromium-1169\chrome-win
set CHROMIUM_DST=%DIST_DIR%\chrome-win

REM ---- 1. 复制 .env 模板到 exe 同级 ----
echo [1/3] 复制 .env 模板...
if exist .env (
    copy /Y .env "%DIST_DIR%\.env" >nul
    echo   [OK] .env 已复制
) else (
    echo   [SKIP] .env 不存在，请手动创建
)

REM ---- 2. 复制 Chromium 浏览器 ----
echo [2/3] 复制 Chromium 浏览器...
if exist "%CHROMIUM_SRC%" (
    if exist "%CHROMIUM_DST%" rmdir /s /q "%CHROMIUM_DST%"
    mkdir "%CHROMIUM_DST%" 2>nul
    robocopy "%CHROMIUM_SRC%" "%CHROMIUM_DST%" /E /XD Dictionaries MEIPreload PrivacySandboxAttestationsPreloaded /NFL /NDL /NJH /NJS /nc /ns /np >nul
    echo   [OK] Chromium 已复制到 %CHROMIUM_DST%
) else (
    echo   [WARN] Chromium 未安装，路径: %CHROMIUM_SRC%
    echo   请先运行: python -m playwright install chromium
)

REM ---- 3. 确认产物 ----
echo [3/3] 确认产物...
if exist "%DIST_DIR%\WeChatOA.exe" (
    for %%f in ("%DIST_DIR%\WeChatOA.exe") do echo   WeChatOA.exe: %%~zf 字节
) else (
    echo   [ERROR] WeChatOA.exe 未找到！
)

REM 计算总大小
set TOTAL_SIZE=0
for /f "tokens=*" %%i in ('dir /s /a "%DIST_DIR%" 2^>nul ^| findstr "字节"') do set TOTAL_SIZE=%%i
echo   目录总大小: %TOTAL_SIZE%

echo.
echo ===== 完成 =====
echo 产物路径: %CD%\%DIST_DIR%
echo 运行: %DIST_DIR%\WeChatOA.exe
echo.
echo 分发说明：
echo   - 完整的发布包需要包含: WeChatOA.exe + chrome-win/ + .env + license.dat
echo   - 升级包只需替换 WeChatOA.exe
pause
