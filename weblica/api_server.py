"""
FastAPI HTTP server for stateful browser session management.

Usage:
    python -m weblica.api_server

Agent workflow:
    1. POST /sessions                    → create session, get session_id
    2. POST /sessions/{id}/navigate      → navigate to URL
    3. POST /sessions/{id}/click         → click element
    4. GET  /sessions/{id}/state         → query current state any time
    5. GET  /sessions/{id}/screenshot    → get PNG screenshot
    6. POST /sessions/{id}/save          → persist to disk
    7. DELETE /sessions/{id}             → destroy when done
"""

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from .session_manager import SessionManager
from .auth import AuthManager, AuthConfig

app = FastAPI(
    title="Weblica Session API",
    description="Stateful browser session management for AI agents.",
    version="0.2.0",
)

manager = SessionManager()


@app.post("/sessions")
async def create_session(
    headless: bool = True,
    cookies_file: Optional[str] = None,
    capture_body_types: Optional[str] = None,
):
    """Create a new browser session. Returns session_id.
    
    capture_body_types: comma-separated list of resource types to capture full body for.
                        Default: "xhr,fetch,document" (API calls + page HTML).
                        Set to "all" to capture everything (not recommended — produces huge logs).
    """
    auth = None
    if cookies_file:
        auth = AuthManager(AuthConfig(cookies_file=cookies_file))
    
    capture_body_for = None
    if capture_body_types:
        if capture_body_types.strip().lower() == "all":
            capture_body_for = None  # None = default behavior in NetworkInterceptor, but we'll override
        else:
            capture_body_for = set(t.strip() for t in capture_body_types.split(","))
    
    session_id = await manager.create_session(
        headless=headless,
        auth_manager=auth,
        capture_body_for=capture_body_for,
    )
    return {"session_id": session_id, "status": "created"}


@app.get("/sessions")
async def list_sessions():
    """List all active sessions with their current state."""
    return {"sessions": manager.list_sessions()}


@app.get("/sessions/{session_id}/state")
async def get_state(session_id: str):
    """Get full state snapshot of a session."""
    try:
        session = await manager.get_session(session_id)
        return await session.get_state()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sessions/{session_id}/navigate")
async def navigate(session_id: str, url: str):
    """Navigate to a URL. Returns updated state snapshot."""
    try:
        session = await manager.get_session(session_id)
        return await session.navigate(url)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sessions/{session_id}/click")
async def click(session_id: str, selector: str, pre_wait: int = 0):
    """Click an element by CSS selector. Returns updated state snapshot."""
    try:
        session = await manager.get_session(session_id)
        return await session.click(selector, pre_wait=pre_wait)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sessions/{session_id}/input")
async def input_text(session_id: str, selector: str, value: str):
    """Fill an input field. Returns updated state snapshot."""
    try:
        session = await manager.get_session(session_id)
        return await session.input(selector, value)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sessions/{session_id}/scroll")
async def scroll(session_id: str, direction: str = "bottom"):
    """Scroll the page. Returns updated state snapshot."""
    try:
        session = await manager.get_session(session_id)
        return await session.scroll(direction)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sessions/{session_id}/wait")
async def wait(session_id: str, ms: int = 2000):
    """Wait for N milliseconds. Returns updated state snapshot."""
    try:
        session = await manager.get_session(session_id)
        return await session.wait(ms)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/sessions/{session_id}/screenshot")
async def get_screenshot(session_id: str):
    """Get current page screenshot as PNG."""
    try:
        session = await manager.get_session(session_id)
        screenshot = await session.screenshot()
        return StreamingResponse(iter([screenshot]), media_type="image/png")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/sessions/{session_id}/dom")
async def get_dom(session_id: str):
    """Get current page HTML."""
    try:
        session = await manager.get_session(session_id)
        return {"html": await session.get_dom()}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/sessions/{session_id}/interactive-elements")
async def get_interactive_elements(session_id: str):
    """Get all interactive elements (buttons, links, inputs) with bounding boxes."""
    try:
        session = await manager.get_session(session_id)
        return {"elements": await session.get_interactive_elements()}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/sessions/{session_id}/network-log")
async def get_network_log(session_id: str, clear: bool = False):
    """Get captured network traffic. Set clear=true to empty buffer after reading."""
    try:
        session = await manager.get_session(session_id)
        log = await session.get_network_log()
        if clear:
            session.clear_network_log()
        return {"interactions": log}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/sessions/{session_id}/save")
async def save_session(session_id: str):
    """Persist session state (cookies, storage, screenshot, state.json) to disk."""
    try:
        session = await manager.get_session(session_id)
        path = await session.save()
        return {"saved_to": str(path), "status": "saved"}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/sessions/{session_id}")
async def destroy_session(session_id: str):
    """Close browser and destroy session."""
    try:
        await manager.destroy_session(session_id)
        return {"status": "destroyed"}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up all browser sessions on server shutdown."""
    await manager.close_all()


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)


if __name__ == "__main__":
    main()
