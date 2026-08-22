import asyncio
import json

from websockets.asyncio.client import connect

from app.config import NAPCAT_WS_LOG_TARGET as WS_LOG_TARGET
from app.config import NAPCAT_WS_TOKEN as WS_TOKEN
from app.config import NAPCAT_WS_URL as WS_URL

headers = None
if WS_TOKEN:
    headers = {"Authorization": f"Bearer {WS_TOKEN}"}


async def main():
    print(f"正在连接：{WS_LOG_TARGET}")

    async with connect(
        WS_URL,
        additional_headers=headers,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=20,
    ) as ws:
        print("已连接 NapCat WebSocket。现在去群里随便发一条消息测试。")
        print("按 Ctrl + C 停止测试。\n")

        async for raw in ws:
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if (
                event.get("post_type") == "message"
                and event.get("message_type") == "group"
            ):
                group_id = event.get("group_id")
                user_id = event.get("user_id")
                message = event.get("raw_message", "")

                print(f"[群 {group_id}] 用户 {user_id}: {message}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已停止。")
