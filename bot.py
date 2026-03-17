"""PowerBot entrypoint.

Keeping this file tiny makes upgrades easier.
All real logic lives in bot_core.py.
"""

from bot_core import run


if __name__ == "__main__":
    run()
