"""
WebReplayer - Local Replay and Testing Engine

Provides:
- Local HTTP server for cloned sites
- Hot-reload during development
- Screenshot comparison (before/after)
- Interaction recording and playback
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime

import aiohttp
from aiohttp import web
from playwright.async_api import Page, async_playwright

from .browser import CloakBrowser


@dataclass
class Interaction:
    """Recorded user interaction."""
    timestamp: float
    type: str  # click, input, scroll, navigate
    target: str  # CSS selector or description
    value: Optional[str] = None
    coordinates: Optional[Dict[str, int]] = None


@dataclass
class ReplaySession:
    """A recorded session for replay."""
    start_url: str
    interactions: List[Interaction]
    screenshots: List[str]  # paths to screenshots
    metadata: Dict[str, Any]


class WebReplayer:
    """
    Replays cloned web applications locally and provides testing utilities.
    """

    def __init__(self, clone_dir: str = "./cloned", port: int = 8080):
        self.clone_dir = Path(clone_dir)
        self.port = port
        self.server: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def start_server(self) -> str:
        """Start the local replay server."""
        if not self.clone_dir.exists():
            raise FileNotFoundError(f"Clone directory not found: {self.clone_dir}")

        app = web.Application()
        
        # Serve cloned files
        app.router.add_static("/", self.clone_dir, show_index=True)
        
        # API endpoints
        app.router.add_get("/weblica/api/status", self._handle_status)
        app.router.add_get("/weblica/api/manifest", self._handle_manifest)
        
        self.server = web.AppRunner(app)
        await self.server.setup()
        
        self._site = web.TCPSite(self.server, "localhost", self.port)
        await self._site.start()
        
        url = f"http://localhost:{self.port}"
        print(f"[SERVER] Replay server started at {url}")
        return url

    async def stop_server(self):
        """Stop the local replay server."""
        if self._site:
            await self._site.stop()
        if self.server:
            await self.server.cleanup()
        print("[STOP] Replay server stopped")

    async def _handle_status(self, request: web.Request) -> web.Response:
        """Handle status API request."""
        return web.json_response({
            "status": "running",
            "clone_dir": str(self.clone_dir),
            "timestamp": datetime.now().isoformat(),
        })

    async def _handle_manifest(self, request: web.Request) -> web.Response:
        """Handle manifest API request."""
        manifest_path = self.clone_dir / "weblica-manifest.json"
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return web.json_response(data)
        return web.json_response({"error": "Manifest not found"}, status=404)

    async def take_screenshot(
        self,
        url: str,
        output_path: Optional[str] = None,
        full_page: bool = True,
        wait_for: Optional[str] = None,
    ) -> Path:
        """Take a screenshot of a URL for visual comparison."""
        output_path = Path(output_path or f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        
        async with CloakBrowser(headless=True) as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=10000)
            
            await page.screenshot(path=str(output_path), full_page=full_page)
            print(f"[SCREENSHOT] Screenshot saved: {output_path}")
            
        return output_path

    async def compare_visual(
        self,
        original_url: str,
        clone_url: Optional[str] = None,
        output_dir: str = "./comparison",
    ) -> Dict[str, Path]:
        """
        Compare visual appearance between original and clone.
        
        Returns paths to original screenshot, clone screenshot, and diff image.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        clone_url = clone_url or f"http://localhost:{self.port}/index.html"
        
        # Take screenshots
        original_shot = await self.take_screenshot(
            original_url, 
            output_path=output_dir / "original.png"
        )
        
        clone_shot = await self.take_screenshot(
            clone_url,
            output_path=output_dir / "clone.png"
        )
        
        # Try to create diff using PIL if available
        diff_path = output_dir / "diff.png"
        try:
            from PIL import Image, ImageChops
            
            img1 = Image.open(original_shot).convert("RGB")
            img2 = Image.open(clone_shot).convert("RGB")
            
            # Resize to same dimensions
            if img1.size != img2.size:
                img2 = img2.resize(img1.size)
            
            diff = ImageChops.difference(img1, img2)
            diff.save(diff_path)
            
            # Calculate difference percentage
            diff_bbox = diff.getbbox()
            if diff_bbox:
                diff_area = (diff_bbox[2] - diff_bbox[0]) * (diff_bbox[3] - diff_bbox[1])
                total_area = img1.size[0] * img1.size[1]
                diff_percent = (diff_area / total_area) * 100
            else:
                diff_percent = 0
                
            print(f"[DIFF] Visual difference: {diff_percent:.2f}%")
            
        except ImportError:
            print("[WARN] PIL not available, skipping diff generation")
            diff_path = None
        
        return {
            "original": original_shot,
            "clone": clone_shot,
            "diff": diff_path,
        }

    async def record_interactions(self, url: str, duration: int = 60) -> ReplaySession:
        """
        Record user interactions on a page for later replay.
        
        Args:
            url: URL to record on
            duration: Recording duration in seconds
            
        Returns:
            ReplaySession with recorded interactions
        """
        session = ReplaySession(
            start_url=url,
            interactions=[],
            screenshots=[],
            metadata={"started_at": datetime.now().isoformat()},
        )
        
        async with CloakBrowser(headless=False, slow_mo=50) as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            
            print(f"[RECORD] Recording started. Interact with the page for {duration}s...")
            print("   Press Ctrl+C to stop early")
            
            # Inject interaction recording script
            await page.evaluate("""
                window._weblicaInteractions = [];
                
                document.addEventListener('click', (e) => {
                    window._weblicaInteractions.push({
                        timestamp: Date.now(),
                        type: 'click',
                        target: e.target.tagName + (e.target.id ? '#' + e.target.id : '') + 
                                (e.target.className ? '.' + e.target.className.split(' ').join('.') : ''),
                        coordinates: { x: e.clientX, y: e.clientY }
                    });
                });
                
                document.addEventListener('input', (e) => {
                    window._weblicaInteractions.push({
                        timestamp: Date.now(),
                        type: 'input',
                        target: e.target.tagName + (e.target.id ? '#' + e.target.id : '') + 
                                (e.target.name ? '[name=' + e.target.name + ']' : ''),
                        value: e.target.value
                    });
                });
                
                let lastScroll = 0;
                window.addEventListener('scroll', () => {
                    const now = Date.now();
                    if (now - lastScroll > 500) {
                        window._weblicaInteractions.push({
                            timestamp: now,
                            type: 'scroll',
                            target: 'window',
                            value: JSON.stringify({ x: window.scrollX, y: window.scrollY })
                        });
                        lastScroll = now;
                    }
                });
            """)
            
            try:
                await asyncio.sleep(duration)
            except asyncio.CancelledError:
                pass
            
            # Retrieve recorded interactions
            raw_interactions = await page.evaluate("() => window._weblicaInteractions")
            
            for raw in raw_interactions:
                session.interactions.append(Interaction(
                    timestamp=raw["timestamp"],
                    type=raw["type"],
                    target=raw["target"],
                    value=raw.get("value"),
                    coordinates=raw.get("coordinates"),
                ))
            
            # Take final screenshot
            screenshot_path = f"recorded_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            session.screenshots.append(screenshot_path)
            
        session.metadata["ended_at"] = datetime.now().isoformat()
        session.metadata["interaction_count"] = len(session.interactions)
        
        print(f"[DONE] Recorded {len(session.interactions)} interactions")
        return session

    async def replay_interactions(self, session: ReplaySession, target_url: Optional[str] = None):
        """Replay a recorded interaction session."""
        url = target_url or session.start_url
        
        async with CloakBrowser(headless=False, slow_mo=100) as browser:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            
            print(f"[PLAY] Replaying {len(session.interactions)} interactions...")
            
            start_time = session.interactions[0].timestamp if session.interactions else 0
            
            for interaction in session.interactions:
                # Wait relative to recording timing
                if interaction.timestamp > start_time:
                    wait_ms = (interaction.timestamp - start_time) / 1000
                    wait_ms = min(wait_ms, 3)  # Cap at 3s between actions
                    await asyncio.sleep(wait_ms)
                
                try:
                    if interaction.type == "click":
                        if interaction.coordinates:
                            await page.mouse.click(
                                interaction.coordinates["x"],
                                interaction.coordinates["y"]
                            )
                        else:
                            # Try to find by selector
                            try:
                                await page.click(interaction.target, timeout=2000)
                            except:
                                pass
                                
                    elif interaction.type == "input":
                        try:
                            await page.fill(interaction.target, interaction.value or "", timeout=2000)
                        except:
                            pass
                            
                    elif interaction.type == "scroll":
                        if interaction.value:
                            coords = json.loads(interaction.value)
                            await page.evaluate(f"window.scrollTo({coords['x']}, {coords['y']})")
                            
                except Exception as e:
                    print(f"    [WARN] Failed to replay action: {e}")
            
            print("[DONE] Replay complete")
            
            # Final screenshot
            await page.screenshot(path="replay_final.png", full_page=True)

    def save_session(self, session: ReplaySession, path: str):
        """Save a replay session to file."""
        data = {
            "start_url": session.start_url,
            "interactions": [asdict(i) for i in session.interactions],
            "screenshots": session.screenshots,
            "metadata": session.metadata,
        }
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_session(self, path: str) -> ReplaySession:
        """Load a replay session from file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return ReplaySession(
            start_url=data["start_url"],
            interactions=[Interaction(**i) for i in data["interactions"]],
            screenshots=data["screenshots"],
            metadata=data["metadata"],
        )
