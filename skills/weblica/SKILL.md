# Weblica Skill

## Description

Intelligent Web Application Cloning & Replaying Tool powered by CloakBrowser (CloakHQ patched Chromium), NetworkInterceptor (dynamic HTTP request/response capture), and AgentOrchestrator (Agent-in-the-Loop supervision).

Use this skill when you need to:
- Clone a web application's frontend for offline analysis or local replay
- Capture and reproduce web page interactions for testing or demonstration
- Compare a cloned site against the original for visual regression
- Extract frontend assets, frameworks, and API endpoints from a target site
- **Intercept and record all dynamic API calls** triggered by page navigation and user interactions
- **Reverse-engineer a site's API surface** without reading minified JavaScript
- Perform stealth web crawling that bypasses basic anti-bot detection
- Clone sites that require authentication via human-in-the-loop cooperation

## When to Use

Trigger this skill when the user requests any of the following:
- "Clone this website" / "Copy this web app" / "Download this site"
- "Replay this web app locally" / "Host this cloned site"
- "Record interactions on this page" / "Automate clicking through this site"
- "Compare the clone with the original" / "Screenshot diff"
- "Analyze what frameworks this site uses" / "Extract frontend assets"
- "Clone a site that requires login" / "Clone behind authentication"
- Any request involving `weblica`, `CloakBrowser`, `playwright clone`, `stealth crawl`

## When NOT to Use

Do NOT use this skill for:
- General web scraping of data/tables (use dedicated scraping tools instead)
- Backend API testing without a browser context
- Penetration testing or attacking sites without explicit authorization
- Cloning sites the user does not own or have permission to clone

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

### 1. Clone a Website

```bash
python -m weblica clone <URL> [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output` | `./cloned` | Output directory |
| `--headless` | `True` | Run headless (set `--no-headless` to show browser) |
| `-d, --depth` | `1` | Max crawl depth (0 = single page, 2 = deep crawl) |
| `--proxy` | none | Proxy URL, e.g. `http://127.0.0.1:7890` |
| `--slow-mo` | none | Slow down by N ms for debugging |
| `--humanize` | `True` | Human-like mouse/keyboard/scroll behavior (CloakBrowser mode) |
| `--no-humanize` | `False` | Disable human-like behavior (faster, less stealthy) |
| `--agent-mode` | `False` | Enable Agent-in-the-Loop supervision (DFS, pause at obstacles) |
| `--agent-stepped` | `False` | Start in STEPPED mode: agent approves every atomic action |

**Authentication options for `clone`:**

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
│       ├── assets.json        # CSS, JS, images, fonts referenced by this page
│       ├── links.json         # Discovered internal links
│       ├── forms.json         # Forms and buttons (backward-compatible)
│       ├── interactions.json  # Enhanced interactive elements: buttons/links/inputs with selectors, events, hrefs
│       ├── network.json       # Full network traffic + API calls with COMPLETE request/response bodies
│       └── snapshots.json     # DOM before/after for interactive operations (click, scroll, etc.)
├── navigation.json            # Site-wide page tree: parent→children, depth groups
├── weblica-manifest.json      # Clone metadata
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
| `-d, --dir` | `./cloned` | Clone directory to serve |
| `-p, --port` | `8080` | HTTP server port |

**Agent note:** Start this in background if the user wants to continue working:
```bash
python -m weblica replay -d ./cloned -p 8080
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
| `-d, --dir` | `./cloned` | Clone directory |
| `-o, --output` | `./comparison` | Output dir for screenshots |

Produces: `original.png`, `clone.png`, `diff.png` (if Pillow available)

## Python API Reference

For programmatic control within agent workflows:

```python
import asyncio
from weblica import WebCloner, WebReplayer
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
        dashboard_links = [l for l in ctx.discovered_links if "dashboard" in l]
        if dashboard_links:
            ctx.action_params["filter"] = dashboard_links
        ctx.recommended_action = "continue"
        return ctx

    ctx.recommended_action = "continue"
    return ctx

