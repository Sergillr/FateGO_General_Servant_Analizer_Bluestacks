from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .vision import Match, load_image, match

DEFAULT_THRESHOLD = 0.82


class ScreenDetector:
    """Detecta en que pantalla esta el juego comparando 'anclas' (recortes unicos).

    Cada ancla es un PNG en assets/anchors/<nombre>.png. El nombre del archivo
    es el nombre de la pantalla: servant_list.png -> "servant_list".
    """

    def __init__(self, anchors_dir: Path, overrides: dict[str, dict] | None = None):
        self.anchors_dir = anchors_dir
        self.overrides = overrides or {}
        self.anchors: dict[str, np.ndarray] = {}
        self.reload()

    def reload(self) -> None:
        self.anchors = {}
        if not self.anchors_dir.exists():
            return
        for path in sorted(self.anchors_dir.glob("*.png")):
            img = load_image(path)
            if img is not None and img.size:
                self.anchors[path.stem] = img

    @property
    def names(self) -> list[str]:
        return sorted(self.anchors)

    def _threshold(self, name: str) -> float:
        return float(self.overrides.get(name, {}).get("threshold", DEFAULT_THRESHOLD))

    def detect(self, frame: np.ndarray) -> Match | None:
        best: Match | None = None
        for name, tpl in self.anchors.items():
            found = match(frame, tpl, name=name, threshold=self._threshold(name))
            if found and (best is None or found.score > best.score):
                best = found
        return best

    def detect_all(self, frame: np.ndarray) -> list[Match]:
        found: list[Match] = []
        for name, tpl in self.anchors.items():
            hit = match(frame, tpl, name=name, threshold=self._threshold(name))
            if hit:
                found.append(hit)
        return sorted(found, key=lambda m: m.score, reverse=True)

    @classmethod
    def from_disk(cls, anchors_dir: Path) -> "ScreenDetector":
        overrides: dict[str, dict] = {}
        cfg_path = anchors_dir / "anchors.json"
        if cfg_path.exists():
            try:
                overrides = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                overrides = {}
        return cls(anchors_dir, overrides)
