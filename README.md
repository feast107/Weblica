# Weblica 🔷

> **Intelligent Web Application Cloning & Replaying Tool**
>
> 基于 CloakBrowser（隐蔽式 Playwright）与 Agent-in-the-Loop 智能编排引擎的 Web 应用客户端克隆复现工具。

---

## Agent Quick Start

如果你是 AI Agent，按以下方式调用本工具：

```bash
# 1. 环境检查（必须先执行）
pip install -r requirements.txt 2>/dev/null || true
playwright install chromium 2>/dev/null || true

# 2. 克隆目标站点（推荐 agent-mode）
python -m weblica clone <TARGET_URL> -o ./cloned --depth 2 --agent-mode

# 3. 启动本地复现服务器
python -m weblica replay -d ./cloned -p 8080
# 访问 http://localhost:8080/weblica-index.html

# 4. 视觉对比（验证克隆质量）
python -m weblica compare <TARGET_URL> -d ./cloned -o ./comparison
```

**关键输出目录：**
- `./cloned/` — 克隆结果（HTML + assets）
- `./cloned/analysis/page_001/` — 页面分析报告目录（按种类拆分的 JSON/HTML/PNG 文件，含截图、iframe、DOM 快照）
- `./cloned/navigation.json` — 站点全局导航树（parent→children、depth 分组）
- `./cloned/weblica-manifest.json` — 克隆元数据（页面数、资源数）
- `./cloned/weblica-session.json` — **完整网络会话记录**（所有请求/响应、操作链、API 汇总）
- `./cloned/.weblica-state.json` — 断点续传状态文件
- `./comparison/` — 对比截图（`original.png`, `clone.png`, `diff.png`）

---

## 功能特性

- **🕵️ 隐蔽克隆 (CloakBrowser)** — 优先使用 CloakHQ 补丁版 Chromium（58 项 C++ 级反检测补丁），自动降级到 Playwright + JS 注入方案。支持人类化行为模拟（鼠标、键盘、滚动）
- **🔬 智能分析 (SmartAnalyzer)** — 自动提取页面 DOM 结构、CSS/JS 资源、图片字体、API 端点，并检测前端框架（React、Vue、Angular、Next.js、Nuxt.js 等）
- **📡 网络流量拦截 (NetworkInterceptor)** — 动态监听页面发出的所有 HTTP 请求/响应，捕获完整响应体（文本类型，上限 500KB），自动触发交互来捕获懒加载 API
- **📸 页面截图** — 每个克隆页面保存 `screenshot.png`（完整页面截图），便于视觉验证与对比
- **🖼️ iframe 内容捕获** — 自动提取并保存页面内所有非主框架 iframe 的 HTML 内容（`iframe_00.html`、`iframe_01.html`…）
- **🔓 SSL 证书跳过** — 资源下载自动忽略 SSL 验证错误，支持证书不匹配或自签名证书的站点
- **🤖 Agent-in-the-Loop 编排 (AgentOrchestrator)** — 深度优先遍历，每个页面都是决策单元。Agent 在每个障碍点介入分析，用户可在浏览器中手动解决登录/验证码后自动接管继续
- **🔄 人机协作克隆** — 浏览器窗口在遇到登录页时**保持打开**，用户完成登录后工具自动检测并继续后续深度克隆
- **📦 深度爬取** — 支持多级页面递归克隆，自动下载并重写静态资源引用为本地路径
- **🖥️ 本地复现 (WebReplayer)** — 一键启动本地 HTTP 服务器浏览克隆结果，支持热重载
- **📸 视觉对比** — 对原始站点与克隆结果进行截图对比，量化差异
- **🎬 交互录制回放** — 录制用户在页面上的点击、输入、滚动等操作，支持在克隆站点上回放验证
- **🔐 身份认证支持** — Cookie 注入、Bearer Token、Basic Auth、浏览器持久化人工登录、验证码检测、认证状态持久化

---

## 架构概览