async def workflow():
    async with AgentOrchestrator(
        start_url="https://example.com",
        output_dir="./cloned",
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

**`AgentOrchestrator`** — Hybrid-mode Agent-in-the-Loop cloning engine
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
- Browser page is KEPT OPEN when obstacles are detected
- State persisted to `.weblica-state.json` after each page

**`WebCloner`** — Main batch cloning engine
- `async clone(url: str) -> Path` — Start cloning
- `output_dir`, `headless`, `max_depth`, `proxy` — Config via constructor

**`WebReplayer`** — Local replay and testing
- `async start_server() -> str` — Returns server URL
- `async stop_server()` — Clean shutdown
- `async compare_visual(original_url, clone_url, output_dir) -> dict`
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

### Workflow A: Agent-in-the-Loop Clone → Replay → Compare (Recommended)

Use when user wants a full clone with agent supervision.

```
1. python -m weblica clone <URL> -o ./cloned --depth 2 --agent-mode
   # Or stepped mode for full control: --agent-mode --agent-stepped
2. Agent reviews decision contexts at each obstacle/completed page
3. Read analysis/page_*/index.json for overview, then deep-dive into category files
4. Read weblica-session.json for complete API call chains
5. python -m weblica compare <URL> -d ./cloned -o ./comparison
6. python -m weblica replay -d ./cloned -p 8080
```

**Analyzing captured API traffic:**
```python
import json

# Load session report
with open("cloned/weblica-session.json") as f:
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

### Workflow E: Human-in-the-Loop Authenticated Clone (NEW)

Use when the target requires login and user can interact with browser.

**This is the MOST RELIABLE way to clone authenticated sites.**

```
1. python -m weblica clone <URL> -o ./cloned --depth 2 --agent-mode --no-headless
2. Orchestrator detects login page → browser window STAYS OPEN
3. Tell user: "Please complete login in the browser window"
4. Orchestrator polls page state with _wait_for_browser_login()
5. Login detected automatically → DFS continues with authenticated session
6. All subsequent pages are cloned with the login session
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

### Workflow D: Authenticated Clone (Traditional Methods)

Use when user has cookies or tokens ready.

**Option 1: Cookie injection**
```
python -m weblica clone <URL> -o ./cloned --cookies ./cookies.json
```

**Option 2: Bearer token**
```
python -m weblica clone <URL> -o ./cloned --bearer-token <TOKEN>
```

**Option 3: Reuse saved auth state**
```
python -m weblica clone <URL> -o ./cloned --auth-state-file ./weblica-auth-state.json
```

### Workflow B: Deep Crawl with Analysis

Use when user wants to understand site architecture.

```
1. python -m weblica clone <URL> -o ./cloned --depth 2 --agent-mode
2. Read navigation.json for site structure and page hierarchy
3. Read analysis/page_001/index.json for overview (note parent_url, depth)
4. Read analysis/page_001/metadata.json for frameworks
5. Read analysis/page_001/network.json for API endpoints and traffic (includes response bodies)
6. Read analysis/page_001/interactions.json for buttons, links, forms with selectors
7. Read analysis/page_001/snapshots.json for DOM changes after interactions
8. Read weblica-manifest.json for asset inventory
```

### Workflow C: Interaction Recording → Replay on Clone

Use when user wants to test if cloned site supports the same interactions.

```
1. python -m weblica record <URL> --duration 30 -o session.json
2. python -m weblica replay -d ./cloned -p 8080
3. (Python API) Load session and replay on http://localhost:8080/index.html
```

## Agent Execution Guidelines

### Hybrid Mode: SUPERVISED vs STEPPED

The orchestrator supports two granularity levels, and the agent can switch dynamically:

| Mode | Granularity | Yield Points | Use When |
|------|-------------|--------------|----------|
| **SUPERVISED** | Per-page | Checkpoints B (obstacles) and F (queue decision) | Most clones — fast, agent reviews results |
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
| `abort` | — | Stop entire clone job |
| `switch_mode` | `mode`, `after_switch` | Toggle SUPERVISED/STEPPED |

**Checkpoint F (Queue Decision) actions:**
- `continue` — Queue discovered links normally
- `filter_links` — Provide `filter: [...]` or `exclude: [...]` in `action_params` to control which links are queued

### Before Running

1. **Verify environment:** Check Python packages and Playwright browser are installed.
2. **Check output directory:** If it already exists, warn the user or use a new name to avoid overwriting.
3. **Respect depth:** Default depth=1 is safe. Only increase to 2+ if user explicitly requests deep crawling.

### During Execution

1. **Clone output is verbose:** The tool prints progress lines. Capture stderr/stdout to show the user.
2. **Headless by default:** Use `--no-headless` only when debugging or if the user needs to see the browser.
3. **Proxy support:** If the user is in a restricted network, ask if they need a proxy before cloning.
4. **Authentication:** If the target requires login, recommend **Workflow E** (human-in-the-loop with `--agent-mode --no-headless`):
   - It is more reliable than `--wait-login` because the page stays open
   - The orchestrator detects login success automatically
   - No need to export cookies or find tokens
   - If user cannot use browser window, fall back to cookies/token methods

### After Execution

1. **Always report the output directory path.**
2. **Mention key findings:** Number of pages cloned, number of assets, detected frameworks (from analysis JSON).
3. **For replay:** Provide the exact localhost URL to open.
4. **For comparison:** Report visual diff percentage and show image paths.
5. **For authenticated clones:** Note that the clone captured the post-login state.

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

Each cloned page gets its own directory with split category files:

**`index.json`** — Quick overview + navigation context
- `page_index`, `url`, `title`, `depth` (DFS depth), `parent_url` (where this page was discovered from)
- `assets_count`, `links_count`, `forms_count`, `api_calls_count`
- `files` — manifest pointing to other files in the directory

**`metadata.json`** — High-level page info
- `url`, `title`, `description`, `meta_tags`, `favicon`, `frameworks`

**`dom.html`** — Complete page HTML (open directly in browser)
- Full `document.documentElement.outerHTML` snapshot at clone time
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

### `navigation.json` (root directory) — Site-wide page tree (NEW)
- `pages` — Flat list of all pages with `page_index`, `url`, `title`, `depth`, `parent_url`
- `tree.by_parent` — Map of parent URL → list of child URLs
- `tree.by_depth` — Map of depth level → list of URLs at that level
- `tree.root` — List of entry-point URLs (no parent)
- Use this to reconstruct the site's routing hierarchy and navigation flow

### `weblica-manifest.json`

Clone metadata:
- `total_pages`, `total_assets`
- `pages` — List of all cloned URLs
- `blocked` — URLs that required manual intervention
- `skipped` — URLs agent chose to skip
- `assets` — Map of original URL → local relative path

### `.weblica-state.json`

AgentOrchestrator resume state:
- `visited_urls`, `completed_urls`, `blocked_urls`, `skipped_urls`
- `url_queue` — Remaining pages to crawl
- Allows safe interruption and resumption of clone jobs

## Best Practices

- **Agent-mode is recommended for most clones.** It provides supervision, obstacle detection, and human-in-the-loop support.
- **Single-page clones** are most reliable. Deep crawling may hit rate limits or anti-bot measures.
- **SPA (React/Vue/Angular)** clones capture the hydrated DOM but dynamic data from APIs will be frozen at clone-time state.
- **Large sites:** Clone depth 1 first, inspect results, then decide if deeper crawling is needed.
- **Stealth:** CloakBrowser handles basic detection, but advanced WAFs (Cloudflare, Akamai) may still challenge automation. In such cases, use `--agent-mode --no-headless` for manual intervention.
- **Auth state reuse:** After a successful `--agent-mode --no-headless` run with login, the `.weblica-state.json` preserves the clone progress. The browser cookies from the session are also preserved in the context.

## Dependencies

- `playwright>=1.40.0`
- `aiohttp>=3.9.0`
- `aiofiles>=23.0.0`
- `Pillow>=10.0.0`
