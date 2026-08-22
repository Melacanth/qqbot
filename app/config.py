from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", encoding="utf-8")


def parse_id_set(raw: str) -> set[str]:
    """支持英文逗号、中文逗号、英文分号、中文分号。"""
    normalized = (raw or "").replace("，", ",").replace("；", ",")
    normalized = normalized.replace(";", ",")
    return {
        item.strip()
        for item in normalized.split(",")
        if item.strip()
    }


def read_int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def read_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def read_bool_env(name: str, default: bool = False) -> bool:
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def resolve_path(raw_path: str, base_dir: Path) -> Path:
    path = Path(os.path.expandvars(raw_path.strip())).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


# 核心目录。相对路径分别基于 PROJECT_ROOT 或 DATA_DIR 解析。
DATA_DIR = resolve_path(os.getenv("DATA_DIR", "."), PROJECT_ROOT)
LOG_DIR = resolve_path(os.getenv("LOG_DIR", "logs"), PROJECT_ROOT)
IMAGE_ROOT = resolve_path(os.getenv("IMAGE_ROOT", "image_library"), DATA_DIR)
DATABASE_PATH = resolve_path(
    os.getenv("DATABASE_PATH", "bot_state.db"),
    DATA_DIR,
)
SUMMARY_IMAGE_DIR = resolve_path(
    os.getenv("SUMMARY_IMAGE_DIR", "generated_summaries"),
    DATA_DIR,
)

_summary_font_path = os.getenv("SUMMARY_FONT_PATH", "").strip()
SUMMARY_FONT_PATH = (
    resolve_path(_summary_font_path, PROJECT_ROOT)
    if _summary_font_path
    else None
)

_summary_font_candidates: list[Path] = []
if SUMMARY_FONT_PATH:
    _summary_font_candidates.append(SUMMARY_FONT_PATH)
_windows_dir = os.getenv("WINDIR", "").strip()
if os.name == "nt" and _windows_dir:
    _windows_font_dir = Path(_windows_dir) / "Fonts"
    _summary_font_candidates.extend([
        _windows_font_dir / "msyh.ttc",
        _windows_font_dir / "simhei.ttf",
        _windows_font_dir / "simsun.ttc",
    ])
elif os.name != "nt":
    _summary_font_candidates.extend([
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ])
SUMMARY_FONT_CANDIDATES = tuple(_summary_font_candidates)

KEYWORD_CONFIG_PATH = resolve_path(
    os.getenv("KEYWORD_CONFIG_PATH", "keyword_triggers.json"),
    PROJECT_ROOT,
)
KEYWORD_LOCAL_CONFIG_PATH = resolve_path(
    os.getenv("KEYWORD_LOCAL_CONFIG_PATH", "keyword_triggers.local.json"),
    DATA_DIR,
)

_ocr_temp_dir = os.getenv("OCR_TEMP_DIR", "").strip()
OCR_TEMP_DIR = (
    resolve_path(_ocr_temp_dir, DATA_DIR)
    if _ocr_temp_dir
    else Path(tempfile.gettempdir()).resolve() / "qq_bot_image_ocr"
)
OCR_DEBUG_DIR = OCR_TEMP_DIR / "debug"


# DeepSeek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv(
    "DEEPSEEK_BASE_URL",
    "https://api.deepseek.com",
).strip()
DEEPSEEK_MODEL = os.getenv(
    "DEEPSEEK_MODEL",
    "deepseek-v4-flash",
).strip()
DEEPSEEK_TIMEOUT_SECONDS = read_float_env(
    "DEEPSEEK_TIMEOUT_SECONDS",
    60.0,
    1.0,
)
DEEPSEEK_MAX_RETRIES = read_int_env("DEEPSEEK_MAX_RETRIES", 2, 0)


# NapCat WebSocket
DEFAULT_NAPCAT_WS_URL = "ws://127.0.0.1:3001"
NAPCAT_WS_URL = (
    os.getenv("NAPCAT_WS_URL", "").strip()
    or DEFAULT_NAPCAT_WS_URL
)
NAPCAT_WS_TOKEN = os.getenv("NAPCAT_WS_TOKEN", "").strip()


