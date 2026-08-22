from __future__ import annotations

import asyncio
import mimetypes
import re
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.config import IMAGE_MAX_BYTES, IMAGE_ROOT

CATEGORY_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9_-]{1,40}$")
UPLOAD_RE = re.compile(r"^/?上传(?:\s+|[:：])?(.+?)\s*$")
RANDOM_RE = re.compile(r"^/?随机\s*(.+?)\s*$")

CQ_REPLY_RE = re.compile(r"\[CQ:reply,id=([^,\]]+)")
CQ_TAG_RE = re.compile(r"\[CQ:[^\]]+\]")

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
}

# 记录每个图库上一次发送的图片，避免连续抽到同一张。
_last_sent_images: dict[str, str] = {}


def normalize_category(name: str) -> str | None:
    """校验图库名，避免路径穿越。"""
    name = name.strip()

    if CATEGORY_RE.fullmatch(name):
        return name

    return None


def extract_segments(event: dict) -> list[dict]:
    """从 NapCat array 格式消息中取消息段。"""
    message = event.get("message")

    if not isinstance(message, list):
        return []

    return [
        segment
        for segment in message
        if isinstance(segment, dict)
    ]


def extract_text(event: dict) -> str:
    """读取 array 消息中的纯文本，兼容 string 模式作为兜底。"""
    segments = extract_segments(event)

    if segments:
        parts = []

        for segment in segments:
            if segment.get("type") != "text":
                continue

            data = segment.get("data", {})
            text = data.get("text", "")

            if isinstance(text, str):
                parts.append(text)

        return "".join(parts).strip()

    raw = event.get("raw_message") or event.get("message") or ""

    if not isinstance(raw, str):
        return ""

    return CQ_TAG_RE.sub("", raw).strip()


def extract_reply_id(event: dict) -> str | None:
    """获取当前消息回复的目标消息 ID。"""
    for segment in extract_segments(event):
        if segment.get("type") != "reply":
            continue

        data = segment.get("data", {})
        reply_id = data.get("id") or data.get("message_id")

        if reply_id is not None:
            return str(reply_id)

    raw = event.get("raw_message") or ""

    if isinstance(raw, str):
        match = CQ_REPLY_RE.search(raw)

        if match:
            return match.group(1)

    return None


def extract_first_image_url(event: dict) -> str | None:
    """取一条消息中的第一张图片 URL。"""
    for segment in extract_segments(event):
        if segment.get("type") != "image":
            continue

        data = segment.get("data", {})

        for key in ("url", "file"):
            value = data.get(key, "")

            if isinstance(value, str) and value.startswith(
                ("http://", "https://")
            ):
                return value

    return None


def parse_upload_category(text: str) -> str | None:
    """
    支持：
    上传 表情包
    上传表情包
    /上传 表情包
    """
    match = UPLOAD_RE.fullmatch(text.strip())

    return match.group(1).strip() if match else None


def parse_random_category(text: str) -> str | None:
    """
    支持：
    随机表情包
    随机 表情包
    /随机 表情包
    """
    match = RANDOM_RE.fullmatch(text.strip())

    return match.group(1).strip() if match else None


def _guess_extension(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()

    if suffix in IMAGE_EXTENSIONS:
        return suffix

    extension = mimetypes.guess_extension(
        content_type.split(";", 1)[0].strip()
    )

    if extension == ".jpe":
        extension = ".jpg"

    if extension in IMAGE_EXTENSIONS:
        return extension

    return ".jpg"


def _download_image(
    url: str,
    folder: Path,
    max_bytes: int,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)

    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )

    temp_path = folder / f"{uuid.uuid4().hex}.part"

    try:
        with urlopen(request, timeout=30) as response:
            content_type = response.headers.get(
                "Content-Type",
                "application/octet-stream",
            )

            content_length = response.headers.get("Content-Length")

            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ValueError(
                            f"图片超过大小限制：最多 "
                            f"{max_bytes // 1024 // 1024}MB"
                        )
                except ValueError:
                    raise
                except Exception:
                    pass

            url_suffix = Path(urlparse(url).path).suffix.lower()

            if (
                not content_type.lower().startswith("image/")
                and url_suffix not in IMAGE_EXTENSIONS
            ):
                raise ValueError("被回复消息中的文件不是可识别图片")

            extension = _guess_extension(url, content_type)
            final_path = folder / f"{uuid.uuid4().hex}{extension}"

            downloaded = 0

            with temp_path.open("wb") as file:
                while True:
                    chunk = response.read(64 * 1024)

                    if not chunk:
                        break

                    downloaded += len(chunk)

                    if downloaded > max_bytes:
                        raise ValueError(
                            f"图片超过大小限制：最多 "
                            f"{max_bytes // 1024 // 1024}MB"
                        )

                    file.write(chunk)

        temp_path.replace(final_path)
        return final_path

    except Exception:
        if temp_path.exists():
            temp_path.unlink()

        raise


async def save_image_from_url(
    image_url: str,
    category: str,
) -> Path:
    normalized = normalize_category(category)

    if normalized is None:
        raise ValueError(
            "图库名只能包含中文、英文、数字、下划线或短横线，"
            "且不超过 40 个字符。"
        )

    target_folder = IMAGE_ROOT / normalized

    return await asyncio.to_thread(
        _download_image,
        image_url,
        target_folder,
        IMAGE_MAX_BYTES,
    )


def choose_random_image(category: str) -> Path | None:
    normalized = normalize_category(category)

    if normalized is None:
        return None

    folder = IMAGE_ROOT / normalized

    if not folder.is_dir():
        return None

    images = sorted(
        [
            path
            for path in folder.iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=lambda path: path.name.lower(),
    )

    if not images:
        return None

    previous_name = _last_sent_images.get(normalized)

    # 目录有多张图时，优先排除上一张，避免“看起来没随机”。
    candidates = [
        path
        for path in images
        if path.name != previous_name
    ]

    if not candidates:
        candidates = images

    selected = secrets.choice(candidates)

    _last_sent_images[normalized] = selected.name

    print(
        f"[图库随机] 分类={normalized} | "
        f"候选={len(images)} | "
        f"选中={selected.name}"
    )

    return selected
