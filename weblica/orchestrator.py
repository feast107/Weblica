"""
AgentOrchestrator - Agent-in-the-Loop Cloning Engine

Replaces the "fire-and-forget" batch cloning model with an event-driven,
agent-supervised workflow. The orchestrator pauses at key decision points,
builds a structured context for the agent, and resumes only after the agent
chooses an action.

Design principles:
1. Depth-First Search (DFS) traversal
2. Every page is a "decision unit" - agent sees, thinks, acts
3. State is persisted after each step - safe to interrupt / resume
4. Obstacles (auth, CAPTCHA, errors) are surfaced to agent, not swallowed
"""

import json
import asyncio
from enum import Enum, auto
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List, Callable, Set, Awaitable
from urllib.parse import urlparse, urljoin

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
    status: Optional[str] = None  # HTTP status or "unknown"
    text_preview: str = ""  # First 500 chars of body text
    has_login_form: bool = False
    has_captcha: bool = False
    error_indicators: List[str] = field(default_factory=list)
    redirect_chain: List[str] = field(default_factory=list)
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
    full_analysis: Optional[PageAnalysis] = None  # Available after ANALYZING phase
    
    # Discovery
    discovered_links: List[str] = field(default_factory=list)
    discovered_assets: int = 0
    
    # History
    parent_url: Optional[str] = None
    previous_decisions: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metrics
    time_spent_ms: int = 0
    retry_count: int = 0
    
    # Agent output (filled by agent)
    recommended_action: str = "continue"  # continue, skip, retry, auth, manual, abort
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
    url_queue: List[tuple] = field(default_factory=list)  # (url, depth, parent)
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
    
    Usage (agent mode):
        orchestrator = AgentOrchestrator(url, max_depth=2)
        async for decision_context in orchestrator.run_dfs():
            # Agent sees the context, makes a decision
            decision_context.recommended_action = "continue"
            # Loop continues automatically
    
    Usage (programmatic callback):
        async def my_agent(ctx: DecisionContext) -> DecisionContext:
            if ctx.obstacle == ObstacleType.LOGIN_REQUIRED:
                ctx.recommended_action = "auth"
                ctx.action_params["method"] = "cookie"
            return ctx
        
        orchestrator = AgentOrchestrator(url, decision_callback=my_agent)
        await orchestrator.run_dfs()
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
        if self.cloner:
            await self.cloner.__aexit__(exc_type, exc_val, exc_tb)

    async def run_dfs(self) -> DecisionContext:
        """
        Generator-style DFS clone with agent decision points.
        Yields a DecisionContext at every obstacle or after every page analysis.
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
            url, depth, parent = self.state.url_queue.pop()  # DFS: pop from end (LIFO)
            
            if url in self.state.visited_urls:
                continue
            if depth > self.max_depth:
                continue
            
            self.state.visited_urls.append(url)
            
            # Process the page
            ctx = await self._process_page(url, depth, parent)
            
            # Yield for agent decision if there's an obstacle or we want agent to review
            if ctx.obstacle != ObstacleType.NONE or ctx.phase in (ClonePhase.BLOCKED, ClonePhase.COMPLETED):
                if self.decision_callback:
                    ctx = await self.decision_callback(ctx)
                yield ctx
            
            # Apply agent decision
            if ctx.recommended_action == "abort":
                print("[ORCH] Agent requested abort. Stopping.")
                break
            elif ctx.recommended_action == "skip":
                self.state.skipped_urls.append(url)
                continue
            elif ctx.recommended_action == "retry":
                self.state.visited_urls.remove(url)
                self.state.url_queue.append((url, depth, parent))
                continue
            elif ctx.recommended_action == "auth":
                # Agent wants to apply authentication
                await self._apply_agent_auth(ctx.action_params)
                # Re-queue for retry with new auth
                self.state.visited_urls.remove(url)
                self.state.url_queue.append((url, depth, parent))
                continue
            elif ctx.recommended_action == "manual":
                # Agent wants user to manually handle this page
                # Pause and wait - but since we're in async generator,
                # we need the caller to handle this via the yielded context
                self.state.blocked_urls.append({
                    "url": url,
                    "reason": ctx.notes or "manual intervention requested",
                    "snapshot": asdict(ctx.snapshot),
                })
                continue
            
            # If completed successfully, add discovered links to queue (DFS: prepend)
            if ctx.phase == ClonePhase.COMPLETED and ctx.discovered_links:
                new_items = [
                    (link, depth + 1, url)
                    for link in ctx.discovered_links
                    if link not in self.state.visited_urls
                    and link not in [u for u, _, _ in self.state.url_queue]
                ]
                # DFS: prepend so deeper pages are processed first
                self.state.url_queue.extend(new_items)
            
            # Persist state after each page
            self.state.save(self.state_file)
        
        # Finalize - use orchestrator state for manifest
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

    async def _process_page(self, url: str, depth: int, parent: Optional[str]) -> DecisionContext:
        """Process a single page through all phases, returning a decision context."""
        snapshot = PageSnapshot(url=url, title="", depth=depth)
        ctx = DecisionContext(
            phase=ClonePhase.NAVIGATING,
            obstacle=ObstacleType.NONE,
            snapshot=snapshot,
            parent_url=parent,
        )
        
        page = await self.cloner.browser.new_page()
        try:
            # Phase 1: Auth injection
            if self.auth_manager and depth == 0 and len(self.state.visited_urls) == 1:
                await self.auth_manager.apply_to_context(page.context, url)
            if self.auth_manager:
                await self.auth_manager.apply_to_page(page)
            
            # Phase 2: Navigate
            print(f"  [PAGE] Navigating: {url} (depth={depth})")
            response = await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)
            
            snapshot.title = await page.title()
            snapshot.status = str(response.status) if response else "unknown"
            
            # Phase 3: Obstacle detection (auth check)
            ctx.phase = ClonePhase.AUTH_CHECKING
            
            # Check for login page indicators
            body_text = await page.evaluate("() => document.body.innerText")
            snapshot.text_preview = body_text[:500] if body_text else ""
            
            login_keywords = ["登录", "login", "sign in", "注册", "register", "密码", "password", "账号", "account"]
            if any(kw in body_text.lower() for kw in login_keywords):
                # Check if there are actual login forms
                has_form = await page.evaluate("""
                    () => document.querySelectorAll('input[type="password"], input[name*="pass"], form[action*="login"], form[action*="signin"]').length > 0
                """)
                if has_form:
                    snapshot.has_login_form = True
                    ctx.obstacle = ObstacleType.LOGIN_REQUIRED
                    ctx.notes = f"Login form detected on page. Title: {snapshot.title}"
                    return ctx
            
            # Check for CAPTCHA
            if self.auth_manager:
                captcha = await self.auth_manager.detect_captcha(page)
                if captcha:
                    snapshot.has_captcha = True
                    ctx.obstacle = ObstacleType.CAPTCHA
                    ctx.notes = f"CAPTCHA detected: {captcha}"
                    return ctx
            
            # Check for access denied / error pages
            error_indicators = []
            if response and response.status >= 400:
                error_indicators.append(f"HTTP {response.status}")
            error_texts = ["access denied", "forbidden", "unauthorized", "403", "401", "禁止访问", "无权限", "需要登录"]
            for et in error_texts:
                if et in body_text.lower():
                    error_indicators.append(et)
            if error_indicators:
                snapshot.error_indicators = error_indicators
                ctx.obstacle = ObstacleType.ACCESS_DENIED
                ctx.notes = f"Access issues: {', '.join(error_indicators)}"
                return ctx
            
            # Phase 4: Analyze
            ctx.phase = ClonePhase.ANALYZING
            analysis = await self.analyzer.analyze(page)
            ctx.full_analysis = analysis
            ctx.discovered_links = analysis.links[:20]
            ctx.discovered_assets = len(analysis.stylesheets) + len(analysis.scripts) + len(analysis.images) + len(analysis.fonts)
            
            # Phase 5: Download assets
            ctx.phase = ClonePhase.ASSET_DOWNLOADING
            await self.cloner._download_assets(analysis, url)
            
            # Phase 6: Persist HTML
            ctx.phase = ClonePhase.PERSISTING
            html = await self.cloner._rewrite_html(page, analysis, url)
            page_filename = self.cloner._get_page_filename(url)
            html_path = self.output_dir / page_filename
            html_path.write_text(html, encoding="utf-8")
            
            # Save analysis
            analysis_path = self.output_dir / f"analysis_{len(self.state.visited_urls)}.json"
            analysis_path.write_text(self.analyzer.export_json(analysis), encoding="utf-8")
            
            self.state.completed_urls.append(url)
            ctx.phase = ClonePhase.COMPLETED
            print(f"    [OK] Completed: {page_filename} | Assets: {ctx.discovered_assets} | Links: {len(ctx.discovered_links)}")
            
        except Exception as e:
            ctx.obstacle = ObstacleType.UNKNOWN
            ctx.notes = f"Exception: {str(e)}"
            ctx.phase = ClonePhase.BLOCKED
            print(f"    [ERR] {url}: {e}")
        finally:
            await page.close()
        
        return ctx

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
        
        # Save updated auth state
        if self.auth_manager and params.get("save", True):
            self.state.auth_state_file = self.state_file.replace(".json", "-auth.json")

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
