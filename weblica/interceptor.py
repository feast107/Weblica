"""
Network Interceptor - Captures all HTTP requests/responses from a Playwright page.

Eliminates the need to reverse-engineer minified JS by observing actual API traffic.

Entity hierarchy:
    Session
      └── PageOperation[]
            ├── action (navigate | click | input | scroll | wait)
            ├── interactions[] (request/response pairs triggered by the action)
            ├── before_state
            └── after_state
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from pathlib import Path

from playwright.async_api import Page, Request, Response


@dataclass
class CapturedRequest:
    """A single HTTP request captured from the browser."""
    url: str
    method: str
    headers: Dict[str, str] = field(default_factory=dict)
    post_data: Optional[str] = None
    resource_type: str = ""
    timestamp: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "method": self.method,
            "headers": self.headers,
            "post_data": self.post_data,
            "resource_type": self.resource_type,
            "timestamp": self.timestamp,
        }


@dataclass
class CapturedResponse:
    """A single HTTP response captured from the browser."""
    status: int
    status_text: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    body_preview: Optional[str] = None
    content_type: Optional[str] = None
    timestamp: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "status_text": self.status_text,
            "headers": self.headers,
            "body_preview": self.body_preview,
            "content_type": self.content_type,
            "timestamp": self.timestamp,
        }


@dataclass
class NetworkInteraction:
    """A request/response pair triggered by a page action."""
    request: CapturedRequest
    response: Optional[CapturedResponse] = None
    duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "response": self.response.to_dict() if self.response else None,
            "duration_ms": self.duration_ms,
        }


@dataclass
class PageState:
    """Snapshot of a page at a specific moment."""
    url: str
    title: str = ""
    body_text_preview: str = ""
    timestamp: float = 0.0
    
    @staticmethod
    async def capture(page: Page) -> "PageState":
        """Capture current page state."""
        try:
            title = await page.title()
        except Exception:
            title = ""
        try:
            body_text = await page.evaluate("() => document.body.innerText")
            body_preview = body_text[:500] if body_text else ""
        except Exception:
            body_preview = ""
        return PageState(
            url=page.url,
            title=title,
            body_text_preview=body_preview,
            timestamp=time.time(),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "body_text_preview": self.body_text_preview,
            "timestamp": self.timestamp,
        }


@dataclass
class PageOperation:
    """
    A single operation on a page and all its consequences.
    
    Entity chain: PageState -> Action -> NetworkTraffic -> PageState
    """
    operation_id: int
    page_url: str
    depth: int
    
    action: str = "navigate"  # navigate | click | input | scroll | wait | custom
    target: Optional[str] = None  # CSS selector or description
    action_params: Dict[str, Any] = field(default_factory=dict)
    
    before_state: Optional[PageState] = None
    after_state: Optional[PageState] = None
    
    interactions: List[NetworkInteraction] = field(default_factory=list)
    
    start_time: float = 0.0
    end_time: float = 0.0
    
    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000 if self.end_time > self.start_time else 0.0
    
    @property
    def api_calls(self) -> List[NetworkInteraction]:
        """Filter interactions that are likely API calls (XHR/fetch)."""
        return [
            i for i in self.interactions
            if i.request.resource_type in ("xhr", "fetch", "document", "script")
            and not i.request.url.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2", ".ttf"))
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "page_url": self.page_url,
            "depth": self.depth,
            "action": self.action,
            "target": self.target,
            "action_params": self.action_params,
            "before_state": self.before_state.to_dict() if self.before_state else None,
            "after_state": self.after_state.to_dict() if self.after_state else None,
            "interactions": [i.to_dict() for i in self.interactions],
            "api_calls": [i.to_dict() for i in self.api_calls],
            "duration_ms": self.duration_ms,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


class NetworkInterceptor:
    """
    Attaches to a Playwright page and records all request/response traffic.
    
    Usage:
        interceptor = NetworkInterceptor(page)
        interceptor.start()
        
        # ... perform actions on page ...
        await page.click("button.load-more")
        await page.wait_for_load_state("networkidle")
        
        traffic = interceptor.stop_and_collect()
    """
    
    def __init__(self, page: Page, max_body_preview: int = 2000):
        self.page = page
        self.max_body_preview = max_body_preview
        
        # In-flight requests awaiting responses
        self._pending: Dict[str, CapturedRequest] = {}
        # Completed interactions
        self._interactions: List[NetworkInteraction] = []
        
        self._request_handler = None
        self._response_handler = None
        self._active = False
    
    def start(self):
        """Start listening to network events."""
        if self._active:
            return
        self._active = True
        self._pending.clear()
        self._interactions.clear()
        
        self._request_handler = lambda req: asyncio.create_task(self._on_request(req))
        self._response_handler = lambda resp: asyncio.create_task(self._on_response(resp))
        
        self.page.on("request", self._request_handler)
        self.page.on("response", self._response_handler)
    
    def stop(self):
        """Stop listening but keep collected data."""
        if not self._active:
            return
        self._active = False
        
        if self._request_handler:
            self.page.remove_listener("request", self._request_handler)
        if self._response_handler:
            self.page.remove_listener("response", self._response_handler)
        
        self._request_handler = None
        self._response_handler = None
    
    def stop_and_collect(self) -> List[NetworkInteraction]:
        """Stop listening and return all captured interactions."""
        self.stop()
        return list(self._interactions)
    
    def clear(self):
        """Clear all captured data."""
        self._pending.clear()
        self._interactions.clear()
    
    async def _on_request(self, request: Request):
        """Record an outgoing request."""
        try:
            headers = {}
            try:
                raw_headers = await request.all_headers()
                headers = dict(raw_headers)
            except Exception:
                pass
            
            post_data = None
            try:
                post_data = request.post_data
            except Exception:
                pass
            
            captured = CapturedRequest(
                url=request.url,
                method=request.method,
                headers=headers,
                post_data=post_data,
                resource_type=request.resource_type,
                timestamp=time.time(),
            )
            
            self._pending[request.url] = captured
        except Exception:
            pass
    
    async def _on_response(self, response: Response):
        """Record an incoming response and pair it with its request."""
        try:
            request_url = response.request.url
            captured_req = self._pending.pop(request_url, None)
            
            if not captured_req:
                # Response without recorded request (e.g., from cache)
                try:
                    headers = dict(await response.request.all_headers())
                except Exception:
                    headers = {}
                captured_req = CapturedRequest(
                    url=request_url,
                    method=response.request.method,
                    headers=headers,
                    resource_type=response.request.resource_type,
                    timestamp=time.time(),
                )
            
            # Capture response headers and status
            resp_headers = {}
            try:
                raw_headers = await response.all_headers()
                resp_headers = dict(raw_headers)
            except Exception:
                pass
            
            content_type = resp_headers.get("content-type", "")
            
            # Try to capture body preview for API-like responses
            body_preview = None
            if content_type and any(ct in content_type for ct in ["json", "javascript", "text", "xml"]):
                try:
                    body = await response.body()
                    text = body.decode("utf-8", errors="replace")
                    body_preview = text[:self.max_body_preview]
                    if len(text) > self.max_body_preview:
                        body_preview += f"\n... ({len(text)} bytes total)"
                except Exception:
                    pass
            
            captured_resp = CapturedResponse(
                status=response.status,
                status_text=response.status_text,
                headers=resp_headers,
                body_preview=body_preview,
                content_type=content_type,
                timestamp=time.time(),
            )
            
            interaction = NetworkInteraction(
                request=captured_req,
                response=captured_resp,
                duration_ms=(captured_resp.timestamp - captured_req.timestamp) * 1000,
            )
            
            self._interactions.append(interaction)
        except Exception:
            pass


class SessionRecorder:
    """
    Records a complete session of page operations with full network telemetry.
    
    Usage:
        recorder = SessionRecorder()
        
        # Operation 1: Navigate
        op = await recorder.record_navigate(page, url="...", depth=0)
        
        # Operation 2: Click a button
        op = await recorder.record_click(page, selector="button.load", depth=0)
        
        # Save
        recorder.save("session.json")
    """
    
    def __init__(self):
        self.operations: List[PageOperation] = []
        self._counter = 0
    
    def _next_id(self) -> int:
        self._counter += 1
        return self._counter
    
    async def record_navigate(self, page: Page, url: str, depth: int = 0, wait_until: str = "networkidle") -> PageOperation:
        """Record a page navigation and all resulting network traffic."""
        op = PageOperation(
            operation_id=self._next_id(),
            page_url=url,
            depth=depth,
            action="navigate",
            target=url,
        )
        
        interceptor = NetworkInterceptor(page)
        interceptor.start()
        op.start_time = time.time()
        
        try:
            op.before_state = await PageState.capture(page)
            await page.goto(url, wait_until=wait_until, timeout=60000)
            await asyncio.sleep(1)  # Allow trailing requests to complete
            op.after_state = await PageState.capture(page)
        except Exception as e:
            op.after_state = await PageState.capture(page)
        
        op.end_time = time.time()
        op.interactions = interceptor.stop_and_collect()
        self.operations.append(op)
        return op
    
    async def record_click(self, page: Page, selector: str, depth: int = 0, wait_for_network: bool = True) -> PageOperation:
        """Record a click action and all resulting network traffic."""
        op = PageOperation(
            operation_id=self._next_id(),
            page_url=page.url,
            depth=depth,
            action="click",
            target=selector,
        )
        
        interceptor = NetworkInterceptor(page)
        interceptor.start()
        op.start_time = time.time()
        
        try:
            op.before_state = await PageState.capture(page)
            await page.click(selector)
            if wait_for_network:
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
            await asyncio.sleep(0.5)
            op.after_state = await PageState.capture(page)
        except Exception as e:
            op.after_state = await PageState.capture(page)
        
        op.end_time = time.time()
        op.interactions = interceptor.stop_and_collect()
        self.operations.append(op)
        return op
    
    async def record_input(self, page: Page, selector: str, text: str, depth: int = 0) -> PageOperation:
        """Record a text input action and all resulting network traffic."""
        op = PageOperation(
            operation_id=self._next_id(),
            page_url=page.url,
            depth=depth,
            action="input",
            target=selector,
            action_params={"text": text},
        )
        
        interceptor = NetworkInterceptor(page)
        interceptor.start()
        op.start_time = time.time()
        
        try:
            op.before_state = await PageState.capture(page)
            await page.fill(selector, text)
            await asyncio.sleep(0.5)
            op.after_state = await PageState.capture(page)
        except Exception:
            op.after_state = await PageState.capture(page)
        
        op.end_time = time.time()
        op.interactions = interceptor.stop_and_collect()
        self.operations.append(op)
        return op
    
    async def record_wait(self, page: Page, duration: float = 2.0, depth: int = 0) -> PageOperation:
        """Record a wait period to capture background polling/heartbeat requests."""
        op = PageOperation(
            operation_id=self._next_id(),
            page_url=page.url,
            depth=depth,
            action="wait",
            action_params={"duration": duration},
        )
        
        interceptor = NetworkInterceptor(page)
        interceptor.start()
        op.start_time = time.time()
        
        op.before_state = await PageState.capture(page)
        await asyncio.sleep(duration)
        op.after_state = await PageState.capture(page)
        
        op.end_time = time.time()
        op.interactions = interceptor.stop_and_collect()
        self.operations.append(op)
        return op
    
    def get_api_summary(self) -> List[Dict[str, Any]]:
        """Extract a flat list of all API-like calls across all operations."""
        results = []
        for op in self.operations:
            for api in op.api_calls:
                results.append({
                    "operation_id": op.operation_id,
                    "action": op.action,
                    "url": api.request.url,
                    "method": api.request.method,
                    "status": api.response.status if api.response else None,
                    "resource_type": api.request.resource_type,
                    "duration_ms": api.duration_ms,
                })
        return results
    
    def save(self, path: str):
        """Save the full session to a JSON file."""
        data = {
            "total_operations": len(self.operations),
            "total_interactions": sum(len(op.interactions) for op in self.operations),
            "total_api_calls": sum(len(op.api_calls) for op in self.operations),
            "operations": [op.to_dict() for op in self.operations],
            "api_summary": self.get_api_summary(),
        }
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


import asyncio
