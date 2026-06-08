# Weblica Skill

## Description

Intelligent Web Application Exploration & Replaying Tool powered by CloakBrowser (CloakHQ patched Chromium), NetworkInterceptor (dynamic HTTP request/response capture), and AgentOrchestrator (Agent-in-the-Loop supervision).

Use this skill when you need to:
- Explore a web application's frontend for offline analysis or local replay
- Capture and reproduce web page interactions for testing or demonstration
- Compare an explored site against the original for visual regression
- Extract frontend assets, frameworks, and API endpoints from a target site
- **Intercept and record all dynamic API calls** triggered by page navigation and user interactions
- **Reverse-engineer a site's API surface** without reading minified JavaScript
- Perform stealth web crawling that bypasses basic anti-bot detection
- Explore sites that require authentication via human-in-the-loop cooperation

## When to Use

Trigger this skill when the user requests any of the following:
- "Explore this website" / "Analyze this web app" / "Map this site"
- "Replay this web app locally" / "Host this explored site"
- "Record interactions on this page" / "Automate clicking through this site"
- "Compare the explored site with the original" / "Screenshot diff"
- "Analyze what frameworks this site uses" / "Extract frontend assets"
- "Explore a site that requires login" / "Explore behind authentication"
- Any request involving `weblica`, `CloakBrowser`, `playwright explore`, `stealth crawl`

## When NOT to Use

Do NOT use this skill for:
- General web scraping of data/tables (use dedicated scraping tools instead)
- Backend API testing without a browser context
- Penetration testing or attacking sites without explicit authorization
- Exploring sites the user does not own or have permission to explore

## Environment Requirements

- Python >= 3.9
- Dependencies in `requirements.txt` installed
- Playwright browsers installed: `playwright install chromium`
- (Optional) CloakBrowser patched Chromium for enhanced stealth: `pip install cloakbrowser`
  - Auto-download: `python -m weblica.browser --download` (requires internet)
  - Use local binary: `set CLOAKBROWSER_BINARY_PATH=D:\Shared\Code\Git\CloakBrowser\bin\cloakbrowser-windows-x64\chrome.exe`
  - Verify: `python -c "from weblica.browser import CloakBrowser; import asyncio; async def t(): b=CloakBrowser(); await b.launch(); print('Real cloak:', b._using_real_cloak); await b.close(); asyncio.run(t())"` → should print `True`
- Working directory must be the project root (`d:\Shared\Code\Git\Weblica`)

## Installation Check

Before use, verify the tool is ready:

```bash
# Check Python packages
pip show playwright aiohttp Pillow 2>/dev/null || pip install -r requirements.txt

# Check Playwright browser
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.chromium.launch(); p.stop(); print('OK')"
```

If browser is missing, run: `playwright install chromium`

## Commands Reference

### 1. Explore a Website

```bash
python -m weblica explore <URL> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output` | `./explored` | Output directory |
| `--headless` | `True` | Run headless (set `--no-headless` to show browser) |
| `-d, --depth` | `1` | Max crawl depth (0 = single page, 2 = deep crawl) |
| `--proxy` | none | Proxy URL, e.g. `http://127.0.0.1:7890` |
| `--slow-mo` | none | Slow down by N ms for debugging |
| `--humanize` | `True` | Human-like mouse/keyboard/scroll behavior (CloakBrowser mode) |
| `--no-humanize` | `False` | Disable human-like behavior (faster, less stealthy) |
| `--agent-mode` | `False` | Enable Agent-in-the-Loop supervision (BFS, pause at obstacles) |
| `--agent-stepped` | `False` | Start in STEPPED mode: agent approves every atomic action |

**Authentication options for `explore`:**

| Option | Description |
|--------|-------------|
| `--cookies <file>` | JSON file with cookies |
| `--bearer-token <token>` | Bearer token for API auth |
| `--basic-auth <user:pass>` | Basic auth credentials |
| `--wait-login` | Pause for manual login (requires `--no-headless`) |
| `--login-timeout <s>` | Login wait timeout (default: 300) |
| `--login-selector <sel>` | CSS selector indicating login success |
| `--captcha-action <mode>` | `warn` / `block` / `auto_click` |
| `--save-auth` | Save auth state after login |
| `--auth-state-file <file>` | Path to save/load auth state |
| `--auth-config <file>` | Full auth config JSON file |

