"""Percorsi, modelli predefiniti e costanti del progetto."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

HOST = "127.0.0.1"
PORT = 8765

# Separazione della voce (nomi dei modelli di audio-separator).
SEPARATOR_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
SEPARATOR_CANDIDATES = [SEPARATOR_MODEL, "vocals_mel_band_roformer.ckpt", "htdemucs_ft.yaml"]

# Curva di altezza.
PITCH_TRACKER = "swiftf0"
PITCH_CANDIDATES = ["swiftf0", "fcpe"]

# Testo.
WHISPER_MODEL = "large-v3"
LYRICS_DURATION_TOLERANCE_S = 3.0

# Limiti.
MAX_DURATION_S = 900
MIN_NOTES = 5


def data_dir() -> Path:
    """Cartella dei dati; si legge l'ambiente a ogni chiamata."""
    override = os.environ.get("KARAOKE_DATA_DIR")
    return Path(override) if override else REPO_ROOT / "data"


def library_dir() -> Path:
    return data_dir() / "library"


def models_dir() -> Path:
    return data_dir() / "models"
