"""Passo 5: il testo sincronizzato riga per riga.

Prima si cerca su LRCLIB un testo già sincronizzato e scritto da persone. Se
i suoi tempi non combaciano con la voce, o se LRCLIB ha solo il testo di
un'altra versione del brano, se ne tengono le parole e i tempi si ricavano
dalla voce (vedi `align`). Se il testo non c'è proprio, si trascrive la voce
con Whisper. Senza testo si gioca lo stesso.
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
from . import align
from .progress import ByteProgress, watching

log = logging.getLogger(__name__)

LRCLIB_URL = "https://lrclib.net"
USER_AGENT = "karaoke-tracciato/0.1"
WHISPER_DOWNLOAD_LABEL = "Scarico il modello di trascrizione"
LyricsSource = Literal["lrclib", "aligned", "whisper", "none"]


class LyricsError(Exception):
    """La ricerca del testo si è rotta; il messaggio è in italiano e va mostrato così com'è."""


class LrclibUnreachable(Exception):
    """LRCLIB non ha risposto: non si sa se il testo ci sia."""


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
    # Più righe di fila in un tempo in cui non si possono cantare. Si guarda a gruppi e non
    # alla riga singola: una traduzione o un coro allo stesso istante della riga principale è normale.
    group = config.LYRICS_RUSH_GROUP_LINES
    letters = [sum(1 for char in text if char.isalnum()) for _, text in entries]
    for i in range(len(entries) - group):
        span = entries[i + group][0] - entries[i][0]
        if sum(letters[i:i + group]) > span * config.LYRICS_MAX_LETTERS_PER_S:
            minutes, seconds = divmod(int(entries[i][0]), 60)
            return f"attorno a {minutes}:{seconds:02d} le righe sono troppo fitte per essere cantate"

    if not notes:
        return None
    margin = config.LYRICS_VOICE_MARGIN_S
    middles = [n.start + n.duration / 2 for n in notes]
    covered = [any(line.start - margin <= middle <= line.end + margin for line in lines) for middle in middles]
    total = sum(n.duration for n in notes)
    wordless = sum(n.duration for n, inside in zip(notes, covered) if not inside)
    if wordless > total * config.LYRICS_MAX_WORDLESS_SHARE:
        return f"il {wordless / total:.0%} del canto cade dove il testo tace"

    # Il contrario: righe che scorrono mentre nessuno canta (testo in anticipo, o di un'altra versione).
    silent = sum(1 for line in lines
                 if not any(line.start - margin <= middle <= line.end + margin for middle in middles))
    if silent > len(lines) * config.LYRICS_MAX_SILENT_LINES_SHARE:
        return f"{silent} righe su {len(lines)} cadono dove nessuno canta"
    return None


# --- LRCLIB ------------------------------------------------------------------