**Output structure:**
```
<output_dir>/
├── index.html                 # Main page (renamed from path)
├── <other_pages>.html         # Crawled sub-pages (static snapshots with local asset paths)
├── assets/                    # Downloaded and rewritten frontend assets
│   ├── css/                   # Stylesheets
│   ├── js/                    # Scripts
│   ├── images/                # Images
│   ├── fonts/                 # Fonts
│   └── api/                   # Captured API response samples
├── analysis/                  # Per-page deep analysis
│   └── page_001/
│       ├── index.json         # Overview: URL, title, depth, parent_url, file manifest
│       ├── metadata.json      # Title, description, meta tags, detected frameworks
│       ├── dom.html           # Full page HTML (open directly in browser)
│       ├── screenshot.png     # Full page screenshot
│       ├── iframe_00.html     # iframe content (when embedded frames exist)
│       ├── iframe_meta.json   # iframe metadata: src, actual_url, name, capture method
│       ├── assets.json        # CSS, JS, images, fonts referenced by this page
│       ├── links.json         # Discovered internal links
│       ├── forms.json         # Forms and buttons (backward-compatible)
│       ├── interactions.json  # Enhanced interactive elements: buttons/links/inputs with selectors, events, hrefs
│       ├── network.json       # Full network traffic + API calls with COMPLETE request/response bodies
│       └── snapshots.json     # DOM before/after for interactive operations (click, scroll, etc.)
├── navigation.json            # Site-wide page tree: parent→children, depth groups
├── iframe_route_map.json      # iframe routing map: container page → iframe src → matched content page
├── weblica-manifest.json      # Explore metadata
├── weblica-session.json       # Complete session recording (all operations + traffic)
├── weblica-index.html         # Browsable index page
└── .weblica-state.json        # Resume state for AgentOrchestrator
```

### 2. Start Local Replay Server

```bash
python -m weblica replay [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-d, --dir` | `./explored` | Explore directory to serve |
| `-p, --port` | `8080` | HTTP server port |

**Agent note:** Start this in background if the user wants to continue working:
```bash
python -m weblica replay -d ./explored -p 8080
# Then access http://localhost:8080/weblica-index.html
```

### 3. Record User Interactions

```bash
python -m weblica record <URL> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--duration` | `60` | Recording time in seconds |
| `-o, --output` | `./session.json` | Session save path |

### 4. Visual Comparison

```bash
python -m weblica compare <URL> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-d, --dir` | `./explored` | Explore directory |
| `-o, --output` | `./comparison` | Output dir for screenshots |

Produces: `original.png`, `explored.png`, `diff.png` (if Pillow available)

## Session API（有状态浏览器会话）

Weblica 可以作为**长期浏览器会话服务**运行，Agent 通过 HTTP API 远程控制浏览器。浏览器在 API 调用之间保持打开，Agent 可以随时暂停、查询状态、继续操作。

> **核心理念：Agent 主动探索，不是预编排脚本。**
> 
> 不要写一个一次性跑完的 Python 脚本。Agent 应该在**观察 → 决策 → 行动**的循环中，根据每次 API 返回的结果决定下一步做什么。浏览器状态是实时可见的，Agent 像人类分析师一样边探索边理解。

### 启动服务

```bash
python -m weblica.api_server
# → http://localhost:8765
```

**Network log 过滤（重要）**

默认只保存 `xhr`/`fetch`/`document` 的响应 body。静态资源（`script`、`stylesheet`、`image`、`font`）只记录元数据（URL、status、headers），不保存 body。这避免了 network log 被 JS/CSS 源码撑爆（ geo18 实测：从 449 KB → 6 KB，减少 **99%**）。

如需自定义：
```bash
# 只记录 API 调用（最精简）
curl -X POST "http://localhost:8765/sessions?capture_body_types=xhr,fetch"

# 记录 API + 页面 HTML（默认）
curl -X POST "http://localhost:8765/sessions?capture_body_types=xhr,fetch,document"

# 记录所有类型（不推荐 — 静态资源 body 会产生巨大日志）
curl -X POST "http://localhost:8765/sessions?capture_body_types=all"
```

### Agent 主动探索工作流

Agent 通过**反复调用 API 观察浏览器状态并做出决策**，而非预写脚本。典型循环：

