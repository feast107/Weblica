"""
AuthManager - Authentication handling for Weblica

Supports multiple authentication methods:
1. Cookie injection (from JSON file or dict)
2. LocalStorage / SessionStorage injection
3. Bearer Token / Basic Auth headers
4. Manual login wait (interactive mode)
5. CAPTCHA detection and alerting
6. Auth state persistence (save/load cookies & storage)
"""

import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse

from playwright.async_api import Page, BrowserContext


@dataclass
class AuthConfig:
    """Authentication configuration."""
    # Cookie auth
    cookies: List[Dict[str, Any]] = field(default_factory=list)
    cookies_file: Optional[str] = None
    
    # Storage auth
    local_storage: Dict[str, str] = field(default_factory=dict)
    session_storage: Dict[str, str] = field(default_factory=dict)
    storage_file: Optional[str] = None
    
    # Token auth
    bearer_token: Optional[str] = None
    basic_auth: Optional[tuple] = None  # (username, password)
    
    # Interactive auth
    wait_for_login: bool = False
    login_timeout: int = 300  # seconds
    login_selector: Optional[str] = None  # CSS selector indicating logged-in state
    
    # CAPTCHA handling
    captcha_action: str = "warn"  # warn, block, auto_click
    
    # State persistence
    save_auth_state: bool = False
    auth_state_file: Optional[str] = None


