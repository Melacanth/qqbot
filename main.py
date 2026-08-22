from __future__ import annotations

import asyncio

from app.database import init_db
from app.napcat_client import run_bot


def main() -> None:
    init_db()

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n机器人已停止。")


if __name__ == "__main__":
    main()
