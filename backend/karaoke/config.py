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
WHISPER_EMPTY_RUN = 3               # parole a durata zero vicine oltre le quali Whisper sta girando a vuoto
# Testo scritto messo sui tempi della voce (vedi pipeline/align.py). Soglie tarate sui quattro brani della prova.
ALIGN_MIN_ANCHOR_RUN = 3            # parole di fila uguali tra testo scritto e trascritto perché valgano come ancora
ALIGN_MIN_HEARD_WORD_S = 0.05       # Whisper dà durata zero alle parole che ripete a vuoto
ALIGN_VOICE_MARGIN_S = 0.3          # una parola trascritta più lontana di così da ogni nota è inventata
ALIGN_WINDOW_BEFORE_S = 1.5         # quanto si allarga la finestra di una riga attorno a dove l'ha sentita Whisper
ALIGN_WINDOW_AFTER_S = 1.0
ALIGN_WINDOW_OVERLAP_S = 0.2        # quanto può sconfinare nella riga vicina
ALIGN_FIRST_WORD_GAP_S = 1.0        # buco dentro la prima parola oltre il quale l'attacco è dopo il buco
ALIGN_MAX_FIRST_WORD_S = 1.0        # una prima parola più lunga, per Whisper, ha inghiottito la pausa prima
ALIGN_MAX_EARLIER_S = 2.0           # di quanto Whisper può anticipare l'attacco trovato dall'allineatore
ALIGN_MIN_SCORE = 0.05              # sotto, l'allineatore non ha riconosciuto niente
ALIGN_MAX_BLIND_WINDOW_S = 6.0      # una riga non riconosciuta resta solo se non poteva finire più lontano di così
ALIGN_MIN_SUNG_SHARE = 0.5          # una riga che nessuno ha sentito deve cadere almeno per metà sul canto
ALIGN_MIN_LETTER_S = 0.03           # sotto questa durata per lettera la riga è stata schiacciata: non c'era posto
ALIGN_MIN_KEPT_SHARE = 0.5          # in automatico: se si ritrova meno di metà delle righe, il testo non è di questo brano

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
