"""
Stateful browser session management for long-lived exploration.

ExplorationSession wraps a single CloakBrowser + Page + NetworkInterceptor
and maintains it across multiple Agent API calls. The browser stays alive
between calls, preserving cookies, localStorage, and page state.

SessionManager manages multiple ExplorationSessions in-memory.
"""

import uuid
import json
import asyncio
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from datetime import datetime

from .browser import CloakBrowser
from .interceptor import NetworkInterceptor
from .auth import AuthManager


@dataclass
class ActionRecord:
    action: str
    params: Dict[str, Any]
    timestamp: str
    before_url: str
    after_url: str
    interaction_type: str


@dataclass
class SessionState:
    session_id: str
    current_url: str
    current_title: str
    created_at: str
    last_active_at: str
    history: List[ActionRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExplorationSession:
    """
    A single long-lived browser session.

    The browser context and page are kept open across multiple API calls.
    Agent can navigate, click, input, scroll, and query state at any time.
    """

    def __init__(
        self,
        session_id: str,
        output_dir: Path,
        headless: bool = True,
        auth_manager: Optional[AuthManager] = None,
        capture_body_for: Optional[set] = None,
    ):
        self.session_id = session_id
        self.output_dir = output_dir
        self.headless = headless
        self.auth_manager = auth_manager
        self.capture_body_for = capture_body_for

        self.browser: Optional[CloakBrowser] = None
        self.page: Optional[Any] = None
        self.interceptor: Optional[NetworkInterceptor] = None

        self.state = SessionState(
            session_id=session_id,
            current_url="",
            current_title="",
            created_at=datetime.now().isoformat(),
            last_active_at=datetime.now().isoformat(),
        )

        self._initialized = False

    async def initialize(self) -> None:
        """Launch browser, create page, and start network interceptor."""
        if self._initialized:
            return

        self.browser = CloakBrowser(headless=self.headless)
        await self.browser.launch()

        self.page = await self.browser.new_page()

        self.interceptor = NetworkInterceptor(
            self.page,
            capture_body_for=self.capture_body_for,
        )
        self.interceptor.start()

        self._initialized = True

    # ------------------------------------------------------------------
    # Mutating actions
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> Dict[str, Any]:
        """Navigate to URL and return state snapshot."""
        if not self.page:
            raise RuntimeError("Session not initialized. Call initialize() first.")

        if self.auth_manager:
            await self.auth_manager.apply_to_context(self.page.context, url)
            await self.auth_manager.apply_to_page(self.page)

        await self.page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(1.5)

        return await self._build_snapshot("navigate", {"url": url})

    async def click(self, selector: str, pre_wait: int = 0) -> Dict[str, Any]:
        """Click an element and return state snapshot."""
        if not self.page:
            raise RuntimeError("Session not initialized.")

        if pre_wait:
            await asyncio.sleep(pre_wait / 1000)

        before_url = self.page.url
        await self.page.click(selector)
        await asyncio.sleep(2)

        interaction_type = "navigation" if self.page.url != before_url else "dom_update"
        return await self._build_snapshot("click", {"selector": selector}, interaction_type)

    async def input(self, selector: str, value: str) -> Dict[str, Any]:
        """Fill an input field and return state snapshot."""
        if not self.page:
            raise RuntimeError("Session not initialized.")

        await self.page.fill(selector, value)
        await asyncio.sleep(1)

        return await self._build_snapshot("input", {"selector": selector, "value": value})

    async def scroll(self, direction: str = "bottom") -> Dict[str, Any]:
        """Scroll the page and return state snapshot."""
        if not self.page:
            raise RuntimeError("Session not initialized.")

        if direction == "bottom":
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            await self.page.evaluate("window.scrollTo(0, 0)")
        elif direction == "down":
            await self.page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
        elif direction == "up":
            await self.page.evaluate("window.scrollBy(0, -window.innerHeight * 0.8)")

        await asyncio.sleep(1.5)
        return await self._build_snapshot("scroll", {"direction": direction})

    async def wait(self, ms: int = 2000) -> Dict[str, Any]:
        """Wait for N milliseconds."""
        if not self.page:
            raise RuntimeError("Session not initialized.")

        await asyncio.sleep(ms / 1000)
        return await self._build_snapshot("wait", {"ms": ms})

    # ------------------------------------------------------------------
    # Queries (non-mutating)
    # ------------------------------------------------------------------

    async def screenshot(self) -> bytes:
        """Return current page screenshot as PNG bytes."""
        if not self.page:
            raise RuntimeError("Session not initialized.")
        return await self.page.screenshot(full_page=True)

    async def get_state(self) -> Dict[str, Any]:
        """Return comprehensive state snapshot."""
        if not self.page:
            raise RuntimeError("Session not initialized.")
        return await self._build_snapshot("get_state", {})

    async def get_dom(self) -> str:
        """Return current page HTML."""
        if not self.page:
            raise RuntimeError("Session not initialized.")
        return await self.page.content()

    async def get_interactive_elements(self) -> List[Dict[str, Any]]:
        """Return all interactive elements with bounding boxes."""
        if not self.page:
            raise RuntimeError("Session not initialized.")

        return await self.page.evaluate("""() => {
            const elements = [];
            const interactiveSelectors = 'a, button, input, textarea, select, [role="button"], [onclick]';
            document.querySelectorAll(interactiveSelectors).forEach((el, i) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                if (rect.width === 0 || rect.height === 0 || style.display === 'none' || style.visibility === 'hidden') return;
                elements.push({
                    index: i,
                    tag: el.tagName.toLowerCase(),
                    text: (el.textContent || el.value || el.placeholder || '').trim().substring(0, 80),
                    selector: el.id ? '#' + el.id : el.className ? '.' + el.className.split(/\\s+/).filter(c=>c).slice(0,2).join('.') : el.tagName.toLowerCase(),
                    type: el.type || null,
                    name: el.name || null,
                    id: el.id || null,
                    className: el.className || null,
                    href: el.href || null,
                    placeholder: el.placeholder || null,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    visible: true,
                });
            });
            return elements;
        }""")

    async def get_network_log(self) -> List[Dict[str, Any]]:
        """Return all captured network traffic since last query (or start)."""
        if not self.interceptor:
            return []

        # Read interactions without stopping the interceptor
        interactions = list(self.interceptor._interactions)
        return [t.to_dict() for t in interactions]

    def clear_network_log(self) -> None:
        """Clear the network log buffer."""
        if self.interceptor:
            self.interceptor.clear()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def save(self) -> Path:
        """Persist session state to disk."""
        session_dir = self.output_dir / "sessions" / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        if self.page:
            # Cookies
            cookies = await self.page.context.cookies()
            (session_dir / "cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")

            # Storage
            storage = await self.page.evaluate("""() => ({
                localStorage: Object.fromEntries(Object.entries(localStorage)),
                sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
            })""")
            (session_dir / "storage.json").write_text(json.dumps(storage, indent=2, ensure_ascii=False), encoding="utf-8")

            # Screenshot
            screenshot = await self.page.screenshot(full_page=True)
            (session_dir / "screenshot.png").write_bytes(screenshot)

            # Network log
            network_log = await self.get_network_log()
            log_path = session_dir / "network_log.jsonl"
            with log_path.open("a", encoding="utf-8") as f:
                for entry in network_log:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.clear_network_log()

        # State
        self.state.last_active_at = datetime.now().isoformat()
        (session_dir / "state.json").write_text(
            json.dumps(asdict(self.state), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return session_dir

    async def close(self) -> None:
        """Close browser and clean up resources."""
        if self.interceptor:
            self.interceptor.stop()
            self.interceptor = None
        if self.page:
            try:
                await self.page.close()
            except Exception:
                pass
            self.page = None
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _build_snapshot(
        self,
        action: str,
        params: Dict[str, Any],
        interaction_type: str = "dom_update",
    ) -> Dict[str, Any]:
        """Build a comprehensive state snapshot after an action."""
        url = self.page.url
        title = await self.page.title()
        html = await self.page.content()

        record = ActionRecord(
            action=action,
            params=params,
            timestamp=datetime.now().isoformat(),
            before_url=self.state.current_url,
            after_url=url,
            interaction_type=interaction_type,
        )
        self.state.history.append(record)
        self.state.current_url = url
        self.state.current_title = title
        self.state.last_active_at = datetime.now().isoformat()

        return {
            "session_id": self.session_id,
            "interaction_type": interaction_type,
            "current_url": url,
            "current_title": title,
            "html_length": len(html),
            "history_length": len(self.state.history),
            "action": action,
            "params": params,
            "timestamp": record.timestamp,
        }


class SessionManager:
    """
    Registry of all active ExplorationSessions.

    Creates, tracks, and destroys browser sessions. Each session is independent
    and holds its own CloakBrowser instance.
    """

    def __init__(self, output_dir: str = "./weblica-sessions"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: Dict[str, ExplorationSession] = {}

    async def create_session(
        self,
        headless: bool = True,
        auth_manager: Optional[AuthManager] = None,
        capture_body_for: Optional[set] = None,
    ) -> str:
        """Create and initialize a new browser session. Returns session_id."""
        session_id = str(uuid.uuid4())[:8]
        session = ExplorationSession(
            session_id=session_id,
            output_dir=self.output_dir,
            headless=headless,
            auth_manager=auth_manager,
            capture_body_for=capture_body_for,
        )
        await session.initialize()
        self.sessions[session_id] = session
        return session_id

    async def get_session(self, session_id: str) -> ExplorationSession:
        """Get an existing session by ID."""
        if session_id not in self.sessions:
            raise KeyError(f"Session '{session_id}' not found. Active sessions: {list(self.sessions.keys())}")
        return self.sessions[session_id]

    async def destroy_session(self, session_id: str) -> None:
        """Close browser and remove session from registry."""
        if session_id in self.sessions:
            await self.sessions[session_id].close()
            del self.sessions[session_id]

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Return summary of all active sessions."""
        return [
            {
                "session_id": s.session_id,
                "current_url": s.state.current_url,
                "current_title": s.state.current_title,
                "created_at": s.state.created_at,
                "last_active_at": s.state.last_active_at,
                "history_count": len(s.state.history),
            }
            for s in self.sessions.values()
        ]

    async def close_all(self) -> None:
        """Close all sessions and clean up."""
        for session in list(self.sessions.values()):
            await session.close()
        self.sessions.clear()
