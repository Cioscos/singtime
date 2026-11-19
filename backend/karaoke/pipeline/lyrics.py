"""Passo 5: il testo sincronizzato riga per riga.

Prima si cerca su LRCLIB un testo già sincronizzato e scritto da persone;
se non c'è, si trascrive la traccia voce con Whisper. Senza testo si gioca lo stesso.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Literal

import httpx

from .. import config
from ..models import LyricLine, Note, SongMeta, Word

log = logging.getLogger(__name__)

LRCLIB_URL = "https://lrclib.net"
USER_AGENT = "karaoke-tracciato/0.1"
LyricsSource = Literal["lrclib", "whisper", "none"]

# --- formato LRC -------------------------------------------------------------

_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """Coppie (secondi, testo) ordinate per tempo; le righe vuote restano come (tempo, "")."""
    entries: list[tuple[float, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        stamps = []
        while (match := _LRC_TIME.match(line)) is not None:
            seconds = float(match.group(2).replace(":", "."))
            stamps.append(round(int(match.group(1)) * 60 + seconds, 3))
            line = line[match.end():].lstrip()
        entries.extend((stamp, line) for stamp in stamps)
    return sorted(entries, key=lambda entry: entry[0])


def lines_from_lrc(entries: list[tuple[float, str]], notes: list[Note],
                   duration_s: float) -> list[LyricLine]:
    """Ogni riga finisce con l'ultima nota cantata prima della riga successiva."""
    lines: list[LyricLine] = []
    for i, (start, text) in enumerate(entries):
        if not text:
            continue
        limit = entries[i + 1][0] if i + 1 < len(entries) else max(duration_s, start)
        ends = [n.start + n.duration for n in notes if start <= n.start < limit]
        end = min(max(ends), limit) if ends else limit
        lines.append(LyricLine(start=start, end=max(end, start), text=text, words=None))
    return lines


# --- LRCLIB ------------------------------------------------------------------

def fetch_lrclib(artist: str, title: str, duration_s: float,
                 client: httpx.Client | None = None) -> str | None:
    """Il testo sincronizzato della stessa versione del brano, oppure None.

    Si accetta solo se la durata coincide entro pochi secondi: la versione su
    YouTube spesso non è quella su cui il testo è stato sincronizzato.
    Non solleva mai per errori di rete.
    """
    own_client = client is None
    client = client or httpx.Client(base_url=LRCLIB_URL, timeout=10.0)
    headers = {"User-Agent": USER_AGENT}
    tolerance = config.LYRICS_DURATION_TOLERANCE_S
    try:
        exact = client.get("/api/get", headers=headers, params={
            "artist_name": artist, "track_name": title, "duration": int(round(duration_s))})
        if exact.status_code == 200:
            data = exact.json()
            if data.get("syncedLyrics") and abs((data.get("duration") or duration_s) - duration_s) <= tolerance:
                return data["syncedLyrics"]
        search = client.get("/api/search", headers=headers,
                            params={"artist_name": artist, "track_name": title})
        if search.status_code != 200:
            return None
        candidates = [c for c in search.json()
                      if c.get("syncedLyrics") and c.get("duration") is not None
                      and abs(c["duration"] - duration_s) <= tolerance]
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs(c["duration"] - duration_s))["syncedLyrics"]
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("LRCLIB non raggiungibile: %s", exc)
        return None
    finally:
        if own_client:
            client.close()


# --- Whisper -----------------------------------------------------------------

def _line(words: list[Word]) -> LyricLine:
    return LyricLine(start=words[0].start, end=words[-1].end,
                     text=" ".join(w.text for w in words), words=list(words))


def _split_words(words: list[Word], max_chars: int) -> list[list[Word]]:
    text_length = sum(len(w.text) for w in words) + len(words) - 1
    if len(words) < 2 or text_length <= max_chars:
        return [words]
    middle = len(words) / 2
    # Si spezza alla pausa più lunga; a parità, quella più vicina al centro.
    cut = max(range(1, len(words)),
              key=lambda i: (words[i].start - words[i - 1].end, -abs(i - middle)))
    return _split_words(words[:cut], max_chars) + _split_words(words[cut:], max_chars)


def lines_from_words(segments: list[list[Word]], max_chars: int = 48) -> list[LyricLine]:
    """Una riga per segmento; i segmenti troppo lunghi si spezzano tra due parole."""
    lines: list[LyricLine] = []
    for segment in segments:
        words = [Word(w.start, w.end, w.text.strip()) for w in segment if w.text.strip()]
        if words:
            lines.extend(_line(part) for part in _split_words(words, max_chars))
    return lines


_whisper: dict[str, Any] = {}


def _load_whisper() -> Any:
    if "model" in _whisper:
        return _whisper["model"]
    import torch

    if sys.platform == "win32":
        # ctranslate2 cerca cuBLAS e cuDNN: sono già dentro PyTorch.
        torch_lib = Path(torch.__file__).parent / "lib"
        if torch_lib.is_dir():
            os.add_dll_directory(str(torch_lib))
            os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ.get("PATH", "")
    from faster_whisper import WhisperModel

    root = str(config.models_dir() / "whisper")
    model = None
    if torch.cuda.is_available():
        try:
            model = WhisperModel(config.WHISPER_MODEL, device="cuda", compute_type="float16",
                                 download_root=root)
        except Exception as exc:  # librerie CUDA non trovate: si ripiega sulla CPU
            log.warning("Whisper su GPU non disponibile (%s): uso la CPU, sarà più lento.", exc)
    if model is None:
        model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8",
                             download_root=root)
    _whisper["model"] = model
    return model


def transcribe(vocals: Path, language: str | None) -> tuple[list[LyricLine], str | None]:
    """Trascrive la traccia voce; restituisce le righe e la lingua rilevata."""
    import librosa

    model = _load_whisper()
    # L'audio si decodifica qui: il decoder interno di faster-whisper 1.2 non è
    # compatibile con le versioni recenti di PyAV.
    audio, _ = librosa.load(str(vocals), sr=16000, mono=True)
    segments, info = model.transcribe(audio, language=language,
                                      word_timestamps=True, vad_filter=True)
    grouped = [[Word(float(w.start), float(w.end), w.word) for w in (segment.words or [])]
               for segment in segments]
    return lines_from_words(grouped), getattr(info, "language", None)


# --- scelta della fonte ------------------------------------------------------

def find_lyrics(meta: SongMeta, vocals: Path, notes: list[Note],
                fetch: Callable[..., str | None] = fetch_lrclib,
                transcribe_fn: Callable[[Path, str | None], tuple[list[LyricLine], str | None]] = transcribe,
                ) -> tuple[list[LyricLine], LyricsSource, str | None]:
    """(righe, origine, lingua rilevata). Non fallisce mai per testo assente."""
    if meta.artist and meta.title and meta.duration_s:
        synced = fetch(meta.artist, meta.title, meta.duration_s)
        if synced:
            lines = lines_from_lrc(parse_lrc(synced), notes, meta.duration_s)
            if lines:
                return lines, "lrclib", None
    try:
        lines, language = transcribe_fn(vocals, meta.language if meta.language_user else None)
    except Exception as exc:
        log.warning("Trascrizione non riuscita: %s", exc)
        return [], "none", None
    return (lines, "whisper", language) if lines else ([], "none", language)
