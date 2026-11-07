from __future__ import annotations

import argparse
import importlib
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fatego.config import ASSETS_DIR, DATA_DIR, OUTPUT_DIR, Config  # noqa: E402


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def _adb(cfg: Config):
    from fatego.adb import Adb

    adb = Adb(cfg)
    adb.ensure()
    return adb


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = Config.load()
    problems = 0

    print("== Entorno ==")
    print(f"Python {sys.version.split()[0]} en {sys.executable}")
    for module, label in [
        ("numpy", "numpy"),
        ("cv2", "opencv-python"),
        ("PIL", "pillow"),
        ("reportlab", "reportlab"),
        ("httpx", "httpx"),
        ("pytesseract", "pytesseract"),
    ]:
        try:
            importlib.import_module(module)
            print(f"  [ok] {label}")
        except Exception as exc:  # noqa: BLE001
            problems += 1
            print(f"  [x ] {label}: {exc}")

    print("\n== ADB ==")
    try:
        from fatego.adb import Adb

        adb = Adb(cfg)
        print(f"  [ok] binario: {adb.adb}")
        try:
            print(f"  [i ] {adb.connect()}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] connect: {exc}")
        devices = adb.devices()
        print(f"  [i ] dispositivos: {devices or 'ninguno'}")
        if adb.serial not in devices:
            problems += 1
            print("  [x ] El emulador no aparece. Activa ADB en BlueStacks (Ajustes > Avanzado).")
        else:
            width, height = adb.wm_size()
            print(f"  [i ] resolucion: {width}x{height}")
            if (width, height) != (cfg.device.width, cfg.device.height):
                print(
                    f"  [!] config.toml espera {cfg.device.width}x{cfg.device.height}. "
                    "Iguala la resolucion o actualiza la config."
                )
            try:
                frame = adb.screencap()
                print(f"  [ok] captura: {frame.shape[1]}x{frame.shape[0]}")
            except Exception as exc:  # noqa: BLE001
                problems += 1
                print(f"  [x ] captura: {exc}")
            focus = adb.focus()
            print(f"  [i ] foco: {focus or 'desconocido'}")
            if "fate" not in focus.lower() and "fgo" not in focus.lower():
                print("  [!] Puede que FGO no este en primer plano.")
    except Exception as exc:  # noqa: BLE001
        problems += 1
        print(f"  [x ] {exc}")

    print("\n== Vision ==")
    anchors = sorted((ASSETS_DIR / "anchors").glob("*.png"))
    if anchors:
        for anchor in anchors:
            print(f"  [ok] ancla: {anchor.stem}")
    else:
        print("  [!] Sin anclas. Crea 'servant_list' y 'servant_detail' con tools/calibrate.py")
    print(f"  [i ] ROIs definidos: {len(cfg.rois)}")
    for required in ("name", "level", "np_level", "skill_1", "skill_2", "skill_3"):
        if required not in cfg.rois:
            print(f"  [!] falta el ROI '{required}'")

    print("\n== OCR ==")
    from fatego.ocr import Ocr, rapid_engine

    if rapid_engine() is not None:
        print("  [ok] RapidOCR (motor principal)")
    else:
        problems += 1
        print("  [x ] RapidOCR no disponible. Instala: pip install rapidocr-onnxruntime")

    ocr = Ocr(cfg.device.language)
    if ocr.available:
        print(f"  [ok] motor activo: {ocr.engine_name}")
    else:
        print(f"  [!] {ocr.reason}")

    print("\n== Atlas Academy ==")
    cache = DATA_DIR / "cache" / f"{cfg.atlas.region}_basic_servant.json"
    print(f"  [{'ok' if cache.exists() else 'i '}] indice en cache: {cache.exists()}")
    print("      Precalienta con: python run.py atlas --index")

    print(f"\nResultado: {'TODO OK' if problems == 0 else f'{problems} problema(s)'}")
    return 0 if problems == 0 else 1


