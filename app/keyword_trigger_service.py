from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import KEYWORD_CONFIG_PATH, KEYWORD_LOCAL_CONFIG_PATH

DEFAULT_CONFIG = {
    "rules": [
        {
            "id": "silver_wing",
            "enabled": True,
            "keywords": ["银翼"],
            "match_mode": "contains",
            "reply": "全体成员今天三角洲禁止玩银翼，遇到银翼放鸟禁止打鸟。",
            "group_ids": [],
            "cooldown_seconds": 300,
            "priority": 100,
        }
    ]
}


@dataclass
class KeywordRule:
    id: str
    enabled: bool
    keywords: list[str]
    match_mode: str
    reply: str
    group_ids: set[str]
    cooldown_seconds: int
    priority: int
    order: int


class KeywordTriggerService:
    def __init__(
        self,
        base_path: Path = KEYWORD_CONFIG_PATH,
        local_path: Path = KEYWORD_LOCAL_CONFIG_PATH,
    ) -> None:
        self.base_path = base_path
        self.local_path = local_path
        self._rules: list[KeywordRule] = []
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._loaded_mtimes: tuple[float | None, float | None] | None = None
        self._disabled = False

    def get_reply(self, group_id: str, message: str) -> str | None:
        self._reload_if_needed()

        if self._disabled:
            return None

        text = str(message or "")
        if not text.strip():
            return None

        now = time.monotonic()
        for rule in self._matched_rules(group_id, text):
            cooldown_key = (str(group_id), rule.id)
            last_time = self._cooldowns.get(cooldown_key, 0.0)

            if now - last_time < rule.cooldown_seconds:
                continue

            self._cooldowns[cooldown_key] = now
            return rule.reply

        return None

    def _reload_if_needed(self) -> None:
        self._ensure_default_config()
        mtimes = (
            self._get_mtime(self.base_path),
            self._get_mtime(self.local_path),
        )

        if self._loaded_mtimes == mtimes:
            return

        self._loaded_mtimes = mtimes
        self._load_rules()

    def _ensure_default_config(self) -> None:
        if self.base_path.exists():
            return

        try:
            self.base_path.write_text(
                json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[关键词触发] 创建默认配置失败：{exc}")

    def _load_rules(self) -> None:
        try:
            base_rules = self._read_config_rules(self.base_path)
            local_rules = (
                self._read_config_rules(self.local_path)
                if self.local_path.exists()
                else []
            )
        except Exception as exc:
            self._rules = []
            self._disabled = True
            print(f"[关键词触发] 配置加载失败，已禁用：{exc}")
            return

        merged_rules = self._merge_rules(base_rules, local_rules)
        rules: list[KeywordRule] = []

        for index, raw_rule in enumerate(merged_rules):
            rule = self._parse_rule(raw_rule, index)
            if rule is not None:
                rules.append(rule)

        self._rules = rules
        self._disabled = False
        print(f"[关键词触发] 已加载 {len(rules)} 条规则")

    def _read_config_rules(self, path: Path) -> list[dict[str, Any]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} root must be an object")

        rules = data.get("rules", [])
        if not isinstance(rules, list):
            raise ValueError(f"{path.name} rules must be a list")

        return [
            item
            for item in rules
            if isinstance(item, dict)
        ]

    def _merge_rules(
        self,
        base_rules: list[dict[str, Any]],
        local_rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = list(base_rules)
        id_to_index = {
            str(rule.get("id")): index
            for index, rule in enumerate(merged)
            if rule.get("id")
        }

        for rule in local_rules:
            rule_id = str(rule.get("id") or "").strip()
            if rule_id and rule_id in id_to_index:
                merged[id_to_index[rule_id]] = rule
            else:
                if rule_id:
                    id_to_index[rule_id] = len(merged)
                merged.append(rule)

        return merged

    def _parse_rule(
        self,
        raw: dict[str, Any],
        order: int,
    ) -> KeywordRule | None:
        rule_id = str(raw.get("id") or "").strip()
        reply = str(raw.get("reply") or "").strip()
        match_mode = str(raw.get("match_mode") or "contains").strip().lower()

        raw_keywords = raw.get("keywords", [])
        if not isinstance(raw_keywords, list):
            raw_keywords = []

        keywords = [
            str(keyword).strip()
            for keyword in raw_keywords
            if str(keyword).strip()
        ]

        if not rule_id or not reply or not keywords:
            return None

        if match_mode != "contains":
            return None

        raw_group_ids = raw.get("group_ids", [])
        if not isinstance(raw_group_ids, list):
            raw_group_ids = []

        group_ids = {
            str(group_id).strip()
            for group_id in raw_group_ids
            if str(group_id).strip()
        }

        try:
            cooldown_seconds = max(0, int(raw.get("cooldown_seconds", 0)))
        except (TypeError, ValueError):
            cooldown_seconds = 0

        try:
            priority = int(raw.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0

        return KeywordRule(
            id=rule_id,
            enabled=bool(raw.get("enabled", True)),
            keywords=keywords,
            match_mode=match_mode,
            reply=reply,
            group_ids=group_ids,
            cooldown_seconds=cooldown_seconds,
            priority=priority,
            order=order,
        )

    def _matched_rules(
        self,
        group_id: str,
        text: str,
    ) -> list[KeywordRule]:
        normalized_text = text.lower()
        matched: list[KeywordRule] = []

        for rule in self._rules:
            if not rule.enabled:
                continue

            if rule.group_ids and str(group_id) not in rule.group_ids:
                continue

            if rule.match_mode != "contains":
                continue

            for keyword in rule.keywords:
                if keyword.lower() in normalized_text:
                    matched.append(rule)
                    break

        return sorted(
            matched,
            key=lambda item: (-item.priority, item.order),
        )

    @staticmethod
    def _get_mtime(path: Path) -> float | None:
        try:
            return path.stat().st_mtime
        except FileNotFoundError:
            return None


keyword_trigger_service = KeywordTriggerService()


def init_keyword_triggers() -> None:
    keyword_trigger_service._reload_if_needed()


def get_keyword_trigger_reply(group_id: str, message: str) -> str | None:
    return keyword_trigger_service.get_reply(group_id, message)
