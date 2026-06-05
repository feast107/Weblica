"""
Weblica CLI - Command line interface for the cloning and replay tool.

Usage:
    python -m weblica clone <url> [options]
    python -m weblica replay [options]
    python -m weblica record <url> [options]
    python -m weblica compare <original_url> [options]
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

from .cloner import WebCloner
from .replayer import WebReplayer
from .auth import AuthManager, AuthConfig
from .orchestrator import AgentOrchestrator, DecisionContext, ClonePhase, ObstacleType


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="weblica",
        description="Weblica - Intelligent Web Application Cloning & Replaying Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s clone https://example.com -o ./my_clone
  %(prog)s clone https://example.com --headless --depth 2
  %(prog)s replay -d ./my_clone -p 9090
  %(prog)s record https://example.com --duration 30
  %(prog)s compare https://example.com -d ./my_clone
        """,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Clone command
    clone_parser = subparsers.add_parser(
        "clone",
        help="Clone a web application",
        description="Clone a web application using stealth browsing and intelligent analysis.",
    )
    clone_parser.add_argument("url", help="Target URL to clone")
    clone_parser.add_argument(
        "-o", "--output",
        default="./cloned",
        help="Output directory (default: ./cloned)",
    )
    clone_parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)",
    )
    clone_parser.add_argument(
        "--no-headless",
        action="store_true",
        dest="no_headless",
        help="Show browser window during cloning",
    )
    clone_parser.add_argument(
        "-d", "--depth",
        type=int,
        default=1,
        help="Maximum crawl depth (default: 1)",
    )
    clone_parser.add_argument(
        "--proxy",
        help="Proxy server URL (e.g., http://proxy:8080)",
    )
    clone_parser.add_argument(
        "--slow-mo",
        type=int,
        help="Slow down operations by specified milliseconds",
    )
    clone_parser.add_argument(
        "--humanize",
        action="store_true",
        default=True,
        help="Enable human-like mouse/keyboard behavior with CloakBrowser (default: True)",
    )
    clone_parser.add_argument(
        "--no-humanize",
        action="store_true",
        dest="no_humanize",
        help="Disable human-like behavior (faster but less stealthy)",
    )
    
    # Authentication options
    auth_group = clone_parser.add_argument_group("Authentication")
    auth_group.add_argument(
        "--cookies",
        help="Path to JSON file containing cookies",
    )
    auth_group.add_argument(
        "--bearer-token",
        help="Bearer token for API authentication",
    )
    auth_group.add_argument(
        "--basic-auth",
        help="Basic auth credentials in format 'username:password'",
    )
    auth_group.add_argument(
        "--wait-login",
        action="store_true",
        help="Pause and wait for manual login before cloning",
    )
    auth_group.add_argument(
        "--login-timeout",
        type=int,
        default=300,
        help="Timeout in seconds for manual login (default: 300)",
    )
    auth_group.add_argument(
        "--login-selector",
        help="CSS selector indicating successful login (e.g., '.user-profile')",
    )
    auth_group.add_argument(
        "--captcha-action",
        choices=["warn", "block", "auto_click"],
        default="warn",
        help="CAPTCHA handling mode (default: warn)",
    )
    auth_group.add_argument(
        "--save-auth",
        action="store_true",
        help="Save auth state (cookies, storage) after login",
    )
    auth_group.add_argument(
        "--auth-state-file",
        default="./weblica-auth-state.json",
        help="File to save/load auth state (default: ./weblica-auth-state.json)",
    )
    auth_group.add_argument(
        "--auth-config",
        help="Path to JSON file with full auth configuration",
    )
    
    # Agent mode
    clone_parser.add_argument(
        "--agent-mode",
        action="store_true",
        help="Enable agent-in-the-loop supervision (DFS, pause at obstacles)",
    )
    
    # Replay command
    replay_parser = subparsers.add_parser(
        "replay",
        help="Start local replay server",
        description="Start a local HTTP server to browse the cloned application.",
    )
    replay_parser.add_argument(
        "-d", "--dir",
        default="./cloned",
        help="Clone directory to serve (default: ./cloned)",
    )
    replay_parser.add_argument(
        "-p", "--port",
        type=int,
        default=8080,
        help="Server port (default: 8080)",
    )
    
    # Record command
    record_parser = subparsers.add_parser(
        "record",
        help="Record user interactions",
        description="Record user interactions on a page for later replay.",
    )
    record_parser.add_argument("url", help="URL to record on")
    record_parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Recording duration in seconds (default: 60)",
    )
    record_parser.add_argument(
        "-o", "--output",
        default="./session.json",
        help="Output file for the session (default: ./session.json)",
    )
    
    # Compare command
    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare original and clone visually",
        description="Take screenshots of original and cloned sites for visual comparison.",
    )
    compare_parser.add_argument("url", help="Original URL to compare")
    compare_parser.add_argument(
        "-d", "--dir",
        default="./cloned",
        help="Clone directory (default: ./cloned)",
    )
    compare_parser.add_argument(
        "-o", "--output",
        default="./comparison",
        help="Output directory for comparison images (default: ./comparison)",
    )
    
    return parser