### 核心架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Weblica                                     │
├─────────────┬─────────────┬───────────────────┬─────────────────────┤
│ CloakBrowser│ SmartAnalyzer│ NetworkInterceptor│ AgentOrchestrator   │ WebReplayer         │
│  (隐蔽浏览器) │  (智能分析器)  │  (网络拦截器)      │  (Agent编排引擎)     │  (复现服务器)        │
├─────────────┼─────────────┼─────────────────┼───────────────────┼─────────────────────┤
│ • CloakHQ   │ • DOM 结构   │ • 请求/响应监听  │ • DFS 深度优先     │ • 本地 HTTP 服务     │
│   补丁内核   │ • 资源提取   │ • 自动交互触发   │ • 障碍点 Agent 介入 │ • 截图对比          │
│ • UA 轮换    │ • 框架检测   │ • API 调用链记录 │ • 浏览器持久化      │ • 交互录制回放       │
│ • WebDriver  │ • API 发现   │ • Session 回放   │ • 登录自动检测      │                     │
│   抹除       │ • 表单分析   │                 │ • 断点续传          │                     │
│ • Canvas     │             │                 │ • 人机协作          │                     │
│   指纹混淆   │             │                 │                     │                     │
│ • 人类化行为 │             │                 │                     │                     │
└─────────────┴─────────────┴───────────────────┴─────────────────────┘
                            │
                    ┌───────┴───────┐
                    │   Playwright   │
                    │   + aiohttp    │
                    └───────────────┘
```

### Agent-in-the-Loop 流程

```
┌─────────────┐     加载页面      ┌─────────────┐
│   DFS 遍历   │ ───────────────► │  Phase 1    │
│  (深度优先)  │                  │ 导航+障碍检测 │
└─────────────┘                  └──────┬──────┘
       ▲                                │
       │         检测到障碍              ▼
       │    ┌───────────────── 浏览器 Page 保持打开
       │    │                           │
       │    │                    ┌──────┴──────┐
       │    │                    │  Agent 决策  │
       │    │                    │  上下文输出  │
       │    │                    └──────┬──────┘
       │    │                           │
       │    │    ┌──────────────────────┘
       │    │    │ 用户手动登录 / Agent 决策
       │    │    ▼
       │    │ ┌──────────────┐
       │    └ │ 登录成功检测  │
       │      │ (轮询检测)   │
       │      └──────┬───────┘
       │             │ 登录成功
       │             ▼
       │      ┌──────────────┐
       └──────┤  Phase 2     │
              │ 分析+下载+保存│
              └──────────────┘
```

---

## 安装

```bash
# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（仅需一次）
playwright install chromium

# （可选）安装 CloakBrowser 补丁版 Chromium，提升反检测能力
pip install cloakbrowser
python -m weblica.browser --download
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
| `--humanize` | `True` | 人类化行为（鼠标/键盘/滚动），CloakBrowser 模式下生效 |
| `--no-humanize` | `False` | 禁用人类化行为（更快但隐蔽性降低） |
| `--agent-mode` | `False` | 启用 Agent-in-the-Loop 监督模式 |
| `--agent-stepped` | `False` | 以步进模式启动：Agent 审批每个原子操作（点击/滚动/输入） |

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
│   ├── fonts/                 # 字体
│   └── api/                   # 捕获的 API 响应样本
├── analysis/
│   └── page_001/              # 页面分析目录（按种类拆分）
│       ├── index.json         # 概览：URL、title、depth、parent_url、文件清单
│       ├── metadata.json      # 标题、描述、Meta 标签、框架检测
│       ├── dom.html           # 完整页面 HTML（可直接在浏览器中打开）
│       ├── screenshot.png     # 完整页面截图
│       ├── iframe_00.html     # iframe 内容（如有内嵌框架）
│       ├── assets.json        # CSS、JS、图片、字体
│       ├── links.json         # 外链与内链
│       ├── forms.json         # 表单、按钮（向后兼容）
│       ├── interactions.json  # 增强交互元素：按钮/链接/输入框，含 selector、onclick、href
│       ├── network.json       # 网络流量 + API 调用（含完整 request/response bodies）
│       └── snapshots.json     # 交互前后的 DOM 快照（滚动、点击等）
├── navigation.json            # 站点全局导航树（parent→children、depth 分组）
├── weblica-manifest.json      # 克隆清单
├── weblica-session.json       # 完整会话记录（操作链 + 流量）
├── weblica-index.html         # 索引浏览页
└── .weblica-state.json        # 断点续传状态
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

