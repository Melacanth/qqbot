from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import (
    SUMMARY_FONT_CANDIDATES,
    SUMMARY_IMAGE_DIR,
    SUMMARY_IMAGE_MAX_HEIGHT,
    SUMMARY_IMAGE_THEME,
    SUMMARY_IMAGE_WIDTH,
)


@dataclass
class RenderUnit:
    kind: str
    text: str
    lines: list[str]
    indent: int = 0
    bullet: bool = False
    spacing_after: int = 8


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            pass

    return {}


def _normalize_items(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    text = str(value).strip()
    if not text:
        return []

    lines = [
        re.sub(r"^\s*[-*•\d.、)）]+\s*", "", line).strip()
        for line in text.splitlines()
    ]

    return [line for line in lines if line]


def _normalize_topics(value: Any) -> list[dict[str, Any]]:
    topics = []

    if not isinstance(value, list):
        return topics

    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            title = str(
                item.get("title")
                or item.get("name")
                or f"话题 {index}"
            ).strip()
            details = _normalize_items(
                item.get("details")
                or item.get("points")
                or item.get("items")
            )
        else:
            title = f"话题 {index}"
            details = _normalize_items(item)

        topics.append({
            "title": title or f"话题 {index}",
            "details": details,
        })

    return topics


def _normalize_todos(value: Any) -> list[dict[str, str]]:
    todos = []

    if not isinstance(value, list):
        for item in _normalize_items(value):
            todos.append({
                "item": item,
                "status": "待确认",
                "note": "",
            })
        return todos

    for raw in value:
        if isinstance(raw, dict):
            item = str(raw.get("item") or raw.get("title") or "").strip()
            status = str(raw.get("status") or "待确认").strip()
            note = str(raw.get("note") or "").strip()
        else:
            item = str(raw).strip()
            status = "待确认"
            note = ""

        if item:
            todos.append({
                "item": item,
                "status": status or "待确认",
                "note": note,
            })

    return todos


def parse_summary_text(text: str) -> dict[str, Any]:
    data = _extract_json_object(text)

    if data:
        open_questions = _normalize_items(
            data.get("open_questions")
            or data.get("pending")
        )

        return {
            "title": str(data.get("title") or "群聊总结").strip() or "群聊总结",
            "overview": str(data.get("overview") or "").strip(),
            "topics": _normalize_topics(data.get("topics")),
            "conclusions": _normalize_items(data.get("conclusions")),
            "todos": _normalize_todos(data.get("todos")),
            "open_questions": open_questions,
            "timeline": _normalize_items(data.get("timeline")),
            "raw": text,
        }

    return {
        "title": "群聊总结",
        "overview": "",
        "topics": [],
        "conclusions": [],
        "todos": [],
        "open_questions": [],
        "timeline": [],
        "raw": text.strip() or "暂无",
    }


def _load_font(size: int):
    from PIL import ImageFont

    for path in SUMMARY_FONT_CANDIDATES:
        if not path.is_file():
            continue

        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue

    return ImageFont.load_default()


def _text_width(draw, text: str, font) -> float:
    try:
        return draw.textlength(text, font=font)
    except Exception:
        left, _, right, _ = draw.textbbox((0, 0), text, font=font)
        return right - left


def _wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    text = str(text).strip()

    if not text:
        return ["暂无"]

    lines: list[str] = []

    for raw_line in text.splitlines():
        raw_line = raw_line.strip()

        if not raw_line:
            lines.append("")
            continue

        current = ""

        for char in raw_line:
            candidate = current + char

            if current and _text_width(draw, candidate, font) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate

        if current:
            lines.append(current)

    return lines or ["暂无"]


def _safe_group_id(group_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(group_id))[:64] or "group"


def _colors() -> dict[str, str]:
    if SUMMARY_IMAGE_THEME == "light":
        return {
            "bg": "#f6f7fb",
            "card": "#ffffff",
            "title": "#111827",
            "text": "#1f2937",
            "muted": "#6b7280",
            "accent": "#2563eb",
            "rule": "#e5e7eb",
            "chip": "#eaf1ff",
        }

    return {
        "bg": "#0d1117",
        "card": "#141b23",
        "title": "#f8fafc",
        "text": "#dbe4ee",
        "muted": "#97a6b5",
        "accent": "#7dd3fc",
        "rule": "#263241",
        "chip": "#1e3141",
    }


def _font_for(unit: RenderUnit, fonts: dict[str, Any]):
    return fonts.get(unit.kind, fonts["body"])


def _line_height(unit: RenderUnit) -> int:
    return {
        "section": 34,
        "topic": 33,
        "body": 31,
        "muted": 28,
    }.get(unit.kind, 31)


def _unit_height(unit: RenderUnit) -> int:
    return len(unit.lines) * _line_height(unit) + unit.spacing_after


def _make_unit(
    draw,
    fonts: dict[str, Any],
    content_width: int,
    kind: str,
    text: str,
    indent: int = 0,
    bullet: bool = False,
    spacing_after: int = 8,
) -> RenderUnit:
    font = fonts.get(kind, fonts["body"])
    bullet_space = 28 if bullet else 0
    max_width = content_width - indent - bullet_space
    return RenderUnit(
        kind=kind,
        text=text,
        lines=_wrap_text(draw, text, font, max_width),
        indent=indent,
        bullet=bullet,
        spacing_after=spacing_after,
    )


def _build_units(
    data: dict[str, Any],
    draw,
    fonts: dict[str, Any],
    content_width: int,
) -> list[RenderUnit]:
    units: list[RenderUnit] = []

    if data["overview"]:
        units.append(_make_unit(
            draw, fonts, content_width,
            "section", "整体概览", spacing_after=8,
        ))
        units.append(_make_unit(
            draw, fonts, content_width,
            "body", data["overview"], spacing_after=18,
        ))

    if data["topics"]:
        units.append(_make_unit(
            draw, fonts, content_width,
            "section", "主要话题与讨论细节", spacing_after=10,
        ))

        for index, topic in enumerate(data["topics"], start=1):
            units.append(_make_unit(
                draw, fonts, content_width,
                "topic", f"{index}. {topic['title']}", spacing_after=8,
            ))

            details = topic["details"] or ["暂无"]
            for detail in details:
                units.append(_make_unit(
                    draw, fonts, content_width,
                    "body", detail, indent=18, bullet=True, spacing_after=8,
                ))

            units[-1].spacing_after = 18

    section_items = [
        ("已形成结论", data["conclusions"]),
        ("关键时间线", data["timeline"]),
        ("仍待确认的问题", data["open_questions"]),
    ]

    for heading, items in section_items:
        if not items:
            continue

        units.append(_make_unit(
            draw, fonts, content_width,
            "section", heading, spacing_after=10,
        ))

        for item in items:
            units.append(_make_unit(
                draw, fonts, content_width,
                "body", item, indent=18, bullet=True, spacing_after=8,
            ))

        units[-1].spacing_after = 18

    if data["todos"]:
        units.append(_make_unit(
            draw, fonts, content_width,
            "section", "待办事项", spacing_after=10,
        ))

        for todo in data["todos"]:
            text = todo["item"]
            if todo["status"]:
                text += f"｜状态：{todo['status']}"
            if todo["note"]:
                text += f"｜说明：{todo['note']}"

            units.append(_make_unit(
                draw, fonts, content_width,
                "body", text, indent=18, bullet=True, spacing_after=8,
            ))

        units[-1].spacing_after = 18

    if not units:
        units.append(_make_unit(
            draw, fonts, content_width,
            "section", "总结内容", spacing_after=10,
        ))
        for item in _normalize_items(data["raw"]) or ["暂无"]:
            units.append(_make_unit(
                draw, fonts, content_width,
                "body", item, indent=18, bullet=True, spacing_after=8,
            ))

    return units


def _split_large_unit(unit: RenderUnit, available_lines: int) -> tuple[RenderUnit, RenderUnit]:
    first_lines = unit.lines[:available_lines]
    rest_lines = unit.lines[available_lines:]

    first = RenderUnit(
        kind=unit.kind,
        text=unit.text,
        lines=first_lines,
        indent=unit.indent,
        bullet=unit.bullet,
        spacing_after=8,
    )
    rest = RenderUnit(
        kind=unit.kind,
        text=unit.text,
        lines=rest_lines,
        indent=unit.indent,
        bullet=False,
        spacing_after=unit.spacing_after,
    )

    return first, rest


def _paginate(units: list[RenderUnit], max_content_height: int) -> list[list[RenderUnit]]:
    pages: list[list[RenderUnit]] = []
    current: list[RenderUnit] = []
    current_height = 0
    index = 0

    while index < len(units):
        unit = units[index]
        height = _unit_height(unit)

        if current and current_height + height > max_content_height:
            pages.append(current)
            current = []
            current_height = 0
            continue

        if height > max_content_height:
            line_height = _line_height(unit)
            available_lines = max(
                1,
                (max_content_height - unit.spacing_after) // line_height,
            )
            first, rest = _split_large_unit(unit, available_lines)
            current.append(first)
            pages.append(current)
            current = []
            current_height = 0
            units[index] = rest
            continue

        current.append(unit)
        current_height += height
        index += 1

    if current:
        pages.append(current)

    return pages or [[]]


def _draw_unit(draw, unit: RenderUnit, x: int, y: int, fonts, colors) -> int:
    font = _font_for(unit, fonts)
    line_height = _line_height(unit)
    fill = colors["text"]

    if unit.kind in {"section", "topic"}:
        fill = colors["accent"]
    elif unit.kind == "muted":
        fill = colors["muted"]

    text_x = x + unit.indent

    if unit.bullet:
        draw.ellipse(
            (text_x + 4, y + 11, text_x + 12, y + 19),
            fill=colors["accent"],
        )
        text_x += 28

    for line in unit.lines:
        draw.text((text_x, y), line, font=font, fill=fill)
        y += line_height

    return y + unit.spacing_after


def render_summary_images(
    summary_text: str,
    group_id: str,
    group_name: str | None = None,
) -> list[Path]:
    from PIL import Image, ImageDraw

    data = parse_summary_text(summary_text)
    width = SUMMARY_IMAGE_WIDTH
    max_height = SUMMARY_IMAGE_MAX_HEIGHT
    colors = _colors()

    margin_x = 42
    margin_y = 34
    padding_x = 36
    padding_y = 28
    footer_height = 34
    header_height = 88
    content_width = width - margin_x * 2 - padding_x * 2
    max_content_height = (
        max_height
        - margin_y * 2
        - padding_y * 2
        - header_height
        - footer_height
    )

    fonts = {
        "title": _load_font(40),
        "meta": _load_font(22),
        "section": _load_font(28),
        "topic": _load_font(27),
        "body": _load_font(25),
        "muted": _load_font(21),
    }

    measure = Image.new("RGB", (width, 200), colors["bg"])
    measure_draw = ImageDraw.Draw(measure)
    units = _build_units(data, measure_draw, fonts, content_width)
    pages = _paginate(units, max_content_height)

    output_dir = SUMMARY_IMAGE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_group_id = _safe_group_id(group_id)
    group_label = group_name or f"群 {group_id}"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    paths: list[Path] = []

    for page_number, page_units in enumerate(pages, start=1):
        content_height = sum(_unit_height(unit) for unit in page_units)
        image_height = min(
            max_height,
            max(
                760,
                margin_y * 2
                + padding_y * 2
                + header_height
                + footer_height
                + content_height,
            ),
        )

        image = Image.new("RGB", (width, image_height), colors["bg"])
        draw = ImageDraw.Draw(image)

        x0 = margin_x
        y0 = margin_y
        x1 = width - margin_x
        y1 = image_height - margin_y
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=22,
            fill=colors["card"],
        )

        x = x0 + padding_x
        y = y0 + padding_y
        title = str(data.get("title") or "群聊总结").strip() or "群聊总结"
        draw.text((x, y), title, font=fonts["title"], fill=colors["title"])

        meta = f"{group_label} · {generated_at}"
        draw.text(
            (x, y + 48),
            meta,
            font=fonts["meta"],
            fill=colors["muted"],
        )

        y += header_height
        draw.line((x, y, x + content_width, y), fill=colors["rule"], width=2)
        y += 20

        for unit in page_units:
            y = _draw_unit(draw, unit, x, y, fonts, colors)

        footer = f"{page_number} / {len(pages)}"
        footer_width = _text_width(draw, footer, fonts["muted"])
        draw.text(
            (
                width - margin_x - padding_x - footer_width,
                image_height - margin_y - padding_y - 4,
            ),
            footer,
            font=fonts["muted"],
            fill=colors["muted"],
        )

        filename = (
            f"summary_{safe_group_id}_{timestamp}_"
            f"p{page_number}_{time.time_ns() % 1_000_000}.png"
        )
        output_path = output_dir / filename
        image.save(output_path, "PNG")
        paths.append(output_path)

    return paths


def render_summary_image(
    summary_text: str,
    group_id: str,
    group_name: str | None = None,
) -> Path:
    return render_summary_images(
        summary_text=summary_text,
        group_id=group_id,
        group_name=group_name,
    )[0]
