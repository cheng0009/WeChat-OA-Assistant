# WeChat OA Assistant

微信公众号文章自动化发布助手。支持定时抓取 AI 资讯、生成文章、自动发布到微信公众号。

## 功能

- AI 资讯聚合：自动抓取每日 AI 行业动态（基于 AI HOT API）
- 智能写作：调用 DeepSeek API 自动生成公众号文章
- 定时发布：按设定时间自动发布到微信公众号后台
- CLI 工具：支持命令行手动触发抓取、生成、发布操作

## 下载与安装

从 [Releases](https://github.com/cheng0009/WeChat-OA-Assistant/releases) 页面下载以下两个文件：

| 文件 | 说明 |
|------|------|
| `WeChatOA.exe` | 主程序（单文件，无需安装） |
| `chrome-win.zip` | 内置 Chromium 浏览器（约 150 MB，解压到同目录） |

### 文件结构

```
WeChatOA.exe
chrome-win/              # 解压 chrome-win.zip 得到
.env                     # 配置文件（见下方）
license.dat              # 授权文件（联系开发者获取）
```

## 快速开始

### 1. 配置 .env

复制以下内容创建 `.env` 文件（与 exe 同目录）：

```ini
# DeepSeek API 配置
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# AI HOT API 配置
AIHOT_API_BASE=https://aihot.virxact.com
AIHOT_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36

# 应用配置
APP_HOST=0.0.0.0
APP_PORT=8000
SCHEDULE_HOUR=9
SCHEDULE_MINUTE=0
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
```

### 2. 获取授权

联系开发者获取 `license.dat`，放置到 exe 同目录。

### 3. 运行

双击 `WeChatOA.exe` 启动 Web 服务，浏览器打开 `http://localhost:8000` 即可访问管理界面。

## 命令行工具

```batch
# 手动抓取 AI 资讯
WeChatOA.exe --fetch

# 手动生成文章
WeChatOA.exe --generate

# 手动发布文章
WeChatOA.exe --publish
```

## 开发

### 环境要求

- Python 3.10+
- Miniconda / Conda
- Playwright（Chromium）

### 本地运行

```bash
git clone https://github.com/cheng0009/WeChat-OA-Assistant.git
cd WeChat-OA-Assistant
pip install -r requirements.txt
playwright install chromium
python run.py
```

## 授权机制

本软件采用机器指纹 + HMAC-SHA256 签名验证的授权机制。每份 `license.dat` 绑定一台机器的硬件信息，不可迁移。未授权状态下程序拒绝运行。

## License

Proprietary. 未经授权禁止商用或二次分发。