# ---------------------------------------------------------------------------
# captura / deteccion
# ---------------------------------------------------------------------------
def cmd_shot(args: argparse.Namespace) -> int:
    from fatego.vision import save_png

    cfg = Config.load()
    adb = _adb(cfg)
    frame = adb.screencap()
    out = Path(args.out) if args.out else (
        OUTPUT_DIR / "screenshots" / f"shot_{datetime.now():%Y%m%d_%H%M%S}.png"
    )
    save_png(frame, out)
    print(f"Guardado: {out} ({frame.shape[1]}x{frame.shape[0]})")
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    from fatego.capture import stable_frame
    from fatego.screens import ScreenDetector
    from fatego.vision import annotate, save_png

    cfg = Config.load()
    adb = _adb(cfg)
    frame = stable_frame(adb, timeout=cfg.scan.settle_timeout, interval=cfg.scan.settle_interval)
    detector = ScreenDetector.from_disk(ASSETS_DIR / "anchors")
    hits = detector.detect_all(frame)

    if not hits:
        print("No reconozco ninguna pantalla (revisa las anclas).")
    for hit in hits:
        print(f"  {hit.name:20s} score={hit.score:.3f} rect={hit.rect}")

    out = OUTPUT_DIR / "debug" / f"detect_{datetime.now():%Y%m%d_%H%M%S}.png"
    save_png(annotate(frame, hits), out)
    print(f"Anotado: {out}")
    return 0


# ---------------------------------------------------------------------------
# lectura OCR
# ---------------------------------------------------------------------------
def cmd_read(args: argparse.Namespace) -> int:
    """OCR de una captura (o de la pantalla actual) para calibrar zonas."""
    from fatego.ocr import Ocr
    from fatego.vision import crop, load_image, save_png

    cfg = Config.load()
    if args.image:
        frame = load_image(args.image)
        if frame is None:
            print(f"No pude abrir: {args.image}")
            return 1
        origin = (0, 0)
    else:
        adb = _adb(cfg)
        frame = adb.screencap()
        origin = (0, 0)

    if args.roi:
        x, y, w, h = (int(v) for v in args.roi)
        frame = crop(frame, (x, y, w, h))
        origin = (x, y)

    ocr = Ocr(cfg.device.language)
    if not ocr.available:
        print(f"[!] {ocr.reason}")
        return 1

    lines = ocr.lines(frame)
    if not lines:
        print("Sin texto detectado. Prueba una region mas amplia (contexto).")
        return 0

    print(f"Motor: {ocr.engine_name} · {len(lines)} lineas")
    for line in lines:
        x, y, w, h = line.rect
        print(f"  {line.score:4.2f}  ({x + origin[0]:4d},{y + origin[1]:4d}) "
              f"{w:4d}x{h:3d}  {line.text!r}")

    if args.annotate:
        from fatego.vision import Match, annotate

        marks = [Match(ln.text, ln.score, ln.rect) for ln in lines]
        out = OUTPUT_DIR / "debug" / f"read_{datetime.now():%Y%m%d_%H%M%S}.png"
        save_png(annotate(frame, marks), out)
        print(f"Anotado: {out}")

    joined = " ".join(ln.text for ln in lines)
    print(f"\nTexto: {joined!r}")
    print(f"Numeros: {re.findall(r'\d[\d,]*', joined)}")
    return 0


# ---------------------------------------------------------------------------
# escaneo
# ---------------------------------------------------------------------------
def cmd_scan(args: argparse.Namespace) -> int:
    from fatego.atlas import AtlasClient
    from fatego.extract import Extractor
    from fatego.navigator import RosterScanner
    from fatego.ocr import Ocr
    from fatego.screens import ScreenDetector
    from fatego.store import Roster

    cfg = Config.load()
    adb = _adb(cfg)
    detector = ScreenDetector.from_disk(ASSETS_DIR / "anchors")
    ocr = Ocr(cfg.device.language, enabled=not args.no_ocr)
    if not ocr.available:
        log(f"[!] OCR no disponible: {ocr.reason}")
    atlas = None if args.no_atlas else AtlasClient(cfg.atlas, DATA_DIR / "cache")

    extractor = Extractor(cfg, ocr, atlas, DATA_DIR / "portraits", log=log)
    roster = Roster(DATA_DIR / "roster.json").load()
    log(f"Roster actual: {len(roster)} servants")

    scanner = RosterScanner(adb, detector, extractor, roster, cfg, log=log)
    if args.mode == "manual":
        count = scanner.scan_manual(
            limit=args.limit, name_hint=args.name, keep_screens=args.keep_screens
        )
    else:
        count = scanner.scan_auto(
            limit=args.limit,
            dry_run=args.dry_run,
            keep_screens=args.keep_screens,
            navigate=not args.no_nav,
        )

    log(f"Capturados en esta sesion: {count}. Total en roster: {len(roster)}")
    return 0


