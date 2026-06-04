# Weblica 🔷

> **Intelligent Web Application Cloning & Replaying Tool**
>
> 基于 CloakBrowser（隐蔽式 Playwright）与智能分析引擎的 Web 应用客户端克隆复现工具。

---

## Agent Quick Start

如果你是 AI Agent，按以下方式调用本工具：

```bash
# 1. 环境检查（必须先执行）
pip install -r requirements.txt 2>/dev/null || true
playwright install chromium 2>/dev/null || true

# 2. 克隆目标站点
python -m weblica clone <TARGET_URL> -o ./cloned --depth 1

# 3. 启动本地复现服务器
python -m weblica replay -d ./cloned -p 8080
# 访问 http://localhost:8080/weblica-index.html

# 4. 视觉对比（验证克隆质量）
python -m weblica compare <TARGET_URL> -d ./cloned -o ./comparison
```

**关键输出目录：**
- `./cloned/` — 克隆结果（HTML + assets）
- `./cloned/analysis_1.json` — 页面分析报告（框架、API、资源列表）
- `./cloned/weblica-manifest.json` — 克隆元数据（页面数、资源数）
- `./comparison/` — 对比截图（`original.png`, `clone.png`, `diff.png`）

---

## 功能特性

- **🕵️ 隐蔽克隆 (CloakBrowser)** — 内置多种反检测策略（WebDriver 隐藏、Canvas 指纹混淆、Plugin 伪造、权限伪装），降低被目标站点识别和拦截的概率
- **🔬 智能分析 (SmartAnalyzer)** — 自动提取页面 DOM 结构、CSS/JS 资源、图片字体、API 端点，并检测前端框架（React、Vue、Angular、Next.js、Nuxt.js 等）
- **📦 深度爬取** — 支持多级页面递归克隆，自动下载并重写静态资源引用为本地路径
- **🖥️ 本地复现 (WebReplayer)** — 一键启动本地 HTTP 服务器浏览克隆结果，支持热重载
- **📸 视觉对比** — 对原始站点与克隆结果进行截图对比，量化差异
- **🎬 交互录制回放** — 录制用户在页面上的点击、输入、滚动等操作，支持在克隆站点上回放验证
- **🔐 身份认证支持** — Cookie 注入、Bearer Token、Basic Auth、等待人工登录、验证码检测、认证状态持久化

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        Weblica                              │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│ CloakBrowser│ SmartAnalyzer│ WebCloner   │ WebReplayer       │
│  (隐蔽浏览器) │  (智能分析器)  │  (克隆引擎)  │  (复现服务器)      │
├─────────────┼─────────────┼─────────────┼───────────────────┤
│ • UA 轮换    │ • DOM 结构   │ • 递归爬取   │ • 本地 HTTP 服务   │
│ • WebDriver  │ • 资源提取   │ • 资产下载   │ • 截图对比        │
│   抹除       │ • 框架检测   │ • HTML 重写  │ • 交互录制回放     │
│ • Canvas     │ • API 发现   │ • 索引生成   │                   │
│   指纹混淆   │ • 表单分析   │             │                   │
│ • 行为模拟   │             │             │                   │
└─────────────┴─────────────┴─────────────┴───────────────────┘
                            │
                    ┌───────┴───────┐
                    │   Playwright   │
                    │   + aiohttp    │
                    └───────────────┘
```

---

## 安装

```bash
# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（仅需一次）
playwright install chromium
```

---

## CLI 命令

### `clone` — 克隆站点

```bash
python -m weblica clone <URL> [OPTIONS]
```

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `-o, --output` | `./cloned` | 输出目录 |
| `--headless` | `True` | 无头模式（`--no-headless` 显示窗口） |
| `-d, --depth` | `1` | 最大爬取深度 |
| `--proxy` | 无 | 代理地址，如 `http://127.0.0.1:7890` |
| `--slow-mo` | 无 | 操作延迟（毫秒），调试用 |

