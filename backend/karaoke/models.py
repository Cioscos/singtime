"""Strutture dati condivise tra pipeline, libreria e API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np

STAGES = ("acquire", "separate", "pitch", "notes", "lyrics")
PLAYABLE_STAGES = ("acquire", "separate", "pitch", "notes")

StageStatus = Literal["pending", "running", "done", "error"]
# "aligned": le parole di LRCLIB (di qualunque versione) messe sui tempi di questa registrazione.
LyricsChoice = Literal["auto", "lrclib", "aligned", "whisper", "none"]
# Da dove viene il testo che c'è adesso; "manual" è quello scritto da chi gioca.
LyricsOrigin = Literal["lrclib", "aligned", "whisper", "manual", "none"]


@dataclass
class StageState:
    status: StageStatus = "pending"
    error: str | None = None
    detail: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_stages() -> dict[str, StageState]:
    return {name: StageState() for name in STAGES}


@dataclass
class SongMeta:
    id: str
    title: str
    artist: str
    duration_s: float | None
    source_kind: Literal["youtube", "file"]
    source_ref: str
    separator_model: str
    pitch_tracker: str
    language: str | None = None
    language_user: bool = False
    lyrics_source: LyricsOrigin | None = None
    # Da dove chi gioca vuole il testo; "auto" lascia decidere al confronto con la voce.
    lyrics_choice: LyricsChoice = "auto"
    # Che cosa c'è da sapere sull'ultima ricerca del testo (per esempio perché LRCLIB è stato scartato).
    lyrics_note: str | None = None
    lyrics_offset_s: float = 0.0
    created_at: str = field(default_factory=_now)
    stages: dict[str, StageState] = field(default_factory=_fresh_stages)

    @property
    def playable(self) -> bool:
        """Si può giocare quando esistono le note; il testo è facoltativo."""
        return all(self.stages[s].status == "done" for s in PLAYABLE_STAGES)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SongMeta:
        data = dict(data)
        stages = _fresh_stages()
        for name, state in (data.pop("stages", None) or {}).items():
            if name in stages:
                stages[name] = StageState(**state)
        return cls(**data, stages=stages)


@dataclass
class Note:
    """Una barra: inizio e durata in secondi, altezza in semitoni MIDI con decimali."""

    start: float
    duration: float
    pitch: float


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class LyricLine:
    start: float
    end: float
    text: str
    words: list[Word] | None


@dataclass
class PitchCurve:
    """Altezza della voce nel tempo; `midi` vale NaN dove non c'è voce."""

    times: np.ndarray
    midi: np.ndarray
