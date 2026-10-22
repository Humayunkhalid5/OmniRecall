"""User exclusion rules, applied before anything is persisted (design.md §3).

Rule types:
- ``app``: an application name, matched case-insensitively against the
  application that owned the clipboard or screen.
- ``path``: a folder; files inside it are never imported.
- ``pattern``: literal text, matched case-insensitively. It is not a regular
  expression, so a rule can never hang the engine.
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePath

from omnirecall.errors import ValidationError
from omnirecall.storage.repository import Repository

RULE_TYPES = ("app", "path", "pattern")
MAX_RULES = 500
MAX_RULE_CHARS = 500


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold().strip()


def _app_key(name: str) -> str:
    """Comparable app name: case-folded, without a trailing ``.exe`` or ``.app``."""
    key = _fold(name)
    for suffix in (".exe", ".app"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    return key


@dataclass(frozen=True)
class Rules:
    apps: frozenset[str]
    paths: tuple[PurePath, ...]
    patterns: tuple[str, ...]

    def app_excluded(self, app: str | None) -> bool:
        return app is not None and _app_key(app) in self.apps

    def path_excluded(self, path: Path) -> bool:
        resolved = PurePath(os.path.normcase(str(path)))
        return any(resolved == root or root in resolved.parents for root in self.paths)

    def pattern_excluded(self, text: str) -> bool:
        if not self.patterns:
            return False
        folded = _fold(text)
        return any(p in folded for p in self.patterns)


class ExclusionService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def validate(self, rule_type: str, rule_value: str) -> str:
        if rule_type not in RULE_TYPES:
            raise ValidationError("Unknown exclusion type", "rule_type")
        value = rule_value.strip()
        if not value or len(value) > MAX_RULE_CHARS:
            raise ValidationError("Enter a value up to 500 characters", "rule_value")
        if rule_type == "path":
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise ValidationError("Folder exclusions need a full path", "rule_value")
            value = str(path.resolve())
        if rule_type == "pattern" and len(value) < 3:
            raise ValidationError("Text exclusions need at least 3 characters", "rule_value")
        return value

    def add(self, rule_type: str, rule_value: str) -> str:
        value = self.validate(rule_type, rule_value)
        existing = self.repo.list_exclusions()
        if len(existing) >= MAX_RULES:
            raise ValidationError("Too many exclusions", "rule_value")
        for rule in existing:
            if rule["rule_type"] == rule_type and _fold(rule["rule_value"]) == _fold(value):
                return str(rule["id"])
        return self.repo.create_exclusion(rule_type, value)

    def rules(self) -> Rules:
        apps: set[str] = set()
        paths: list[PurePath] = []
        patterns: list[str] = []
        for rule in self.repo.list_exclusions():
            if not rule["enabled"]:
                continue
            value = str(rule["rule_value"])
            if rule["rule_type"] == "app":
                apps.add(_app_key(value))
            elif rule["rule_type"] == "path":
                paths.append(PurePath(os.path.normcase(value)))
            else:
                patterns.append(_fold(value))
        return Rules(frozenset(apps), tuple(paths), tuple(patterns))
