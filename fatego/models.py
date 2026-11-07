from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "unknown"


def make_key(name: str, atlas_id: int | None) -> str:
    if atlas_id:
        return f"svt:{atlas_id}"
    return f"name:{slugify(name)}"


@dataclass
class ServantRecord:
    key: str
    name: str
    atlas_id: int | None = None
    class_name: str | None = None
    rarity: int | None = None
    level: int | None = None
    max_level: int | None = None
    np_level: int | None = None
    skills: list[int] = field(default_factory=list)
    append_skills: list[int] = field(default_factory=list)
    bond: int | None = None
    fou_atk: int | None = None
    fou_hp: int | None = None
    ce: str | None = None
    portrait: str | None = None
    screenshots: list[str] = field(default_factory=list)
    atlas: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServantRecord":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def display_name(self) -> str:
        return self.name or self.key

    @property
    def maxed_level(self) -> bool:
        return bool(self.level and self.max_level and self.level >= self.max_level)

    @property
    def skills_maxed(self) -> bool:
        return len(self.skills) == 3 and all(s >= 10 for s in self.skills)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