```
1. POST /sessions                          → 创建会话，获取 session_id
2. POST /sessions/{id}/navigate?url=...    → 进入目标页面
3. GET  /sessions/{id}/interactive-elements → 观察：当前页有哪些按钮/输入框？
   └─ Agent 决策：点击 "a.btn-add" 试试
4. POST /sessions/{id}/click?selector=...  → 行动：点击 Add 按钮
   └─ 返回 {"interaction_type": "dom_update"} → Agent 决策：弹出了表单
5. GET  /sessions/{id}/interactive-elements → 观察：表单里有哪些字段？
   └─ Agent 决策：填充 title 和 content
6. POST /sessions/{id}/input?selector=...  → 行动：填写表单
7. GET  /sessions/{id}/state               → 验证：状态是否正确？
8. GET  /sessions/{id}/screenshot          → 视觉验证：页面看起来对吗？
9. GET  /sessions/{id}/network-log         → 分析：点击触发了哪些 API？
10. POST /sessions/{id}/save               → 关键节点持久化
   └─ Agent 可以暂停做任何其他事，浏览器保持打开
11. （Agent 回来继续）POST /sessions/{id}/click → 继续探索...
12. DELETE /sessions/{id}                  → 任务完成，销毁
```

### 核心端点

| 端点 | 用途 | Agent 何时调用 |
|------|------|---------------|
| `POST /sessions` | 创建会话 | 开始新任务时 |
| `POST /sessions/{id}/navigate?url=...` | 导航 | 进入新页面 |
| `POST /sessions/{id}/click?selector=...` | 点击 | Agent 决定与某个元素交互 |
| `POST /sessions/{id}/input?selector=...&value=...` | 输入 | Agent 决定填写表单字段 |
| `POST /sessions/{id}/scroll?direction=...` | 滚动 | 页面内容未完全加载 |
| `POST /sessions/{id}/wait?ms=...` | 等待 | Ajax 加载需要时间 |
| `GET /sessions/{id}/state` | 状态快照 | **每次操作后检查**，决定下一步 |
| `GET /sessions/{id}/screenshot` | 截图 | **视觉验证**，确认页面状态 |
| `GET /sessions/{id}/interactive-elements` | 可交互元素 | **决策依据**，决定下一步 selector |
| `GET /sessions/{id}/dom` | 当前 HTML | 需要解析 DOM 结构时 |
| `GET /sessions/{id}/network-log` | 网络日志 | **分析 API 调用**，理解后端交互 |
| `POST /sessions/{id}/save` | 持久化 | 关键节点保存，Agent 可安全暂停 |
| `DELETE /sessions/{id}` | 销毁 | 任务完成 |

### 状态快照（每次操作返回）

```json
{
  "session_id": "abc123",
  "interaction_type": "dom_update",
  "current_url": "https://example.com/admin",
  "current_title": "Dashboard",
  "html_length": 45231,
  "history_length": 5,
  "action": "click",
  "params": {"selector": "a.btn-add"},
  "timestamp": "2026-06-07T23:03:00"
}
```

**Agent 决策依据：**
- `interaction_type` 决定下一步策略：
  - `"navigation"` → URL 变了，需要重新 `interactive-elements` 了解新页面
  - `"dom_update"` → DOM 变化但 URL 没变（弹窗/表单出现），继续在当前页探索
  - `"no_change"` → 无变化，selector 可能错了，换元素重试
- `interactive-elements` 返回的元素列表（含坐标、selector、文本）是 Agent **选择下一个操作目标**的核心输入
- `screenshot` 提供视觉上下文，Agent 可以确认页面是否加载正确、弹窗是否出现
- `network-log` 让 Agent **逆向理解**点击/输入触发了什么后端 API，从而推断数据流

### ❌ 不要这样做

```python
# BAD: 预编排脚本，Agent 不参与决策
MODULES = [("article", url1), ("ai_task", url2), ...]
for key, url in MODULES:
    requests.post(f"{API}/navigate", params={"url": url})
    requests.post(f"{API}/click", params={"selector": "a.btn-add"})  # 假设一定存在
    requests.get(f"{API}/screenshot")
```

这种写法的问题：
- `a.btn-add` 不一定存在（如 webmedia 模块用不同的 class）
- Agent 看不到中间状态，无法调整策略
- 点击失败后无法换 selector 重试
- 无法根据页面实际内容决定探索深度