## CloakBrowser 集成

Weblica 优先使用 **CloakBrowser (CloakHQ)** —— 一个基于 Chromium 的补丁版浏览器，包含 58 项 C++ 级反检测补丁（WebDriver 抹除、Canvas/WebGL 指纹混淆、自动化特征消除等）。当补丁版二进制不可用时，自动降级到 Playwright + JS 注入方案。

### 安装 CloakBrowser

**方式一：自动下载（需要外网访问）**

```bash
pip install cloakbrowser
python -m weblica.browser --download
```

**方式二：使用本地已有的二进制（推荐）**

如果已经下载或自行编译了 CloakBrowser 补丁版 Chromium，通过环境变量指定路径即可，无需等待在线下载：

```bash
# Windows CMD
set CLOAKBROWSER_BINARY_PATH=D:\Shared\Code\Git\CloakBrowser\bin\cloakbrowser-windows-x64\chrome.exe

# Windows PowerShell
$env:CLOAKBROWSER_BINARY_PATH="D:\Shared\Code\Git\CloakBrowser\bin\cloakbrowser-windows-x64\chrome.exe"

# Bash (Git Bash / MSYS2)
export CLOAKBROWSER_BINARY_PATH="D:\Shared\Code\Git\CloakBrowser\bin\cloakbrowser-windows-x64\chrome.exe"
```

**方式三：手动下载到默认缓存目录**

```bash
# 查看所需版本和下载地址
python -m weblica.browser

# 手动下载并解压到 cloakbrowser 默认缓存目录
curl -L -o cloakbrowser.zip "https://cloakbrowser.dev/chromium-v<VERSION>/cloakbrowser-windows-x64.zip"
unzip cloakbrowser.zip -d "C:\Users\<USER>\.cloakbrowser\chromium-<VERSION>"
```

### 验证是否在使用官方二进制

```bash
export CLOAKBROWSER_BINARY_PATH="D:\Shared\Code\Git\CloakBrowser\bin\cloakbrowser-windows-x64\chrome.exe"
python -c "from weblica.browser import CloakBrowser; import asyncio; async def t(): b=CloakBrowser(); await b.launch(); print('Real cloak:', b._using_real_cloak); await b.close(); asyncio.run(t())"
```

输出 `Real cloak: True` 表示正在使用官方补丁版 Chromium。输出 `False` 则表示降级到了 Playwright + JS 注入方案。

> **注意**：`python -c "import cloakbrowser; print(cloakbrowser.binary_info()['installed'])"` 可能返回 `False`，这是预期行为——`binary_info()` 只检查 cloakbrowser 的默认缓存目录，不会检查 `CLOAKBROWSER_BINARY_PATH` 环境变量指向的路径。只要设置了环境变量且文件存在，Weblica 就会正确加载。

### 人类化行为 (`--humanize`)

CloakBrowser 模式下默认启用 `humanize`，会对所有页面交互（点击、输入、滚动）注入人类化延迟和轨迹，大幅降低被反爬虫系统检测的概率。

```bash
# 默认启用 humanize
python -m weblica clone https://example.com

# 禁用 humanize（速度更快，但隐蔽性降低）
python -m weblica clone https://example.com --no-humanize
```

---

## Agent 工作流模板

### 模板 A：Agent-in-the-Loop 克隆（推荐）

适用于大多数场景，Agent 在每个页面完成后监督审查（SUPERVISED 模式）。
对于复杂页面，Agent 可动态切换到步进模式（STEPPED），逐操作审批。

```
Step 1: python -m weblica clone <URL> -o ./cloned --depth 2 --agent-mode
        # 或步进模式: --agent-mode --agent-stepped
Step 2: 工具自动执行 DFS 遍历，在检查点生成决策上下文
Step 3: Agent 审查页面结果，决定哪些链接值得深入、是否需要额外交互
Step 4: 读取 ./cloned/analysis/page_*/ 下的分析结果
Step 5: python -m weblica compare <URL> -d ./cloned -o ./comparison
Step 6: python -m weblica replay -d ./cloned -p 8080
Step 7: 告知用户访问 http://localhost:8080/weblica-index.html
```

