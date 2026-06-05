r"""
CloakBrowser - Stealth-enhanced Browser

Tries to use real CloakBrowser (CloakHQ) patched Chromium first.
Automatically falls back to Playwright + JS evasion if the CloakBrowser
binary is not available.

To manually install the CloakBrowser binary:
    python -m weblica.browser --download

Or set CLOAKBROWSER_BINARY_PATH to an existing patched Chromium:
    set CLOAKBROWSER_BINARY_PATH=C:\path\to\chrome.exe
"""

import asyncio
import logging
import os
import random
import sys
from typing import Optional, Dict, Any, List

# Try importing real CloakBrowser (CloakHQ)
try:
    import cloakbrowser
    HAS_CLOAKBROWSER = True
except ImportError:
    HAS_CLOAKBROWSER = False

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from .auth import AuthManager, AuthConfig

logger = logging.getLogger("weblica.browser")


class CloakBrowser:
    """
    Unified stealth browser interface.

    Priority:
    1. Real CloakBrowser (CloakHQ) with C++ patches + humanize
    2. Fallback: Playwright + JS evasion scripts

    API is fully backward-compatible with the original Playwright wrapper.
    """

    # Realistic user agents (used for fallback mode)
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    ]

    # Evasion scripts injected into every page (fallback mode only)
    EVASION_SCRIPTS: List[str] = [
        # Remove webdriver property
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        """,
        # Spoof plugins
        """
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {
                    0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
                    description: "Portable Document Format",
                    filename: "internal-pdf-viewer",
                    length: 1,
                    name: "Chrome PDF Plugin"
                },
                {
                    0: {type: "application/pdf", suffixes: "pdf", description: "Portable Document Format"},
                    description: "Portable Document Format",
                    filename: "internal-pdf-viewer2",
                    length: 1,
                    name: "Chrome PDF Viewer"
                }
            ]
        });
        """,
        # Spoof languages
        """
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en']
        });
        """,
        # Hide automation-related properties
        """
        delete navigator.__proto__.webdriver;
        window.chrome = { runtime: {} };
        """,
        # Canvas fingerprint randomization (subtle noise)
        """
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;

        HTMLCanvasElement.prototype.toDataURL = function(type) {
            if (this.width > 16 && this.height > 16) {
                const ctx = this.getContext('2d');
                if (ctx) {
                    const imageData = ctx.getImageData(0, 0, this.width, this.height);
                    const data = imageData.data;
                    data[0] = data[0] ^ 1;
                    ctx.putImageData(imageData, 0, 0);
                }
            }
            return originalToDataURL.apply(this, arguments);
        };
        """,
        # Permission query override
        """
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ||
            parameters.name === 'clipboard-read' ||
            parameters.name === 'clipboard-write'
                ? Promise.resolve({ state: 'prompt', onchange: null })
                : originalQuery(parameters)
        );
        """,
    ]

    def __init__(
        self,
        headless: bool = True,
        user_agent: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None,
        proxy: Optional[str] = None,
        slow_mo: Optional[int] = None,
        auth_manager: Optional[AuthManager] = None,
        humanize: bool = True,
    ):
        self.headless = headless
        self.user_agent = user_agent or random.choice(self.USER_AGENTS)
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self.proxy = proxy
        self.slow_mo = slow_mo
        self.auth_manager = auth_manager
        self.humanize = humanize

        self._using_real_cloak = False
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        await self.launch()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def launch(self):
        """Launch the stealth browser (CloakBrowser preferred, Playwright fallback)."""
        if HAS_CLOAKBROWSER:
            info = cloakbrowser.binary_info()
            # Check default cache OR local override via CLOAKBROWSER_BINARY_PATH
            from cloakbrowser.config import get_local_binary_override
            local_override = get_local_binary_override()
            has_binary = info.get("installed") or (
                local_override and os.path.exists(local_override)
            )
            if has_binary:
                try:
                    await self._launch_with_cloakbrowser()
                    return self
                except Exception as e:
                    logger.warning("[CLOAK] Real CloakBrowser launch failed: %s", e)
                    logger.warning("[CLOAK] Falling back to Playwright + JS evasion.")
            else:
                logger.info(
                    "[CLOAK] CloakBrowser binary not installed (expected at %s). "
                    "Using Playwright fallback.",
                    info.get("binary_path", "unknown"),
                )
                if local_override:
                    logger.info(
                        "[CLOAK] CLOAKBROWSER_BINARY_PATH set to '%s' but file not found.",
                        local_override,
                    )
                logger.info(
                    "[CLOAK] To use real CloakBrowser: python -m weblica.browser --download"
                )

        await self._launch_with_playwright()
        return self

    async def _launch_with_cloakbrowser(self):
        """Launch using real CloakBrowser (CloakHQ) patched Chromium."""
        # Resolve proxy format
        proxy = self.proxy
        if proxy and not isinstance(proxy, dict):
            proxy = {"server": proxy}

        if self.slow_mo:
            logger.warning(
                "[CLOAK] slow_mo=%s is not supported in CloakBrowser mode (ignored).",
                self.slow_mo,
            )

        # Build context kwargs
        context_kwargs: Dict[str, Any] = {"ignore_https_errors": True}
        if self.auth_manager and self.auth_manager.config.basic_auth:
            username, password = self.auth_manager.config.basic_auth
            context_kwargs["http_credentials"] = {
                "username": username,
                "password": password,
            }

        # Use launch_context_async for full stealth + humanize support
        self._context = await cloakbrowser.launch_context_async(
            headless=self.headless,
            proxy=proxy,
            user_agent=self.user_agent,
            viewport=self.viewport,
            locale="zh-CN",
            timezone="Asia/Shanghai",
            humanize=self.humanize,
            stealth_args=True,
            **context_kwargs,
        )
        # Note: launch_context_async patches context.close() to also close
        # the underlying browser and Playwright instance.
        self._using_real_cloak = True
        logger.info(
            "[CLOAK] Real CloakBrowser active (humanize=%s, stealth_args=True)",
            self.humanize,
        )

    async def _launch_with_playwright(self):
        """Launch using stock Playwright with JS evasion (fallback mode)."""
        self._playwright = await async_playwright().start()

        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        launch_options: Dict[str, Any] = {
            "headless": self.headless,
            "args": browser_args,
        }

        if self.slow_mo:
            launch_options["slow_mo"] = self.slow_mo

        # Fallback to existing chromium if version mismatch
        fallback_chrome = r"C:\Users\feast\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        if os.path.exists(fallback_chrome):
            launch_options["executable_path"] = fallback_chrome

        self._browser = await self._playwright.chromium.launch(**launch_options)

        context_options: Dict[str, Any] = {
            "viewport": self.viewport,
            "user_agent": self.user_agent,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "permissions": [],
            "java_script_enabled": True,
            "ignore_https_errors": True,
        }

        if self.proxy:
            context_options["proxy"] = {"server": self.proxy}

        if self.auth_manager and self.auth_manager.config.basic_auth:
            username, password = self.auth_manager.config.basic_auth
            context_options["http_credentials"] = {
                "username": username,
                "password": password,
            }

        self._context = await self._browser.new_context(**context_options)

        # Inject evasion scripts for every new page
        await self._context.add_init_script(
            "\n".join(self.EVASION_SCRIPTS)
        )

        logger.info("[CLOAK] Playwright fallback active (JS evasion)")

    async def new_page(self) -> Page:
        """Create a new page with stealth settings applied."""
        if not self._context:
            raise RuntimeError("Browser not launched. Call launch() first.")

        page = await self._context.new_page()

        if not self._using_real_cloak:
            # Additional page-level evasions (fallback only)
            await page.add_init_script("""
                // Override the navigator.webdriver again for extra safety
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false
                });

                // Spoof notification permissions
                const originalNotification = window.Notification;
                window.Notification = function(title, options) {
                    return new originalNotification(title, options);
                };
                window.Notification.permission = 'default';
                window.Notification.requestPermission = async () => 'default';
            """)

        return page

    async def close(self):
        """Close browser and cleanup."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self._using_real_cloak = False

    async def mimic_human_behavior(self, page: Page):
        """Simulate realistic human-like mouse movements and scrolling.

        Note: When using real CloakBrowser with humanize=True, this is
        mostly redundant because CloakBrowser patches page interactions
        automatically. Kept for fallback mode compatibility.
        """
        if self._using_real_cloak:
            # CloakBrowser's humanize handles this at the interaction level
            await asyncio.sleep(random.uniform(0.3, 1.0))
            return

        # Random scroll behavior
        scroll_amount = random.randint(300, 800)
        await page.mouse.wheel(0, scroll_amount)
        await asyncio.sleep(random.uniform(0.5, 2.0))

        # Random mouse movement
        x = random.randint(100, self.viewport["width"] - 100)
        y = random.randint(100, self.viewport["height"] - 100)
        await page.mouse.move(x, y, steps=random.randint(5, 15))

        # Random delay
        await asyncio.sleep(random.uniform(0.3, 1.5))