async def default_agent_callback(ctx: DecisionContext) -> DecisionContext:
    """
    Default agent callback for --agent-mode.
    
    With the new orchestrator design, the browser page STAYS OPEN when an
    obstacle is detected. The user can interact with the real browser window.
    """
    import time
    
    print("\n" + "=" * 60)
    print("AGENT DECISION POINT")
    print("=" * 60)
    print(f"URL:        {ctx.snapshot.url}")
    print(f"Phase:      {ctx.phase.name}")
    print(f"Obstacle:   {ctx.obstacle.name}")
    print(f"Title:      {ctx.snapshot.title}")
    print(f"Status:     {ctx.snapshot.status}")
    print(f"Depth:      {ctx.snapshot.depth}")
    if ctx.snapshot.has_login_form:
        print("[ALERT] Login form detected on page!")
    if ctx.snapshot.has_captcha:
        print("[ALERT] CAPTCHA detected on page!")
    if ctx.snapshot.error_indicators:
        print(f"[ALERT] Error indicators: {ctx.snapshot.error_indicators}")
    if ctx.notes:
        print(f"Notes:      {ctx.notes}")
    if ctx.discovered_assets:
        print(f"Assets:     {ctx.discovered_assets}")
    if ctx.discovered_links:
        print(f"Links:      {len(ctx.discovered_links)}")
    print("-" * 60)
    
    # If there's no obstacle, auto-continue
    if ctx.obstacle == ObstacleType.NONE and ctx.phase == ClonePhase.COMPLETED:
        ctx.recommended_action = "continue"
        print("Auto-decision: continue (no obstacles)")
        print("=" * 60 + "\n")
        return ctx
    
    # Write context to file for external monitoring
    context_file = Path("./weblica-decision-context.json")
    context_file.write_text(json.dumps({
        "url": ctx.snapshot.url,
        "phase": ctx.phase.name,
        "obstacle": ctx.obstacle.name,
        "title": ctx.snapshot.title,
        "has_login_form": ctx.snapshot.has_login_form,
        "has_captcha": ctx.snapshot.has_captcha,
        "error_indicators": ctx.snapshot.error_indicators,
        "notes": ctx.notes,
        "text_preview": ctx.snapshot.text_preview,
        "discovered_links": ctx.discovered_links[:10],
        "discovered_assets": ctx.discovered_assets,
        "retry_count": ctx.retry_count,
        "timestamp": time.time(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # Handle specific obstacles
    if ctx.obstacle == ObstacleType.LOGIN_REQUIRED:
        print("[DECISION] Login page detected.")
        print("[DECISION] The browser window is OPEN. You can:")
        print("  1. Type 'manual' -> I'll wait for you to login in the browser (page stays open)")
        print("  2. Type 'skip'  -> Skip this page and continue with others")
        print("  3. Type 'abort' -> Stop the entire clone job")
        
        decision_file = Path("./weblica-decision.json")
        start = time.time()
        while True:
            if decision_file.exists():
                try:
                    decision = json.loads(decision_file.read_text(encoding="utf-8"))
                    ctx.recommended_action = decision.get("action", "manual")
                    ctx.action_params = decision.get("params", {})
                    ctx.notes = decision.get("notes", ctx.notes)
                    decision_file.unlink()
                    print(f"Decision received: {ctx.recommended_action}")
                    print("=" * 60 + "\n")
                    return ctx
                except Exception as e:
                    print(f"Error reading decision file: {e}")
            
            if time.time() - start > 300:
                print("[DECISION] Timeout (300s). Auto-selecting 'manual' - will wait for browser login.")
                ctx.recommended_action = "manual"
                print("=" * 60 + "\n")
                return ctx
            
            await asyncio.sleep(1)
    
    elif ctx.obstacle == ObstacleType.CAPTCHA:
        print("[DECISION] CAPTCHA detected.")
        print("[DECISION] Options: 'manual' (wait for you to solve), 'skip', 'abort'")
        ctx.recommended_action = "manual"
        print("Auto-selecting: manual")
        print("=" * 60 + "\n")
        return ctx
    
    else:
        print("[DECISION] Unhandled obstacle.")
        print("[DECISION] Options: 'skip', 'retry', 'abort'")
        ctx.recommended_action = "skip"
        print("Auto-selecting: skip")
        print("=" * 60 + "\n")
        return ctx


async def handle_clone(args):
    """Handle clone command."""
    headless = not args.no_headless if args.no_headless else args.headless
    
    # Build auth config
    auth_config = None
    if args.auth_config:
        auth_config = AuthConfig(**json.loads(Path(args.auth_config).read_text(encoding="utf-8")))
    else:
        auth_config = AuthConfig()
        if args.cookies:
            auth_config.cookies_file = args.cookies
        if args.bearer_token:
            auth_config.bearer_token = args.bearer_token
        if args.basic_auth:
            parts = args.basic_auth.split(":", 1)
            if len(parts) == 2:
                auth_config.basic_auth = (parts[0], parts[1])
            else:
                print("[AUTH] Warning: Basic auth format should be 'username:password'")
        if args.wait_login:
            auth_config.wait_for_login = True
            auth_config.login_timeout = args.login_timeout
            if args.login_selector:
                auth_config.login_selector = args.login_selector
        auth_config.captcha_action = args.captcha_action
        if args.save_auth:
            auth_config.save_auth_state = True
            auth_config.auth_state_file = args.auth_state_file
    
    auth_manager = AuthManager(auth_config) if auth_config else None
    
    # Agent mode uses orchestrator
    if args.agent_mode:
        async with AgentOrchestrator(
            start_url=args.url,
            output_dir=args.output,
            max_depth=args.depth,
            headless=headless,
            proxy=args.proxy,
            auth_manager=auth_manager,
            decision_callback=default_agent_callback,
            humanize=not args.no_humanize,
        ) as orch:
            async for ctx in orch.run_dfs():
                # The callback handles everything; this loop just drains the generator
                pass
            print(orch.get_summary())
        return
    
    # Standard mode uses batch cloner
    async with WebCloner(
        output_dir=args.output,
        headless=headless,
        max_depth=args.depth,
        proxy=args.proxy,
        auth_manager=auth_manager,
        humanize=not args.no_humanize,
    ) as cloner:
        if args.slow_mo:
            cloner.browser.slow_mo = args.slow_mo
        await cloner.clone(args.url)


async def handle_replay(args):
    """Handle replay command."""
    replayer = WebReplayer(clone_dir=args.dir, port=args.port)
    
    try:
        url = await replayer.start_server()
        print(f"\n[SERVER] Open your browser to: {url}")
        print("   Press Ctrl+C to stop the server\n")
        
        # Keep running
        while True:
            await asyncio.sleep(3600)
            
    except KeyboardInterrupt:
        print("\n")
    finally:
        await replayer.stop_server()


async def handle_record(args):
    """Handle record command."""
    replayer = WebReplayer()
    session = await replayer.record_interactions(args.url, duration=args.duration)
    replayer.save_session(session, args.output)
    print(f"[SAVE] Session saved to: {args.output}")


async def handle_compare(args):
    """Handle compare command."""
    replayer = WebReplayer(clone_dir=args.dir)
    
    # Start server temporarily
    server_url = await replayer.start_server()
    clone_url = f"{server_url}/index.html"
    
    try:
        results = await replayer.compare_visual(
            original_url=args.url,
            clone_url=clone_url,
            output_dir=args.output,
        )
        
        print(f"\n[DIFF] Comparison results saved to: {args.output}")
        for name, path in results.items():
            if path:
                print(f"   {name}: {path}")
    finally:
        await replayer.stop_server()


async def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    command_handlers = {
        "clone": handle_clone,
        "replay": handle_replay,
        "record": handle_record,
        "compare": handle_compare,
    }
    
    handler = command_handlers.get(args.command)
    if handler:
        await handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
