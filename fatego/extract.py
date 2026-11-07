from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import numpy as np

from .atlas import AtlasClient, pretty_class
from .config import Config
from .detail import (
    PANEL_ROI,
    DetailReading,
    apply_panel,
    missing_fields,
    parse_np_extra,
    parse_panel,
    read_status,
)
from .models import ServantRecord, make_key
from .ocr import Ocr
from .vision import crop, save_png


def _clean_name(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"\bLv\.?\s*\d+.*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^[^A-Za-z0-9]+", "", text)
    return text.strip()


class Extractor:
    """Convierte las capturas de una ficha de servant en un ServantRecord.

    `frames[0]` es la ficha sin desplazar (bloque Status) y el resto son las
    capturas tomadas mientras se baja por skills, append skills y NP.
    """

    def __init__(
        self,
        cfg: Config,
        ocr: Ocr,
        atlas: AtlasClient | None = None,
        portraits_dir: Path | None = None,
        log=print,
    ):
        self.cfg = cfg
        self.ocr = ocr
        self.atlas = atlas
        self.portraits_dir = portraits_dir or (cfg.path.parent / "data" / "portraits")
        self.log = log

    # -- lectura --------------------------------------------------------
    def read(self, frames: list[np.ndarray]) -> DetailReading:
        reading = read_status(frames[0], self.ocr)
        state: dict = {}
        for frame in frames[1:]:
            lines = self.ocr.lines(crop(frame, PANEL_ROI))
            state = parse_panel(lines, state)
            parse_np_extra(lines, state)
        apply_panel(reading, state)
        reading.missing = missing_fields(reading)
        return reading

    # -- registro -------------------------------------------------------
    def extract_detail(
        self,
        frames: list[np.ndarray] | np.ndarray,
        name_hint: str | None = None,
        save_screen: bool = False,
    ) -> ServantRecord:
        if isinstance(frames, np.ndarray):
            frames = [frames]
        if not frames:
            raise ValueError("No hay capturas para analizar")

        reading = self.read(frames)

        name = _clean_name(reading.name or name_hint or "")
        if not name:
            name = f"unknown_{datetime.now():%Y%m%d_%H%M%S}"
            reading.missing.append("name")

        atlas_entry = None
        if self.atlas:
            try:
                atlas_entry = self.atlas.match(name)
            except Exception as exc:  # noqa: BLE001
                self.log(f"[!] Atlas no disponible: {exc}")

        atlas_id = int(atlas_entry["id"]) if atlas_entry and atlas_entry.get("id") else None
        key = make_key(name, atlas_id)

        record = ServantRecord(
            key=key,
            name=name,
            atlas_id=atlas_id,
            class_name=reading.class_name or pretty_class((atlas_entry or {}).get("className")),
            rarity=(int(atlas_entry["rarity"]) if atlas_entry and atlas_entry.get("rarity") else None),
            level=reading.level,
            max_level=reading.max_level,
            np_level=reading.np_level,
            bond=reading.bond,
            fou_atk=reading.fou_atk,
            fou_hp=reading.fou_hp,
        )
        record.skills = [reading.skills.get(i) for i in (1, 2, 3)]
        record.skills = [s for s in record.skills if s is not None]
        record.append_skills = [reading.append_skills.get(i) for i in range(1, 6)]

        # Retrato: la tarjeta de la izquierda.
        portrait_roi = self.cfg.roi("portrait")
        if portrait_roi:
            try:
                portrait = crop(frames[0], portrait_roi)
                if portrait.size:
                    path = save_png(portrait, self.portraits_dir / f"{key.replace(':', '_')}.png")
                    record.portrait = str(path.relative_to(self.cfg.path.parent))
            except Exception as exc:  # noqa: BLE001
                self.log(f"[!] No se pudo guardar el retrato: {exc}")

        if save_screen:
            screens_dir = self.cfg.path.parent / "data" / "screens"
            stamp = f"{datetime.now():%Y%m%d_%H%M%S}_{key.replace(':', '_')}"
            for index, frame in enumerate(frames):
                path = save_png(frame, screens_dir / f"{stamp}_{index}.png")
                record.screenshots.append(str(path.relative_to(self.cfg.path.parent)))

        if self.atlas:
            try:
                self.atlas.enrich(record)
            except Exception as exc:  # noqa: BLE001
                self.log(f"[!] No se pudo enriquecer con Atlas: {exc}")

        record.raw = {
            "detail": reading.as_dict(),
            "missing": sorted(set(reading.missing)),
            "ocr_available": self.ocr.available,
            "ocr_engine": self.ocr.engine_name,
            "ocr_reason": self.ocr.reason,
        }
        if reading.missing:
            self.log(
                "[!] Campos sin leer: "
                + ", ".join(sorted(set(reading.missing)))
                + ". Revisa data/roster.json o vuelve a capturar la ficha."
            )
        return record