# ---------------------------------------------------------------------------
# CLI helper for manual binary download
# ---------------------------------------------------------------------------

def _print_download_help():
    """Print instructions for obtaining the CloakBrowser binary."""
    info = cloakbrowser.binary_info() if HAS_CLOAKBROWSER else {}
    print("=" * 60)
    print("  CloakBrowser Binary Download Helper")
    print("=" * 60)
    if info:
        print(f"  Required version: {info.get('version', 'unknown')}")
        print(f"  Platform:         {info.get('platform', 'unknown')}")
        print(f"  Expected path:    {info.get('binary_path', 'unknown')}")
        print(f"  Download URL:     {info.get('download_url', 'unknown')}")
    print()
    print("  Option 1: Let cloakbrowser auto-download on first use")
    print("            (requires internet access to cloakbrowser.dev)")
    print()
    print("  Option 2: Manual download")
    if info:
        print(f"            curl -L -o cloakbrowser.zip \"{info.get('download_url', '')}\"")
        cache_dir = info.get("cache_dir", "")
        print(f"            unzip cloakbrowser.zip -d \"{cache_dir}\"")
    print()
    print("  Option 3: Set CLOAKBROWSER_BINARY_PATH env var")
    print("            to point to an existing patched Chromium binary.")
    print()
    print("  Note:  The patched binary is required for real CloakBrowser.")
    print("         Without it, Weblica falls back to Playwright + JS evasion.")
    print("=" * 60)


def _attempt_download():
    """Trigger cloakbrowser's built-in download (best-effort)."""
    print("[DOWNLOAD] Triggering CloakBrowser binary download...")
    try:
        path = cloakbrowser.ensure_binary()
        print(f"[DOWNLOAD] Success! Binary at: {path}")
        return 0
    except Exception as e:
        print(f"[DOWNLOAD] Failed: {e}")
        print()
        _print_download_help()
        return 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--download":
        if not HAS_CLOAKBROWSER:
            print("[ERR] cloakbrowser package not installed.")
            print("      Run: pip install cloakbrowser")
            sys.exit(1)
        sys.exit(_attempt_download())
    else:
        _print_download_help()
