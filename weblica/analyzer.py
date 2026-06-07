"""
Smart Analyzer - Analyzes web application structure and dependencies

Extracts:
- DOM structure and components
- CSS stylesheets
- JavaScript files and inline scripts
- API endpoints and network patterns
- Static assets (images, fonts, etc.)
- Framework detection (React, Vue, Angular, etc.)
"""

import json
import re
from typing import Dict, List, Set, Optional, Any
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass, field, asdict

from playwright.async_api import Page


@dataclass
class AssetInfo:
    """Information about a web asset."""
    url: str
    type: str  # script, stylesheet, image, font, xhr, etc.
    content: Optional[str] = None
    filename: Optional[str] = None
    size: Optional[int] = None


@dataclass
class APIEndpoint:
    """Discovered API endpoint."""
    url: str
    method: str
    headers: Dict[str, str] = field(default_factory=dict)
    request_body: Optional[str] = None
    response_type: Optional[str] = None


@dataclass
class FrameworkInfo:
    """Detected framework/library info."""
    name: str
    version: Optional[str] = None
    confidence: float = 0.0  # 0-1


@dataclass
class PageAnalysis:
    """Complete analysis result of a web page."""
    url: str
    title: str
    description: Optional[str] = None
    
    # Structure
    html_structure: str = ""
    body_text: str = ""
    
    # Assets
    stylesheets: List[AssetInfo] = field(default_factory=list)
    scripts: List[AssetInfo] = field(default_factory=list)
    images: List[AssetInfo] = field(default_factory=list)
    fonts: List[AssetInfo] = field(default_factory=list)
    
    # APIs
    api_endpoints: List[APIEndpoint] = field(default_factory=list)
    
    # Tech stack
    frameworks: List[FrameworkInfo] = field(default_factory=list)
    
    # Metadata
    meta_tags: Dict[str, str] = field(default_factory=dict)
    favicon: Optional[str] = None
    
    # Interactive elements
    forms: List[Dict[str, Any]] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    links_detailed: List[Dict[str, Any]] = field(default_factory=list)
    buttons: List[str] = field(default_factory=list)
    buttons_detailed: List[Dict[str, Any]] = field(default_factory=list)
    interactive_elements: List[Dict[str, Any]] = field(default_factory=list)


