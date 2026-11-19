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
PITCH_TRACKER = "fcpe"
PITCH_CANDIDATES = ["swiftf0", "fcpe"]

# Testo.
WHISPER_MODEL = "large-v3"
LYRICS_DURATION_TOLERANCE_S = 3.0
# Quando il testo trovato in rete non è quello di questa registrazione (vedi lyrics.lrc_mismatch).
LYRICS_MAX_LETTERS_PER_S = 30.0     # il rap più fitto della prova arriva a 20
LYRICS_RUSH_GROUP_LINES = 3         # righe di fila su cui si misura: una riga doppia o una svista non contano
LYRICS_VOICE_MARGIN_S = 0.75
LYRICS_MAX_WORDLESS_SHARE = 0.15    # quota del canto che può cadere fuori dalle righe
LYRICS_MAX_SILENT_LINES_SHARE = 0.25  # quota delle righe che possono cadere dove nessuno canta
# Una prima parola trascritta così tanto prima della seconda è rimasta indietro (vedi lyrics._pull_in_first_word).
WHISPER_LEFT_BEHIND_GAP_S = 2.5     # nella prova le pause vere arrivano a 2,1 s, quelle false partono da 2,8
WHISPER_LEFT_BEHIND_WORD_S = 0.6

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
