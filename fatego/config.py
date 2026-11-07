from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
DATA_DIR = ROOT / "data"
ASSETS_DIR = ROOT / "assets"
OUTPUT_DIR = ROOT / "output"


@dataclass
class AdbConfig:
    host: str = "127.0.0.1"
    port: int = 5555
    adb_path: str = ""

    @property
    def serial(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class DeviceConfig:
    width: int = 1920
    height: int = 1080
    dpi: int = 240
    language: str = "en"


@dataclass
class ScanConfig:
    action_delay: float = 0.6
    jitter: float = 0.25
    scroll_pause: float = 1.0
    max_scrolls: int = 60
    settle_timeout: float = 6.0
    settle_interval: float = 0.25


@dataclass
class ListConfig:
    cols: int = 3
    rows: int = 3
    x0: int = 330
    y0: int = 300
    dx: int = 420
    dy: int = 250


@dataclass
class AtlasConfig:
    region: str = "NA"
    base_url: str = "https://api.atlasacademy.io"


@dataclass
class ReportConfig:
    title: str = "Fate/Grand Order - Servant Report"
    author: str = "FGO Servant Analyzer"


def _section(data: dict[str, Any], key: str, dc_type):
    raw = data.get(key, {}) or {}
    valid = {f.name for f in fields(dc_type)}
    return dc_type(**{k: v for k, v in raw.items() if k in valid})


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@dataclass
class Config:
    adb: AdbConfig
    device: DeviceConfig
    scan: ScanConfig
    list: ListConfig
    atlas: AtlasConfig
    report: ReportConfig
    rois: dict[str, tuple[int, int, int, int]]
    path: Path = CONFIG_PATH

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        raw: dict[str, Any] = {}
        if path.exists():
            raw = tomllib.loads(path.read_text(encoding="utf-8"))

        rois: dict[str, tuple[int, int, int, int]] = {}
        for name, box in (raw.get("rois") or {}).items():
            if isinstance(box, (list, tuple)) and len(box) == 4:
                rois[name] = tuple(int(v) for v in box)  # type: ignore[assignment]

        # data/rois.json (lo escribe tools/calibrate.py) tiene prioridad
        for name, box in _read_json(DATA_DIR / "rois.json").items():
            if isinstance(box, (list, tuple)) and len(box) == 4:
                rois[name] = tuple(int(v) for v in box)  # type: ignore[assignment]

        list_cfg = _section(raw, "list", ListConfig)
        for key, value in _read_json(DATA_DIR / "grid.json").items():
            if hasattr(list_cfg, key):
                setattr(list_cfg, key, int(value))

        return cls(
            adb=_section(raw, "adb", AdbConfig),
            device=_section(raw, "device", DeviceConfig),
            scan=_section(raw, "scan", ScanConfig),
            list=list_cfg,
            atlas=_section(raw, "atlas", AtlasConfig),
            report=_section(raw, "report", ReportConfig),
            rois=rois,
            path=path,
        )

    def roi(self, name: str) -> tuple[int, int, int, int] | None:
        return self.rois.get(name)
