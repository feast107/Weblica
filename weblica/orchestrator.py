"""
AgentOrchestrator - Agent-in-the-Loop Cloning Engine

Replaces the "fire-and-forget" batch cloning model with an event-driven,
agent-supervised workflow. The orchestrator pauses at key decision points,
builds a structured context for the agent, and resumes only after the agent
chooses an action.

CRITICAL DESIGN: When an obstacle (login, CAPTCHA) is detected, the browser
page is KEPT OPEN. The user can interact with the real browser window to
solve the obstacle. The orchestrator polls the page state and automatically
continues once the obstacle is cleared.

Design principles:
1. Depth-First Search (DFS) traversal
2. Every page is a "decision unit" - agent sees, thinks, acts
3. State is persisted after each step - safe to interrupt / resume
4. Obstacles (auth, CAPTCHA, errors) are surfaced to agent, not swallowed
5. Browser page stays alive during agent decision / user interaction
"""

import json
import asyncio
from enum import Enum, auto
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List, Callable, Awaitable
from urllib.parse import urlparse

from playwright.async_api import Page

from .browser import CloakBrowser
from .analyzer import SmartAnalyzer, PageAnalysis
from .auth import AuthManager, AuthConfig
from .cloner import WebCloner
from .interceptor import NetworkInterceptor, SessionRecorder, PageOperation


class ClonePhase(Enum):
    """Current phase of a page clone operation."""
    IDLE = auto()
    NAVIGATING = auto()
    AUTH_CHECKING = auto()
    ANALYZING = auto()
    DECIDING = auto()
    AUTHENTICATING = auto()
    ASSET_DOWNLOADING = auto()
    PERSISTING = auto()
    COMPLETED = auto()
    SKIPPED = auto()
    BLOCKED = auto()


class ObstacleType(Enum):
    """Types of obstacles that require agent intervention."""
    NONE = auto()
    LOGIN_REQUIRED = auto()
    CAPTCHA = auto()
    RATE_LIMITED = auto()
    ACCESS_DENIED = auto()
    ERROR_PAGE = auto()
    CONFIRMATION_REQUIRED = auto()
    DYNAMIC_CONTENT_NOT_LOADED = auto()
    UNKNOWN = auto()


class AgentMode(Enum):
    """Agent supervision mode."""
    SUPERVISED = "supervised"   # Coarse-grained: agent介入 at page completion (方案2)
    STEPPED = "stepped"         # Fine-grained: agent介入 at every atomic action (方案4)


@dataclass
class PageSnapshot:
    """Lightweight snapshot of a page for agent decision-making."""
    url: str
    title: str
    depth: int
    status: Optional[str] = None
    text_preview: str = ""
    has_login_form: bool = False
    has_captcha: bool = False
    error_indicators: List[str] = field(default_factory=list)
    screenshot_path: Optional[str] = None


@dataclass
class DecisionContext:
    """
    Complete context presented to the agent at a decision point.
    The agent reads this, chooses an action, and the orchestrator resumes.
    
    In STEPPED mode, the agent sees every atomic operation and decides
    the next action. In SUPERVISED mode, the agent only sees high-level
    page results and can switch modes for complex pages.
    """
    phase: ClonePhase
    obstacle: ObstacleType
    
    snapshot: PageSnapshot
    full_analysis: Optional[PageAnalysis] = None
    
    discovered_links: List[str] = field(default_factory=list)
    discovered_assets: int = 0
    
    parent_url: Optional[str] = None
    previous_decisions: List[Dict[str, Any]] = field(default_factory=list)
    
    time_spent_ms: int = 0
    retry_count: int = 0
    
    recommended_action: str = "continue"
    action_params: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    
    # Hybrid mode support
    mode: str = "supervised"
    available_actions: List[str] = field(default_factory=list)
    observation: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CloneState:
    """Persisted state of the entire clone job."""
    start_url: str
    max_depth: int
    visited_urls: List[str] = field(default_factory=list)
    completed_urls: List[str] = field(default_factory=list)
    blocked_urls: List[Dict[str, Any]] = field(default_factory=list)
    skipped_urls: List[str] = field(default_factory=list)
    url_queue: List[tuple] = field(default_factory=list)
    auth_state_file: Optional[str] = None
    
    def save(self, path: str):
        Path(path).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
    
    @staticmethod
    def load(path: str) -> "CloneState":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return CloneState(**{k: v for k, v in data.items()})


