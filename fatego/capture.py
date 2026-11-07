from __future__ import annotations

import time

import cv2
import numpy as np

from .adb import Adb


def grab(adb: Adb) -> np.ndarray:
    return adb.screencap()


def stable_frame(
    adb: Adb,
    timeout: float = 6.0,
    interval: float = 0.25,
    threshold: float = 0.6,
) -> np.ndarray:
    """Espera a que dos capturas consecutivas sean casi identicas.

    Evita leer una pantalla a medio animar (fundidos, transiciones, scroll).
    """
    prev = grab(adb)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(interval)
        cur = grab(adb)
        if cur.shape == prev.shape and cv2.absdiff(cur, prev).mean() < threshold:
            return cur
        prev = cur
    return prev


def ahash(img: np.ndarray, size: int = 8) -> int:
    """Hash perceptual (average hash) empaquetado en un entero de 64 bits."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    bits = (small > small.mean()).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
