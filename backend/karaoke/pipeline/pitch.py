"""Passo 3: dalla traccia voce alla curva di altezza nel tempo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..models import PitchCurve

# Estensione utile per una voce cantata, in Hz.
F0_MIN = 65.0
F0_MAX = 1100.0

_FCPE_SR = 16000
_FCPE_HOP = 160  # 10 ms

# Un'istanza per tracker, tenuta in memoria tra un brano e l'altro.
_models: dict[str, Any] = {}


def hz_to_midi(hz: np.ndarray) -> np.ndarray:
    return 69.0 + 12.0 * np.log2(np.asarray(hz, dtype=float) / 440.0)


def _swiftf0(vocals: Path) -> PitchCurve:
    from swift_f0 import SwiftF0

    model = _models.get("swiftf0")
    if model is None:
        model = _models["swiftf0"] = SwiftF0()
    result = model.detect_file(str(vocals), fmin=F0_MIN, fmax=F0_MAX)
    hz = np.asarray(result.pitch_hz, dtype=float)
    voiced = (np.asarray(result.confidence) >= 0.5) & (hz > 0)
    midi = np.full(len(hz), np.nan)
    midi[voiced] = hz_to_midi(hz[voiced])
    return PitchCurve(np.asarray(result.timestamps, dtype=float), midi)


def _fcpe(vocals: Path) -> PitchCurve:
    import librosa
    import torch
    from torchfcpe import spawn_bundled_infer_model

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = _models.get("fcpe")
    if model is None:
        model = _models["fcpe"] = spawn_bundled_infer_model(device=device)
    audio, _ = librosa.load(str(vocals), sr=_FCPE_SR, mono=True)
    frames = len(audio) // _FCPE_HOP + 1
    tensor = torch.from_numpy(audio).float().unsqueeze(0).unsqueeze(-1).to(device)
    with torch.no_grad():
        f0 = model.infer(tensor, sr=_FCPE_SR, decoder_mode="local_argmax", threshold=0.006,
                         f0_min=F0_MIN, f0_max=F0_MAX, interp_uv=False,
                         output_interp_target_length=frames)
    hz = f0.squeeze().detach().cpu().numpy().astype(float).reshape(-1)
    midi = np.full(len(hz), np.nan)
    voiced = hz > 0
    midi[voiced] = hz_to_midi(hz[voiced])
    return PitchCurve(np.arange(len(hz)) * (_FCPE_HOP / _FCPE_SR), midi)


_TRACKERS = {"swiftf0": _swiftf0, "fcpe": _fcpe}


def track_pitch(vocals: Path, tracker: str) -> PitchCurve:
    """Curva di altezza della traccia voce; `midi` è NaN dove non c'è voce."""
    if tracker not in _TRACKERS:
        raise ValueError(f"Tracker sconosciuto: {tracker}")
    return _TRACKERS[tracker](vocals)