def format_websocket_target(url: str) -> str:
    """返回适合日志输出的连接目标，不包含凭据、路径或查询参数。"""
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "<无效 WebSocket 地址>"

    if scheme not in {"ws", "wss"} or not hostname:
        return "<无效 WebSocket 地址>"

    display_host = f"[{hostname}]" if ":" in hostname else hostname
    authority = f"{display_host}:{port}" if port is not None else display_host
    return f"{scheme}://{authority}"


NAPCAT_WS_LOG_TARGET = format_websocket_target(NAPCAT_WS_URL)


# 可选 VLM。现有 OCR 业务链路不会自动启用它。
VLM_ENABLED = read_bool_env("VLM_ENABLED", False)
VLM_API_KEY = os.getenv("VLM_API_KEY", "").strip() or DEEPSEEK_API_KEY
VLM_BASE_URL = os.getenv("VLM_BASE_URL", "").strip() or DEEPSEEK_BASE_URL
VLM_MODEL = os.getenv("VLM_MODEL", "").strip()
VLM_MAX_TOKENS = read_int_env("VLM_MAX_TOKENS", 1600, 1)


# Tavily
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
WEB_SEARCH_ENABLED = read_bool_env("WEB_SEARCH_ENABLED", True)
WEB_SEARCH_MAX_RESULTS = read_int_env("WEB_SEARCH_MAX_RESULTS", 5, 1)
WEB_SEARCH_CACHE_MINUTES = read_int_env(
    "WEB_SEARCH_CACHE_MINUTES",
    20,
    0,
)
WEB_SEARCH_MAX_CONTENT_CHARS = read_int_env(
    "WEB_SEARCH_MAX_CONTENT_CHARS",
    1800,
    200,
)
TAVILY_TIMEOUT_SECONDS = read_float_env("TAVILY_TIMEOUT_SECONDS", 15.0, 1.0)


# OCR
def discover_tesseract_cmd() -> Path:
    configured = (
        os.getenv("IMAGE_OCR_TESSERACT_CMD", "").strip()
        or os.getenv("TESSERACT_CMD", "").strip()
    )
    if configured:
        return resolve_path(configured, PROJECT_ROOT)

    executable_name = "tesseract.exe" if os.name == "nt" else "tesseract"
    discovered = shutil.which(executable_name)
    if discovered:
        return Path(discovered).resolve()

    if os.name == "nt":
        program_files = Path(os.getenv("ProgramFiles", "C:/Program Files"))
        return program_files / "Tesseract-OCR" / "tesseract.exe"

    # Debian、Ubuntu 和 Raspberry Pi OS 的 apt 包安装在此处。
    return Path("/usr/bin/tesseract")


IMAGE_OCR_TESSERACT_CMD = discover_tesseract_cmd()

IMAGE_OCR_LANGS = (
    os.getenv("IMAGE_OCR_LANGS", "chi_sim+eng").strip()
    or "chi_sim+eng"
)
IMAGE_OCR_MAX_BYTES = read_int_env(
    "IMAGE_OCR_MAX_BYTES",
    10 * 1024 * 1024,
    1,
)
IMAGE_OCR_USE_OPENCV = read_bool_env("IMAGE_OCR_USE_OPENCV", True)
IMAGE_OCR_MAX_SIDE = read_int_env("IMAGE_OCR_MAX_SIDE", 1800, 800)
IMAGE_OCR_DEBUG_SAVE = read_bool_env("IMAGE_OCR_DEBUG_SAVE", False)

_ocr_psms: list[int] = []
for _item in os.getenv("IMAGE_OCR_PSMS", "6,11").split(","):
    try:
        _psm = int(_item.strip())
    except ValueError:
        continue
    if _psm in {6, 11} and _psm not in _ocr_psms:
        _ocr_psms.append(_psm)
IMAGE_OCR_PSMS = _ocr_psms or [6, 11]