**认证选项：**

| 选项 | 说明 |
|------|------|
| `--cookies <file>` | Cookie JSON 文件路径 |
| `--bearer-token <token>` | Bearer Token 认证 |
| `--basic-auth <user:pass>` | Basic Auth 认证 |
| `--wait-login` | 暂停等待人工登录（需配合 `--no-headless`） |
| `--login-timeout <s>` | 登录等待超时（默认 300 秒） |
| `--login-selector <sel>` | 登录成功检测 CSS 选择器 |
| `--captcha-action <mode>` | 验证码处理：`warn`/`block`/`auto_click` |
| `--save-auth` | 登录成功后保存认证状态 |
| `--auth-state-file <file>` | 认证状态保存路径 |
| `--auth-config <file>` | 完整认证配置 JSON 文件 |

**输出结构：**
```
cloned/
├── index.html                 # 主页面
├── <other_pages>.html         # 子页面
├── assets/
│   ├── css/                   # 样式表
│   ├── js/                    # 脚本
│   ├── images/                # 图片
│   └── fonts/                 # 字体
├── analysis_1.json            # 智能分析报告
├── weblica-manifest.json      # 克隆清单
└── weblica-index.html         # 索引浏览页
```

### `replay` — 本地复现

```bash
python -m weblica replay -d ./cloned -p 8080
```

浏览器访问 `http://localhost:8080/weblica-index.html`

### `compare` — 视觉对比

```bash
python -m weblica compare https://example.com -d ./cloned -o ./comparison
```

生成 `original.png`、`clone.png`、`diff.png`

### `record` — 交互录制

```bash
python -m weblica record https://example.com --duration 30 -o session.json
```

---

## Agent 工作流模板

### 模板 A：标准克隆 → 复现 → 对比

适用于用户要求"克隆这个网站并看看效果"。

```
Step 1: python -m weblica clone <URL> -o ./cloned --depth 1
Step 2: 读取 ./cloned/analysis_1.json，汇报检测到的框架和资源数量
Step 3: python -m weblica compare <URL> -d ./cloned -o ./comparison
Step 4: 汇报 diff 结果（如有 Pillow）
Step 5: python -m weblica replay -d ./cloned -p 8080
Step 6: 告知用户访问 http://localhost:8080/weblica-index.html
```

### 模板 D：认证克隆

适用于需要登录后才能访问的站点。

```
# 方式 1：使用已有 Cookie
Step 1: python -m weblica clone <URL> -o ./cloned --cookies ./cookies.json

# 方式 2：使用 Token
Step 1: python -m weblica clone <URL> -o ./cloned --bearer-token <TOKEN>

# 方式 3：等待人工登录（打开浏览器让用户手动登录）
Step 1: python -m weblica clone <URL> -o ./cloned --no-headless --wait-login --save-auth
Step 2: 用户完成登录后，工具自动继续克隆
Step 3: 认证状态保存到 ./weblica-auth-state.json，后续可直接复用

# 方式 4：复用已保存的认证状态
Step 1: python -m weblica clone <URL> -o ./cloned --cookies ./weblica-auth-state.json
```

### 模板 B：深度架构分析

适用于用户要求"分析这个网站用了什么技术"。

```
Step 1: python -m weblica clone <URL> -o ./cloned --depth 2
Step 2: 读取 ./cloned/analysis_1.json
Step 3: 提取并汇报：
        - frameworks[] → 检测到的前端框架及版本
        - api_endpoints[] → 发现的 API 端点
        - scripts[] → JS 资源列表
        - forms[] → 表单结构
Step 4: 读取 weblica-manifest.json 汇报总页面数/资源数
```

### 模板 C：交互验证

适用于用户要求"验证克隆的页面能不能正常交互"。