class AuthManager:
    """
    Handles authentication for stealth browsing sessions.
    """

    # CAPTCHA-related keywords and selectors
    CAPTCHA_INDICATORS = [
        "captcha",
        "验证码",
        "recaptcha",
        "hcaptcha",
        "turnstile",
        "安全验证",
        "人机验证",
        "滑动验证",
        "点击验证",
    ]
    
    CAPTCHA_SELECTORS = [
        ".g-recaptcha",
        ".h-captcha",
        "[data-sitekey]",
        "iframe[src*='recaptcha']",
        "iframe[src*='captcha']",
        "iframe[src*='turnstile']",
        ".captcha",
        "#captcha",
        "[class*='captcha']",
        "[id*='captcha']",
        "[class*='verify']",
        "[class*='slide']",
    ]

    def __init__(self, config: AuthConfig):
        self.config = config
        
        # Load from files if specified
        if config.cookies_file:
            self._load_cookies_from_file(config.cookies_file)
        if config.storage_file:
            self._load_storage_from_file(config.storage_file)

    def _load_cookies_from_file(self, path: str):
        """Load cookies from a JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            print(f"[AUTH] Warning: Cookies file not found: {path}")
            return
        
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.config.cookies.extend(data)
            elif isinstance(data, dict) and "cookies" in data:
                self.config.cookies.extend(data["cookies"])
            print(f"[AUTH] Loaded {len(data) if isinstance(data, list) else len(data.get('cookies', []))} cookies from {path}")
        except Exception as e:
            print(f"[AUTH] Error loading cookies: {e}")

    def _load_storage_from_file(self, path: str):
        """Load local/session storage from a JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            print(f"[AUTH] Warning: Storage file not found: {path}")
            return
        
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            self.config.local_storage.update(data.get("localStorage", {}))
            self.config.session_storage.update(data.get("sessionStorage", {}))
            print(f"[AUTH] Loaded storage from {path}")
        except Exception as e:
            print(f"[AUTH] Error loading storage: {e}")

    async def apply_to_context(self, context: BrowserContext, base_url: str):
        """Apply authentication to a browser context before navigation."""
        domain = urlparse(base_url).netloc
        
        # 1. Inject cookies
        if self.config.cookies:
            # Ensure cookies have required fields
            valid_cookies = []
            for cookie in self.config.cookies:
                if "name" in cookie and "value" in cookie:
                    # Add domain if missing
                    if "domain" not in cookie:
                        cookie = dict(cookie)
                        cookie["domain"] = domain
                    valid_cookies.append(cookie)
            
            if valid_cookies:
                await context.add_cookies(valid_cookies)
                print(f"[AUTH] Injected {len(valid_cookies)} cookies for {domain}")
        
        # 2. Set up HTTP headers for token auth
        if self.config.bearer_token:
            await context.set_extra_http_headers({
                "Authorization": f"Bearer {self.config.bearer_token}"
            })
            print("[AUTH] Set Bearer token in headers")
        
        # 3. Basic auth is handled via context options, not here

    async def apply_to_page(self, page: Page):
        """Apply page-level auth (localStorage, sessionStorage)."""
        # 1. Inject localStorage
        if self.config.local_storage:
            for key, value in self.config.local_storage.items():
                await page.evaluate(f"""
                    localStorage.setItem({json.dumps(key)}, {json.dumps(value)});
                """)
            print(f"[AUTH] Injected {len(self.config.local_storage)} localStorage items")
        
        # 2. Inject sessionStorage
        if self.config.session_storage:
            for key, value in self.config.session_storage.items():
                await page.evaluate(f"""
                    sessionStorage.setItem({json.dumps(key)}, {json.dumps(value)});
                """)
            print(f"[AUTH] Injected {len(self.config.session_storage)} sessionStorage items")

    async def handle_login_flow(self, page: Page) -> bool:
        """
        Handle interactive login flow.
        
        Returns True if login was successful, False otherwise.
        """
        if not self.config.wait_for_login:
            return True
        
        print("[AUTH] Waiting for manual login...")
        print(f"[AUTH] Please log in within {self.config.login_timeout} seconds")
        print("[AUTH] The browser window is open for you to interact with")
        
        start_time = asyncio.get_event_loop().time()
        check_interval = 2  # Check every 2 seconds
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            remaining = self.config.login_timeout - elapsed
            
            if remaining <= 0:
                print("[AUTH] Login timeout reached")
                return False
            
            # Check if logged-in selector is present
            if self.config.login_selector:
                try:
                    visible = await page.is_visible(self.config.login_selector, timeout=1000)
                    if visible:
                        print(f"[AUTH] Login detected via selector: {self.config.login_selector}")
                        break
                except:
                    pass
            
            # Check for URL change (common after login redirect)
            current_url = page.url
            if "/login" not in current_url and "/signin" not in current_url:
                # Additional check: look for common login success indicators
                has_logout = await page.evaluate("""
                    () => {
                        const text = document.body.innerText.toLowerCase();
                        return text.includes('logout') || text.includes('退出') || 
                               text.includes('登出') || text.includes('我的');
                    }
                """)
                if has_logout:
                    print("[AUTH] Login detected (logout button found)")
                    break
            
            await asyncio.sleep(check_interval)
        
        # Save auth state if requested
        if self.config.save_auth_state:
            await self.save_auth_state(page)
        
        return True

    async def detect_captcha(self, page: Page) -> Optional[str]:
        """
        Detect if a CAPTCHA is present on the page.
        
        Returns the detected CAPTCHA type or None.
        """
        page_text = await page.evaluate("() => document.body.innerText")
        page_html = await page.content()
        page_text_lower = page_text.lower()
        page_html_lower = page_html.lower()
        
        # Check text indicators
        for indicator in self.CAPTCHA_INDICATORS:
            if indicator.lower() in page_text_lower or indicator.lower() in page_html_lower:
                # Check for selectors to confirm
                for selector in self.CAPTCHA_SELECTORS:
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            return f"{indicator} ({selector})"
                    except:
                        pass
                # If no selector match but text matches, still report
                if indicator in ["验证码", "安全验证", "人机验证"]:
                    return indicator
        
        # Additional check: look for common CAPTCHA iframe patterns
        iframes = await page.query_selector_all("iframe")
        for iframe in iframes:
            src = await iframe.get_attribute("src") or ""
            if any(k in src.lower() for k in ["recaptcha", "captcha", "turnstile"]):
                return f"iframe CAPTCHA: {src[:60]}"
        
        return None

    async def handle_captcha(self, page: Page) -> bool:
        """
        Handle CAPTCHA based on configured action.
        
        Returns True if可以继续, False if should abort.
        """
        captcha_type = await self.detect_captcha(page)
        if not captcha_type:
            return True
        
        print(f"[AUTH] CAPTCHA detected: {captcha_type}")
        
        if self.config.captcha_action == "block":
            print("[AUTH] CAPTCHA blocking enabled. Aborting.")
            return False
        elif self.config.captcha_action == "warn":
            print("[AUTH] CAPTCHA present. You may need to solve it manually if using --no-headless")
            # Give user time to see the warning
            await asyncio.sleep(2)
            return True
        elif self.config.captcha_action == "auto_click":
            # Try to find and click CAPTCHA checkbox (for simple ones)
            checkbox_selectors = [
                ".recaptcha-checkbox-border",
                "[class*='checkbox']",
                "#recaptcha-anchor",
            ]
            for selector in checkbox_selectors:
                try:
                    await page.click(selector, timeout=2000)
                    print(f"[AUTH] Auto-clicked CAPTCHA element: {selector}")
                    await asyncio.sleep(3)  # Wait for CAPTCHA to process
                    return True
                except:
                    pass
            print("[AUTH] Auto-click failed. Continuing anyway.")
            return True
        
        return True

    async def save_auth_state(self, page: Page):
        """Save current cookies and storage to file for reuse."""
        file_path = Path(self.config.auth_state_file or "./weblica-auth-state.json")
        
        try:
            cookies = await page.context.cookies()
            local_storage = await page.evaluate("() => Object.assign({}, localStorage)")
            session_storage = await page.evaluate("() => Object.assign({}, sessionStorage)")
            
            state = {
                "url": page.url,
                "cookies": cookies,
                "localStorage": local_storage,
                "sessionStorage": session_storage,
            }
            
            file_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[AUTH] Auth state saved to: {file_path}")
            
        except Exception as e:
            print(f"[AUTH] Error saving auth state: {e}")

    @staticmethod
    def create_from_json(path: str) -> "AuthManager":
        """Create AuthManager from a JSON configuration file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        config = AuthConfig(**data)
        return AuthManager(config)


def prompt_for_login_info() -> AuthConfig:
    """
    Interactive prompt to gather login information from user.
    Returns an AuthConfig based on user input.
    """
    config = AuthConfig()
    
    print("\n[AUTH] Authentication Setup")
    print("-" * 40)
    
    # Cookie file
    cookie_path = input("Cookie JSON file path (or Enter to skip): ").strip()
    if cookie_path:
        config.cookies_file = cookie_path
    
    # Bearer token
    token = input("Bearer token (or Enter to skip): ").strip()
    if token:
        config.bearer_token = token
    
    # Manual login
    wait_login = input("Wait for manual login? (y/n): ").strip().lower()
    if wait_login in ("y", "yes"):
        config.wait_for_login = True
        selector = input("Login success CSS selector (or Enter for auto-detect): ").strip()
        if selector:
            config.login_selector = selector
    
    # Save state
    save = input("Save auth state after login? (y/n): ").strip().lower()
    if save in ("y", "yes"):
        config.save_auth_state = True
        config.auth_state_file = input("State file path (default: ./weblica-auth-state.json): ").strip()
        if not config.auth_state_file:
            config.auth_state_file = "./weblica-auth-state.json"
    
    print("-" * 40)
    return config
