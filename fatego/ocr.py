from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .vision import to_gray

# ---------------------------------------------------------------------------
# Motores disponibles
# ---------------------------------------------------------------------------
# RapidOCR (ONNX, modelos PP-OCRv4) es el motor principal: es el unico que lee
# bien la tipografia de FGO con degradado blanco + borde negro, SIEMPRE que se
# le pase una region amplia con contexto (no un recorte pegado al numero).
# Tesseract queda como respaldo para texto latino.
# ---------------------------------------------------------------------------

_RAPID_ENGINE = None
_RAPID_FAILED: str = ""


def rapid_engine():
    """Instancia unica de RapidOCR (la carga del modelo tarda ~2 s)."""
    global _RAPID_ENGINE, _RAPID_FAILED
    if _RAPID_ENGINE is not None:
        return _RAPID_ENGINE
    if _RAPID_FAILED:
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR

        _RAPID_ENGINE = RapidOCR()
    except Exception as exc:  # noqa: BLE001
        _RAPID_FAILED = f"{exc.__class__.__name__}: {exc}"
        return None
    return _RAPID_ENGINE


def find_tesseract() -> str | None:
    """Busca el binario aunque el PATH del proceso aun no este actualizado."""
    found = shutil.which("tesseract")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


@dataclass
class TextLine:
    """Una linea de texto detectada, con su caja en coordenadas de la imagen."""

    text: str
    score: float
    rect: tuple[int, int, int, int]  # x, y, ancho, alto

    @property
    def center(self) -> tuple[int, int]:
        x, y, w, h = self.rect
        return x + w // 2, y + h // 2