```
Step 1: python -m weblica clone <URL> -o ./cloned
Step 2: python -m weblica record <URL> --duration 30 -o session.json
Step 3: python -m weblica replay -d ./cloned -p 8080
Step 4: (Python API) 加载 session.json 并在 localhost:8080 上回放
Step 5: 对比回放结果，报告交互是否成功
```

---

## Python API

```python
import asyncio
from weblica import WebCloner, WebReplayer

async def workflow():
    # 克隆
    async with WebCloner(output_dir="./cloned", max_depth=1) as cloner:
        await cloner.clone("https://example.com")
    
    # 本地服务
    replayer = WebReplayer(clone_dir="./cloned", port=8080)
    url = await replayer.start_server()
    
    # 视觉对比
    results = await replayer.compare_visual(
        original_url="https://example.com",
        output_dir="./comparison"
    )
    
    await replayer.stop_server()

asyncio.run(workflow())
```

---

## 项目结构

```
weblica/
├── __init__.py      # 包入口与导出
├── __main__.py      # python -m weblica
├── cli.py           # 命令行接口（argparse）
├── browser.py       # CloakBrowser 隐蔽浏览器
├── analyzer.py      # SmartAnalyzer 智能分析器
├── cloner.py        # WebCloner 克隆引擎
├── replayer.py      # WebReplayer 复现服务器
├── auth.py          # AuthManager 认证管理器
└── utils.py         # 工具函数
```

---

## CloakBrowser 反检测策略

| 策略 | 说明 |
|------|------|
| `navigator.webdriver` 移除 | 抹除自动化标记 |
| User-Agent 轮换 | 模拟真实浏览器 UA |
| Plugin/MIME 伪造 | 填充 Chrome PDF 插件信息 |
| Canvas 指纹混淆 | 对 canvas 输出添加微噪声 |
| Permission 查询覆盖 | 将通知等权限返回为 `prompt` |
| 语言/时区伪装 | 设置为 `zh-CN` / `Asia/Shanghai` |
| 鼠标行为模拟 | 随机滚动和鼠标移动 |

---

## 输出文件格式

### `analysis_N.json`

```json
{
  "url": "https://example.com",
  "title": "Example Domain",
  "description": "...",
  "frameworks": [
    {"name": "React", "version": "18.2.0", "confidence": 0.9}
  ],
  "api_endpoints": [
    {"url": "/api/v1/users", "method": "GET"}
  ],
  "scripts": [
    {"url": "https://cdn.example.com/app.js", "type": "script"}
  ],
  "forms": [...],
  "links": [...]
}
```

### `weblica-manifest.json`

```json
{
  "total_pages": 5,
  "total_assets": 42,
  "pages": ["https://example.com", "https://example.com/about"],
  "assets": {
    "https://cdn.example.com/style.css": "assets/css/style_a1b2c3d4.css"
  }
}
```

---

## 错误处理速查

| 错误 | 原因 | 解决 |
|------|------|------|
| `Browser not launched` | Playwright 浏览器未安装 | `playwright install chromium` |
| `TimeoutError` | 页面加载过慢或被拦截 | 检查网络/代理，或增加超时 |
| `404 on assets` | CDN 跨域资源 | 正常现象，部分资源可能无法下载 |
| `PIL not available` | Pillow 未安装 | `pip install Pillow` 以生成 diff 图 |
| `Address already in use` | 端口被占用 | 换用 `-p <其他端口>` |
| `CAPTCHA detected` | 页面出现验证码 | 使用 `--no-headless --wait-login` 手动处理，或调整 `--captcha-action` |

---

## 注意事项

1. **合法合规**：仅供学习研究和合法授权的安全测试。遵守目标站点的 `robots.txt` 及相关法律法规。
2. **动态内容**：SPA（React/Vue/Angular）克隆结果为静态快照，API 数据为克隆时刻的冻结状态。
3. **反爬对抗**：CloakBrowser 可绕过基础检测，但高级 WAF（Cloudflare Turnstile、Akamai）可能需要额外处理。

---

## License

[Apache License 2.0](LICENSE)