def fetch_lrclib(artist: str, title: str, duration_s: float,
                 client: httpx.Client | None = None) -> str | None:
    """Il testo sincronizzato della stessa versione del brano, oppure None.

    Si accetta solo se la durata coincide entro pochi secondi: la versione su
    YouTube spesso non è quella su cui il testo è stato sincronizzato.
    Se il servizio non risponde solleva `LrclibUnreachable`: "non lo so" non è "non c'è".
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
        exact = _answered(client.get("/api/get", headers=headers, params={
            "artist_name": artist, "track_name": title, "duration": int(round(duration_s))}))
        if exact.status_code == 200:
            data = exact.json()
            # Qui la durata l'abbiamo chiesta noi: se la risposta non la ripete, vale la nostra.
            if distance(data, missing_duration=duration_s) is not None:
                return data["syncedLyrics"]
        search = _answered(client.get("/api/search", headers=headers,
                                      params={"artist_name": artist, "track_name": title}))
        if search.status_code != 200:
            return None
        found = search.json()
        # Il servizio è tenuto da volontari: una risposta di forma strana vale come "non trovato".
        ranked = [(gap, c) for c in (found if isinstance(found, list) else [])
                  if (gap := distance(c)) is not None]
        if not ranked:
            return None
        return min(ranked, key=lambda pair: pair[0])[1]["syncedLyrics"]
    except httpx.HTTPError as exc:
        raise LrclibUnreachable(str(exc) or type(exc).__name__) from exc
    except ValueError as exc:                       # una risposta che non è JSON vale come "non trovato"
        log.warning("Risposta di LRCLIB illeggibile: %s", exc)
        return None
    finally:
        if own_client:
            client.close()


def _answered(response: httpx.Response) -> httpx.Response:
    if response.status_code >= 500 or response.status_code == 429:
        raise LrclibUnreachable(f"risposta {response.status_code}")
    return response


def fetch_lrclib_text(artist: str, title: str, duration_s: float,
                      client: httpx.Client | None = None) -> list[str] | None:
    """Le righe del testo del brano, di qualunque versione: quella più vicina per durata. Oppure None.

    Solo le parole: i tempi di un'altra versione non servono, si ricavano dalla voce.
    Se il servizio non risponde solleva `LrclibUnreachable`.
    """
    own_client = client is None
    client = client or httpx.Client(base_url=LRCLIB_URL, timeout=10.0)
    try:
        search = _answered(client.get("/api/search", headers={"User-Agent": USER_AGENT},
                                      params={"artist_name": artist, "track_name": title}))
        found = search.json() if search.status_code == 200 else []
    except httpx.HTTPError as exc:
        raise LrclibUnreachable(str(exc) or type(exc).__name__) from exc
    except ValueError as exc:
        log.warning("Risposta di LRCLIB illeggibile: %s", exc)
        return None
    finally:
        if own_client:
            client.close()

    def distance(candidate: dict[str, Any]) -> float:
        duration = candidate.get("duration")
        known = isinstance(duration, (int, float)) and not isinstance(duration, bool)
        return abs(duration - duration_s) if known else float("inf")

    candidates = [c for c in (found if isinstance(found, list) else []) if isinstance(c, dict)]
    for candidate in sorted(candidates, key=distance):
        synced, plain = candidate.get("syncedLyrics"), candidate.get("plainLyrics")
        lines = [text for _, text in parse_lrc(synced) if text] if isinstance(synced, str) else []
        if not lines and isinstance(plain, str):
            lines = [line.strip() for line in plain.splitlines() if line.strip()]
        if lines:
            return lines
    return None


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


def transcribe_words(vocals: Path, language: str | None, on_detail: Callable[[str], None] | None = None,
                     follow_context: bool = True) -> tuple[list[list[Word]], str | None]:
    """Le parole che Whisper sente nella traccia voce, un gruppo per segmento, e la lingua rilevata.

    Senza il suo filtro dei silenzi: è fatto per il parlato e del canto scarta frasi intere.
    Le parole inventate dove nessuno canta le toglie chi chiama, guardando le note.
    Con `follow_context` ogni tratto si trascrive sapendo che cosa è stato detto prima.
    """
    import librosa

    model = _load_whisper(on_detail)
    # L'audio si decodifica qui: il decoder interno di faster-whisper 1.2 non è
    # compatibile con le versioni recenti di PyAV.
    audio, _ = librosa.load(str(vocals), sr=16000, mono=True)
    segments, info = model.transcribe(audio, language=language, word_timestamps=True, vad_filter=False,
                                      condition_on_previous_text=follow_context)
    grouped = [[Word(float(w.start), float(w.end), w.word) for w in (segment.words or [])]
               for segment in segments]
    return grouped, getattr(info, "language", None)


def _sung_words(grouped: list[list[Word]], notes: list[Note]) -> list[list[Word]]:
    """Toglie le parole che Whisper si è inventato: dove nessuno canta, o ripetute a vuoto.

    Quando gira a vuoto ripete una frase già detta dando a ogni parola durata zero.
    Senza note (non dovrebbe succedere: senza note non c'è brano) non si toglie niente.
    """
    def empty(word: Word) -> bool:
        return word.end - word.start < config.ALIGN_MIN_HEARD_WORD_S

    def sung(word: Word) -> bool:
        low, high = word.start - config.ALIGN_VOICE_MARGIN_S, word.end + config.ALIGN_VOICE_MARGIN_S
        return not notes or any(note.start < high and note.start + note.duration > low for note in notes)

    kept = []
    for segment in grouped:
        words = [word for i, word in enumerate(segment) if sung(word) and not (
            empty(word) and sum(1 for near in segment[max(0, i - 2): i + 3] if empty(near)) >= config.WHISPER_EMPTY_RUN)]
        if words:
            kept.append(words)
    return kept


def transcribe(vocals: Path, language: str | None, notes: list[Note],
               on_detail: Callable[[str], None] | None = None) -> tuple[list[LyricLine], str | None]:
    """Trascrive la traccia voce; restituisce le righe e la lingua rilevata.

    Le parole sono di Whisper. I tempi no, dove si può: sul canto li sbaglia (attacca la
    pausa alla parola che segue), quindi li rifinisce l'allineatore, riga per riga, attorno
    a dove Whisper ha sentito le parole.
    """
    import librosa

    # Senza contesto: sul canto, sapere che cosa è stato detto prima lo fa a volte girare a
    # vuoto o saltare strofe intere, e ogni giro dà un risultato diverso.
    grouped, detected = transcribe_words(vocals, language, on_detail, follow_context=False)
    lines = lines_from_words(_sung_words(grouped, notes))
    if not lines:
        return lines, detected
    try:
        audio, _ = librosa.load(str(vocals), sr=align.SAMPLE_RATE, mono=True)
        refined, _ = align.place_lines([line.text for line in lines],
                                       [word for line in lines for word in line.words or []], notes,
                                       len(audio) / align.SAMPLE_RATE, align.VoiceAligner(audio, on_detail))
    except Exception as exc:                # senza allineatore il testo c'è lo stesso, con i tempi di Whisper
        log.warning("Tempi della trascrizione non rifiniti (%s): restano quelli di Whisper.", exc)
        return lines, detected
    return refined or lines, detected


def align_to_voice(text: list[str], vocals: Path, notes: list[Note], language: str | None,
                   on_detail: Callable[[str], None] | None = None) -> tuple[list[LyricLine], int, str | None]:
    """Mette `text` sui tempi della voce: (righe, quante non si sono ritrovate, lingua rilevata)."""
    import librosa

    # Qui Whisper serve solo a dire all'incirca dove cade ogni riga: le parole inventate
    # dove nessuno canta le toglie `place_lines`.
    grouped, detected = transcribe_words(vocals, language, on_detail)
    heard = [word for segment in grouped for word in segment]
    audio, _ = librosa.load(str(vocals), sr=align.SAMPLE_RATE, mono=True)
    lines, lost = align.place_lines(text, heard, notes, len(audio) / align.SAMPLE_RATE,
                                    align.VoiceAligner(audio, on_detail))
    return lines, lost, detected


# --- scelta della fonte ------------------------------------------------------

AlignFn = Callable[[list[str], Path, list[Note], str | None], tuple[list[LyricLine], int, str | None]]
UNREACHABLE = "LRCLIB non è raggiungibile: riprova più tardi"


def _reason(exc: Exception) -> str:
    """La prima riga dell'errore, corta abbastanza da stare nella schermata."""
    first = next((line.strip() for line in str(exc).splitlines() if line.strip()), type(exc).__name__)
    return first[:200].rstrip(".")


def _lost_note(lost: int) -> str:
    return ("1 riga del testo non si ritrova nella voce" if lost == 1
            else f"{lost} righe del testo non si ritrovano nella voce")


def find_lyrics(meta: SongMeta, vocals: Path, notes: list[Note],
                fetch: Callable[..., str | None] = fetch_lrclib,
                transcribe_fn: Callable[[Path, str | None, list[Note]], tuple[list[LyricLine], str | None]] = transcribe,
                fetch_text: Callable[..., list[str] | None] = fetch_lrclib_text,
                align_fn: AlignFn = align_to_voice,
                ) -> tuple[list[LyricLine], LyricsSource, str | None, str | None]:
    """(righe, origine, lingua rilevata, nota per chi guarda). Non fallisce mai per testo assente.

    La fonte la decide `meta.lyrics_choice`. Con "auto" vale LRCLIB se combacia con la
    voce; se non combacia, o se LRCLIB ha solo un'altra versione del brano, le sue parole
    si allineano alla voce; se nemmeno così si trova un testo, si trascrive. La nota spiega
    un esito che da solo non si capirebbe (LRCLIB scartato, righe non ritrovate, brano assente).

    Se la trascrizione o l'allineamento voluto si rompono solleva `LyricsError`: il brano
    si gioca comunque, ma il motivo deve arrivare a chi guarda, non restare in un log.
    """
    choice = meta.lyrics_choice
    if choice == "none":
        return [], "none", None, None
    language = meta.language if meta.language_user else None
    searchable = bool(meta.artist and meta.title and meta.duration_s)

    note = None                              # perché, alla fine, si è trascritta la voce
    if choice != "whisper":
        text: list[str] | None = None        # le parole da mettere sui tempi di questa registrazione
        mismatch = None
        reachable = True
        if choice in ("auto", "lrclib"):
            try:
                synced = fetch(meta.artist, meta.title, meta.duration_s) if searchable else None
            except LrclibUnreachable as exc:
                log.warning("LRCLIB non raggiungibile: %s", exc)
                if choice == "lrclib":
                    # Un errore lascia il testo che c'era: senza risposta non si sa se LRCLIB ne abbia uno.
                    raise LyricsError(UNREACHABLE) from exc
                synced, reachable = None, False
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
                log.info("Testo di LRCLIB scartato (%s): ne allineo le parole alla voce.", mismatch)
                text = [line for _, line in entries if line]

        if text is None and searchable and reachable:
            try:
                text = fetch_text(meta.artist, meta.title, meta.duration_s)
            except LrclibUnreachable as exc:
                log.warning("LRCLIB non raggiungibile: %s", exc)
                if choice == "aligned":
                    raise LyricsError(UNREACHABLE) from exc
        if text:
            try:
                lines, lost, detected = align_fn(text, vocals, notes, language)
            except Exception as exc:
                if choice == "aligned":
                    raise LyricsError(f"Allineamento non riuscito ({_reason(exc)})") from exc
                log.warning("Allineamento non riuscito (%s): trascrivo la voce.", exc)
                lines, lost, detected = [], 0, None
            # In automatico il testo deve ritrovarsi per buona parte: se no è di un altro brano,
            # o la voce non si capisce, ed è meglio la trascrizione.
            if lines and (choice == "aligned" or len(lines) >= len(text) * config.ALIGN_MIN_KEPT_SHARE):
                why = (f"Il testo di LRCLIB non combacia con la voce ({mismatch})" if mismatch
                       else "LRCLIB ha il testo di un'altra versione del brano" if choice == "auto" else None)
                parts = ([f"{why}: l'ho allineato alla voce"] if why else []) + ([_lost_note(lost)] if lost else [])
                return lines, "aligned", detected, "; ".join(parts) or None
        if choice == "aligned":
            note = ("Per cercare su LRCLIB servono artista e titolo" if not searchable
                    else "Il testo di LRCLIB non si ritrova nella voce" if text
                    else "LRCLIB non ha un testo per questo brano")
            return [], "none", None, note
        if mismatch:
            note = f"Il testo di LRCLIB non combacia con la voce ({mismatch}): ho trascritto la voce"
        elif text:
            note = "Il testo di LRCLIB non si ritrova nella voce: ho trascritto la voce"

    try:
        lines, detected = transcribe_fn(vocals, language, notes)
    except Exception as exc:
        raise LyricsError(f"Trascrizione non riuscita ({_reason(exc)})") from exc
    return (lines, "whisper", detected, note) if lines else ([], "none", detected, note)
