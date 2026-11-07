from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .ocr import Ocr, TextLine
from .vision import crop

# ---------------------------------------------------------------------------
# Zonas fijas del bloque "Status" (no se mueven al hacer scroll).
# Calibradas sobre 1920x1080 con la ficha abierta en la pestana Status.
# ---------------------------------------------------------------------------
STATUS_ROIS: dict[str, tuple[int, int, int, int]] = {
    "name": (700, 0, 1230, 120),
    "class": (1690, 60, 230, 80),
    "level": (1080, 300, 480, 150),
    "stats": (1090, 445, 830, 80),
    "fou": (1090, 495, 830, 80),
    "bond": (1200, 660, 260, 130),
}

# Zona con el texto que se desplaza (panel derecho).
PANEL_ROI = (760, 255, 1160, 825)

SKILL_LABEL = re.compile(r"^SKILL\s*(\d+)$", re.IGNORECASE)
LEVEL_IN_LINE = re.compile(r"Lv\.?\s*(\d+)", re.IGNORECASE)
NUM = r"\d[\d,\.]*"


def _to_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _center_y(line: TextLine) -> int:
    return line.rect[1] + line.rect[3] // 2


@dataclass
class DetailReading:
    name: str | None = None
    class_name: str | None = None
    level: int | None = None
    max_level: int | None = None
    hp: int | None = None
    atk: int | None = None
    cost: int | None = None
    fou_atk: int | None = None
    fou_hp: int | None = None
    bond: int | None = None
    bond_max: int | None = None
    np_level: int | None = None
    np_max: int | None = None
    np_name: str | None = None
    np_rank: str | None = None
    np_class: str | None = None
    skills: dict[int, int] = field(default_factory=dict)
    append_skills: dict[int, int | None] = field(default_factory=dict)
    skill_names: dict[int, str] = field(default_factory=dict)
    class_skills: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "class": self.class_name,
            "level": self.level,
            "max_level": self.max_level,
            "hp": self.hp,
            "atk": self.atk,
            "cost": self.cost,
            "fou_atk": self.fou_atk,
            "fou_hp": self.fou_hp,
            "bond": self.bond,
            "bond_max": self.bond_max,
            "np_level": self.np_level,
            "np_max": self.np_max,
            "np_name": self.np_name,
            "np_rank": self.np_rank,
            "np_class": self.np_class,
            "skills": self.skills,
            "append_skills": self.append_skills,
            "skill_names": self.skill_names,
            "class_skills": self.class_skills,
            "missing": self.missing,
        }


# ---------------------------------------------------------------------------
# Bloque Status (ROIs fijas)
# ---------------------------------------------------------------------------
def read_status(frame: np.ndarray, ocr: Ocr) -> DetailReading:
    reading = DetailReading()

    name = ocr.text(crop(frame, STATUS_ROIS["name"]))
    if name:
        reading.name = re.sub(r"\s+", " ", name).strip(" .,-")

    class_name = ocr.text(crop(frame, STATUS_ROIS["class"]))
    if class_name:
        reading.class_name = class_name.strip(" .,-")

    level, max_level = ocr.digits_with_slash(crop(frame, STATUS_ROIS["level"]))
    reading.level, reading.max_level = level, max_level

    stats = ocr.text(crop(frame, STATUS_ROIS["stats"]))
    hp = re.search(r"HP\s*(" + NUM + ")", stats, re.IGNORECASE)
    atk = re.search(r"ATK\s*(" + NUM + ")", stats, re.IGNORECASE)
    cost = re.search(r"COST\s*(" + NUM + ")", stats, re.IGNORECASE)
    if hp:
        reading.hp = _to_int(hp.group(1))
    if atk:
        reading.atk = _to_int(atk.group(1))
    if cost:
        reading.cost = _to_int(cost.group(1))

    fou = ocr.text(crop(frame, STATUS_ROIS["fou"]))
    pairs = re.findall(r"(\d+)\s*/\s*(" + NUM + ")", fou)
    if len(pairs) >= 2:
        reading.fou_atk = _to_int(pairs[0][0])
        reading.fou_hp = _to_int(pairs[1][0])

    bond, bond_max = ocr.digits_with_slash(crop(frame, STATUS_ROIS["bond"]))
    reading.bond, reading.bond_max = bond, bond_max
    return reading


# ---------------------------------------------------------------------------
# Panel con scroll (skills, class skills, append, NP)
# ---------------------------------------------------------------------------
def _find_level_near(lines: list[TextLine], label: TextLine) -> int | None:
    """Nivel que aparece en la misma fila que la etiqueta SKILL n."""
    y = _center_y(label)
    best: tuple[int, int] | None = None
    for line in lines:
        if line is label:
            continue
        if line.rect[0] < label.rect[0] + 40:
            continue
        if abs(_center_y(line) - y) > 34:
            continue
        if "[" in line.text or "]" in line.text:
            continue
        match = LEVEL_IN_LINE.search(line.text)
        if match:
            distance = abs(_center_y(line) - y)
            if best is None or distance < best[0]:
                best = (distance, int(match.group(1)))
    return best[1] if best else None


