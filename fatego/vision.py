from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Match:
    name: str
    score: float
    rect: tuple[int, int, int, int]  # x, y, ancho, alto

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.rect
        return x + w // 2, y + h // 2


def load_image(path: str | Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def save_png(img: np.ndarray, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError(f"No se pudo codificar la imagen: {path}")
    path.write_bytes(buf.tobytes())
    return path


def to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def crop(img: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = roi
    height, width = img.shape[:2]
    x = max(0, min(int(x), width - 1))
    y = max(0, min(int(y), height - 1))
    w = max(1, min(int(w), width - x))
    h = max(1, min(int(h), height - y))
    return img[y : y + h, x : x + w]


def match(
    frame: np.ndarray,
    template: np.ndarray,
    name: str = "template",
    threshold: float = 0.82,
    scales: tuple[float, ...] = (1.0,),
) -> Match | None:
    """Template matching con escala opcional. Devuelve la mejor coincidencia."""
    gray_frame = to_gray(frame)
    gray_tpl = to_gray(template)
    fh, fw = gray_frame.shape[:2]
    best: Match | None = None

    for scale in scales:
        if scale == 1.0:
            tpl = gray_tpl
        else:
            tpl = cv2.resize(
                gray_tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
        th, tw = tpl.shape[:2]
        if th > fh or tw > fw or th < 4 or tw < 4:
            continue
        result = cv2.matchTemplate(gray_frame, tpl, cv2.TM_CCOEFF_NORMED)
        result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, score, _, loc = cv2.minMaxLoc(result)
        if best is None or score > best.score:
            best = Match(name, float(score), (int(loc[0]), int(loc[1]), int(tw), int(th)))

    if best is None or best.score < threshold:
        return None
    return best


def match_all(
    frame: np.ndarray,
    template: np.ndarray,
    name: str = "template",
    threshold: float = 0.8,
    min_distance: int = 40,
) -> list[Match]:
    gray_frame = to_gray(frame)
    tpl = to_gray(template)
    th, tw = tpl.shape[:2]
    if th > gray_frame.shape[0] or tw > gray_frame.shape[1]:
        return []

    result = cv2.matchTemplate(gray_frame, tpl, cv2.TM_CCOEFF_NORMED)
    result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
    ys, xs = np.where(result >= threshold)
    hits = sorted(
        (Match(name, float(result[y, x]), (int(x), int(y), int(tw), int(th))) for y, x in zip(ys, xs)),
        key=lambda m: m.score,
        reverse=True,
    )

    kept: list[Match] = []
    for hit in hits:
        cx, cy = hit.center
        if all((cx - k.center[0]) ** 2 + (cy - k.center[1]) ** 2 > min_distance**2 for k in kept):
            kept.append(hit)
    return kept


def annotate(img: np.ndarray, matches: list[Match]) -> np.ndarray:
    out = img.copy()
    for m in matches:
        x, y, w, h = m.rect
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 200, 0), 2)
        cv2.putText(
            out,
            f"{m.name} {m.score:.2f}",
            (x, max(18, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 200, 0),
            2,
            cv2.LINE_AA,
        )
    return out