# 图库与摘要图片
IMAGE_MAX_BYTES = read_int_env("IMAGE_MAX_BYTES", 10 * 1024 * 1024, 1)
SUMMARY_IMAGE_WIDTH = read_int_env("SUMMARY_IMAGE_WIDTH", 1080, 640)
SUMMARY_IMAGE_MAX_HEIGHT = read_int_env(
    "SUMMARY_IMAGE_MAX_HEIGHT",
    2000,
    1200,
)
SUMMARY_IMAGE_THEME = os.getenv("SUMMARY_IMAGE_THEME", "dark").strip().lower()
SUMMARY_MAX_TOKENS = read_int_env("SUMMARY_MAX_TOKENS", 1600, 400)
SUMMARY_DETAIL_LEVEL = os.getenv(
    "SUMMARY_DETAIL_LEVEL",
    "detailed",
).strip().lower()


# 机器人运行参数
TRIGGER_PREFIX = os.getenv("TRIGGER_PREFIX", "/ai").strip()
COOLDOWN_SECONDS = read_int_env("COOLDOWN_SECONDS", 5, 0)
STYLE_SAMPLE_LIMIT = read_int_env("STYLE_SAMPLE_LIMIT", 100, 1)
STYLE_REFRESH_MIN_MESSAGES = read_int_env(
    "STYLE_REFRESH_MIN_MESSAGES",
    40,
    1,
)
STYLE_REFRESH_MINUTES = read_int_env("STYLE_REFRESH_MINUTES", 30, 0)
STYLE_REFRESH_SECONDS = STYLE_REFRESH_MINUTES * 60

ALLOWED_GROUP_IDS = parse_id_set(os.getenv("ALLOWED_GROUP_IDS", ""))
ADMIN_USER_IDS = parse_id_set(os.getenv("ADMIN_USER_IDS", ""))
IMAGE_BLACKLIST_USER_IDS = parse_id_set(
    os.getenv("IMAGE_BLACKLIST_USER_IDS", "")
)
THINKING_WHITELIST_USER_IDS = parse_id_set(
    os.getenv("THINKING_WHITELIST_USER_IDS", "")
)

THINKING_MAX_TOKENS = read_int_env("THINKING_MAX_TOKENS", 2400, 1)
THINKING_DAILY_FREE_LIMIT = read_int_env(
    "THINKING_DAILY_FREE_LIMIT",
    5,
    0,
)
THINKING_REASONING_EFFORT = os.getenv(
    "THINKING_REASONING_EFFORT",
    "high",
).strip().lower()
if THINKING_REASONING_EFFORT not in {"high", "max"}:
    THINKING_REASONING_EFFORT = "high"

PRO_MODEL = os.getenv("PRO_MODEL", "deepseek-v4-pro").strip()
PRO_DAILY_LIMIT = read_int_env("PRO_DAILY_LIMIT", 10, 0)
PRO_MAX_TOKENS = read_int_env("PRO_MAX_TOKENS", 2600, 1)
PRO_REASONING_EFFORT = os.getenv(
    "PRO_REASONING_EFFORT",
    "high",
).strip().lower()
if PRO_REASONING_EFFORT not in {"high", "max"}:
    PRO_REASONING_EFFORT = "high"

GROUP_MEMORY_LIMIT = read_int_env("GROUP_MEMORY_LIMIT", 500, 50)
GROUP_MEMORY_RETENTION_DAYS = read_int_env(
    "GROUP_MEMORY_RETENTION_DAYS",
    7,
    0,
)
GROUP_MEMORY_CONTEXT_LIMIT = min(
    GROUP_MEMORY_LIMIT,
    read_int_env("GROUP_MEMORY_CONTEXT_LIMIT", 80, 10),
)
GROUP_MEMORY_CONTEXT_MAX_CHARS = read_int_env(
    "GROUP_MEMORY_CONTEXT_MAX_CHARS",
    12000,
    2000,
)
GROUP_MEMORY_MESSAGE_MAX_CHARS = read_int_env(
    "GROUP_MEMORY_MESSAGE_MAX_CHARS",
    500,
    50,
)


# 兼容旧导入名称；内部代码统一使用新名称。
MODEL = DEEPSEEK_MODEL
WS_URL = NAPCAT_WS_URL
WS_TOKEN = NAPCAT_WS_TOKEN
