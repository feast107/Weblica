"""
CloakBrowser - Stealth-enhanced Playwright Browser

Provides anti-detection capabilities to avoid being blocked by target websites.
Implements various evasion techniques to mimic real user behavior.
"""

import asyncio
import random
from typing import Optional, Dict, Any, List
from pathlib import Path

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from .auth import AuthManager, AuthConfig


class CloakBrowser:
    """
    A stealth-wrapped browser using Playwright with anti-detection measures.
    
    Features:
    - User-Agent rotation and normalization
    - Webdriver property removal
    - Permissions masking
    - WebGL/Canvas fingerprint randomization
    - Plugin/mimeTypes spoofing
    - Runtime script injection for evasions
    """

    # Realistic user agents
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    ]

    # Evasion scripts injected into every page
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
    ):
        self.headless = headless
        self.user_agent = user_agent or random.choice(self.USER_AGENTS)
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self.proxy = proxy
        self.slow_mo = slow_mo
        self.auth_manager = auth_manager
        
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        await self.launch()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def launch(self):
        """Launch the stealth browser."""
        self._playwright = await async_playwright().start()
        
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
        
        launch_options = {
            "headless": self.headless,
            "args": browser_args,
        }
        
        if self.slow_mo:
            launch_options["slow_mo"] = self.slow_mo
            
        # Fallback to existing chromium if version mismatch
        fallback_chrome = r"C:\Users\feast\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe"
        import os
        if os.path.exists(fallback_chrome):
            launch_options["executable_path"] = fallback_chrome
        
        self._browser = await self._playwright.chromium.launch(**launch_options)
        
        context_options = {
            "viewport": self.viewport,
            "user_agent": self.user_agent,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "permissions": [],
            "java_script_enabled": True,
        }
        
        if self.proxy:
            context_options["proxy"] = {"server": self.proxy}
        
        # Add basic auth if configured
        if self.auth_manager and self.auth_manager.config.basic_auth:
            username, password = self.auth_manager.config.basic_auth
            context_options["http_credentials"] = {
                "username": username,
                "password": password,
            }
        
        self._context = await self._browser.new_context(**context_options)
        
        # Apply auth manager to context (cookies, headers)
        if self.auth_manager:
            # base_url will be set when clone starts
            pass
        
        # Inject evasion scripts for every new page
        await self._context.add_init_script(
            "\n".join(self.EVASION_SCRIPTS)
        )
        
        return self

    async def new_page(self) -> Page:
        """Create a new page with stealth settings applied."""
        if not self._context:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        page = await self._context.new_page()
        
        # Additional page-level evasions
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
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def mimic_human_behavior(self, page: Page):
        """Simulate realistic human-like mouse movements and scrolling."""
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
