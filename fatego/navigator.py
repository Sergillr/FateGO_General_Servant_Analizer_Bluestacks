from __future__ import annotations

import random
import time

import numpy as np

from .adb import Adb
from .capture import ahash, hamming, stable_frame
from .config import Config
from .detail import PANEL_ROI
from .extract import Extractor
from .models import ServantRecord
from .screens import ScreenDetector
from .store import Roster
from .vision import crop

# Zonas de reconocimiento de pantalla (por texto, no por imagen)
DETAIL_TABS_ROI = (700, 120, 1220, 180)   # Status / Profile / Character Skin / Voice
GRID_TITLE_ROI = (1300, 0, 620, 150)      # "Select Servant"
GRID_COST_ROI = (0, 140, 700, 110)        # "TOTAL COST: 100/113"

SCROLL_X = 1300
SCROLL_TOP = 880
SCROLL_STEP = 550


class RosterScanner:
    """Recorre el roster leyendo la ficha de cada servant.

    Flujo automatico: Formation > Party Setup > slot > "Select Servant" (rejilla)
    y pulsacion larga sobre cada tarjeta para abrir su ficha.
    """

    def __init__(
        self,
        adb: Adb,
        detector: ScreenDetector,
        extractor: Extractor,
        roster: Roster,
        cfg: Config,
        log=print,
    ):
        self.adb = adb
        self.detector = detector
        self.extractor = extractor
        self.roster = roster
        self.cfg = cfg
        self.log = log

    # -- helpers --------------------------------------------------------
    def _sleep(self, base: float | None = None) -> None:
        delay = (base if base is not None else self.cfg.scan.action_delay)
        delay += random.uniform(-self.cfg.scan.jitter, self.cfg.scan.jitter)
        time.sleep(max(0.05, delay))

    def _frame(self, timeout: float | None = None) -> np.ndarray:
        return stable_frame(
            self.adb,
            timeout=timeout or self.cfg.scan.settle_timeout,
            interval=self.cfg.scan.settle_interval,
        )

    # -- reconocimiento por texto ---------------------------------------
    def is_detail(self, frame: np.ndarray) -> bool:
        text = self.extractor.ocr.text(crop(frame, DETAIL_TABS_ROI)).lower()
        hits = sum(key in text for key in ("status", "profile", "char", "voice"))
        return hits >= 2

    def is_grid(self, frame: np.ndarray) -> bool:
        title = self.extractor.ocr.text(crop(frame, GRID_TITLE_ROI)).lower()
        cost = self.extractor.ocr.text(crop(frame, GRID_COST_ROI)).lower()
        return "select" in title and "servant" in title or "cost" in cost

    def is_main(self, frame: np.ndarray) -> bool:
        text = self.extractor.ocr.text(crop(frame, (100, 850, 1750, 160))).lower()
        return sum(key in text for key in ("terminal", "formation", "enhance", "summon")) >= 2

    # -- navegacion -----------------------------------------------------
    def goto_grid(self) -> bool:
        """Intenta llegar a la rejilla 'Select Servant' desde donde este el juego."""
        for _ in range(4):
            frame = self._frame()
            if self.is_grid(frame):
                return True
            if self.is_main(frame):
                break
            self.adb.back()
            self._sleep(0.8)
        else:
            return False

        self.log("[i] Navegando: MENU > Formation > Party Setup > slot 1")
        for x, y in ((1740, 1000), (420, 880), (1500, 230), (250, 400)):
            self.adb.tap(x, y)
            self._sleep(0.9)
        return self.is_grid(self._frame())

    def _quick_frame(self, delay: float = 0.55) -> np.ndarray:
        """Captura rapida tras un scroll (sin esperar a que la pantalla se estabilice)."""
        time.sleep(delay)
        return self.adb.screencap()

    def _scroll_panel(self, step: int = SCROLL_STEP) -> np.ndarray:
        self.adb.swipe(SCROLL_X, SCROLL_TOP, SCROLL_X, SCROLL_TOP - step, 350)
        return self._quick_frame()

    def _scroll_to_top(self, steps: int) -> None:
        for _ in range(steps + 1):
            self.adb.swipe(SCROLL_X, 350, SCROLL_X, 350 + SCROLL_STEP, 300)
            time.sleep(0.2)

    def capture_detail(self, max_scrolls: int = 6) -> list[np.ndarray]:
        """Captura la ficha desde arriba y va bajando hasta el final."""
        frames = [self._frame()]
        last = crop(frames[0], PANEL_ROI)
        for _ in range(max_scrolls):
            frame = self._scroll_panel()
            current = crop(frame, PANEL_ROI)
            frames.append(frame)
            if current.shape == last.shape:
                diff = float(np.abs(current.astype(np.int16) - last.astype(np.int16)).mean())
                if diff < 2.0:
                    break
            last = current
        return frames

    def _back_to_grid(self) -> bool:
        self.adb.back()
        self._sleep(0.8)
        for _ in range(6):
            frame = self._frame(timeout=2.0)
            if self.is_grid(frame):
                return True
            time.sleep(0.3)
        return False

    # -- registro -------------------------------------------------------
    def _store(self, record: ServantRecord) -> None:
        """Si el servant ya existe, conserva la mejor copia y rellena huecos."""
        existing = self.roster.get(record.key)
        if existing:
            if (existing.level or 0) > (record.level or 0):
                for field in ("level", "max_level", "np_level", "bond", "fou_atk", "fou_hp"):
                    if getattr(existing, field) is None:
                        setattr(existing, field, getattr(record, field))
                if len(existing.skills) < 3:
                    existing.skills = record.skills
                if len(existing.append_skills) < 5:
                    existing.append_skills = record.append_skills
                if not existing.portrait:
                    existing.portrait = record.portrait
                self.roster.upsert(existing)
                return
        self.roster.upsert(record)

    # -- modo manual ----------------------------------------------------
    def scan_manual(
        self,
        limit: int | None = None,
        name_hint: str | None = None,
        keep_screens: bool = False,
    ) -> int:
        self.log("Modo manual: abre tu la ficha del servant (pulsacion larga) y pulsa Enter.")
        count = 0
        while not limit or count < limit:
            command = input("  Enter = capturar ficha visible | s = salir: ").strip().lower()
            if command == "s":
                break
            frame = self._frame()
            if not self.is_detail(frame):
                self.log("[!] No parece la ficha de un servant. Abrela antes de pulsar Enter.")
                continue
            frames = self.capture_detail()
            self._scroll_to_top(len(frames) - 1)
            record = self.extractor.extract_detail(
                frames, name_hint=name_hint, save_screen=keep_screens
            )
            self._store(record)
            self.roster.save()
            count += 1
            self.log(
                f"[ok] {record.display_name} | nivel {record.level}/{record.max_level} "
                f"| NP {record.np_level} | skills {record.skills} "
                f"| append {record.append_skills} | bond {record.bond}"
            )
        return count

    # -- modo automatico ------------------------------------------------
    def scan_auto(
        self,
        limit: int | None = None,
        dry_run: bool = False,
        keep_screens: bool = False,
        navigate: bool = True,
    ) -> int:
        if navigate and not self.goto_grid():
            self.log(
                "[!] No estoy en la rejilla 'Select Servant'. Abrela a mano:\n"
                "    MENU > Formation > Party Setup > toca un hueco de servant\n"
                "    (o usa --mode manual para ir tu servant por servant)"
            )
            return 0
        if not self.is_grid(self._frame()):
            self.log("[!] La pantalla actual no es la rejilla de servants.")
            return 0

        grid = self.cfg.list
        count = 0
        seen: set[str] = set()
        page_hash: int | None = None
        repeats = 0

        for page in range(self.cfg.scan.max_scrolls):
            self.log(f"[i] Pagina {page + 1}")
            for row in range(grid.rows):
                for col in range(grid.cols):
                    if limit and count >= limit:
                        return count
                    x = grid.x0 + col * grid.dx
                    y = min(grid.y0 + row * grid.dy, self.cfg.device.height - 40)
                    if dry_run:
                        self.log(f"[dry] long-press ({x}, {y})")
                        continue

                    self.adb.swipe(x, y, x, y, 1100)
                    time.sleep(0.9)
                    frame = self._frame(timeout=4.0)
                    if not self.is_detail(frame):
                        continue

                    frames = self.capture_detail()
                    record = self.extractor.extract_detail(frames, save_screen=keep_screens)
                    if record.name in seen:
                        self.log(f"[.] repetido: {record.display_name}")
                    else:
                        seen.add(record.name)
                        self._store(record)
                        self.roster.save()
                        count += 1
                        self.log(
                            f"[ok] {record.display_name} | nivel {record.level}/{record.max_level} "
                            f"| NP {record.np_level} | skills {record.skills} "
                            f"| append {record.append_skills} | bond {record.bond}"
                        )
                    if not self._back_to_grid():
                        self.log("[!] No vuelvo a la rejilla; paro para no perder el hilo.")
                        return count

            if dry_run:
                break

            before = ahash(self._frame())
            self.adb.swipe(960, 950, 960, 350, 500)
            time.sleep(self.cfg.scan.scroll_pause)
            after_frame = self._frame()
            after = ahash(after_frame)
            if page_hash is not None and hamming(after, page_hash) <= 2:
                repeats += 1
            else:
                repeats = 0
            page_hash = after
            if repeats >= 1 or hamming(before, after) <= 2:
                self.log("[i] Fin de la lista.")
                break

        return count