### ✅ 正确做法：Agent 在循环中决策

```python
# GOOD: Agent 每一步都基于观察结果决策
# 1. 创建会话
r = requests.post(f"{API}/sessions", params={"cookies_file": "cookies.json"})
sid = r.json()["session_id"]

# 2. 导航到目标
requests.post(f"{API}/sessions/{sid}/navigate", params={"url": target_url})

# 3. Agent 观察当前页面有哪些可交互元素
elements = requests.get(f"{API}/sessions/{sid}/interactive-elements").json()
#    Agent 分析：找到 "Add" 按钮的 selector
add_btn = next((e for e in elements["elements"] if "添加" in e["text"]), None)

# 4. Agent 决定点击这个按钮
if add_btn:
    result = requests.post(
        f"{API}/sessions/{sid}/click",
        params={"selector": add_btn["selector"]}
    ).json()
    #    Agent 读取 interaction_type 判断结果
    if result["interaction_type"] == "no_change":
        # Agent 决策：换 selector 重试，或用 iframe 方式
        ...
    elif result["interaction_type"] == "dom_update":
        # Agent 决策：表单出现了，继续探索表单字段
        dom = requests.get(f"{API}/sessions/{sid}/dom").json()
        #    解析 HTML，决定填写哪些字段...
```

### 持久化策略

- `save()` 在关键节点调用（如完成一个模块的探索、捕获到重要表单）
- `save()` 将内存中的网络日志追加到磁盘，然后清空内存缓冲区
- Agent 可以暂停很长时间，浏览器保持打开；回来后从上次状态继续
- 磁盘目录 `weblica-sessions/sessions/{id}/` 包含：cookies、storage、state.json、screenshot.png、network_log.jsonl

---

## Python API Reference

For programmatic control within agent workflows:

```python
import asyncio
from weblica import WebExplorer, WebReplayer
from weblica.orchestrator import AgentOrchestrator, DecisionContext, ObstacleType

async def smart_agent(ctx: DecisionContext) -> DecisionContext:
    """Custom agent: supervised by default, switch to stepped for complex pages."""
    if ctx.obstacle == ObstacleType.LOGIN_REQUIRED:
        ctx.recommended_action = "manual"
        return ctx

    # STEPPED mode: control every atomic action
    if ctx.mode == "stepped":
        if ctx.phase.name == "ANALYZING":
            # After analysis, decide if interaction is needed
            buttons = ctx.observation.get("buttons", [])
            if any("load" in b.get("text", "") for b in buttons):
                ctx.recommended_action = "click"
                ctx.action_params = {"selector": "button.load-more"}
            else:
                ctx.recommended_action = "continue"
        else:
            ctx.recommended_action = "continue"
        return ctx

    # SUPERVISED mode: review at page completion
    if ctx.phase.name == "COMPLETED":
        # Category-based filtering: only queue sidebar navigation links
        ctx.action_params["include_categories"] = ["sidebar_menu"]
        ctx.recommended_action = "continue"
        return ctx

    ctx.recommended_action = "continue"
    return ctx

async def workflow():
    async with AgentOrchestrator(
        start_url="https://example.com",
        output_dir="./explored",
        max_depth=2,
        agent_mode="supervised",   # "supervised" or "stepped"
        decision_callback=smart_agent,
    ) as orch:
        async for ctx in orch.run_dfs():
            # Yields at checkpoints (mode-dependent granularity)
            pass
        print(orch.get_summary())
```

### Key Classes

**`AgentOrchestrator`** — Hybrid-mode Agent-in-the-Loop exploration engine
- `async run_dfs()` — Generator yielding DecisionContext at 6 checkpoints:
  - **A**: Post-navigation (STEPPED only)
  - **B**: Obstacle detected (both modes)
  - **C**: Post-analysis (STEPPED only)
  - **D**: Post-download (STEPPED only)
  - **E**: Post-persist (STEPPED only)
  - **F**: Queue decision (both modes — the "方案2" supervised review point)