class AgentOrchestrator:
    """
    Main orchestrator that drives the clone with agent supervision.
    
    Key difference from batch cloner: the browser PAGE stays open when an
    obstacle is detected, allowing the user to interact with the real browser
    window to solve login/CAPTCHA challenges.
    """

    def __init__(
        self,
        start_url: str,
        output_dir: str = "./cloned",
        max_depth: int = 2,
        headless: bool = True,
        proxy: Optional[str] = None,
        auth_manager: Optional[AuthManager] = None,
        decision_callback: Optional[Callable[[DecisionContext], Awaitable[DecisionContext]]] = None,
        state_file: Optional[str] = None,
        humanize: bool = True,
        agent_mode: str = "supervised",
    ):
        self.start_url = start_url
        self.output_dir = Path(output_dir)
        self.max_depth = max_depth
        self.headless = headless
        self.proxy = proxy
        self.auth_manager = auth_manager
        self.decision_callback = decision_callback
        self.state_file = state_file or str(self.output_dir / ".weblica-state.json")
        self.humanize = humanize
        self.agent_mode = AgentMode(agent_mode)
        
        self.cloner: Optional[WebCloner] = None
        self.state: Optional[CloneState] = None
        self.analyzer = SmartAnalyzer()
        self.recorder = SessionRecorder()
        
        # The currently open page (kept alive during agent decisions)
        self._active_page: Optional[Page] = None
        
        # Network interceptor for the current page
        self._interceptor: Optional[NetworkInterceptor] = None
        
        # Last decision context (for stepped mode checkpoint communication)
        self._last_decision_ctx: Optional[DecisionContext] = None

    async def __aenter__(self):
        self.cloner = WebCloner(
            output_dir=str(self.output_dir),
            headless=self.headless,
            max_depth=self.max_depth,
            proxy=self.proxy,
            auth_manager=self.auth_manager,
            humanize=self.humanize,
        )
        await self.cloner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_active_page()
        if self.cloner:
            await self.cloner.__aexit__(exc_type, exc_val, exc_tb)

    async def _close_active_page(self):
        """Safely close the active page if one exists."""
        if self._interceptor:
            self._interceptor.stop()
            self._interceptor = None
        if self._active_page:
            try:
                await self._active_page.close()
            except Exception:
                pass
            self._active_page = None

    # ------------------------------------------------------------------
    # Hybrid-mode Agent helpers
    # ------------------------------------------------------------------

    async def _agent_decide(
        self,
        ctx: DecisionContext,
        actions: List[str],
        observation: Dict[str, Any] = None,
    ) -> DecisionContext:
        """
        Unified agent decision entry point.
        
        STEPPED mode: calls decision_callback so the agent can choose the
        next atomic action (scroll, click, input, wait, continue, skip, etc.).
        
        SUPERVISED mode: automatically sets recommended_action='continue',
        letting the tool run the standard fast path.
        
        Either mode supports 'switch_mode' to dynamically toggle granularity.
        """
        ctx.mode = self.agent_mode.value
        ctx.available_actions = actions
        ctx.observation = observation or {}

        if self.agent_mode == AgentMode.STEPPED and self.decision_callback:
            print(f"[ORCH] Checkpoint {ctx.phase.name} | actions={actions}")
            ctx = await self.decision_callback(ctx)

            # Handle dynamic mode switching
            if ctx.recommended_action == "switch_mode":
                new_mode = ctx.action_params.get(
                    "mode",
                    "supervised" if self.agent_mode == AgentMode.STEPPED else "stepped",
                )
                self.agent_mode = AgentMode(new_mode)
                print(f"[ORCH] Agent switched mode -> {new_mode}")
                # Consume the switch and use the follow-up action
                ctx.recommended_action = ctx.action_params.get("after_switch", "continue")
        else:
            # SUPERVISED: auto-continue unless the action itself is abort/skip
            if ctx.recommended_action not in ("abort", "skip"):
                ctx.recommended_action = "continue"

        self._last_decision_ctx = ctx
        return ctx

    async def _observe_page(self, page: Page) -> Dict[str, Any]:
        """Collect lightweight observation data for agent decision-making."""
        try:
            url = page.url
            title = await page.title()

            # Visible interactive elements
            buttons = await page.evaluate("""
                () => Array.from(document.querySelectorAll('button, a[href], [role="button"], input[type="submit"]'))
                    .filter(el => {
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    })
                    .map(el => ({
                        tag: el.tagName.toLowerCase(),
                        text: (el.textContent || el.value || '').trim().slice(0, 50),
                        id: el.id || '',
                        class: (el.className || '').toString().split(' ')[0],
                        href: el.href || '',
                    }))
                    .slice(0, 20)
            """)

            inputs = await page.evaluate("""
                () => Array.from(document.querySelectorAll('input, textarea, select'))
                    .filter(el => {
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    })
                    .map(el => ({
                        type: el.type || el.tagName.toLowerCase(),
                        name: el.name || '',
                        placeholder: el.placeholder || '',
                        id: el.id || '',
                    }))
                    .slice(0, 10)
            """)

            scroll = await page.evaluate("""
                () => ({
                    scrollY: window.scrollY,
                    scrollHeight: document.body.scrollHeight,
                    clientHeight: window.innerHeight,
                    atBottom: (window.scrollY + window.innerHeight) >= document.body.scrollHeight - 100
                })
            """)

            modals = await page.evaluate("""
                () => Array.from(document.querySelectorAll('.modal, [role="dialog"], .overlay, .popup, .toast, .ant-modal, .el-dialog'))
                    .map(el => ({
                        className: el.className || '',
                        id: el.id || '',
                        visible: el.offsetParent !== null,
                    }))
                    .slice(0, 5)
            """)

            return {
                "url": url,
                "title": title,
                "buttons": buttons,
                "inputs": inputs,
                "scroll": scroll,
                "modals": modals,
            }
        except Exception as e:
            return {"error": str(e), "url": getattr(page, 'url', 'unknown')}

    async def _execute_action(self, page: Page, action: str, params: Dict[str, Any]):
        """Execute a single atomic action instructed by the agent."""
        target = params.get("target", "") or params.get("selector", "")

        if action == "scroll":
            direction = params.get("direction", "bottom")
            amount = params.get("amount", "0.8")
            if direction == "bottom":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "top":
                await page.evaluate("window.scrollTo(0, 0)")
            elif direction == "down":
                await page.evaluate(f"window.scrollBy(0, window.innerHeight * {amount})")
            elif direction == "up":
                await page.evaluate(f"window.scrollBy(0, -window.innerHeight * {amount})")
            print(f"    [AGENT] Scroll {direction}")
            await asyncio.sleep(1.5)

        elif action == "click":
            selector = target
            if selector:
                try:
                    await page.click(selector)
                    print(f"    [AGENT] Click: {selector}")
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"    [AGENT] Click failed: {selector} -> {e}")

        elif action == "input":
            selector = target
            value = params.get("value", "")
            if selector and value:
                try:
                    await page.fill(selector, value)
                    print(f"    [AGENT] Input: {selector} = {value}")
                except Exception as e:
                    print(f"    [AGENT] Input failed: {selector} -> {e}")

        elif action == "wait":
            ms = params.get("ms", 2000)
            print(f"    [AGENT] Wait {ms}ms")
            await asyncio.sleep(ms / 1000)

        elif action == "screenshot":
            path = params.get("path", f"screenshot_{int(asyncio.get_event_loop().time())}.png")
            try:
                await page.screenshot(path=str(self.output_dir / path))
                print(f"    [AGENT] Screenshot: {path}")
            except Exception as e:
                print(f"    [AGENT] Screenshot failed: {e}")

    # ------------------------------------------------------------------
    # Core DFS loop (hybrid mode)
    # ------------------------------------------------------------------

    async def run_dfs(self):
        """
        Hybrid-mode DFS clone with agent decision points.
        
        SUPERVISED mode (方案2): Agent介入 at page completion. Fast path.
        STEPPED mode (方案4): Agent介入 at every atomic action. Full control.
        
        The agent can dynamically switch modes via 'switch_mode' action.
        """
        print(f"[ORCH] Starting DFS in {self.agent_mode.value.upper()} mode")
        
        # Initialize or resume state
        if Path(self.state_file).exists():
            print(f"[ORCH] Resuming from state file: {self.state_file}")
            self.state = CloneState.load(self.state_file)
        else:
            self.state = CloneState(
                start_url=self.start_url,
                max_depth=self.max_depth,
                url_queue=[(self.start_url, 0, None)],
            )
        
        # Ensure output dirs exist
        assets_dir = self.output_dir / "assets"
        for subdir in ["css", "js", "images", "fonts", "api"]:
            (assets_dir / subdir).mkdir(parents=True, exist_ok=True)
        
        while self.state.url_queue:
            url, depth, parent = self.state.url_queue.pop()  # DFS: LIFO
            
            if url in self.state.visited_urls:
                continue
            if depth > self.max_depth:
                continue
            
            self.state.visited_urls.append(url)
            
            # =============================================================
            # PHASE 1: Navigate & detect obstacles
            # =============================================================
            ctx = await self._process_page_phase1(url, depth, parent)
            
            # Checkpoint A: Post-navigation (STEPPED mode only)
            if self.agent_mode == AgentMode.STEPPED and ctx.obstacle == ObstacleType.NONE:
                ctx = await self._agent_decide(
                    ctx,
                    actions=["analyze", "scroll", "click", "wait", "screenshot", "skip", "switch_mode", "abort"],
                    observation=await self._observe_page(self._active_page),
                )
                yield ctx
                if ctx.recommended_action == "abort":
                    break
                if ctx.recommended_action == "skip":
                    self.state.skipped_urls.append(url)
                    await self._close_active_page()
                    continue
                if ctx.recommended_action in ("scroll", "click", "input", "wait", "screenshot"):
                    await self._execute_action(self._active_page, ctx.recommended_action, ctx.action_params)
            
            # Checkpoint B: Obstacle handling (BOTH modes)
            if ctx.obstacle != ObstacleType.NONE:
                ctx = await self._agent_decide(
                    ctx,
                    actions=["retry", "skip", "manual", "auth", "abort"],
                )
                yield ctx
                
                if ctx.recommended_action == "abort":
                    break
                elif ctx.recommended_action == "skip":
                    self.state.skipped_urls.append(url)
                    await self._close_active_page()
                    continue
                elif ctx.recommended_action == "retry":
                    if self._active_page and ctx.obstacle == ObstacleType.LOGIN_REQUIRED:
                        logged_in = await self._wait_for_browser_login(self._active_page, timeout=600)
                        if logged_in:
                            ctx.obstacle = ObstacleType.NONE
                        else:
                            self.state.blocked_urls.append({
                                "url": url,
                                "reason": ctx.notes or "login not completed",
                                "snapshot": asdict(ctx.snapshot),
                            })
                            await self._close_active_page()
                            continue
                    else:
                        self.state.visited_urls.remove(url)
                        self.state.url_queue.append((url, depth, parent))
                        await self._close_active_page()
                        continue
                elif ctx.recommended_action == "auth":
                    await self._apply_agent_auth(ctx.action_params)
                    self.state.visited_urls.remove(url)
                    self.state.url_queue.append((url, depth, parent))
                    await self._close_active_page()
                    continue
                elif ctx.recommended_action == "manual":
                    if self._active_page and ctx.obstacle == ObstacleType.LOGIN_REQUIRED:
                        logged_in = await self._wait_for_browser_login(self._active_page, timeout=600)
                        if logged_in:
                            ctx.obstacle = ObstacleType.NONE
                        else:
                            self.state.blocked_urls.append({
                                "url": url,
                                "reason": ctx.notes or "manual login not completed",
                                "snapshot": asdict(ctx.snapshot),
                            })
                            await self._close_active_page()
                            continue
                    else:
                        self.state.blocked_urls.append({
                            "url": url,
                            "reason": ctx.notes or "manual intervention requested",
                            "snapshot": asdict(ctx.snapshot),
                        })
                        await self._close_active_page()
                        continue
            
            # =============================================================
            # PHASE 2: Analyze, interact, download, persist (inline)
            # =============================================================
            if ctx.obstacle == ObstacleType.NONE and self._active_page:
                page = self._active_page
                page_idx = len(self.state.visited_urls)
                
                try:
                    # ---- 2.1 Analyze page ----
                    ctx.phase = ClonePhase.ANALYZING
                    analysis = await self.analyzer.analyze(page)
                    ctx.full_analysis = analysis
                    ctx.discovered_links = analysis.links[:20]
                    ctx.discovered_assets = (
                        len(analysis.stylesheets) + len(analysis.scripts) +
                        len(analysis.images) + len(analysis.fonts)
                    )
                    
                    # Record navigation traffic
                    nav_interactions = []
                    if self._interceptor:
                        nav_interactions = self._interceptor.stop_and_collect()
                        self._interceptor.clear()
                        self._interceptor.start()
                    
                    nav_op = PageOperation(
                        operation_id=len(self.recorder.operations) + 1,
                        page_url=url,
                        depth=depth,
                        action="navigate",
                        target=url,
                        interactions=nav_interactions,
                    )
                    self.recorder.operations.append(nav_op)
                    
                    api_count = len(nav_op.api_calls)
                    if api_count > 0:
                        print(f"    [API] Captured {api_count} API calls during navigation")
                        for api in nav_op.api_calls[:5]:
                            status = api.response.status if api.response else "?"
                            print(f"      {api.request.method} {api.request.url[:80]} -> {status}")
                    
                    # Checkpoint C: Post-analysis (STEPPED mode)
                    if self.agent_mode == AgentMode.STEPPED:
                        ctx = await self._agent_decide(
                            ctx,
                            actions=["continue", "scroll", "click", "input", "wait", "screenshot", "skip", "switch_mode", "abort"],
                            observation=await self._observe_page(page),
                        )
                        yield ctx
                        if ctx.recommended_action == "abort":
                            ctx.phase = ClonePhase.BLOCKED
                            await self._close_active_page()
                            break
                        if ctx.recommended_action == "skip":
                            ctx.phase = ClonePhase.SKIPPED
                            await self._close_active_page()
                            continue
                    
                    # ---- 2.2 Interact ----
                    if self.agent_mode == AgentMode.STEPPED:
                        # Agent-driven interaction loop
                        while ctx.recommended_action in ("scroll", "click", "input", "wait", "screenshot"):
                            await self._execute_action(page, ctx.recommended_action, ctx.action_params)
                            ctx = await self._agent_decide(
                                ctx,
                                actions=["continue", "scroll", "click", "input", "wait", "screenshot", "skip", "abort"],
                                observation=await self._observe_page(page),
                            )
                            yield ctx
                            if ctx.recommended_action in ("abort", "skip"):
                                break
                        
                        if ctx.recommended_action == "abort":
                            ctx.phase = ClonePhase.BLOCKED
                            await self._close_active_page()
                            break
                        if ctx.recommended_action == "skip":
                            ctx.phase = ClonePhase.SKIPPED
                            await self._close_active_page()
                            continue
                    else:
                        # SUPERVISED: automatic interactions
                        await self._auto_interact(page, url, depth)
                    
                    # ---- 2.3 Download assets ----
                    ctx.phase = ClonePhase.ASSET_DOWNLOADING
                    await self.cloner._download_assets(analysis, url)
                    
                    # Checkpoint D: Post-download (STEPPED mode)
                    if self.agent_mode == AgentMode.STEPPED:
                        ctx = await self._agent_decide(
                            ctx,
                            actions=["continue", "persist", "skip", "abort"],
                        )
                        yield ctx
                        if ctx.recommended_action == "abort":
                            ctx.phase = ClonePhase.BLOCKED
                            await self._close_active_page()
                            break
                        if ctx.recommended_action == "skip":
                            ctx.phase = ClonePhase.SKIPPED
                            await self._close_active_page()
                            continue
                    
                    # ---- 2.4 Persist HTML ----
                    ctx.phase = ClonePhase.PERSISTING
                    html = await self.cloner._rewrite_html(page, analysis, url)
                    page_filename = self.cloner._get_page_filename(url)
                    html_path = self.output_dir / page_filename
                    html_path.write_text(html, encoding="utf-8")
                    
                    # Checkpoint E: Post-persist (STEPPED mode)
                    if self.agent_mode == AgentMode.STEPPED:
                        ctx = await self._agent_decide(
                            ctx,
                            actions=["continue", "skip", "abort"],
                        )
                        yield ctx
                        if ctx.recommended_action == "abort":
                            ctx.phase = ClonePhase.BLOCKED
                            await self._close_active_page()
                            break
                        if ctx.recommended_action == "skip":
                            ctx.phase = ClonePhase.SKIPPED
                            await self._close_active_page()
                            continue
                    
                    # ---- 2.5 Save analysis split ----
                    await self._save_analysis_split(url, depth, analysis, page_idx)
                    
                    self.state.completed_urls.append(url)
                    ctx.phase = ClonePhase.COMPLETED
                    
                    print(f"    [OK] Completed: {page_filename} | Assets: {ctx.discovered_assets} | Links: {len(ctx.discovered_links)} | APIs: {api_count} | Analysis: analysis/page_{page_idx:03d}/")
                    
                except Exception as e:
                    print(f"    [ERR] Phase2 failed for {url}: {e}")
                    ctx.obstacle = ObstacleType.UNKNOWN
                    ctx.phase = ClonePhase.BLOCKED
            
            # Clean up page
            await self._close_active_page()
            
            # =============================================================
            # Checkpoint F: Queue decision (BOTH modes)
            # This is the "方案2" supervised intervention point.
            # =============================================================
            if ctx.phase == ClonePhase.COMPLETED and ctx.discovered_links:
                ctx = await self._agent_decide(
                    ctx,
                    actions=["continue", "filter_links", "add_link", "switch_mode", "abort"],
                    observation={
                        "queue_size": len(self.state.url_queue),
                        "discovered_links": ctx.discovered_links,
                        "current_depth": depth,
                    },
                )
                yield ctx
                
                if ctx.recommended_action == "abort":
                    break
                if ctx.recommended_action == "switch_mode":
                    pass  # Already handled inside _agent_decide
                
                # Apply link filtering if agent provided it
                links_to_queue = ctx.discovered_links
                if ctx.action_params.get("filter"):
                    allowed = set(ctx.action_params["filter"])
                    links_to_queue = [l for l in links_to_queue if l in allowed]
                if ctx.action_params.get("exclude"):
                    excluded = set(ctx.action_params["exclude"])
                    links_to_queue = [l for l in links_to_queue if l not in excluded]
                
                # Safety net: dangerous links
                DANGEROUS = ['logout', 'signout', 'exit', 'quit', 'sign-out', 'log-out']
                safe_links = [l for l in links_to_queue if not any(d in l.lower() for d in DANGEROUS)]
                if len(safe_links) < len(links_to_queue):
                    print(f"    [FILTER] Skipped {len(links_to_queue)-len(safe_links)} dangerous link(s)")
                
                new_items = [
                    (link, depth + 1, url)
                    for link in safe_links
                    if link not in self.state.visited_urls
                    and link not in [u for u, _, _ in self.state.url_queue]
                ]
                self.state.url_queue.extend(new_items)
            
            # Persist state after each page
            self.state.save(self.state_file)
        
        # Finalize
        await self._finalize()

    async def _process_page_phase1(self, url: str, depth: int, parent: Optional[str]) -> DecisionContext:
        """
        Phase 1: Open page, navigate, detect obstacles.
        Returns immediately when an obstacle is found, KEEPING THE PAGE OPEN.
        """
        snapshot = PageSnapshot(url=url, title="", depth=depth)
        ctx = DecisionContext(
            phase=ClonePhase.NAVIGATING,
            obstacle=ObstacleType.NONE,
            snapshot=snapshot,
            parent_url=parent,
        )
        
        # Create new page and keep reference
        page = await self.cloner.browser.new_page()
        self._active_page = page
        
        # Start network interceptor immediately to capture all traffic
        self._interceptor = NetworkInterceptor(page)
        self._interceptor.start()
        
        try:
            # Auth injection
            if self.auth_manager and depth == 0 and len(self.state.visited_urls) == 1:
                await self.auth_manager.apply_to_context(page.context, url)
            if self.auth_manager:
                await self.auth_manager.apply_to_page(page)
            
            # Navigate
            print(f"  [PAGE] Navigating: {url} (depth={depth})")
            response = await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)
            
            snapshot.title = await page.title()
            snapshot.status = str(response.status) if response else "unknown"
            
            # Auth checking
            ctx.phase = ClonePhase.AUTH_CHECKING
            body_text = await page.evaluate("() => document.body.innerText")
            snapshot.text_preview = body_text[:500] if body_text else ""
            
            # Check for login page
            login_keywords = ["登录", "login", "sign in", "注册", "register", "密码", "password", "账号", "account"]
            if any(kw in body_text.lower() for kw in login_keywords):
                has_form = await page.evaluate("""
                    () => document.querySelectorAll('input[type="password"], input[name*="pass"], form[action*="login"], form[action*="signin"]').length > 0
                """)
                if has_form:
                    snapshot.has_login_form = True
                    ctx.obstacle = ObstacleType.LOGIN_REQUIRED
                    ctx.notes = f"Login form detected. Title: {snapshot.title}"
                    print(f"    [AUTH] Login page detected: {snapshot.title}")
                    print(f"    [AUTH] Browser page is KEPT OPEN. Please login in the browser window.")
                    return ctx  # PAGE STAYS OPEN
            
            # Check for CAPTCHA
            if self.auth_manager:
                captcha = await self.auth_manager.detect_captcha(page)
                if captcha:
                    snapshot.has_captcha = True
                    ctx.obstacle = ObstacleType.CAPTCHA
                    ctx.notes = f"CAPTCHA: {captcha}"
                    print(f"    [AUTH] CAPTCHA detected: {captcha}")
                    return ctx  # PAGE STAYS OPEN
            
            # Check for access denied
            error_indicators = []
            if response and response.status >= 400:
                error_indicators.append(f"HTTP {response.status}")
            for et in ["access denied", "forbidden", "unauthorized", "403", "401", "禁止访问", "无权限", "需要登录"]:
                if et in body_text.lower():
                    error_indicators.append(et)
            if error_indicators:
                snapshot.error_indicators = error_indicators
                ctx.obstacle = ObstacleType.ACCESS_DENIED
                ctx.notes = f"Access issues: {', '.join(error_indicators)}"
                return ctx  # PAGE STAYS OPEN
            
        except Exception as e:
            ctx.obstacle = ObstacleType.UNKNOWN
            ctx.notes = f"Exception: {str(e)}"
            ctx.phase = ClonePhase.BLOCKED
            print(f"    [ERR] {url}: {e}")
        
        return ctx

    async def _save_analysis_split(self, url: str, depth: int, analysis: PageAnalysis, page_idx: int):
        """Save analysis as split files under analysis/page_NNN/ directory."""
        # Build full analysis data with network traffic included
        analysis_data = json.loads(self.analyzer.export_json(analysis))
        analysis_data["network_operations"] = [
            op.to_dict() for op in self.recorder.operations
            if op.page_url == url
        ]
        analysis_data["api_summary"] = [
            {
                "url": api.request.url,
                "method": api.request.method,
                "status": api.response.status if api.response else None,
                "resource_type": api.request.resource_type,
                "duration_ms": api.duration_ms,
            }
            for op in self.recorder.operations
            if op.page_url == url
            for api in op.api_calls
        ]
        
        analysis_dir = self.output_dir / "analysis" / f"page_{page_idx:03d}"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. metadata.json
        metadata = {
            "url": analysis_data.get("url"),
            "title": analysis_data.get("title"),
            "description": analysis_data.get("description"),
            "meta_tags": analysis_data.get("meta_tags", []),
            "favicon": analysis_data.get("favicon"),
            "frameworks": analysis_data.get("frameworks", []),
        }
        (analysis_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        
        # 2. dom.json
        dom = {
            "html_structure": analysis_data.get("html_structure", {}),
            "body_text": analysis_data.get("body_text", ""),
        }
        (analysis_dir / "dom.json").write_text(
            json.dumps(dom, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        
        # 3. assets.json
        assets = {
            "stylesheets": analysis_data.get("stylesheets", []),
            "scripts": analysis_data.get("scripts", []),
            "images": analysis_data.get("images", []),
            "fonts": analysis_data.get("fonts", []),
        }
        (analysis_dir / "assets.json").write_text(
            json.dumps(assets, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        
        # 4. links.json
        links_data = {"links": analysis_data.get("links", [])}
        (analysis_dir / "links.json").write_text(
            json.dumps(links_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        
        # 5. forms.json
        forms_data = {
            "forms": analysis_data.get("forms", []),
            "buttons": analysis_data.get("buttons", []),
        }
        (analysis_dir / "forms.json").write_text(
            json.dumps(forms_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        
        # 6. network.json
        network_data = {
            "api_endpoints": analysis_data.get("api_endpoints", []),
            "api_summary": analysis_data.get("api_summary", []),
            "network_operations": analysis_data.get("network_operations", []),
        }
        (analysis_dir / "network.json").write_text(
            json.dumps(network_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        
        # index.json
        index = {
            "page_index": page_idx,
            "url": analysis_data.get("url"),
            "title": analysis_data.get("title"),
            "assets_count": (
                len(analysis_data.get("stylesheets", [])) +
                len(analysis_data.get("scripts", [])) +
                len(analysis_data.get("images", [])) +
                len(analysis_data.get("fonts", []))
            ),
            "links_count": len(analysis_data.get("links", [])),
            "forms_count": len(analysis_data.get("forms", [])),
            "api_calls_count": len(analysis_data.get("api_summary", [])),
            "files": {
                "metadata": "metadata.json",
                "dom": "dom.json",
                "assets": "assets.json",
                "links": "links.json",
                "forms": "forms.json",
                "network": "network.json",
            },
        }
        (analysis_dir / "index.json").write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    
    async def _auto_interact(self, page: Page, url: str, depth: int):
        """
        Perform automatic interactions to trigger lazy-loaded APIs.
        E.g., scroll to bottom, click 'load more' buttons.
        """
        interaction_count = 0
        
        # Interaction 1: Scroll to bottom to trigger infinite scroll / lazy load
        try:
            prev_height = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height > prev_height:
                interaction_count += 1
                print(f"    [INTERACT] Scrolled, page height {prev_height} -> {new_height}")
        except Exception:
            pass
        
        # Interaction 2: Click common "load more" / "show more" buttons
        load_more_selectors = [
            "button:has-text('加载更多')",
            "button:has-text('Load More')",
            "button:has-text('查看更多')",
            "button:has-text('Show More')",
            "a:has-text('加载更多')",
            "a:has-text('查看更多')",
            ".load-more",
            ".loadmore",
            "[data-action='load-more']",
            "button.btn-primary:has-text('更多')",
        ]
        
        for selector in load_more_selectors:
            try:
                if await page.is_visible(selector, timeout=500):
                    print(f"    [INTERACT] Clicking: {selector}")
                    
                    # Record pre-click state
                    if self._interceptor:
                        self._interceptor.stop()
                        click_interactions_before = list(self._interceptor._interactions)
                        self._interceptor.clear()
                        self._interceptor.start()
                    else:
                        click_interactions_before = []
                    
                    await page.click(selector)
                    await asyncio.sleep(2)  # Wait for API response
                    
                    # Record post-click traffic
                    click_interactions = []
                    if self._interceptor:
                        click_interactions = self._interceptor.stop_and_collect()
                        self._interceptor.clear()
                        self._interceptor.start()
                    
                    click_op = PageOperation(
                        operation_id=len(self.recorder.operations) + 1,
                        page_url=url,
                        depth=depth,
                        action="click",
                        target=selector,
                        interactions=click_interactions,
                    )
                    self.recorder.operations.append(click_op)
                    
                    api_count = len(click_op.api_calls)
                    if api_count > 0:
                        print(f"    [API] Click triggered {api_count} API calls")
                        for api in click_op.api_calls[:3]:
                            status = api.response.status if api.response else "?"
                            print(f"      {api.request.method} {api.request.url[:80]} -> {status}")
                    
                    interaction_count += 1
                    break  # Only click the first matching button
            except Exception:
                continue
        
        # Interaction 3: Wait for background polling / heartbeat
        try:
            await asyncio.sleep(2)
            wait_interactions = []
            if self._interceptor:
                wait_interactions = self._interceptor.stop_and_collect()
                self._interceptor.clear()
                self._interceptor.start()
            
            if wait_interactions:
                wait_op = PageOperation(
                    operation_id=len(self.recorder.operations) + 1,
                    page_url=url,
                    depth=depth,
                    action="wait",
                    interactions=wait_interactions,
                )
                self.recorder.operations.append(wait_op)
        except Exception:
            pass
        
        if interaction_count > 0:
            print(f"    [INTERACT] Performed {interaction_count} auto-interactions")
        
        return interaction_count

    async def _wait_for_browser_login(self, page: Page, timeout: int = 600) -> bool:
        """
        Poll the browser page to detect if user has completed login.
        The browser window stays open during this wait.
        
        Detection heuristics:
        1. Logout button / user profile appears
        2. URL changes away from login page
        3. Password input disappears
        4. Body text changes significantly
        """
        print(f"[ORCH] Polling browser for login success (timeout: {timeout}s)...")
        print("[ORCH] Please complete login in the browser window now.")
        
        start_time = asyncio.get_event_loop().time()
        check_interval = 2
        last_text = ""
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            remaining = timeout - elapsed
            
            if remaining <= 0:
                print("[ORCH] Login wait timeout reached.")
                return False
            
            try:
                current_url = page.url
                body_text = await page.evaluate("() => document.body.innerText")
                
                # Heuristic 1: Logout / user profile indicators
                has_logout = await page.evaluate("""
                    () => {
                        const t = document.body.innerText;
                        const indicators = ['logout', '退出', '登出', '我的', '个人中心', '用户中心', '管理中心', 'dashboard', '控制台'];
                        return indicators.some(i => t.includes(i));
                    }
                """)
                
                # Heuristic 2: URL no longer on login page
                not_login_url = all(x not in current_url.lower() for x in ["/login", "/signin", "/auth", "/user"])
                
                # Heuristic 3: No password inputs
                no_password = await page.evaluate('() => document.querySelectorAll("input[type=password]").length === 0')
                
                # Heuristic 4: Body text changed significantly (page navigated after login)
                text_changed = last_text and last_text != body_text[:200]
                last_text = body_text[:200]
                
                if has_logout:
                    print(f"[ORCH] Login detected! (logout/user indicator found)")
                    return True
                
                if not_login_url and no_password and elapsed > 5:
                    # If URL changed away from login and no password field, likely logged in
                    print(f"[ORCH] Login detected! (URL changed, no password field)")
                    return True
                
                if text_changed and not_login_url and elapsed > 3:
                    print(f"[ORCH] Login detected! (page navigated after form submit)")
                    return True
                
            except Exception as e:
                # Page might be navigating during check
                pass
            
            # Progress indicator every 10 seconds
            if int(elapsed) % 10 == 0 and int(elapsed) > 0:
                print(f"[ORCH] Still waiting for login... ({int(elapsed)}s / {timeout}s)")
            
            await asyncio.sleep(check_interval)

    async def _apply_agent_auth(self, params: Dict[str, Any]):
        """Apply authentication based on agent's action parameters."""
        method = params.get("method", "cookie")
        
        if method == "cookie" and "file" in params:
            if self.auth_manager is None:
                self.auth_manager = AuthManager(AuthConfig())
            self.auth_manager.config.cookies_file = params["file"]
            self.auth_manager._load_cookies_from_file(params["file"])
            print(f"[ORCH] Applied cookie auth from {params['file']}")
        
        elif method == "token" and "token" in params:
            if self.auth_manager is None:
                self.auth_manager = AuthManager(AuthConfig())
            self.auth_manager.config.bearer_token = params["token"]
            print(f"[ORCH] Applied bearer token auth")
        
        elif method == "basic" and "credentials" in params:
            if self.auth_manager is None:
                self.auth_manager = AuthManager(AuthConfig())
            parts = params["credentials"].split(":", 1)
            if len(parts) == 2:
                self.auth_manager.config.basic_auth = (parts[0], parts[1])
                print(f"[ORCH] Applied basic auth")
        
        elif method == "storage":
            if self.auth_manager is None:
                self.auth_manager = AuthManager(AuthConfig())
            self.auth_manager.config.local_storage.update(params.get("local_storage", {}))
            self.auth_manager.config.session_storage.update(params.get("session_storage", {}))
            print(f"[ORCH] Applied storage auth")

    async def _finalize(self):
        """Generate manifest, index, and network session report."""
        manifest = {
            "cloned_at": str(asyncio.get_event_loop().time()),
            "total_pages": len(self.state.completed_urls),
            "total_assets": len(self.cloner.downloaded_assets),
            "pages": self.state.completed_urls,
            "blocked": [b["url"] for b in self.state.blocked_urls],
            "skipped": self.state.skipped_urls,
            "assets": {url: str(path.relative_to(self.output_dir)).replace("\\", "/")
                      for url, path in self.cloner.downloaded_assets.items()},
        }
        manifest_path = self.output_dir / "weblica-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        
        # Save network session report
        session_path = self.output_dir / "weblica-session.json"
        self.recorder.save(str(session_path))
        
        # Print API summary
        api_summary = self.recorder.get_api_summary()
        if api_summary:
            print(f"[ORCH] Captured {len(api_summary)} API calls total")
            print(f"[ORCH] Session report: {session_path}")
        
        await self.cloner._generate_index_html()
        print(f"[ORCH] DFS clone complete. Visited: {len(self.state.visited_urls)}, Completed: {len(self.state.completed_urls)}, Blocked: {len(self.state.blocked_urls)}, Skipped: {len(self.state.skipped_urls)}")

    def get_summary(self) -> str:
        """Get a human-readable summary of the clone state."""
        if not self.state:
            return "No state initialized."
        
        lines = [
            "=" * 50,
            "Clone Job Summary",
            "=" * 50,
            f"Start URL: {self.state.start_url}",
            f"Max Depth: {self.state.max_depth}",
            f"Visited:   {len(self.state.visited_urls)} pages",
            f"Completed: {len(self.state.completed_urls)} pages",
            f"Blocked:   {len(self.state.blocked_urls)} pages",
            f"Skipped:   {len(self.state.skipped_urls)} pages",
            f"Remaining: {len(self.state.url_queue)} pages in queue",
            "-" * 50,
        ]
        
        if self.state.blocked_urls:
            lines.append("Blocked URLs:")
            for item in self.state.blocked_urls:
                lines.append(f"  - {item['url']}: {item['reason']}")
        
        if self.state.url_queue:
            lines.append("Queue (next 5):")
            for url, depth, _ in self.state.url_queue[:5]:
                lines.append(f"  [{depth}] {url}")
        
        lines.append("=" * 50)
        return "\n".join(lines)
