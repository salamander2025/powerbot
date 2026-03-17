"""PowerBot command-hub modules.

This package contains the command hub architecture:
- one natural-language entry point
- keyword/rule-based intent routing
- focused domain engines for tasks, events, memory, meeting summaries, and advisor mode

The initial implementation is intentionally conservative and fully local.
It does not require AI to work.
"""

from .service import PowerBotHubService

__all__ = ["PowerBotHubService"]