class Ocr:
    """Lectura de texto/numeros con RapidOCR y respaldo de Tesseract."""

    def __init__(self, lang: str = "eng", enabled: bool = True, backend: str = "auto"):
        self.lang = lang
        self.enabled = enabled
        self.backend = backend
        self.reason = ""
        self._available: bool | None = None
        self._tesseract_ready = False

    # -- disponibilidad --------------------------------------------------
    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = False
            if not self.enabled:
                self.reason = "OCR desactivado"
                return False
            if self.backend in ("auto", "rapid") and rapid_engine() is not None:
                self._available = True
                self.reason = ""
                return True
            if self.backend == "rapid":
                self.reason = f"RapidOCR no disponible ({_RAPID_FAILED})"
                return False
            if self._ensure_tesseract():
                self._available = True
            else:
                self.reason = (
                    "Ni RapidOCR ni Tesseract estan disponibles. "
                    "Instala: pip install rapidocr-onnxruntime"
                )
        return self._available

    @property
    def engine_name(self) -> str:
        if rapid_engine() is not None:
            return "rapidocr"
        return "tesseract" if self._tesseract_ready else "none"

    def _ensure_tesseract(self) -> bool:
        if self._tesseract_ready:
            return True
        try:
            import pytesseract

            binary = find_tesseract()
            if binary:
                pytesseract.pytesseract.tesseract_cmd = binary
            pytesseract.get_tesseract_version()
            self._tesseract_ready = True
        except Exception:  # noqa: BLE001
            self._tesseract_ready = False
        return self._tesseract_ready

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _prep(img: np.ndarray, scale: float = 1.0) -> np.ndarray | None:
        if img is None or img.size == 0:
            return None
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if scale != 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return np.ascontiguousarray(img)

    def _rapid_lines(self, img: np.ndarray, scale: float = 1.0) -> list[TextLine]:
        engine = rapid_engine()
        prepared = self._prep(img, scale)
        if engine is None or prepared is None:
            return []
        if min(prepared.shape[:2]) < 12:
            return []
        try:
            result, _ = engine(prepared, use_cls=False, rec_batch_num=16)
        except TypeError:
            # Versiones antiguas de RapidOCR no aceptan estos argumentos.
            try:
                result, _ = engine(prepared)
            except Exception as exc:  # noqa: BLE001
                self.reason = f"RapidOCR: {exc}"
                return []
        except Exception as exc:  # noqa: BLE001
            self.reason = f"RapidOCR: {exc}"
            return []
        out: list[TextLine] = []
        for item in result or []:
            try:
                box, text, score = item[0], item[1], float(item[2])
            except (TypeError, ValueError, IndexError):
                continue
            text = str(text).strip()
            if not text:
                continue
            xs = [p[0] / scale for p in box]
            ys = [p[1] / scale for p in box]
            x0, x1 = int(min(xs)), int(max(xs))
            y0, y1 = int(min(ys)), int(max(ys))
            out.append(TextLine(text, score, (x0, y0, x1 - x0, y1 - y0)))
        out.sort(key=lambda ln: (ln.rect[1], ln.rect[0]))
        return out

    def _tess_text(self, img: np.ndarray, config: str) -> str:
        if not self._ensure_tesseract():
            return ""
        import pytesseract

        try:
            return pytesseract.image_to_string(img, lang=self.lang, config=config).strip()
        except Exception as exc:  # noqa: BLE001
            self.reason = str(exc)
            return ""

    # -- API ------------------------------------------------------------
    def lines(self, img: np.ndarray) -> list[TextLine]:
        """Todas las lineas de la region, en orden de lectura.

        Pasa una region AMPLIA: RapidOCR necesita contexto (etiquetas, otros
        numeros) para segmentar bien. Un recorte de 40x120 suele fallar.
        """
        if not self.enabled or img is None or img.size == 0:
            return []
        if rapid_engine() is not None:
            found = self._rapid_lines(img)
            if not found:
                found = self._rapid_lines(img, scale=2.0)
            return found
        raw = self._tess_text(self._prep(to_gray(img)) or img, "--psm 6")
        return [TextLine(raw, 0.0, (0, 0, img.shape[1], img.shape[0]))] if raw else []

    @staticmethod
    def _variants(img: np.ndarray):
        """Variantes de la misma zona: el detector de RapidOCR es sensible al margen."""
        yield img
        yield cv2.copyMakeBorder(img, 14, 14, 14, 14, cv2.BORDER_REPLICATE)
        yield cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        padded = cv2.copyMakeBorder(img, 16, 16, 16, 16, cv2.BORDER_REPLICATE)
        yield cv2.resize(padded, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)

    def text(self, img: np.ndarray) -> str:
        return re.sub(r"\s+", " ", " ".join(ln.text for ln in self.lines(img))).strip()

    def number(self, img: np.ndarray, pad: int = 0) -> int | None:
        """Primer entero de la region. Usa `labeled` si hay etiqueta de por medio."""
        if img is None or img.size == 0:
            return None
        if pad:
            img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
        for line in self.lines(img):
            match = re.search(r"\d[\d,]*", line.text)
            if match:
                return int(match.group(0).replace(",", ""))
        return None

    def _best_slash(self, img: np.ndarray) -> tuple[int | None, int | None, float]:
        """Prueba varias variantes y se queda con el 'N/M' mas creible."""
        best: tuple[int | None, int | None] = (None, None)
        best_score = -1.0
        for variant in self._variants(img):
            lines = self.lines(variant)
            if not lines:
                continue
            joined = " ".join(ln.text for ln in lines)
            match = re.search(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", joined)
            score = sum(ln.score for ln in lines) / max(1, len(lines))
            if match:
                candidate = (
                    int(match.group(1).replace(",", "")),
                    int(match.group(2).replace(",", "")),
                )
                # Un 'N/M' completo gana siempre a un numero suelto.
                if best[1] is None or score > best_score:
                    best, best_score = candidate, score
                if score > 0.72:
                    break
            elif best[1] is None:
                single = re.search(r"(\d[\d,]*)", joined)
                if single and score > best_score:
                    best = (int(single.group(1).replace(",", "")), None)
                    best_score = score
        return best[0], best[1], best_score

    def digits_with_slash(self, img: np.ndarray) -> tuple[int | None, int | None]:
        """Lee valores tipo '90/90' o 'Lv.155/170' y devuelve (actual, maximo)."""
        if img is None or img.size == 0:
            return None, None
        current, maximum, _ = self._best_slash(img)
        return current, maximum

    def labeled(self, img: np.ndarray, label: str, allow_slash: bool = False) -> int | None:
        """Busca una etiqueta ('Lv.', 'NP', 'Bond') y devuelve el numero asociado."""
        if img is None or img.size == 0:
            return None
        pattern = re.compile(re.escape(label) + r"[^\d]{0,4}(\d[\d,]*)", re.IGNORECASE)
        for line in self.lines(img):
            match = pattern.search(line.text)
            if match:
                return int(match.group(1).replace(",", ""))
        # La etiqueta y el numero pueden venir en lineas separadas.
        found_label = False
        for line in self.lines(img):
            if label.lower() in line.text.lower():
                found_label = True
                continue
            if found_label:
                match = re.search(r"\d[\d,]*", line.text)
                if match:
                    return int(match.group(0).replace(",", ""))
        return None
