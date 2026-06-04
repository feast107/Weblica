"""Allow running weblica as a module: python -m weblica"""

import asyncio
from .cli import main

asyncio.run(main())
