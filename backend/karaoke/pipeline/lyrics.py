"""Passo 5: il testo sincronizzato riga per riga.

Prima si cerca su LRCLIB un testo già sincronizzato e scritto da persone;
se non c'è, o se non combacia con la voce, si trascrive la traccia voce con
Whisper. Senza testo si gioca lo stesso.
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
from .progress import ByteProgress, watching

log = logging.getLogger(__name__)

LRCLIB_URL = "https://lrclib.net"
USER_AGENT = "karaoke-tracciato/0.1"
WHISPER_DOWNLOAD_LABEL = "Scarico il modello di trascrizione"
LyricsSource = Literal["lrclib", "whisper", "none"]


class LyricsError(Exception):
    """La ricerca del testo si è rotta; il messaggio è in italiano e va mostrato così com'è."""


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


def lrc_mismatch(entries: list[tuple[float, str]], lines: list[LyricLine],
                 notes: list[Note]) -> str | None:
    """Perché questo testo non può essere quello di questa registrazione; None se regge.

    Chi carica i testi su LRCLIB a volte copia i tempi di un'altra versione del
    brano o li sbaglia: la durata coincide lo stesso, ma la voce racconta altro.
    """
    rushed = 0
    for (start, text), (following, _) in zip(entries, entries[1:]):
        letters = sum(1 for char in text if char.isalnum())
        if letters > (following - start) * config.LYRICS_MAX_LETTERS_PER_S:
            rushed += 1
    if rushed > config.LYRICS_MAX_RUSHED_LINES:
        return f"{rushed} righe più fitte di quanto si possa cantare"

    margin = config.LYRICS_VOICE_MARGIN_S
    total = sum(n.duration for n in notes)
    wordless = sum(n.duration for n in notes
                   if not any(line.start - margin <= n.start + n.duration / 2 <= line.end + margin
                              for line in lines))
    if total > 0 and wordless > total * config.LYRICS_MAX_WORDLESS_SHARE:
        return f"il {wordless / total:.0%} del canto cade dove il testo tace"
    return None


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
    def distance(candidate: Any, missing_duration: float | None = None) -> float | None:
        """Quanto dista la durata del candidato; None se il candidato non è utilizzabile."""
        if not isinstance(candidate, dict):
            return None
        synced = candidate.get("syncedLyrics")
        duration = candidate.get("duration")
        if duration is None:
            duration = missing_duration
        if not isinstance(synced, str) or not synced.strip():
            return None
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            return None
        gap = abs(duration - duration_s)
        return gap if gap <= tolerance else None

    try:
        exact = client.get("/api/get", headers=headers, params={
            "artist_name": artist, "track_name": title, "duration": int(round(duration_s))})
        if exact.status_code == 200:
            data = exact.json()
            # Qui la durata l'abbiamo chiesta noi: se la risposta non la ripete, vale la nostra.
            if distance(data, missing_duration=duration_s) is not None:
                return data["syncedLyrics"]
        search = client.get("/api/search", headers=headers,
                            params={"artist_name": artist, "track_name": title})
        if search.status_code != 200:
            return None
        found = search.json()
        # Il servizio è tenuto da volontari: una risposta di forma strana vale come "non trovato".
        ranked = [(gap, c) for c in (found if isinstance(found, list) else [])
                  if (gap := distance(c)) is not None]
        if not ranked:
            return None
        return min(ranked, key=lambda pair: pair[0])[1]["syncedLyrics"]
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


def _pull_in_first_word(words: list[Word]) -> list[Word]:
    """Riporta accanto alle altre una prima parola rimasta molto prima del canto.

    Whisper tende ad ancorare la prima parola all'inizio del segmento: se prima
    del canto c'è uno stacco strumentale, la riga comparirebbe con secondi di anticipo.
    """
    if len(words) < 2 or words[1].start - words[0].end <= config.WHISPER_LEFT_BEHIND_GAP_S:
        return words
    first, following = words[0], words[1]
    length = min(first.end - first.start, config.WHISPER_LEFT_BEHIND_WORD_S)
    return [Word(following.start - length, following.start, first.text), *words[1:]]


def lines_from_words(segments: list[list[Word]], max_chars: int = 48) -> list[LyricLine]:
    """Una riga per segmento; i segmenti troppo lunghi si spezzano tra due parole."""
    lines: list[LyricLine] = []
    for segment in segments:
        words = [Word(w.start, w.end, w.text.strip()) for w in segment if w.text.strip()]
        if words:
            lines.extend(_line(part) for part in _split_words(_pull_in_first_word(words), max_chars))
    return lines