- **SUPERVISED mode**: Agent reviews at checkpoint F (page completion). Fast path.
- **STEPPED mode**: Agent approves every atomic action at checkpoints A-E. Full control.
- **Dynamic switching**: Agent can `switch_mode` at any checkpoint.
- `async _observe_page(page)` — Collect visible buttons, inputs, scroll state, modals for agent decisions
- `async _execute_action(page, action, params)` — Execute scroll/click/input/wait/screenshot
- `async _wait_for_browser_login(page, timeout)` — Poll browser for login success
- **`async interact_and_capture(base_url, action, selector, params, wait_for_navigation, timeout)` — P0 API**
  - Opens a fresh page, navigates to `base_url`, applies auth, executes the interaction
  - Captures before/after screenshots, DOM diff, and network traffic into `analysis/interactions/TIMESTAMP_ACTION_SELECTOR/`
  - Detects `interaction_type`: `navigation` (URL changed) / `dom_update` (DOM changed) / `iframe_navigation` (iframe src changed) / `no_change`
  - If navigation/iframe_navigation occurs, automatically analyzes and saves the new state as `analysis/page_NNN/`
  - Returns dict with `interaction_type`, `action_error`, `before`/`after`, `snapshot`, `captured_traffic`, `new_page`
- Browser page is KEPT OPEN when obstacles are detected
- State persisted to `.weblica-state.json` after each page

**`WebExplorer`** — Main batch exploration engine
- `async explore(url: str) -> Path` — Start exploring
- `output_dir`, `headless`, `max_depth`, `proxy` — Config via constructor

**`WebReplayer`** — Local replay and testing
- `async start_server() -> str` — Returns server URL
- `async stop_server()` — Clean shutdown
- `async compare_visual(original_url, explored_url, output_dir) -> dict`
- `async record_interactions(url, duration) -> ReplaySession`
- `async replay_interactions(session, target_url)`

**`CloakBrowser`** — Stealth browser wrapper
- Use as async context manager: `async with CloakBrowser() as browser:`
- `async new_page() -> Page` — Get a stealth-initialized Playwright page
- `async mimic_human_behavior(page)` — Random scroll + mouse movement

**`NetworkInterceptor`** — Dynamic HTTP traffic capture
- Attach to a Playwright `Page`: `interceptor = NetworkInterceptor(page)`
- `start()` / `stop()` — Begin/end listening
- `stop_and_collect() -> List[NetworkInteraction]` — Get all request/response pairs
- Captures XHR/fetch/document/script requests with headers, postData, and **complete response bodies** (up to 500KB, text types only)
- Auto-triggers interactions (scroll, click "load more") to capture lazy-loaded APIs

**`SessionRecorder`** — Session operation chain recorder (NEW)
- `record_navigate(page, url, depth)` — Record navigation + traffic
- `record_click(page, selector, depth)` — Record click + resulting traffic
- `record_input(page, selector, text, depth)` — Record text input + traffic
- `get_api_summary() -> List[dict]` — Flat list of all API calls across operations
- `save(path)` — Export full session to JSON

**`AuthManager`** — Authentication handler
- `apply_to_context(context, base_url)` — Inject cookies, headers before navigation
- `apply_to_page(page)` — Inject localStorage / sessionStorage
- `handle_login_flow(page) -> bool` — Wait for manual login
- `detect_captcha(page) -> Optional[str]` — Detect CAPTCHA presence
- `handle_captcha(page) -> bool` — Handle CAPTCHA per config
- `save_auth_state(page)` — Persist cookies and storage to file

## Standard Workflows

### Workflow A: Agent-in-the-Loop Explore → Replay → Compare (Recommended)

Use when user wants a full explore with agent supervision.

```
1. python -m weblica explore <URL> -o ./explored --depth 2 --agent-mode
   # Or stepped mode for full control: --agent-mode --agent-stepped
2. Agent reviews decision contexts at each obstacle/completed page
3. Read analysis/page_*/index.json for overview, then deep-dive into category files
4. Read weblica-session.json for complete API call chains
5. python -m weblica compare <URL> -d ./explored -o ./comparison
6. python -m weblica replay -d ./explored -p 8080
```

