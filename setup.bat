@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===== AI HOT 公众号助手 - 初始化 =====

if not exist venv\Scripts\python.exe (
    echo [1/5] 创建虚拟环境...
) else (
    echo [1/5] 虚拟环境已存在
)

echo [2/5] 安装依赖...
venv\Scripts\pip install -r requirements.txt

echo [3/5] 安装 Playwright 浏览器...
venv\Scripts\python -m playwright install chromium

echo [4/5] 修复 wechatsogou 兼容性...
venv\Scripts\python -c "
import wechatsogou.filecache as fc
with open(fc.__file__, 'r') as f:
    src = f.read()
if 'cachelib' not in src:
    src = src.replace(
        'from werkzeug.contrib.cache import FileSystemCache',
        'try:\n    from werkzeug.contrib.cache import FileSystemCache\nexcept ImportError:\n    from cachelib.file import FileSystemCache'
    )
    with open(fc.__file__, 'w') as f:
        f.write(src)
    print('  [OK] wechatsogou 兼容补丁已应用')
else:
    print('  [OK] wechatsogou 已兼容')
"

echo [5/5] 检查环境配置...
if not exist .env (
    echo DEEPSEEK_API_KEY=sk-your-key-here > .env
    echo deepseek_base_url=https://api.deepseek.com >> .env
    echo.
    echo ⚠ 已创建 .env 模板文件，请编辑填入你的 DeepSeek API Key
)

echo.
echo ✔ 初始化完成!
echo.
echo 运行: venv\Scripts\python cli.py status
echo 启动: run-server.bat
pause
