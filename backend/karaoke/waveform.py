"""Il profilo di volume di una traccia, per disegnarla nell'editor del testo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

# Un valore ogni centesimo di secondo: basta a vedere dove attacca una parola.
PEAKS_PER_S = 100
_BLOCK_S = 10


def peaks(path: Path, rate: int = PEAKS_PER_S) -> dict[str, Any]:
    """Il picco di ogni finestra, da 0 a 255 rispetto al punto più forte della traccia."""
    values: list[np.ndarray] = []
    with sf.SoundFile(str(path)) as audio:
        window = max(1, round(audio.samplerate / rate))
        # Blocchi multipli della finestra: la traccia intera non sta mai in memoria.
        for block in audio.blocks(blocksize=window * rate * _BLOCK_S, dtype="float32", always_2d=True):
            mono = np.abs(block).max(axis=1)
            missing = -len(mono) % window
            if missing:
                mono = np.pad(mono, (0, missing))
            values.append(mono.reshape(-1, window).max(axis=1))
    levels = np.concatenate(values) if values else np.zeros(0, dtype=np.float32)
    top = float(levels.max()) if len(levels) else 0.0
    scaled = np.round(levels / top * 255) if top > 0 else np.zeros(len(levels))
    return {"rate": rate, "peaks": scaled.astype(int).tolist()}
