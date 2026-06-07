"""
WebExplorer - Intelligent Web Application Exploration Engine

Explores web applications by:
1. Stealth browsing with CloakBrowser
2. Deep page analysis with SmartAnalyzer
3. Asset downloading and organization
4. Static site generation for local replay
"""

import asyncio
import json
import hashlib
import mimetypes
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, urljoin, unquote

import aiohttp
from playwright.async_api import Page

from .browser import CloakBrowser
from .analyzer import SmartAnalyzer, PageAnalysis, AssetInfo
from .auth import AuthManager, AuthConfig


class WebExplorer:
    """
    Main exploration engine that orchestrates the entire exploration process.
    """

    def __init__(
        self,
        output_dir: str = "./explored",
        headless: bool = True,
        max_depth: int = 1,
        proxy: Optional[str] = None,
        auth_manager: Optional[AuthManager] = None,
        humanize: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.headless = headless
        self.max_depth = max_depth
        self.proxy = proxy
        self.auth_manager = auth_manager
        self.humanize = humanize
        
        self.analyzer = SmartAnalyzer()
        self.browser: Optional[CloakBrowser] = None
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Tracking
        self.visited_urls: set = set()
        self.downloaded_assets: Dict[str, Path] = {}

    async def __aenter__(self):
        self.browser = CloakBrowser(
            headless=self.headless,
            proxy=self.proxy,
            auth_manager=self.auth_manager,
            humanize=self.humanize,
        )
        await self.browser.launch()
        
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=10, ssl=False)
        self.session = aiohttp.ClientSession(
            connector=connector,
            headers={
                "User-Agent": self.browser.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        if self.browser:
            await self.browser.close()

    async def explore(self, url: str) -> Path:
        """
        Explore a web application starting from the given URL.
        
        Args:
            url: Target URL to explore
            
        Returns:
            Path to the output directory containing the explored site
        """
        print(f"[EXPLORE] Starting exploration of {url}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create asset directories
        assets_dir = self.output_dir / "assets"
        for subdir in ["css", "js", "images", "fonts", "api"]:
            (assets_dir / subdir).mkdir(parents=True, exist_ok=True)
        
        # Start BFS exploration
        queue = [(url, 0)]
        while queue:
            current_url, depth = queue.pop(0)  # BFS: FIFO
            links = await self._explore_page(current_url, depth)
            if links and depth < self.max_depth:
                queue.extend([(link, depth + 1) for link in links])
        
        # Generate index and manifest
        await self._generate_manifest()
        await self._generate_index_html()
        
        print(f"[DONE] Explore complete! Output: {self.output_dir.absolute()}")
        return self.output_dir

    async def _explore_page(self, url: str, depth: int = 0):
        """Explore a single page and its assets."""
        if url in self.visited_urls or depth > self.max_depth:
            return
        
        self.visited_urls.add(url)
        print(f"  [PAGE] Crawling: {url} (depth={depth})")
        
        safe_links = []
        page = await self.browser.new_page()
        try:
            # Apply auth to context on first page
            if self.auth_manager and depth == 0 and len(self.visited_urls) == 1:
                await self.auth_manager.apply_to_context(page.context, url)
            
            # Apply page-level auth (localStorage, etc.)
            if self.auth_manager:
                await self.auth_manager.apply_to_page(page)
            
            # Navigate with timeout and wait for network idle
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)  # Allow JS frameworks to hydrate
            
            # CAPTCHA detection on first page
            if self.auth_manager and depth == 0:
                captcha_ok = await self.auth_manager.handle_captcha(page)
                if not captcha_ok:
                    print("[AUTH] Explore aborted due to CAPTCHA")
                    return
            
            # Handle manual login if configured (only on first page)
            if self.auth_manager and self.auth_manager.config.wait_for_login and depth == 0:
                login_ok = await self.auth_manager.handle_login_flow(page)
                if not login_ok:
                    print("[AUTH] Login failed or timed out. Continuing with unauthenticated state.")
                # Re-apply page-level auth after potential redirect
                await self.auth_manager.apply_to_page(page)
            
            # Mimic human behavior
            await self.browser.mimic_human_behavior(page)
            
            # Analyze the page
            analysis = await self.analyzer.analyze(page)
            
            # Save analysis
            analysis_path = self.output_dir / f"analysis_{len(self.visited_urls)}.json"
            analysis_path.write_text(self.analyzer.export_json(analysis), encoding="utf-8")
            
            # Download all assets
            await self._download_assets(analysis, url)
            
            # Save modified HTML (with local asset paths)
            html = await self._rewrite_html(page, analysis, url)
            page_filename = self._get_page_filename(url)
            html_path = self.output_dir / page_filename
            html_path.write_text(html, encoding="utf-8")
            
            print(f"    [OK] Saved: {page_filename}")
            
            # Follow links if within depth limit
            if depth < self.max_depth:
                # Filter out dangerous links that could log us out
                DANGEROUS = ['logout', 'signout', 'exit', 'quit', 'sign-out', 'log-out']
                safe_links = [
                    link for link in analysis.links[:20]  # Limit to 20 links per page
                    if not any(d in link.lower() for d in DANGEROUS)
                ]
                if len(safe_links) < len(analysis.links[:20]):
                    skipped = len(analysis.links[:20]) - len(safe_links)
                    print(f"    [FILTER] Skipped {skipped} dangerous link(s) (logout/signout)")
                    
        except Exception as e:
            print(f"    [ERR] Error exploring {url}: {e}")
        finally:
            await page.close()
        
        return safe_links

    async def _download_assets(self, analysis: PageAnalysis, base_url: str):
        """Download all discovered assets."""
        all_assets = (
            analysis.stylesheets +
            analysis.scripts +
            analysis.images +
            analysis.fonts
        )
        
        tasks = []
        for asset in all_assets:
            if asset.url.startswith("http") and asset.url not in self.downloaded_assets:
                tasks.append(self._download_single_asset(asset, base_url))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _download_single_asset(self, asset: AssetInfo, base_url: str):
        """Download a single asset file."""
        try:
            # Apply auth headers to asset downloads if bearer token is set
            headers = {}
            if self.auth_manager and self.auth_manager.config.bearer_token:
                headers["Authorization"] = f"Bearer {self.auth_manager.config.bearer_token}"
            
            async with self.session.get(
                asset.url, 
                timeout=aiohttp.ClientTimeout(total=30),
                headers=headers if headers else None
            ) as resp:
                if resp.status != 200:
                    return
                
                content = await resp.read()
                
                # Determine filename
                parsed = urlparse(asset.url)
                original_name = Path(unquote(parsed.path)).name or "unknown"
                
                # Add hash to avoid collisions
                content_hash = hashlib.md5(content).hexdigest()[:8]
                if "." in original_name:
                    name, ext = original_name.rsplit(".", 1)
                    filename = f"{name}_{content_hash}.{ext}"
                else:
                    filename = f"{original_name}_{content_hash}"
                
                # Determine subdirectory
                type_map = {
                    "stylesheet": "css",
                    "script": "js",
                    "inline-script": "js",
                    "image": "images",
                    "font": "fonts",
                }
                subdir = type_map.get(asset.type, "assets")
                
                asset_path = self.output_dir / "assets" / subdir / filename
                asset_path.write_bytes(content)
                
                self.downloaded_assets[asset.url] = asset_path
                
        except Exception as e:
            print(f"    [WARN] Failed to download {asset.url}: {e}")

    async def _rewrite_html(self, page: Page, analysis: PageAnalysis, base_url: str) -> str:
        """Rewrite HTML to use local asset paths."""
        html = await page.content()
        
        # Replace full asset URLs with local paths
        for asset_url, local_path in self.downloaded_assets.items():
            relative_path = str(local_path.relative_to(self.output_dir)).replace("\\", "/")
            html = html.replace(asset_url, relative_path)
        
        # Replace relative URL variants (path only, and path with query string)
        for asset_url, local_path in self.downloaded_assets.items():
            relative_path = str(local_path.relative_to(self.output_dir)).replace("\\", "/")
            parsed = urlparse(asset_url)
            
            # Variant 1: path only (e.g., /user_assets/css/backend.css)
            relative_variant = parsed.path
            if relative_variant.startswith("/"):
                html = html.replace(f'"{relative_variant}"', f'"{relative_path}"')
                html = html.replace(f"'{relative_variant}'", f"'{relative_path}'")
            
            # Variant 2: path with query string (e.g., /user_assets/css/backend.css?v=1.3.526)
            if parsed.query:
                variant_with_query = f"{parsed.path}?{parsed.query}"
                html = html.replace(f'"{variant_with_query}"', f'"{relative_path}"')
                html = html.replace(f"'{variant_with_query}'", f"'{relative_path}'")
                
                # Variant 3: query with HTML-escaped ampersand (&amp;)
                variant_html_escaped = variant_with_query.replace("&", "&amp;")
                html = html.replace(f'"{variant_html_escaped}"', f'"{relative_path}"')
                html = html.replace(f"'{variant_html_escaped}'", f"'{relative_path}'")
            
            # Variant 4: path with ../ normalization (e.g., /user_assets/js/../libs/...)
            from os.path import normpath
            normalized = normpath(relative_variant)
            if normalized != relative_variant and normalized.startswith("/"):
                html = html.replace(f'"{normalized}"', f'"{relative_path}"')
                html = html.replace(f"'{normalized}'", f"'{relative_path}'")
        
        return html

    def _get_page_filename(self, url: str) -> str:
        """Generate a filename for the explored page."""
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        
        if not path or path == "/":
            return "index.html"
        
        # Convert path to filename
        safe_path = path.replace("/", "_").replace("?", "_").replace("&", "_")
        if not safe_path.endswith(".html"):
            safe_path += ".html"
        
        return safe_path

    async def _generate_manifest(self):
        """Generate a manifest file with exploration metadata."""
        manifest = {
            "explored_at": str(asyncio.get_event_loop().time()),
            "total_pages": len(self.visited_urls),
            "total_assets": len(self.downloaded_assets),
            "pages": list(self.visited_urls),
            "assets": {url: str(path.relative_to(self.output_dir)).replace("\\", "/") 
                      for url, path in self.downloaded_assets.items()},
        }
        
        manifest_path = self.output_dir / "weblica-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    async def _generate_index_html(self):
        """Generate a browsable index page for the explored site."""
        pages_html = "\n".join(
            f'<li><a href="{self._get_page_filename(url)}">{url}</a></li>'
            for url in sorted(self.visited_urls)
        )
        
        assets_html = "\n".join(
            f'<li>{asset_type}: {path.name}</li>'
            for url, path in sorted(self.downloaded_assets.items())
            for asset_type in ["asset"]
        )
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Weblica Explore Index</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 40px 20px;
            background: #0f172a;
            color: #e2e8f0;
        }}
        h1 {{
            color: #38bdf8;
            border-bottom: 2px solid #38bdf8;
            padding-bottom: 10px;
        }}
        h2 {{ color: #818cf8; margin-top: 30px; }}
        a {{ color: #38bdf8; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        ul {{ line-height: 1.8; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: #1e293b;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #334155;
        }}
        .stat-number {{
            font-size: 2em;
            font-weight: bold;
            color: #38bdf8;
        }}
    </style>
</head>
<body>
    <h1>Weblica Explore Index</h1>
    <p>智能克隆结果浏览页</p>
    
    <div class="stats">
        <div class="stat-card">
            <div class="stat-number">{len(self.visited_urls)}</div>
            <div>已克隆页面</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{len(self.downloaded_assets)}</div>
            <div>已下载资源</div>
        </div>
    </div>
    
    <h2>📄 页面列表</h2>
    <ul>{pages_html}</ul>
    
    <footer style="margin-top: 50px; padding-top: 20px; border-top: 1px solid #334155; color: #64748b;">
        Generated by Weblica - Intelligent Web Explorer
    </footer>
</body>
</html>"""
        
        index_path = self.output_dir / "weblica-index.html"
        index_path.write_text(html, encoding="utf-8")