_whisper: dict[str, Any] = {}


def _missing_download(root: str) -> tuple[Path, int] | None:
    """(cartella in cui arriverà il modello, byte da scaricare); None se c'è già o non si sa."""
    import huggingface_hub
    from faster_whisper import utils

    try:
        utils.download_model(config.WHISPER_MODEL, local_files_only=True, cache_dir=root)
        return None                                   # già scaricato
    except Exception:
        pass
    try:
        repo = getattr(utils, "_MODELS", {}).get(config.WHISPER_MODEL, config.WHISPER_MODEL)
        files = huggingface_hub.HfApi().model_info(repo, files_metadata=True).siblings or []
        return Path(root), sum(f.size or 0 for f in files)
    except Exception as exc:                          # senza la dimensione si scarica lo stesso
        log.info("Dimensione del modello di trascrizione non disponibile: %s", exc)
        return None


def _load_whisper(on_detail: Callable[[str], None] | None = None) -> Any:
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

    def load() -> Any:
        if torch.cuda.is_available():
            try:
                return WhisperModel(config.WHISPER_MODEL, device="cuda", compute_type="float16",
                                    download_root=root)
            except Exception as exc:  # librerie CUDA non trovate: si ripiega sulla CPU
                log.warning("Whisper su GPU non disponibile (%s): uso la CPU, sarà più lento.", exc)
        return WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8", download_root=root)

    missing = _missing_download(root) if on_detail is not None else None
    if missing is None or on_detail is None:
        model = load()
    else:
        folder, total = missing
        with watching(folder, total, ByteProgress(on_detail, WHISPER_DOWNLOAD_LABEL)):
            model = load()
    _whisper["model"] = model
    return model


def transcribe(vocals: Path, language: str | None,
               on_detail: Callable[[str], None] | None = None) -> tuple[list[LyricLine], str | None]:
    """Trascrive la traccia voce; restituisce le righe e la lingua rilevata."""
    import librosa

    model = _load_whisper(on_detail)
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
                ) -> tuple[list[LyricLine], LyricsSource, str | None, str | None]:
    """(righe, origine, lingua rilevata, nota per chi guarda). Non fallisce mai per testo assente.

    La fonte la decide `meta.lyrics_choice`; con "auto" vale LRCLIB se combacia
    con la voce, altrimenti la trascrizione. La nota spiega un esito che da
    solo non si capirebbe (LRCLIB scartato, oppure voluto ma senza il brano).

    Se la trascrizione si rompe solleva `LyricsError`: il brano si gioca
    comunque, ma il motivo deve arrivare a chi guarda, non restare in un log.
    """
    choice = meta.lyrics_choice
    if choice == "none":
        return [], "none", None, None

    note = None
    if choice in ("auto", "lrclib"):
        searchable = bool(meta.artist and meta.title and meta.duration_s)
        synced = fetch(meta.artist, meta.title, meta.duration_s) if searchable else None
        entries = parse_lrc(synced) if synced else []
        lines = lines_from_lrc(entries, notes, meta.duration_s or 0.0)
        # Il confronto con la voce serve a scegliere al posto di chi gioca: se ha scelto lui, non si fa.
        mismatch = lrc_mismatch(entries, lines, notes) if lines and choice == "auto" else None
        if lines and not mismatch:
            return lines, "lrclib", None, None
        if choice == "lrclib":
            note = ("LRCLIB non ha un testo sincronizzato per questa versione del brano" if searchable
                    else "Per cercare su LRCLIB servono artista e titolo")
            return [], "none", None, note
        if mismatch:
            log.info("Testo di LRCLIB scartato (%s): trascrivo la voce.", mismatch)
            note = f"Il testo di LRCLIB non combacia con la voce ({mismatch}): ho trascritto la voce"

    try:
        lines, language = transcribe_fn(vocals, meta.language if meta.language_user else None)
    except Exception as exc:
        reason = next((line.strip() for line in str(exc).splitlines() if line.strip()), type(exc).__name__)
        raise LyricsError(f"Trascrizione non riuscita ({reason[:200].rstrip('.')})") from exc
    return (lines, "whisper", language, note) if lines else ([], "none", language, note)
