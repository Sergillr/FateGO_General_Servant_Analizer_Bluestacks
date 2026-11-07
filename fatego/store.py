from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import ServantRecord


class Roster:
    """Roster persistente en JSON. Se puede re-ejecutar el escaneo sin perder datos."""

    def __init__(self, path: Path):
        self.path = path
        self.servants: dict[str, ServantRecord] = {}
        self.updated_at = ""

    def load(self) -> "Roster":
        if not self.path.exists():
            return self
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self

        self.updated_at = data.get("updated_at", "")
        for key, raw in (data.get("servants") or {}).items():
            try:
                self.servants[key] = ServantRecord.from_dict(raw)
            except TypeError:
                continue
        return self

    def upsert(self, record: ServantRecord) -> None:
        record.touch()
        self.servants[record.key] = record

    def get(self, key: str) -> ServantRecord | None:
        return self.servants.get(key)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {
            "version": 1,
            "updated_at": self.updated_at,
            "servants": {k: v.to_dict() for k, v in self.servants.items()},
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return self.path

    def sorted(self) -> list[ServantRecord]:
        return sorted(
            self.servants.values(),
            key=lambda r: (-(r.rarity or 0), r.class_name or "", r.name.lower()),
        )

    def __len__(self) -> int:
        return len(self.servants)