### 模板 D：人机协作克隆（需要登录）

适用于需要登录后才能访问的站点。**浏览器窗口保持打开，用户手动登录后工具自动接管。**

```
# Agent-mode + 浏览器持久化（推荐）
Step 1: python -m weblica clone <URL> -o ./cloned --depth 2 --agent-mode --no-headless
Step 2: 工具检测到登录页 → 浏览器窗口保持打开
Step 3: 用户在浏览器窗口中完成登录
Step 4: 工具轮询检测到登录成功 → 自动继续 DFS 克隆
Step 5: 全部完成后启动 replay 服务器

# 传统方式：使用已有 Cookie
Step 1: python -m weblica clone <URL> -o ./cloned --cookies ./cookies.json

# 传统方式：使用 Token
Step 1: python -m weblica clone <URL> -o ./cloned --bearer-token <TOKEN>
```

### 模板 B：深度架构分析

适用于用户要求"分析这个网站用了什么技术"。

```
Step 1: python -m weblica clone <URL> -o ./cloned --depth 2 --agent-mode
Step 2: 读取 ./cloned/navigation.json 了解站点结构与层级
Step 3: 读取 ./cloned/analysis/page_001/index.json 获取概览
Step 4: 深入分析各页面：
        - analysis/page_*/metadata.json → frameworks[]（检测到的前端框架及版本）
        - analysis/page_*/network.json → api_endpoints[]（发现的 API 端点，含完整响应体）
        - analysis/page_*/assets.json → scripts[]（JS 资源列表）
        - analysis/page_*/interactions.json → buttons/links/inputs（交互元素与 selector）
        - analysis/page_*/snapshots.json → DOM 变化（交互前后对比）
Step 5: 读取 weblica-manifest.json 汇报总页面数/资源数
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
from weblica.orchestrator import AgentOrchestrator, DecisionContext, ObstacleType

async def smart_agent_callback(ctx: DecisionContext) -> DecisionContext:
    """Custom agent logic: supervised by default, switch to stepped for complex pages."""
    
    # Handle obstacles
    if ctx.obstacle == ObstacleType.LOGIN_REQUIRED:
        ctx.recommended_action = "manual"
        return ctx
    
    # STEPPED mode: agent sees every atomic action
    if ctx.mode == "stepped":
        if ctx.phase.name == "ANALYZING":
            # After analysis, decide if we need to interact
            if any("load" in b.get("text", "") for b in ctx.observation.get("buttons", [])):
                ctx.recommended_action = "click"
                ctx.action_params = {"selector": "button.load-more"}
            else:
                ctx.recommended_action = "continue"
        elif ctx.recommended_action in ("scroll", "click", "input", "wait"):
            # After executing an interaction, observe again
            ctx.recommended_action = "continue"
        else:
            ctx.recommended_action = "continue"
        return ctx
    
    # SUPERVISED mode: agent reviews at page completion
    if ctx.phase.name == "COMPLETED":
        # Filter links: only follow dashboard-related pages
        dashboard_links = [l for l in ctx.discovered_links if "dashboard" in l or "admin" in l]
        if dashboard_links:
            ctx.action_params["filter"] = dashboard_links
        ctx.recommended_action = "continue"
        return ctx
    
    ctx.recommended_action = "continue"
    return ctx

async def agent_workflow():
    # Hybrid-mode: start supervised, agent can switch to stepped dynamically
    async with AgentOrchestrator(
        start_url="https://example.com",
        output_dir="./cloned",
        max_depth=2,
        agent_mode="supervised",   # "supervised" or "stepped"
        decision_callback=smart_agent_callback,
    ) as orch:
        async for ctx in orch.run_dfs():
            # Generator yields at every checkpoint (mode-dependent)
            # In SUPERVISED: only at obstacles and page completion
            # In STEPPED: at every atomic action (navigate, analyze, scroll, click, etc.)
            pass
        print(orch.get_summary())

asyncio.run(agent_workflow())
```

---

## 项目结构