**Analyzing captured API traffic:**
```python
import json

# Load session report
with open("explored/weblica-session.json") as f:
    session = json.load(f)

# Print all API calls with response bodies
for api in session["api_summary"]:
    print(f"{api['method']} {api['url']} -> {api['status']}")
    if api.get('response', {}).get('body'):
        body = api['response']['body']
        print(f"  Response ({len(body)} chars): {body[:300]}...")

# Print operations with their before/after page states
for op in session["operations"]:
    print(f"Action: {op['action']} on {op['page_url']}")
    if op.get('before_state'):
        print(f"  Before: {op['before_state']['url']} | {op['before_state']['title']}")
        print(f"  DOM changed: {op['before_state']['dom_html'] != op['after_state']['dom_html'] if op.get('after_state') else 'unknown'}")
    print(f"  APIs captured: {len(op['api_calls'])}")
    for api in op['api_calls'][:3]:
        print(f"    {api['request']['method']} {api['request']['url'][:60]}")
        if api.get('response', {}).get('body'):
            print(f"    Response body preview: {api['response']['body'][:200]}...")
```

### Workflow E: Human-in-the-Loop Authenticated Explore (NEW)

Use when the target requires login and user can interact with browser.

**This is the MOST RELIABLE way to explore authenticated sites.**

```
1. python -m weblica explore <URL> -o ./explored --depth 2 --agent-mode --no-headless
2. Orchestrator detects login page → browser window STAYS OPEN
3. Tell user: "Please complete login in the browser window"
4. Orchestrator polls page state with _wait_for_browser_login()
5. Login detected automatically → BFS continues with authenticated session
6. All subsequent pages are explored with the login session
```

**How it works internally:**
- `_process_page_phase1()` navigates and detects obstacles
- If LOGIN_REQUIRED: page is NOT closed, yields to agent
- Agent returns `manual` decision
- `_wait_for_browser_login()` polls for:
  - Logout button / user profile text appearing
  - URL changing away from login page
  - Password input disappearing
  - Page navigation after form submit
- Upon detection, `_process_page_phase2()` analyzes and saves the page

### Workflow D: Authenticated Explore (Traditional Methods)

Use when user has cookies or tokens ready.

**Option 1: Cookie injection**
```
python -m weblica explore <URL> -o ./explored --cookies ./cookies.json
```

**Option 2: Bearer token**
```
python -m weblica explore <URL> -o ./explored --bearer-token <TOKEN>
```

**Option 3: Reuse saved auth state**
```
python -m weblica explore <URL> -o ./explored --auth-state-file ./weblica-auth-state.json
```

### Workflow B: Deep Crawl with Analysis

Use when user wants to understand site architecture.

```
1. python -m weblica explore <URL> -o ./explored --depth 2 --agent-mode
2. Read navigation.json for site structure and page hierarchy
3. Read analysis/page_001/index.json for overview (note parent_url, depth)
4. Read analysis/page_001/metadata.json for frameworks
5. Read analysis/page_001/network.json for API endpoints and traffic (includes response bodies)
6. Read analysis/page_001/interactions.json for buttons, links, forms with selectors
7. Read analysis/page_001/snapshots.json for DOM changes after interactions
8. Read weblica-manifest.json for asset inventory
```

### Workflow C: Interaction Recording → Replay on Explored Site

Use when user wants to test if explored site supports the same interactions.

```
1. python -m weblica record <URL> --duration 30 -o session.json
2. python -m weblica replay -d ./explored -p 8080
3. (Python API) Load session and replay on http://localhost:8080/index.html
```

## Agent Execution Guidelines

### Hybrid Mode: SUPERVISED vs STEPPED

The orchestrator supports two granularity levels, and the agent can switch dynamically:

| Mode | Granularity | Yield Points | Use When |
|------|-------------|--------------|----------|
| **SUPERVISED** | Per-page | Checkpoints B (obstacles) and F (queue decision) | Most exploration jobs — fast, agent reviews results |
| **STEPPED** | Per-action | Checkpoints A, B, C, D, E, F | Complex pages requiring precise interaction |

**Dynamic switching:** The agent can `switch_mode` at any checkpoint:
```json
{"action": "switch_mode", "params": {"mode": "stepped", "after_switch": "continue"}}
```

### STEPPED Mode: Atomic Actions

When in STEPPED mode, the agent can instruct these atomic operations at checkpoints A-E:

| Action | Params | Description |
|--------|--------|-------------|
| `scroll` | `direction: bottom/top/down/up`, `amount` | Scroll the page |
| `click` | `selector` or `target` | Click an element |
| `input` | `selector`, `value` | Fill an input field |
| `wait` | `ms` | Wait N milliseconds |
| `screenshot` | `path` | Capture page screenshot |
| `continue` | — | Proceed to next checkpoint |
| `skip` | — | Skip current page |
| `abort` | — | Stop entire exploration job |
| `switch_mode` | `mode`, `after_switch` | Toggle SUPERVISED/STEPPED |

