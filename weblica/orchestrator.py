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
    ):
        self.start_url = start_url
        self.output_dir = Path(output_dir)
        self.max_depth = max_depth
        self.headless = headless
        self.proxy = proxy
        self.auth_manager = auth_manager
        self.decision_callback = decision_callback
        self.state_file = state_file or str(self.output_dir / ".weblica-state.json")
        
        self.cloner: Optional[WebCloner] = None
        self.state: Optional[CloneState] = None
        self.analyzer = SmartAnalyzer()
        
        # The currently open page (kept alive during agent decisions)
        self._active_page: Optional[Page] = None

    async def __aenter__(self):
        self.cloner = WebCloner(
            output_dir=str(self.output_dir),
            headless=self.headless,
            max_depth=self.max_depth,
            proxy=self.proxy,
            auth_manager=self.auth_manager,
        )
        await self.cloner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_active_page()
        if self.cloner:
            await self.cloner.__aexit__(exc_type, exc_val, exc_tb)

    async def _close_active_page(self):
        """Safely close the active page if one exists."""
        if self._active_page:
            try:
                await self._active_page.close()
            except Exception:
                pass
            self._active_page = None

    async def run_dfs(self):
        """
        Generator-style DFS clone with agent decision points.
        Yields a DecisionContext at every obstacle or after every page analysis.
        
        CRITICAL: When an obstacle is detected, the browser page is NOT closed.
        The user can interact with the browser window. The orchestrator polls
        the page state and continues automatically once the obstacle clears.
        """
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
            
            # ===== PHASE 1: Open page, navigate, detect obstacles =====
            # Page stays open after this call if obstacle is found
            ctx = await self._process_page_phase1(url, depth, parent)
            
            # ===== DECISION POINT: Yield to agent =====
            if ctx.obstacle != ObstacleType.NONE or ctx.phase in (ClonePhase.BLOCKED, ClonePhase.COMPLETED):
                if self.decision_callback:
                    ctx = await self.decision_callback(ctx)
                yield ctx
            
            # ===== APPLY AGENT DECISION =====
            if ctx.recommended_action == "abort":
                print("[ORCH] Agent requested abort. Stopping.")
                break
            
            elif ctx.recommended_action == "skip":
                self.state.skipped_urls.append(url)
                await self._close_active_page()
                continue
            
            elif ctx.recommended_action == "retry":
                # Agent wants to retry - check if user solved the obstacle in browser
                if self._active_page and ctx.obstacle == ObstacleType.LOGIN_REQUIRED:
                    print("[ORCH] Checking if user completed login in browser...")
                    logged_in = await self._wait_for_browser_login(self._active_page, timeout=600)
                    if logged_in:
                        print("[ORCH] Login detected! Re-analyzing page...")
                        ctx.obstacle = ObstacleType.NONE
                        # Don't re-add to queue - continue processing this page now
                    else:
                        print("[ORCH] Login not detected. Blocking page.")
                        self.state.blocked_urls.append({
                            "url": url,
                            "reason": ctx.notes or "login not completed",
                            "snapshot": asdict(ctx.snapshot),
                        })
                        await self._close_active_page()
                        continue
                else:
                    # Simple retry: re-queue
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
                # Agent wants user to manually handle this page in the browser
                if self._active_page and ctx.obstacle == ObstacleType.LOGIN_REQUIRED:
                    print("[ORCH] MANUAL MODE: Please complete login in the browser window.")
                    print("[ORCH] The browser will stay open. I'll detect when you're done.")
                    logged_in = await self._wait_for_browser_login(self._active_page, timeout=600)
                    if logged_in:
                        print("[ORCH] Login detected! Continuing...")
                        ctx.obstacle = ObstacleType.NONE
                    else:
                        print("[ORCH] Login not completed. Marking as blocked.")
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
            
            # ===== PHASE 2: Analyze, download, persist =====
            # Only reach here if obstacle is NONE (or was cleared by user login)
            if ctx.obstacle == ObstacleType.NONE and self._active_page:
                ctx = await self._process_page_phase2(url, depth, ctx, self._active_page)
                self.state.completed_urls.append(url)
                ctx.phase = ClonePhase.COMPLETED
            
            # Clean up
            await self._close_active_page()
            
            # Queue discovered links (DFS)
            if ctx.phase == ClonePhase.COMPLETED and ctx.discovered_links:
                new_items = [
                    (link, depth + 1, url)
                    for link in ctx.discovered_links
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

    async def _process_page_phase2(self, url: str, depth: int, ctx: DecisionContext, page: Page) -> DecisionContext:
        """
        Phase 2: Analyze page structure, download assets, persist HTML.
        Only called when no obstacles are present (or obstacles were cleared).
        """
        try:
            ctx.phase = ClonePhase.ANALYZING
            analysis = await self.analyzer.analyze(page)
            ctx.full_analysis = analysis
            ctx.discovered_links = analysis.links[:20]
            ctx.discovered_assets = len(analysis.stylesheets) + len(analysis.scripts) + len(analysis.images) + len(analysis.fonts)
            
            ctx.phase = ClonePhase.ASSET_DOWNLOADING
            await self.cloner._download_assets(analysis, url)
            
            ctx.phase = ClonePhase.PERSISTING
            html = await self.cloner._rewrite_html(page, analysis, url)
            page_filename = self.cloner._get_page_filename(url)
            html_path = self.output_dir / page_filename
            html_path.write_text(html, encoding="utf-8")
            
            analysis_path = self.output_dir / f"analysis_{len(self.state.visited_urls)}.json"
            analysis_path.write_text(self.analyzer.export_json(analysis), encoding="utf-8")
            
            print(f"    [OK] Completed: {page_filename} | Assets: {ctx.discovered_assets} | Links: {len(ctx.discovered_links)}")
            
        except Exception as e:
            print(f"    [ERR] Phase2 failed for {url}: {e}")
            ctx.obstacle = ObstacleType.UNKNOWN
            ctx.phase = ClonePhase.BLOCKED
        
        return ctx

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
        """Generate manifest and index."""
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