```
weblica/
├── __init__.py          # 包入口与导出
├── __main__.py          # python -m weblica
├── cli.py               # 命令行接口（argparse）
├── browser.py           # CloakBrowser 隐蔽浏览器
├── analyzer.py          # SmartAnalyzer 智能分析器
├── cloner.py            # WebCloner 克隆引擎
├── replayer.py          # WebReplayer 复现服务器
├── auth.py              # AuthManager 认证管理器
├── orchestrator.py      # AgentOrchestrator Agent编排引擎
└── utils.py             # 工具函数
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

## HTML 资源重写规则

`_rewrite_html` 支持以下路径形式的自动替换：

| 原始形式 | 示例 |
|----------|------|
| 完整 URL | `https://example.com/css/style.css` |
| 绝对路径（无域名） | `/css/style.css` |
| 带查询参数 | `/css/style.css?v=1.2.3` |
| HTML 转义查询 | `/css/style.css?v=1.2.3`（`&` 转 `&amp;`） |
| 含 `../` 的路径 | `/js/../libs/jquery.js`（自动规范化） |

---

## 输出文件格式

### `analysis/page_NNN/` 目录结构

每个克隆的页面都会生成一个独立目录，分析数据按种类拆分为多个小文件：

```
analysis/
└── page_001/
    ├── index.json         # 概览：URL、title、depth、parent_url、文件清单
    ├── metadata.json      # 标题、描述、Meta 标签、检测到的前端框架
    ├── dom.html           # 完整页面 HTML（可直接在浏览器中打开）
    ├── screenshot.png     # 完整页面截图
    ├── iframe_00.html     # iframe 内容（如有内嵌框架）
    ├── assets.json        # CSS、JS、图片、字体资源列表
    ├── links.json         # 页面内所有链接
    ├── forms.json         # 表单和按钮（向后兼容）
    ├── interactions.json  # 增强交互元素：按钮/链接/输入框，含 selector、onclick、href
    ├── network.json       # 完整网络流量、API 调用记录（含完整 request/response bodies）
    └── snapshots.json     # 交互前后的 DOM 快照
```

**`index.json` 示例：**

```json
{
  "page_index": 1,
  "url": "https://example.com",
  "title": "Example Domain",
  "depth": 0,
  "parent_url": null,
  "assets_count": 12,
  "links_count": 8,
  "forms_count": 2,
  "api_calls_count": 15,
  "files": {
    "metadata": "metadata.json",
    "dom": "dom.html",
    "screenshot": "screenshot.png",
    "assets": "assets.json",
    "links": "links.json",
    "forms": "forms.json",
    "interactions": "interactions.json",
    "network": "network.json",
    "snapshots": "snapshots.json"
  }
}
```

### `weblica-manifest.json`

```json
{
  "total_pages": 21,
  "total_assets": 35,
  "pages": ["https://example.com", "https://example.com/user"],
  "blocked": [],
  "skipped": [],
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
| `SSL certificate verify failed` | 目标站点证书不匹配 | 已自动忽略（`ssl=False`），无需处理 |
| `404 on assets` | CDN 跨域资源 | 正常现象，部分资源可能无法下载 |
| `PIL not available` | Pillow 未安装 | `pip install Pillow` 以生成 diff 图 |
| `Address already in use` | 端口被占用 | 换用 `-p <其他端口>` |
| `CAPTCHA detected` | 页面出现验证码 | 使用 `--agent-mode --no-headless` 手动处理 |

---

## 注意事项

1. **合法合规**：仅供学习研究和合法授权的安全测试。遵守目标站点的 `robots.txt` 及相关法律法规。
2. **动态内容**：SPA（React/Vue/Angular）克隆结果为静态快照，API 数据为克隆时刻的冻结状态。
3. **反爬对抗**：CloakBrowser 可绕过基础检测，但高级 WAF（Cloudflare Turnstile、Akamai）可能需要额外处理。
4. **人机协作**：`--agent-mode --no-headless` 模式下浏览器窗口会保持打开，用户可在窗口中完成登录/验证码操作，工具检测到成功后会自动继续。

---

## License

[Apache License 2.0](LICENSE)