**Checkpoint F (Queue Decision) actions:**
- `continue` — Queue discovered links normally (subject to MAX_QUEUE_LINKS=30 safety limit)
- `filter_links` — Provide `filter: [...]` or `exclude: [...]` in `action_params` to control which links are queued
- `filter_links` with `include_categories` — Provide `include_categories: ["sidebar_menu"]` to queue only links from specific categories (sidebar_menu, toolbar, pagination, content)

**Checkpoint F observation structure (available to agent):**
```json
{
  "page_summary": {
    "title": "Dashboard",
    "url": "https://example.com/admin",
    "depth": 1,
    "total_links": 45,
    "links_summary": {
      "by_category": {"sidebar_menu": 17, "toolbar": 3, "pagination": 20, "content": 5},
      "samples": {
        "sidebar_menu": [{"text": "Articles", "href": "...", "selector": "a.nav-link"}]
      }
    },
    "has_iframe": true,
    "interactive_elements": {"buttons": 4, "inputs": 7, "forms": 1}
  },
  "file_references": {
    "dom_html": "analysis/page_002/dom.html",
    "iframe_html": "analysis/page_002/iframe_00.html",
    "interactions_json": "analysis/page_002/interactions.json",
    "network_json": "analysis/page_002/network.json",
    "screenshot_png": "analysis/page_002/screenshot.png"
  },
  "queue_size": 0,
  "current_depth": 1,
  "discovered_links": ["https://example.com/admin/articles", "..."]
}
```
- `page_summary.links_summary` — Categorized link counts and representative samples (max 8 per category)
- `file_references` — Paths to saved analysis files on disk for deep inspection
- **Agent strategy:** Read `page_summary` for quick decisions; read `file_references.*` for deep analysis when needed

### Before Running

1. **Verify environment:** Check Python packages and Playwright browser are installed.
2. **Check output directory:** If it already exists, warn the user or use a new name to avoid overwriting.
3. **Respect depth:** Default depth=1 is safe. Only increase to 2+ if user explicitly requests deep crawling.

### During Execution

1. **Explore output is verbose:** The tool prints progress lines. Capture stderr/stdout to show the user.
2. **Headless by default:** Use `--no-headless` only when debugging or if the user needs to see the browser.
3. **Proxy support:** If the user is in a restricted network, ask if they need a proxy before exploring.
4. **Authentication:** If the target requires login, recommend **Workflow E** (human-in-the-loop with `--agent-mode --no-headless`):
   - It is more reliable than `--wait-login` because the page stays open
   - The orchestrator detects login success automatically
   - No need to export cookies or find tokens
   - If user cannot use browser window, fall back to cookies/token methods

### After Execution

1. **Always report the output directory path.**
2. **Mention key findings:** Number of pages explored, number of assets, detected frameworks (from analysis JSON).
3. **For replay:** Provide the exact localhost URL to open.
4. **For comparison:** Report visual diff percentage and show image paths.
5. **For authenticated explores:** Note that the exploration captured the post-login state.

### Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| `Browser not launched` | Playwright browser not installed | Run `playwright install chromium` |
| `TimeoutError` | Page load too slow or blocked | Increase timeout or check proxy/network |
| `404 on assets` | CDN-referenced resources | Expected — some cross-origin assets may fail |
| `PIL not available` | Pillow not installed | Install with `pip install Pillow` for diff images |
| `Address already in use` | Port occupied | Use `-p <other_port>` for replay |
| `CAPTCHA detected` | Page requires CAPTCHA solving | Use `--agent-mode --no-headless` for manual solving |

## Output File Formats

### `analysis/page_NNN/` directory

Each explored page gets its own directory with split category files:

**`index.json`** — Quick overview + navigation context
- `page_index`, `url`, `title`, `depth` (BFS depth), `parent_url` (where this page was discovered from)
- `assets_count`, `links_count`, `forms_count`, `api_calls_count`
- `files` — manifest pointing to other files in the directory

**`metadata.json`** — High-level page info
- `url`, `title`, `description`, `meta_tags`, `favicon`, `frameworks`

**`dom.html`** — Complete page HTML (open directly in browser)
- Full `document.documentElement.outerHTML` snapshot at explore time
- Use this to understand the visual structure and extract templates

