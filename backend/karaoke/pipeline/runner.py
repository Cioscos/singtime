"""Esegue i cinque passi in ordine e riprende da quello fallito."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import soundfile as sf

from .. import config
from ..library import META, SOURCE, VOCALS, Library
from ..models import STAGES, Note
from . import acquire, lyrics, pitch, separate
from .notes import load_note_params, segment_notes

log = logging.getLogger(__name__)

NO_VOICE = "Nessuna voce trovata"
TRANSCRIBE_NOTICE = "Trascrivo il testo (la prima volta scarico i modelli)…"
ALIGN_NOTICE = "Allineo il testo alla voce (la prima volta scarico i modelli)…"


class NoVoiceError(Exception):
    """Il brano non contiene abbastanza voce per ricavarne un tracciato."""


StageFn = Callable[[Library, str], None]


# --- i passi reali -----------------------------------------------------------

def stage_acquire(library: Library, song_id: str) -> None:
    meta = library.get(song_id)
    folder = library.path(song_id, META).parent
    source = library.path(song_id, SOURCE)
    if meta.source_kind == "youtube":
        original: Path | None = acquire.download_audio(meta.source_ref, folder)
    else:
        uploads = sorted(folder.glob("upload.*"))
        original = uploads[0] if uploads else None
    if original is not None:
        duration = acquire.normalize_audio(original, source)
        original.unlink(missing_ok=True)
    elif source.is_file():
        duration = float(sf.info(str(source)).duration)  # già convertito in un giro precedente
    else:
        raise acquire.AcquireError("Il file originale non c'è più: aggiungi di nuovo il brano.")
    library.update(song_id, duration_s=duration)


def stage_separate(library: Library, song_id: str) -> None:
    meta = library.get(song_id)
    separate.separate(
        library.path(song_id, SOURCE), library.path(song_id, META).parent,
        meta.separator_model, config.models_dir(),
        on_detail=lambda text: library.set_stage(song_id, "separate", "running", detail=text))


def stage_pitch(library: Library, song_id: str) -> None:
    meta = library.get(song_id)
    library.write_pitch(song_id, pitch.track_pitch(library.path(song_id, VOCALS), meta.pitch_tracker))


def stage_notes(library: Library, song_id: str) -> None:
    notes = segment_notes(library.read_pitch(song_id), load_note_params())
    if len(notes) < config.MIN_NOTES:
        raise NoVoiceError(NO_VOICE)
    library.write_notes(song_id, notes)


def stage_lyrics(library: Library, song_id: str) -> None:
    meta = library.get(song_id)

    def detail(text: str) -> None:
        library.set_stage(song_id, "lyrics", "running", detail=text)

    def transcribing(vocals: Path, language: str | None, notes: list[Note]):
        detail(TRANSCRIBE_NOTICE)
        return lyrics.transcribe(vocals, language, notes, on_detail=detail)

    def aligning(text: list[str], vocals: Path, notes: list[Note], language: str | None):
        detail(ALIGN_NOTICE)
        return lyrics.align_to_voice(text, vocals, notes, language, on_detail=detail)

    lines, source, language, note = lyrics.find_lyrics(
        meta, library.path(song_id, VOCALS), library.read_notes(song_id),
        transcribe_fn=transcribing, align_fn=aligning)
    library.write_lyrics(song_id, lines)
    changes: dict[str, object] = {"lyrics_source": source, "lyrics_note": note}
    # Si rilegge: la lingua può essere stata scelta a mano mentre Whisper lavorava.
    if language and not library.get(song_id).language_user:
        changes["language"] = language
    library.update(song_id, **changes)


DEFAULT_STAGES: dict[str, StageFn] = {
    "acquire": stage_acquire,
    "separate": stage_separate,
    "pitch": stage_pitch,
    "notes": stage_notes,
    "lyrics": stage_lyrics,
}


# --- esecuzione --------------------------------------------------------------

class Pipeline:
    def __init__(self, library: Library, stages: dict[str, StageFn] | None = None):
        self.library = library
        self.stages = DEFAULT_STAGES if stages is None else stages

    def run(self, song_id: str, from_stage: str | None = None) -> bool:
        """Esegue i passi mancanti; vero se sono riusciti tutti.

        Senza `from_stage` riparte dal primo passo non completato; con
        `from_stage` rifà quel passo e tutti i successivi.
        """
        meta = self.library.get(song_id)
        if from_stage is not None:
            first = STAGES.index(from_stage)
            for stage in STAGES[first:]:
                self.library.set_stage(song_id, stage, "pending")
        else:
            pending = [i for i, s in enumerate(STAGES) if meta.stages[s].status != "done"]
            if not pending:
                return True
            first = pending[0]

        for stage in STAGES[first:]:
            self.library.set_stage(song_id, stage, "running")
            try:
                self.stages[stage](self.library, song_id)
            except Exception as exc:
                log.exception("Passo %s fallito per %s", stage, song_id)
                self.library.set_stage(song_id, stage, "error", error=str(exc) or type(exc).__name__)
                return False
            self.library.set_stage(song_id, stage, "done")
        return True