# ---------------------------------------------------------------------------
# reporte
# ---------------------------------------------------------------------------
def cmd_report(args: argparse.Namespace) -> int:
    from fatego.report import build_report
    from fatego.store import Roster

    cfg = Config.load()
    roster = Roster(DATA_DIR / "roster.json").load()
    if not len(roster):
        print("El roster esta vacio. Ejecuta 'python run.py scan' o prueba 'python run.py demo'.")
        return 1

    out = Path(args.out) if args.out else (
        OUTPUT_DIR / f"fgo_report_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    )
    build_report(roster, out, title=cfg.report.title, author=cfg.report.author, root=ROOT)
    print(f"PDF generado: {out}")
    if args.open and os.name == "nt":
        os.startfile(out)  # type: ignore[attr-defined]
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from fatego.models import ServantRecord, make_key
    from fatego.report import build_report
    from fatego.store import Roster

    cfg = Config.load()
    roster = Roster(DATA_DIR / "demo_roster.json")

    def demo_record(name: str, **kwargs) -> ServantRecord:
        return ServantRecord(key=make_key(name, None), name=name, **kwargs)

    demo = [
        demo_record("Mash Kyrielight", level=90, max_level=90, np_level=5,
                    skills=[10, 10, 10], append_skills=[10, 10, 10], bond=10,
                    fou_atk=1000, fou_hp=1000),
        demo_record("Artoria Pendragon", level=100, max_level=100, np_level=2,
                    skills=[10, 10, 10], append_skills=[10, 6, 1], bond=9,
                    fou_atk=1000, fou_hp=1000),
        demo_record("Cu Chulainn", level=80, max_level=80, np_level=5,
                    skills=[10, 10, 6], append_skills=[1, 1, 1], bond=10,
                    fou_atk=1000, fou_hp=1000),
        demo_record("Artoria Pendragon (Alter)", level=70, max_level=90, np_level=1,
                    skills=[6, 6, 6], append_skills=[1, 1, 1], bond=5,
                    fou_atk=200, fou_hp=200),
    ]
    if not args.no_atlas:
        try:
            from fatego.atlas import AtlasClient

            atlas = AtlasClient(cfg.atlas, DATA_DIR / "cache")
            for record in demo:
                atlas.enrich(record)
        except Exception as exc:  # noqa: BLE001
            log(f"[!] Sin Atlas: {exc}")

    for record in demo:
        roster.upsert(record)

    out = Path(args.out) if args.out else OUTPUT_DIR / "demo_report.pdf"
    build_report(roster, out, title=cfg.report.title, author=cfg.report.author, root=ROOT)
    print(f"PDF de ejemplo: {out}")
    if args.open and os.name == "nt":
        os.startfile(out)  # type: ignore[attr-defined]
    return 0


# ---------------------------------------------------------------------------
# atlas
# ---------------------------------------------------------------------------
def cmd_atlas(args: argparse.Namespace) -> int:
    from fatego.atlas import AtlasClient

    cfg = Config.load()
    atlas = AtlasClient(cfg.atlas, DATA_DIR / "cache")

    if args.servant:
        data = atlas.servant(args.servant)
        if not data:
            print("No encontrado.")
            return 1
        print(f"{data.get('name')} ({data.get('className')}, {data.get('rarity')}*)")
        print(f"ATK max: {data.get('atkMax')} · HP max: {data.get('hpMax')}")
        for skill in data.get("skills") or []:
            print(f"  skill {skill.get('num')}: {skill.get('name')}")
        for np in data.get("noblePhantasms") or []:
            print(f"  NP: {np.get('name')} ({np.get('rank')})")
        return 0

    if args.name:
        for entry in atlas.search(args.name):
            print(f"{entry.get('id'):>8}  {entry.get('name')}  "
                  f"[{entry.get('className')}] {entry.get('rarity')}*")
        return 0

    index = atlas.index()
    print(f"Indice {cfg.atlas.region}: {len(index)} entradas en cache.")
    return 0


# ---------------------------------------------------------------------------
# calibracion
# ---------------------------------------------------------------------------
def cmd_calibrate(args: argparse.Namespace) -> int:
    script = ROOT / "tools" / "calibrate.py"
    command = [sys.executable, str(script), *args.calibrate_args]
    return subprocess.call(command)


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fgo-analyzer",
        description="Analiza tu roster de FGO en BlueStacks y genera un PDF.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Comprueba entorno, ADB, resolucion y calibracion")

    p = sub.add_parser("shot", help="Guarda una captura de pantalla")
    p.add_argument("--out", help="Ruta del PNG de salida")

    sub.add_parser("detect", help="Detecta en que pantalla esta el juego")

    p = sub.add_parser("read", help="Lee el texto de la pantalla (o de un PNG) para calibrar")
    p.add_argument("--image", help="PNG a analizar (por defecto: captura en vivo)")
    p.add_argument("--roi", nargs=4, metavar=("X", "Y", "W", "H"), help="Region a leer")
    p.add_argument("--annotate", action="store_true", help="Guardar PNG con las cajas detectadas")

    p = sub.add_parser("scan", help="Recorre el roster y guarda los datos")
    p.add_argument("--mode", choices=["manual", "auto"], default="manual")
    p.add_argument("--limit", type=int, help="Maximo de servants a capturar")
    p.add_argument("--name", help="Nombre a usar cuando el OCR del nombre falle (modo manual)")
    p.add_argument("--no-ocr", action="store_true", help="No usar Tesseract")
    p.add_argument("--no-atlas", action="store_true", help="No consultar Atlas Academy")
    p.add_argument("--keep-screens", action="store_true", help="Guardar captura completa de cada ficha")
    p.add_argument("--dry-run", action="store_true", help="Solo simular toques (modo auto)")
    p.add_argument("--no-nav", action="store_true", help="No navegar solo hasta la rejilla de servants")

    p = sub.add_parser("report", help="Genera el PDF desde data/roster.json")
    p.add_argument("--out", help="Ruta del PDF")
    p.add_argument("--open", action="store_true", help="Abrir el PDF al terminar")

    p = sub.add_parser("demo", help="Genera un PDF de ejemplo sin emulador")
    p.add_argument("--out", help="Ruta del PDF")
    p.add_argument("--open", action="store_true")
    p.add_argument("--no-atlas", action="store_true")

    p = sub.add_parser("atlas", help="Consulta Atlas Academy")
    p.add_argument("--index", action="store_true", help="Descarga/cachea el indice de servants")
    p.add_argument("--name", help="Busca servants por nombre")
    p.add_argument("--servant", type=int, help="Muestra un servant por id")

    p = sub.add_parser("calibrate", help="Abre tools/calibrate.py (anclas, ROIs, rejilla)")
    p.add_argument("calibrate_args", nargs=argparse.REMAINDER)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "doctor": cmd_doctor,
        "shot": cmd_shot,
        "detect": cmd_detect,
        "read": cmd_read,
        "scan": cmd_scan,
        "report": cmd_report,
        "demo": cmd_demo,
        "atlas": cmd_atlas,
        "calibrate": cmd_calibrate,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        print("\nCancelado.")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\n[error] {exc}")
        if os.environ.get("FGO_DEBUG"):
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
