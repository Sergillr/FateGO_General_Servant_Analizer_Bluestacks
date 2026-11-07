from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from .config import Config


class AdbError(RuntimeError):
    pass


_BLUESTACKS_CANDIDATES = [
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\BlueStacks_nxt\Engine\HD-Adb.exe",
    r"C:\Program Files\BlueStacks\HD-Adb.exe",
    r"C:\Program Files\BlueStacks\Engine\HD-Adb.exe",
    r"C:\Program Files (x86)\BlueStacks_nxt\HD-Adb.exe",
]


def find_adb(explicit: str = "") -> str:
    if explicit:
        path = Path(explicit)
        if path.exists():
            return str(path)
        raise AdbError(f"adb_path no existe: {explicit}")

    found = shutil.which("adb")
    if found:
        return found

    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(env)
        if root:
            candidate = Path(root) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
            if candidate.exists():
                return str(candidate)

    for candidate in _BLUESTACKS_CANDIDATES:
        if Path(candidate).exists():
            return candidate

    raise AdbError(
        "No encuentro adb. Instala platform-tools o pon la ruta en config.toml [adb] adb_path."
    )


class Adb:
    """Envoltorio minimo de ADB: conectar, capturar y enviar toques."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.adb = find_adb(cfg.adb.adb_path)
        self.serial = cfg.adb.serial

    # -- bajo nivel -----------------------------------------------------
    def _run(self, *args: object, timeout: int = 30, binary: bool = False):
        cmd = [self.adb]
        global_cmds = {"connect", "disconnect", "devices", "start-server", "kill-server"}
        if not args or args[0] not in global_cmds:
            cmd += ["-s", self.serial]
        cmd += [str(a) for a in args]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise AdbError(f"adb no ejecutable: {self.adb}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb timeout: {' '.join(cmd)}") from exc

        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace").strip()
            out = proc.stdout.decode("utf-8", "replace").strip()
            raise AdbError(err or out or f"adb fallo con codigo {proc.returncode}")
        return proc.stdout if binary else proc.stdout.decode("utf-8", "replace").strip()

    # -- conexion -------------------------------------------------------
    def connect(self) -> str:
        return self._run("connect", self.serial, timeout=15)

    def devices(self) -> list[str]:
        out = self._run("devices", timeout=15)
        lines = [ln.strip() for ln in out.splitlines()[1:] if ln.strip()]
        return [ln.split()[0] for ln in lines]

    def ensure(self) -> str:
        try:
            if self.serial in self.devices():
                return self.serial
        except AdbError:
            pass
        self.connect()
        if self.serial not in self.devices():
            raise AdbError(
                f"No hay dispositivo en {self.serial}. "
                "Activa ADB en BlueStacks (Ajustes > Avanzado) y comprueba el puerto."
            )
        return self.serial

    def info(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self._run("shell", "getprop").splitlines():
            if "]: [" in line:
                key, value = line.split("]: [", 1)
                out[key.lstrip("[")] = value.rstrip("]")
        return out

    def wm_size(self) -> tuple[int, int]:
        out = self._run("shell", "wm", "size")
        for line in out.splitlines():
            if ":" in line:
                value = line.split(":", 1)[1].strip()
                if "x" in value:
                    w, h = value.split("x", 1)
                    return int(w), int(h)
        return self.cfg.device.width, self.cfg.device.height

    def focus(self) -> str:
        out = self._run("shell", "dumpsys", "window")
        for line in out.splitlines():
            if "mCurrentFocus" in line:
                return line.strip()
        return ""

    # -- acciones -------------------------------------------------------
    def screencap(self) -> np.ndarray:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                raw = self._run("exec-out", "screencap", "-p", binary=True, timeout=20)
                img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return img
                last_error = AdbError("PNG invalido en exec-out")
            except AdbError as exc:
                last_error = exc
            time.sleep(0.15)

        # Plan B: guardar en el dispositivo y traer el archivo
        tmp = Path(tempfile.gettempdir()) / "fgo_analyzer_shot.png"
        self._run("shell", "screencap", "-p", "/sdcard/_fgo_shot.png", timeout=20)
        self._run("pull", "/sdcard/_fgo_shot.png", str(tmp), timeout=20)
        img = cv2.imread(str(tmp))
        if img is None:
            raise AdbError(f"No se pudo capturar la pantalla: {last_error}")
        return img

    def tap(self, x: int, y: int) -> None:
        self._run("shell", "input", "tap", int(x), int(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None:
        self._run("shell", "input", "swipe", int(x1), int(y1), int(x2), int(y2), int(duration_ms))

    def keyevent(self, code: int | str) -> None:
        self._run("shell", "input", "keyevent", code)

    def back(self) -> None:
        self.keyevent(4)