**`assets.json`** — Asset inventory
- `stylesheets`, `scripts`, `images`, `fonts`

**`links.json`** — Discovered internal links (URL strings)

**`forms.json`** — Interactive elements (backward-compatible)
- `forms`, `buttons` (text-only list)

**`interactions.json`** — Enhanced interactive elements (NEW)
- `buttons_detailed` — Each button with `selector`, `text`, `tag`, `href`, `onclick`, `class`, `id`
- `links_detailed` — Each link with `selector`, `text`, `url`, `title`, `class`, `id`, `target`
- `interactive_elements` — Inputs, textareas, selects with `selector`, `type`, `name`, `placeholder`, `value`, `label`, `required`
- Use this to reverse-engineer click handlers, navigation targets, and form structures

**`network.json`** — Network traffic with FULL response bodies (NEW)
- `api_endpoints` — Discovered API patterns
- `api_summary` — Detailed API calls with complete `request.headers`, `request.post_data`, `response.body`, `response.body_truncated`
- `network_operations` — Full operation chains (navigate → click → wait) with before/after states and all traffic
- **Agent tip:** Read `api_summary` to understand backend data structures without reverse-engineering minified JS

**`snapshots.json`** — DOM before/after for interactions (NEW)
- Records `body.innerHTML` before and after auto-triggered interactions (scroll, click "load more")
- Each entry: `operation_id`, `action`, `target` (selector), `before.dom_html`, `after.dom_html`
- Use this to see what content JS dynamically injects into the page

**`iframe_meta.json`** — iframe metadata per page (NEW)
- Array of iframe descriptors: `index`, `src`, `actual_url`, `name`, `id`, `html_length`, `method` (`frame_evaluate` or `contentDocument_fallback`)
- Includes error entries for cross-origin frames that could not be accessed
- Use this to understand which content is loaded inside iframes and whether it matches another explored page

### `navigation.json` (root directory) — Site-wide page tree (NEW)
- `pages` — Flat list of all pages with `page_index`, `url`, `title`, `depth`, `parent_url`
- `tree.by_parent` — Map of parent URL → list of child URLs
- `tree.by_depth` — Map of depth level → list of URLs at that level
- `tree.root` — List of entry-point URLs (no parent)
- Use this to reconstruct the site's routing hierarchy and navigation flow

### `iframe_route_map.json` (root directory) — iframe routing map (NEW)
- Array of route entries mapping container pages to their iframe content
- Each entry: `container_dir`, `container_url`, `container_title`, `iframe_src`, `iframe_absolute_url`, `matched_content_page`
- `matched_content_page` links to the standalone explored page that corresponds to the iframe URL (if found)
- **Critical for iframe-based architectures** (e.g., AdminLTE with tab-iframes): reveals how the outer shell routes to inner content

### `weblica-manifest.json`

Explore metadata:
- `total_pages`, `total_assets`
- `pages` — List of all explored URLs
- `blocked` — URLs that required manual intervention
- `skipped` — URLs agent chose to skip
- `assets` — Map of original URL → local relative path

### `.weblica-state.json`

AgentOrchestrator resume state:
- `visited_urls`, `completed_urls`, `blocked_urls`, `skipped_urls`
- `url_queue` — Remaining pages to crawl
- Allows safe interruption and resumption of exploration jobs

## Best Practices

- **Agent-mode is recommended for most exploration jobs.** It provides supervision, obstacle detection, and human-in-the-loop support.
- **Single-page exploration** is most reliable. Deep crawling may hit rate limits or anti-bot measures.
- **SPA (React/Vue/Angular)** exploration captures the hydrated DOM but dynamic data from APIs will be frozen at explore-time state.
- **Large sites:** Explore depth 1 first, inspect results, then decide if deeper crawling is needed.
- **Stealth:** CloakBrowser handles basic detection, but advanced WAFs (Cloudflare, Akamai) may still challenge automation. In such cases, use `--agent-mode --no-headless` for manual intervention.
- **Auth state reuse:** After a successful `--agent-mode --no-headless` run with login, the `.weblica-state.json` preserves the exploration progress. The browser cookies from the session are also preserved in the context.

## Dependencies

- `playwright>=1.40.0`
- `aiohttp>=3.9.0`
- `aiofiles>=23.0.0`
- `Pillow>=10.0.0`
