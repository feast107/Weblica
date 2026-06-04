"""
Utility functions for Weblica.
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be used as a filename."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name.strip('. ')


def get_domain(url: str) -> str:
    """Extract domain from URL."""
    return urlparse(url).netloc


def is_same_domain(url1: str, url2: str) -> bool:
    """Check if two URLs belong to the same domain."""
    return get_domain(url1) == get_domain(url2)


def load_json(path: str) -> Dict[str, Any]:
    """Load JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(data: Dict[str, Any], path: str):
    """Save data to JSON file."""
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def retry_async(
    func,
    max_retries: int = 3,
    delay: float = 1.0,
    exceptions=(Exception,),
):
    """Retry an async function with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return await func()
        except exceptions as e:
            if attempt == max_retries - 1:
                raise
            wait = delay * (2 ** attempt)
            print(f"  Retry {attempt + 1}/{max_retries} after {wait}s... ({e})")
            await asyncio.sleep(wait)
