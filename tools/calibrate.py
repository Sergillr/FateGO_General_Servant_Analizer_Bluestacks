"""Herramienta de calibracion visual.

Uso:
    python tools/calibrate.py anchor servant_list
    python tools/calibrate.py anchor servant_detail
    python tools/calibrate.py roi level
    python tools/calibrate.py grid
    python tools/calibrate.py test

Cada comando hace una captura (o usa --image ruta.png) y abre una ventana
donde arrastras un rectangulo con el raton. Enter/Espacio confirma, c cancela.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from fatego.config import ASSETS_DIR, DATA_DIR, OUTPUT_DIR, Config  # noqa: E402
from fatego.vision import annotate, load_image, save_png  # noqa: E402


def get_frame(image: str | None):
    if image:
        frame = load_image(image)
        if frame is None:
            raise SystemExit(f"No se pudo leer la imagen: {image}")
        return frame

    from fatego.adb import Adb

    cfg = Config.load()
    adb = Adb(cfg)
    adb.ensure()
    return adb.screencap()


def select_roi(frame, title: str, max_width: int = 1600):
    scale = min(1.0, max_width / frame.shape[1])
    display = frame
    if scale < 1.0:
        display = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    print(f"[i] Arrastra el rectangulo en la ventana '{title}'. Enter confirma, c cancela.")
    x, y, w, h = cv2.selectROI(title, display, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()

    if w == 0 or h == 0:
        raise SystemExit("Seleccion cancelada.")

    if scale < 1.0:
        x, y, w, h = (int(round(v / scale)) for v in (x, y, w, h))
    return int(x), int(y), int(w), int(h)


def _merge_json(path: Path, data: dict) -> dict:
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            current = {}
    current.update(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def cmd_anchor(args: argparse.Namespace) -> int:
    frame = get_frame(args.image)
    roi = select_roi(frame, f"ancla: {args.name}")
    x, y, w, h = roi
    if w < 20 or h < 20:
        print("[!] El ancla es muy pequena; elige una zona con detalle unico (>= 40x40).")
    crop = frame[y : y + h, x : x + w]
    out = ASSETS_DIR / "anchors" / f"{args.name}.png"
    save_png(crop, out)
    print(f"[ok] Ancla guardada: {out} ({w}x{h})")
    print("     Repite con otra pantalla. Nombres sugeridos: servant_list, servant_detail")
    return 0


def cmd_roi(args: argparse.Namespace) -> int:
    frame = get_frame(args.image)
    roi = select_roi(frame, f"ROI: {args.field}")
    data = _merge_json(DATA_DIR / "rois.json", {args.field: list(roi)})
    print(f"[ok] ROI '{args.field}' = {list(roi)}")
    print(f"     Guardado en {DATA_DIR / 'rois.json'}")
    print(f"     Total de ROIs: {len(data)}")
    return 0


def cmd_grid(args: argparse.Namespace) -> int:
    frame = get_frame(args.image)
    x, y, w, h = select_roi(frame, "rejilla de tarjetas (solo la zona de tarjetas)")
    cols = args.cols or int(input("Columnas visibles: ") or "3")
    rows = args.rows or int(input("Filas visibles: ") or "3")
    if cols < 1 or rows < 1:
        raise SystemExit("Columnas y filas deben ser >= 1")

    dx = w / cols
    dy = h / rows
    grid = {
        "cols": cols,
        "rows": rows,
        "x0": int(round(x + dx / 2)),
        "y0": int(round(y + dy / 2)),
        "dx": int(round(dx)),
        "dy": int(round(dy)),
    }
    _merge_json(DATA_DIR / "grid.json", grid)
    print(f"[ok] Rejilla: {grid}")
    print(f"     Guardado en {DATA_DIR / 'grid.json'}")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    from fatego.screens import ScreenDetector

    frame = get_frame(args.image)
    detector = ScreenDetector.from_disk(ASSETS_DIR / "anchors")
    hits = detector.detect_all(frame)
    if not hits:
        print("[!] Ninguna ancla coincide. Revisa assets/anchors/.")
    for hit in hits:
        print(f"  {hit.name:20s} score={hit.score:.3f} rect={hit.rect}")
    out = OUTPUT_DIR / "debug" / "calibrate_test.png"
    save_png(annotate(frame, hits), out)
    print(f"[i] Imagen anotada: {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibracion visual del analizador")
    parser.add_argument("--image", help="Usar un PNG existente en vez de capturar del emulador")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("anchor", help="Guardar un recorte como ancla de pantalla")
    p.add_argument("name")

    p = sub.add_parser("roi", help="Guardar una zona de lectura (nivel, np_level, skill_1...)")
    p.add_argument("field")

    p = sub.add_parser("grid", help="Definir la rejilla de tarjetas de la lista")
    p.add_argument("--cols", type=int)
    p.add_argument("--rows", type=int)

    sub.add_parser("test", help="Probar las anclas contra la pantalla actual")

    args = parser.parse_args()
    handlers = {"anchor": cmd_anchor, "roi": cmd_roi, "grid": cmd_grid, "test": cmd_test}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
