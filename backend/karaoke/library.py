"""La libreria su disco: una cartella per brano."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .models import LyricLine, Note, PitchCurve, SongMeta, StageState, Word

META = "meta.json"
SOURCE = "source.flac"
VOCALS = "vocals.flac"
INSTRUMENTAL = "instrumental.flac"
PITCH = "pitch.json"
NOTES = "notes.json"
NOTES_SWIFTF0 = "notes.swiftf0.json"
LYRICS = "lyrics.json"
SCORES = "scores.json"

INTERRUPTED = "Elaborazione interrotta"

# Un id è il nome di una cartella: solo lettere, cifre, trattino e trattino basso,
# così non può mai indicare un percorso fuori dalla libreria.
_VALID_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class SongExists(Exception):
    pass


class SongNotFound(Exception):
    pass


def _write_json(path: Path, data: Any) -> None:
    """Scrittura atomica: un file a metà non deve mai sostituire quello buono."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def notes_to_dict(notes: list[Note]) -> dict[str, Any]:
    return {"notes": [asdict(n) for n in notes]}


def lines_to_dict(lines: list[LyricLine]) -> dict[str, Any]:
    return {"lines": [asdict(line) for line in lines]}


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.RLock()

    # --- brani ---------------------------------------------------------

    def path(self, song_id: str, name: str) -> Path:
        if not _VALID_ID.match(song_id):
            raise SongNotFound(song_id)
        return self.root / song_id / name

    def exists(self, song_id: str) -> bool:
        return _VALID_ID.match(song_id) is not None and self.path(song_id, META).is_file()

    def create(self, meta: SongMeta) -> Path:
        if not _VALID_ID.match(meta.id):
            raise ValueError(f"Identificativo non valido: {meta.id!r}")
        with self._lock:
            if self.exists(meta.id):
                raise SongExists(meta.id)
            folder = self.root / meta.id
            folder.mkdir(parents=True, exist_ok=True)
            _write_json(folder / META, meta.to_dict())
            return folder

    def get(self, song_id: str) -> SongMeta:
        with self._lock:
            if not self.exists(song_id):
                raise SongNotFound(song_id)
            return SongMeta.from_dict(_read_json(self.path(song_id, META)))

    def save(self, meta: SongMeta) -> None:
        with self._lock:
            if not self.exists(meta.id):
                raise SongNotFound(meta.id)
            _write_json(self.path(meta.id, META), meta.to_dict())

    def update(self, song_id: str, **changes: Any) -> SongMeta:
        """Legge, modifica e salva in un solo passo: nessuno può infilarsi in mezzo."""
        with self._lock:
            meta = self.get(song_id)
            for name, value in changes.items():
                if not hasattr(meta, name):
                    raise AttributeError(name)
                setattr(meta, name, value)
            self.save(meta)
            return meta

    def list(self) -> list[SongMeta]:
        with self._lock:
            if not self.root.is_dir():
                return []
            metas = [self.get(p.name) for p in self.root.iterdir() if (p / META).is_file()]
        return sorted(metas, key=lambda m: m.created_at, reverse=True)

    def delete(self, song_id: str) -> None:
        with self._lock:
            if not self.exists(song_id):
                raise SongNotFound(song_id)
            shutil.rmtree(self.root / song_id)

    # --- stato dei passi -----------------------------------------------

    def set_stage(self, song_id: str, stage: str, status: str,
                  error: str | None = None, detail: str | None = None) -> None:
        with self._lock:
            meta = self.get(song_id)
            meta.stages[stage] = StageState(status=status, error=error, detail=detail)  # type: ignore[arg-type]
            self.save(meta)

    def reset_interrupted(self) -> int:
        """I passi rimasti "in corso" dopo una chiusura diventano errori riprovabili."""
        count = 0
        with self._lock:
            for meta in self.list():
                changed = False
                for state in meta.stages.values():
                    if state.status == "running":
                        state.status, state.error, state.detail = "error", INTERRUPTED, None
                        changed = True
                        count += 1
                if changed:
                    self.save(meta)
        return count

    # --- risultati della pipeline --------------------------------------

    def write_pitch(self, song_id: str, curve: PitchCurve) -> None:
        midi = [None if math.isnan(v) else round(float(v), 3) for v in curve.midi]
        times = [round(float(t), 4) for t in curve.times]
        _write_json(self.path(song_id, PITCH), {"times": times, "midi": midi})

    def read_pitch(self, song_id: str) -> PitchCurve:
        data = _read_json(self.path(song_id, PITCH))
        midi = np.array([np.nan if v is None else v for v in data["midi"]], dtype=float)
        return PitchCurve(np.array(data["times"], dtype=float), midi)

    def write_notes(self, song_id: str, notes: list[Note], name: str = NOTES) -> None:
        _write_json(self.path(song_id, name), notes_to_dict(notes))

    def read_notes(self, song_id: str, name: str = NOTES) -> list[Note]:
        return [Note(**n) for n in _read_json(self.path(song_id, name))["notes"]]

    def write_lyrics(self, song_id: str, lines: list[LyricLine]) -> None:
        _write_json(self.path(song_id, LYRICS), lines_to_dict(lines))

    def read_lyrics(self, song_id: str) -> list[LyricLine]:
        lines = []
        for raw in _read_json(self.path(song_id, LYRICS))["lines"]:
            words = None if raw["words"] is None else [Word(**w) for w in raw["words"]]
            lines.append(LyricLine(raw["start"], raw["end"], raw["text"], words))
        return lines

    # --- punteggi ------------------------------------------------------

    def read_scores(self, song_id: str) -> dict[str, Any]:
        path = self.path(song_id, SCORES)
        return _read_json(path) if path.is_file() else {}

    def record_score(self, song_id: str, difficulty: str, score: int,
                     accuracy: float, stars: int) -> dict[str, Any]:
        """Tiene solo il risultato migliore per ogni difficoltà."""
        with self._lock:
            if not self.exists(song_id):
                raise SongNotFound(song_id)
            scores = self.read_scores(song_id)
            best = scores.get(difficulty)
            if best is None or score > best["score"]:
                scores[difficulty] = {
                    "score": score, "accuracy": accuracy, "stars": stars,
                    "date": datetime.now(timezone.utc).isoformat(),
                }
                _write_json(self.path(song_id, SCORES), scores)
            return scores