class SmartAnalyzer:
    """Analyzes web applications to extract explorable components."""

    FRAMEWORK_SIGNATURES = {
        "React": [
            r"data-reactroot",
            r"data-reactid",
            r"__REACT_INTL_CONTEXT__",
            r"react-root",
        ],
        "Vue": [
            r"data-v-[a-f0-9]+",
            r"__VUE__",
            r"vue-router",
        ],
        "Angular": [
            r"ng-[a-z-]+",
            r"_ngcontent",
            r"angular",
        ],
        "Svelte": [
            r"svelte-[a-z0-9]+",
        ],
        "Next.js": [
            r"__NEXT_DATA__",
        ],
        "Nuxt.js": [
            r"__NUXT__",
        ],
    }

    def __init__(self):
        self.results: Dict[str, PageAnalysis] = {}

    async def analyze(self, page: Page, capture_network: bool = True) -> PageAnalysis:
        """Perform comprehensive analysis of the current page."""
        url = page.url
        
        analysis = PageAnalysis(url=url, title=await page.title())
        
        # Capture HTML structure
        analysis.html_structure = await page.content()
        
        # Extract text content
        analysis.body_text = await page.evaluate("() => document.body.innerText")
        
        # Extract metadata
        analysis.meta_tags = await self._extract_meta_tags(page)
        analysis.description = analysis.meta_tags.get("description")
        analysis.favicon = await self._extract_favicon(page, url)
        
        # Extract all assets
        analysis.stylesheets = await self._extract_stylesheets(page, url)
        analysis.scripts = await self._extract_scripts(page, url)
        analysis.images = await self._extract_images(page, url)
        analysis.fonts = await self._extract_fonts(page, url)
        
        # Detect frameworks
        analysis.frameworks = self._detect_frameworks(analysis.html_structure)
        
        # Extract interactive elements
        analysis.forms = await self._extract_forms(page)
        analysis.links = await self._extract_links(page, url)
        analysis.links_detailed = await self._extract_links_detailed(page, url)
        analysis.buttons = await self._extract_buttons(page)
        analysis.buttons_detailed = await self._extract_buttons_detailed(page)
        analysis.interactive_elements = await self._extract_interactive_elements(page)
        
        # Extract API endpoints from scripts and page data
        analysis.api_endpoints = await self._extract_api_endpoints(page, analysis.scripts)
        
        self.results[url] = analysis
        return analysis

    async def _extract_meta_tags(self, page: Page) -> Dict[str, str]:
        """Extract all meta tags."""
        return await page.evaluate("""
            () => {
                const meta = {};
                document.querySelectorAll('meta').forEach(tag => {
                    const name = tag.getAttribute('name') || tag.getAttribute('property');
                    const content = tag.getAttribute('content');
                    if (name && content) meta[name] = content;
                });
                return meta;
            }
        """)

    async def _extract_favicon(self, page: Page, base_url: str) -> Optional[str]:
        """Extract favicon URL."""
        favicon = await page.evaluate("""
            () => {
                const link = document.querySelector('link[rel~="icon"]');
                return link ? link.href : null;
            }
        """)
        if favicon and not favicon.startswith("http"):
            favicon = urljoin(base_url, favicon)
        return favicon

    async def _extract_stylesheets(self, page: Page, base_url: str) -> List[AssetInfo]:
        """Extract all CSS stylesheets."""
        urls = await page.evaluate("""
            () => Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
                .map(link => link.href)
                .filter(Boolean)
        """)
        return [AssetInfo(url=urljoin(base_url, u) if not u.startswith("http") else u, 
                         type="stylesheet") for u in urls]

    async def _extract_scripts(self, page: Page, base_url: str) -> List[AssetInfo]:
        """Extract all script sources and inline scripts."""
        scripts = await page.evaluate("""
            () => Array.from(document.querySelectorAll('script')).map(script => ({
                src: script.src,
                type: script.type || 'text/javascript',
                async: script.async,
                defer: script.defer,
                content: script.src ? null : script.textContent.substring(0, 5000)
            }))
        """)
        
        result = []
        for script in scripts:
            if script["src"]:
                url = script["src"] if script["src"].startswith("http") else urljoin(base_url, script["src"])
                result.append(AssetInfo(url=url, type="script"))
            elif script["content"]:
                result.append(AssetInfo(
                    url=f"inline-{len(result)}", 
                    type="inline-script",
                    content=script["content"]
                ))
        return result

    async def _extract_images(self, page: Page, base_url: str) -> List[AssetInfo]:
        """Extract all image sources."""
        urls = await page.evaluate("""
            () => Array.from(new Set([
                ...Array.from(document.querySelectorAll('img')).map(img => img.src),
                ...Array.from(document.querySelectorAll('*[style*="url"]')).map(el => {
                    const match = el.style.backgroundImage.match(/url\\(["']?(.*?)["']?\\)/);
                    return match ? match[1] : null;
                })
            ])).filter(Boolean)
        """)
        return [AssetInfo(
            url=urljoin(base_url, u) if not u.startswith("http") else u,
            type="image"
        ) for u in urls]

    async def _extract_fonts(self, page: Page, base_url: str) -> List[AssetInfo]:
        """Extract font URLs from CSS."""
        # Get all computed stylesheets and look for @font-face
        font_urls = await page.evaluate("""
            () => {
                const fonts = new Set();
                for (const sheet of document.styleSheets) {
                    try {
                        for (const rule of sheet.cssRules || []) {
                            if (rule.style && rule.style.fontFamily) {
                                const src = rule.style.src;
                                if (src) {
                                    const matches = src.match(/url\\(["']?(.*?)["']?\\)/g);
                                    if (matches) {
                                        matches.forEach(m => {
                                            const url = m.match(/url\\(["']?(.*?)["']?\\)/)[1];
                                            fonts.add(url);
                                        });
                                    }
                                }
                            }
                        }
                    } catch (e) {}
                }
                return Array.from(fonts);
            }
        """)
        return [AssetInfo(
            url=urljoin(base_url, u) if not u.startswith("http") else u,
            type="font"
        ) for u in font_urls]

    async def _extract_forms(self, page: Page) -> List[Dict[str, Any]]:
        """Extract form structures."""
        return await page.evaluate("""
            () => Array.from(document.querySelectorAll('form')).map(form => ({
                action: form.action,
                method: form.method,
                id: form.id,
                class: form.className,
                inputs: Array.from(form.querySelectorAll('input, textarea, select')).map(input => ({
                    type: input.type || input.tagName.toLowerCase(),
                    name: input.name,
                    id: input.id,
                    placeholder: input.placeholder,
                    required: input.required,
                }))
            }))
        """)

    async def _extract_links(self, page: Page, base_url: str) -> List[str]:
        """Extract all internal links, filtering out dangerous ones (logout, etc.)."""
        links = await page.evaluate("""
            () => Array.from(new Set(
                Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(href => href.startsWith('http'))
            ))
        """)
        base_domain = urlparse(base_url).netloc
        internal = [l for l in links if urlparse(l).netloc == base_domain]
        
        # Filter out dangerous links that would log the user out or perform destructive actions
        DANGEROUS_PATHS = ['logout', 'signout', 'exit', 'quit', 'sign-out', 'log-out']
        DANGEROUS_QUERIES = ['action=logout', 'action=signout', 'logout=true', 'signout=true']
        safe_links = []
        for link in internal:
            lower = link.lower()
            path = urlparse(link).path.lower()
            query = urlparse(link).query.lower()
            
            # Skip if path contains logout/signout keywords
            if any(d in path for d in DANGEROUS_PATHS):
                continue
            # Skip if query string triggers logout action
            if any(d in query for d in DANGEROUS_QUERIES):
                continue
            # Skip mailto: / tel: (should already be filtered by http check, but be safe)
            if lower.startswith(('mailto:', 'tel:')):
                continue
            
            safe_links.append(link)
        
        return safe_links

    async def _extract_buttons(self, page: Page) -> List[str]:
        """Extract button texts."""
        return await page.evaluate("""
            () => Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'))
                .map(btn => btn.textContent.trim() || btn.value)
                .filter(Boolean)
        """)

    async def _extract_buttons_detailed(self, page: Page) -> List[Dict[str, Any]]:
        """Extract detailed button info: selector, text, tag, classes, onclick, href."""
        return await page.evaluate("""
            () => {
                const getSelector = (el) => {
                    if (el.id) return '#' + el.id;
                    const tag = el.tagName.toLowerCase();
                    const cls = Array.from(el.classList).slice(0, 3).join('.');
                    const txt = el.textContent.trim().substring(0, 30);
                    return cls ? tag + '.' + cls : tag + (txt ? `[title="${txt}"]` : '');
                };
                return Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"], a.btn, a[class*="btn"]'))
                    .map((btn, idx) => ({
                        index: idx,
                        text: (btn.textContent.trim() || btn.value || '').substring(0, 100),
                        tag: btn.tagName.toLowerCase(),
                        selector: getSelector(btn),
                        id: btn.id || null,
                        class: btn.className || null,
                        href: btn.href || null,
                        onclick: btn.getAttribute('onclick') || null,
                        type: btn.type || null,
                        disabled: btn.disabled || false,
                    }))
                    .filter(b => b.text)
            }
        """)

    async def _extract_links_detailed(self, page: Page, base_url: str) -> List[Dict[str, Any]]:
        """Extract detailed link info: url, text, selector, title."""
        raw = await page.evaluate("""
            () => {
                const getSelector = (el) => {
                    if (el.id) return '#' + el.id;
                    const tag = el.tagName.toLowerCase();
                    const cls = Array.from(el.classList).slice(0, 3).join('.');
                    return cls ? tag + '.' + cls : tag;
                };
                return Array.from(document.querySelectorAll('a[href]')).map((a, idx) => ({
                    index: idx,
                    url: a.href,
                    text: (a.textContent.trim() || a.title || '').substring(0, 100),
                    selector: getSelector(a),
                    id: a.id || null,
                    class: a.className || null,
                    title: a.title || null,
                    target: a.target || null,
                }));
            }
        """)
        base_domain = urlparse(base_url).netloc
        DANGEROUS_PATHS = ['logout', 'signout', 'exit', 'quit', 'sign-out', 'log-out']
        DANGEROUS_QUERIES = ['action=logout', 'action=signout', 'logout=true', 'signout=true']
        safe = []
        for link in raw:
            url = link.get("url", "")
            if not url.startswith("http"):
                continue
            if urlparse(url).netloc != base_domain:
                continue
            lower = url.lower()
            path = urlparse(url).path.lower()
            query = urlparse(url).query.lower()
            if any(d in path for d in DANGEROUS_PATHS):
                continue
            if any(d in query for d in DANGEROUS_QUERIES):
                continue
            safe.append(link)
        return safe

    async def _extract_interactive_elements(self, page: Page) -> List[Dict[str, Any]]:
        """Extract all interactive elements: inputs, selects, textareas, toggles."""
        return await page.evaluate("""
            () => {
                const getSelector = (el) => {
                    if (el.id) return '#' + el.id;
                    if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                    const cls = Array.from(el.classList).slice(0, 2).join('.');
                    return cls ? el.tagName.toLowerCase() + '.' + cls : el.tagName.toLowerCase();
                };
                const elements = [];
                // Inputs
                document.querySelectorAll('input:not([type="hidden"]), textarea, select').forEach((el, idx) => {
                    elements.push({
                        index: idx,
                        type: el.type || el.tagName.toLowerCase(),
                        tag: el.tagName.toLowerCase(),
                        selector: getSelector(el),
                        id: el.id || null,
                        name: el.name || null,
                        placeholder: el.placeholder || null,
                        value: el.value ? String(el.value).substring(0, 100) : null,
                        required: el.required || false,
                        disabled: el.disabled || false,
                        label: (document.querySelector('label[for="' + el.id + '"]')?.textContent.trim() || '').substring(0, 50),
                    });
                });
                return elements;
            }
        """)

    async def _extract_api_endpoints(self, page: Page, scripts: List[AssetInfo]) -> List[APIEndpoint]:
        """Extract potential API endpoints from inline scripts and page data."""
        endpoints = []
        
        # Check for __NEXT_DATA__ or __NUXT__
        page_data = await page.evaluate("""
            () => {
                const data = {};
                if (window.__NEXT_DATA__) data.__NEXT_DATA__ = window.__NEXT_DATA__;
                if (window.__NUXT__) data.__NUXT__ = window.__NUXT__;
                if (window.__INITIAL_STATE__) data.__INITIAL_STATE__ = window.__INITIAL_STATE__;
                return data;
            }
        """)
        
        # Extract API patterns from inline scripts
        api_patterns = [
            r'["\'](https?://[^"\']+?/api/[^"\']+)["\']',
            r'["\'](/api/[^"\']+)["\']',
            r'["\']([^"\']*?graphql[^"\']*?)["\']',
            r'fetch\(["\']([^"\']+)["\']',
            r'axios\.[a-z]+\(["\']([^"\']+)["\']',
        ]
        
        for script in scripts:
            if script.type == "inline-script" and script.content:
                for pattern in api_patterns:
                    matches = re.findall(pattern, script.content)
                    for match in matches:
                        if match not in [e.url for e in endpoints]:
                            endpoints.append(APIEndpoint(url=match, method="GET"))
        
        return endpoints

    def _detect_frameworks(self, html: str) -> List[FrameworkInfo]:
        """Detect frontend frameworks from HTML signatures."""
        frameworks = []
        
        for name, patterns in self.FRAMEWORK_SIGNATURES.items():
            for pattern in patterns:
                if re.search(pattern, html, re.IGNORECASE):
                    # Check for version if possible
                    version = None
                    version_match = re.search(
                        rf'{re.escape(name)}[@\s]*([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
                        html, re.IGNORECASE
                    )
                    if version_match:
                        version = version_match.group(1)
                    
                    frameworks.append(FrameworkInfo(
                        name=name,
                        version=version,
                        confidence=0.9
                    ))
                    break
        
        return frameworks

    def export_json(self, analysis: PageAnalysis) -> str:
        """Export analysis result to JSON."""
        return json.dumps(asdict(analysis), indent=2, ensure_ascii=False, default=str)