def parse_panel(
    lines: list[TextLine],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Acumula lo leido en una captura. `state` persiste entre capturas."""
    state.setdefault("section", "status")
    state.setdefault("skills", {})
    state.setdefault("append_skills", {})
    state.setdefault("skill_names", {})
    state.setdefault("class_skills", [])

    for line in lines:
        text = line.text.strip()
        norm = _norm(text)
        if norm in ("skills",):
            state["section"] = "skills"
            continue
        if norm in ("classskills",):
            state["section"] = "classskills"
            continue
        if norm in ("appendskills",):
            state["section"] = "appendskills"
            continue
        if norm in ("noblephantasm",):
            state["section"] = "np"
            continue
        # El subtitulo de la seccion Skills sobrevive al scroll aunque la
        # cabecera "Skills" se quede fuera de la captura.
        if "usedanytime" in norm:
            state["section"] = "skills"
            continue

        label = SKILL_LABEL.match(text)
        if label:
            number = int(label.group(1))
            level = _find_level_near(lines, line)
            section = state["section"]
            if level is not None and section == "status":
                # La cabecera "Skills" se perdio: si hay nivel, son las skills.
                section = state["section"] = "skills"
            if section == "skills" and level is not None:
                state["skills"].setdefault(number, level)
            elif section == "appendskills":
                state["append_skills"].setdefault(number, level)
            elif section == "classskills" and level is not None:
                # Las skills de clase no tienen nivel: esto es la seccion append.
                state["section"] = "appendskills"
                state["append_skills"].setdefault(number, level)
            elif section == "classskills" and level is None:
                # El nombre de la skill de clase esta en la misma fila.
                for other in lines:
                    if other is line or abs(_center_y(other) - _center_y(line)) > 40:
                        continue
                    if other.rect[0] > line.rect[0] + 40 and not LEVEL_IN_LINE.search(other.text):
                        if other.text.strip():
                            state["class_skills"].append(other.text.strip())
                            break
            continue

        # Nombres de skill normal: linea con "Lv. N" a la derecha de SKILL n
        if state["section"] == "skills" and LEVEL_IN_LINE.search(text) and "[" not in text:
            for other in lines:
                other_label = SKILL_LABEL.match(other.text.strip())
                if not other_label:
                    continue
                if abs(_center_y(other) - _center_y(line)) <= 34 and other.rect[0] < line.rect[0]:
                    state["skill_names"][int(other_label.group(1))] = re.sub(
                        r"\s*Lv\.?\s*\d+.*$", "", text, flags=re.IGNORECASE
                    ).strip(" ^·")
                    break

    # NP Lv. (la etiqueta y el valor pueden venir en lineas distintas)
    for line in lines:
        if re.match(r"^NP\s*LV\.?$", line.text.strip(), re.IGNORECASE):
            for other in lines:
                if other is line:
                    continue
                if abs(_center_y(other) - _center_y(line)) > 40:
                    continue
                if other.rect[0] < line.rect[0]:
                    continue
                match = re.search(r"(\d+)\s*/\s*(\d+)", other.text)
                if match:
                    state["np_level"] = int(match.group(1))
                    state["np_max"] = int(match.group(2))
                    break
    return state


def parse_np_extra(lines: list[TextLine], state: dict[str, Any]) -> None:
    """Nombre, rango y clase de la NP (lineas junto a 'Rank' y 'Class')."""
    rank_line: TextLine | None = None
    for line in lines:
        text = line.text.strip()
        if re.match(r"^Rank$", text, re.IGNORECASE):
            rank_line = line
            for other in lines:
                if other is not line and abs(_center_y(other) - _center_y(line)) <= 40 \
                        and other.rect[0] > line.rect[0]:
                    state.setdefault("np_rank", other.text.strip())
                    break
        elif re.match(r"^Class$", text, re.IGNORECASE):
            for other in lines:
                if other is not line and abs(_center_y(other) - _center_y(line)) <= 40 \
                        and other.rect[0] > line.rect[0]:
                    state.setdefault("np_class", other.text.strip())
                    break

    if rank_line is not None and not state.get("np_name"):
        # El nombre de la NP es la linea justo encima de "Rank".
        candidates = [
            ln for ln in lines
            if ln.rect[0] > rank_line.rect[0] - 40
            and _center_y(ln) < _center_y(rank_line) - 20
            and _norm(ln.text) not in ("noblephantasm", "rank", "class", "nplv", "npgauge")
            and not LEVEL_IN_LINE.search(ln.text)
        ]
        if candidates:
            state["np_name"] = max(candidates, key=_center_y).text.strip()


def apply_panel(reading: DetailReading, state: dict[str, Any]) -> None:
    if state.get("skills"):
        reading.skills = dict(sorted(state["skills"].items()))
    if state.get("append_skills"):
        reading.append_skills = dict(sorted(state["append_skills"].items()))
    if state.get("skill_names"):
        reading.skill_names = dict(state["skill_names"])
    if state.get("class_skills"):
        # Quita duplicados conservando el orden de aparicion.
        reading.class_skills = list(dict.fromkeys(state["class_skills"]))
    if state.get("np_level") is not None:
        reading.np_level = state["np_level"]
        reading.np_max = state.get("np_max")
    if state.get("np_rank"):
        reading.np_rank = state["np_rank"]
    if state.get("np_class"):
        reading.np_class = state["np_class"]
    if state.get("np_name"):
        reading.np_name = state["np_name"]


def missing_fields(reading: DetailReading) -> list[str]:
    missing: list[str] = []
    for name in ("name", "level", "max_level", "hp", "atk", "bond", "fou_atk", "fou_hp"):
        if getattr(reading, name) is None:
            missing.append(name)
    if reading.np_level is None:
        missing.append("np_level")
    if len(reading.skills) < 3:
        missing.append("skills")
    return missing
