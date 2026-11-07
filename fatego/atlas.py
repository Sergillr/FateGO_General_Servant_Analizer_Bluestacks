from __future__ import annotations

import difflib
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from .config import AtlasConfig
from .models import ServantRecord


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def pretty_class(value: str | None) -> str | None:
    """'alterEgo' -> 'Alter Ego', 'saber' -> 'Saber'."""
    if not value:
        return value
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", value)
    return spaced[:1].upper() + spaced[1:]


class AtlasClient:
    """Cliente de Atlas Academy (https://atlasacademy.io) con cache en disco.

    Se usa para enriquecer lo leido por OCR: stats, clase, rareza, nombres de
    skills y NP. Nunca es obligatorio: si falla la red, el reporte sigue saliendo.
    """

    def __init__(self, cfg: AtlasConfig, cache_dir: Path, ttl_hours: float = 24.0):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.ttl = ttl_hours * 3600
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._index: list[dict[str, Any]] | None = None
        self._by_name: dict[str, dict[str, Any]] | None = None

    # -- cache ----------------------------------------------------------
    def _cache_path(self, name: str) -> Path:
        return self.cache_dir / f"{self.cfg.region}_{name}.json"

    def _read_cache(self, name: str, ttl: float | None = None) -> Any | None:
        path = self._cache_path(name)
        if not path.exists():
            return None
        ttl = self.ttl if ttl is None else ttl
        if ttl > 0 and (time.time() - path.stat().st_mtime) > ttl:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, name: str, data: Any) -> None:
        try:
            self._cache_path(name).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def _get(self, url: str, cache_name: str, ttl: float | None = None) -> Any:
        cached = self._read_cache(cache_name, ttl)
        if cached is not None:
            return cached
        import httpx

        response = httpx.get(url, timeout=90.0, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
        self._write_cache(cache_name, data)
        return data

    # -- API ------------------------------------------------------------
    def index(self) -> list[dict[str, Any]]:
        if self._index is None:
            url = f"{self.cfg.base_url}/export/{self.cfg.region}/basic_servant.json"
            data = self._get(url, "basic_servant", ttl=7 * 24 * 3600)
            self._index = data if isinstance(data, list) else []
        return self._index

    def servant(self, atlas_id: int) -> dict[str, Any] | None:
        url = f"{self.cfg.base_url}/nice/{self.cfg.region}/servant/{atlas_id}"
        try:
            return self._get(url, f"nice_{atlas_id}", ttl=7 * 24 * 3600)
        except Exception:  # noqa: BLE001 - offline o id inexistente
            return None

    def search(self, name: str, limit: int = 5) -> list[dict[str, Any]]:
        url = f"{self.cfg.base_url}/nice/{self.cfg.region}/servant/search"
        try:
            data = self._get(
                f"{url}?name={name}", f"search_{_norm(name).replace(' ', '_')}", ttl=7 * 24 * 3600
            )
        except Exception:  # noqa: BLE001
            return []
        return data[:limit] if isinstance(data, list) else []

    def _name_index(self) -> dict[str, dict[str, Any]]:
        if self._by_name is None:
            table: dict[str, dict[str, Any]] = {}
            for entry in self.index():
                name = entry.get("name") or ""
                key = _norm(name)
                if not key:
                    continue
                current = table.get(key)
                # Preferimos servants jugables (collectionNo > 0) y el id mas bajo
                score = (1 if entry.get("collectionNo") else 0, -(entry.get("id") or 0))
                if current is None:
                    table[key] = entry
                else:
                    cur_score = (1 if current.get("collectionNo") else 0, -(current.get("id") or 0))
                    if score > cur_score:
                        table[key] = entry
            self._by_name = table
        return self._by_name

    def match(self, name: str) -> dict[str, Any] | None:
        if not name:
            return None
        table = self._name_index()
        key = _norm(name)
        if not key:
            return None
        if key in table:
            return table[key]

        close = difflib.get_close_matches(key, list(table), n=1, cutoff=0.82)
        if close:
            return table[close[0]]
        return None

    def enrich(self, record: ServantRecord) -> bool:
        """Completa clase, rareza, stats y nombres desde Atlas Academy."""
        entry = None
        if record.atlas_id:
            entry = next((e for e in self.index() if e.get("id") == record.atlas_id), None)
            # Si el id no concuerda con el nombre leido, es un id equivocado
            if entry is not None and record.name:
                ratio = difflib.SequenceMatcher(
                    None, _norm(entry.get("name", "")), _norm(record.name)
                ).ratio()
                if ratio < 0.5:
                    entry = None
        if entry is None:
            entry = self.match(record.name)
        if entry is None:
            return False

        record.atlas_id = int(entry["id"])
        record.class_name = pretty_class(entry.get("className")) or record.class_name
        record.rarity = int(entry["rarity"]) if entry.get("rarity") else record.rarity

        nice = self.servant(record.atlas_id) or {}
        np_list = nice.get("noblePhantasms") or []
        skills = nice.get("skills") or []
        face = nice.get("face") or entry.get("face") or ""

        record.atlas = {
            "collectionNo": nice.get("collectionNo") or entry.get("collectionNo"),
            "atk_max": nice.get("atkMax") or entry.get("atkMax"),
            "hp_max": nice.get("hpMax") or entry.get("hpMax"),
            "np_name": (np_list[0].get("name") if np_list else None),
            "np_rank": (np_list[0].get("rank") if np_list else None),
            "skill_names": [s.get("name") for s in skills if s.get("name")],
            "face_url": f"https://static.atlasacademy.io{face}" if face.startswith("/") else face,
            "attribute": nice.get("attribute") or entry.get("attribute"),
        }
        return True
