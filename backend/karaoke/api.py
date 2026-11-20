"""L'API locale: libreria, coda di elaborazione, file per il gioco, impostazioni."""

from __future__ import annotations

import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, waveform
from .fileio import read_json, write_json
from .jobs import JobQueue
from .library import (
    INSTRUMENTAL, LYRICS, NOTES, NOTES_SWIFTF0, PITCH, SOURCE, VOCALS, WAVEFORM, Library, SongNotFound,
    lines_to_dict, notes_to_dict,
)
from .models import STAGES, LyricLine, LyricsChoice, SongMeta, Word
from .pipeline import acquire, separate
from .pipeline.notes import NoteParams, load_note_params, save_note_params, segment_notes

SETTINGS_FILE = "settings.json"
AUDIO_FILES = {"vocals": VOCALS, "instrumental": INSTRUMENTAL, "source": SOURCE}
BUSY = "Il brano è in elaborazione: attendi che finisca."
NO_CACHE = {"Cache-Control": "no-store"}
# Il server serve solo questa macchina: si accettano richieste rivolte a questi
# nomi e provenienti da pagine servite da questi nomi (qualunque porta).
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})


class Settings(BaseModel):
    mic_device_id: str | None = None
    latency_ms: float = 0
    calibrated: bool = False
    guide_volume: float = Field(0.3, ge=0, le=1)
    difficulty: Literal["easy", "normal", "hard"] = "normal"


class UrlBody(BaseModel):
    url: str


class SongPatch(BaseModel):
    title: str | None = None
    artist: str | None = None
    language: str | None = None
    lyrics_offset_s: float | None = None
    lyrics_choice: LyricsChoice | None = None


class RetryBody(BaseModel):
    from_stage: str | None = None


class WordBody(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class LineBody(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    words: list[WordBody] | None = None


class LyricsBody(BaseModel):
    lines: list[LineBody]


def _edited_lines(body: LyricsBody) -> list[LyricLine]:
    """Le righe scritte a mano, controllate; solleva ValueError con il motivo se non reggono."""
    lines: list[LyricLine] = []
    for number, raw in enumerate(body.lines, start=1):
        text = " ".join(raw.text.split())
        if not text:
            raise ValueError(f"La riga {number} è vuota")
        if raw.end < raw.start:
            raise ValueError(f"La riga {number} finisce prima di cominciare")
        if lines and raw.start < lines[-1].start:
            raise ValueError(f"La riga {number} comincia prima della precedente")
        words = None
        if raw.words:
            words = [Word(round(w.start, 3), round(w.end, 3), w.text.strip()) for w in raw.words]
            broken = any(not w.text or w.end < w.start for w in words) or any(
                later.start < earlier.start for earlier, later in zip(words, words[1:]))
            if broken:
                raise ValueError(f"I tempi delle parole della riga {number} non sono in ordine")
        lines.append(LyricLine(round(raw.start, 3), round(raw.end, 3), text, words))
    return lines


class ScoreBody(BaseModel):
    difficulty: Literal["easy", "normal", "hard"]
    score: int
    accuracy: float
    stars: int


class NoteParamsBody(BaseModel):
    min_note_s: float = Field(gt=0, le=2)
    max_gap_s: float = Field(ge=0, le=2)
    vibrato_window_s: float = Field(gt=0, le=2)
    split_semitones: float = Field(gt=0, le=12)
    settle_s: float = Field(gt=0, le=2)
    merge_semitones: float = Field(ge=0, le=12)
    glide_window_s: float = Field(NoteParams().glide_window_s, gt=0, le=2)


def _load_settings() -> Settings:
    path = config.data_dir() / SETTINGS_FILE
    if not path.is_file():
        return Settings()
    return Settings(**read_json(path))


def _save_settings(settings: Settings) -> None:
    write_json(config.data_dir() / SETTINGS_FILE, settings.model_dump())


def create_app(library: Library, jobs: JobQueue,
               probe: Callable[[str], acquire.UrlInfo] = acquire.probe_url,
               static_dir: Path | None = None) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Passi rimasti "in corso" da una chiusura precedente: diventano riprovabili.
        library.reset_interrupted()
        yield

    app = FastAPI(title="Karaoke a tracciato", lifespan=lifespan)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Una pagina web qualsiasi aperta nel browser non deve poter usare questo server.
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        origin = request.headers.get("origin")
        origin_host = (urlparse(origin).hostname or "") if origin else None
        if host not in LOCAL_HOSTS or (origin_host is not None and origin_host not in LOCAL_HOSTS):
            return JSONResponse(status_code=403, content={"detail": "Richiesta non locale rifiutata"})
        return await call_next(request)

    @app.exception_handler(SongNotFound)
    async def song_not_found(request: Request, exc: SongNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Brano non trovato"})

    def song_out(meta: SongMeta) -> dict[str, Any]:
        return {**meta.to_dict(), "playable": meta.playable,
                "queue_position": jobs.position(meta.id),
                "scores": library.read_scores(meta.id)}

    def new_meta(song_id: str, **fields: Any) -> SongMeta:
        return SongMeta(id=song_id, separator_model=config.SEPARATOR_MODEL,
                        pitch_tracker=config.PITCH_TRACKER, **fields)

    def json_file(song_id: str, name: str) -> FileResponse:
        library.get(song_id)
        path = library.path(song_id, name)
        if not path.is_file():
            raise HTTPException(404, "Non ancora disponibile")
        return FileResponse(path, media_type="application/json", headers=NO_CACHE)

    # --- sistema ---------------------------------------------------------

    @app.get("/api/system")
    def system() -> dict[str, Any]:
        gpu, name = separate.device_info()
        return {"gpu": gpu, "gpu_name": name}

    @app.get("/api/settings")
    def get_settings() -> Settings:
        return _load_settings()

    @app.put("/api/settings")
    def put_settings(settings: Settings) -> Settings:
        _save_settings(settings)
        return settings

    @app.get("/api/note-params")
    def get_note_params() -> dict[str, float]:
        return load_note_params().to_dict()

    @app.put("/api/note-params")
    def put_note_params(body: NoteParamsBody) -> dict[str, float]:
        params = NoteParams.from_dict(body.model_dump())
        save_note_params(params)
        return params.to_dict()

    # --- libreria --------------------------------------------------------

    @app.get("/api/songs")
    def list_songs() -> list[dict[str, Any]]:
        return [song_out(meta) for meta in library.list()]

    @app.post("/api/songs/url")
    def add_url(body: UrlBody) -> JSONResponse:
        try:
            info = probe(body.url)
        except acquire.AcquireError as exc:
            raise HTTPException(400, str(exc)) from exc
        song_id = f"yt-{info.youtube_id}"
        if library.exists(song_id):
            return JSONResponse(song_out(library.get(song_id)), status_code=200)
        meta = new_meta(song_id, title=info.title, artist=info.artist, duration_s=info.duration_s,
                        source_kind="youtube", source_ref=acquire.watch_url(info.youtube_id))
        library.create(meta)
        jobs.enqueue(song_id)
        return JSONResponse(song_out(meta), status_code=201)

    @app.post("/api/songs/file")
    def add_file(file: UploadFile = File(...)) -> JSONResponse:
        original_name = Path(file.filename or "brano").name
        suffix = re.sub(r"[^A-Za-z0-9.]", "", Path(original_name).suffix.lower()) or ".bin"
        scratch = config.data_dir() / "tmp" / uuid.uuid4().hex
        scratch.mkdir(parents=True)
        try:
            upload = scratch / f"upload{suffix}"
            with open(upload, "wb") as handle:
                shutil.copyfileobj(file.file, handle)
            try:
                duration = acquire.normalize_audio(upload, scratch / "check.flac")
            except acquire.AcquireError as exc:
                raise HTTPException(400, str(exc)) from exc
            if duration > config.MAX_DURATION_S:
                raise HTTPException(400, acquire.too_long_message(duration))
            song_id = acquire.file_song_id(upload)
            if library.exists(song_id):
                return JSONResponse(song_out(library.get(song_id)), status_code=200)
            artist, title = acquire.file_metadata(upload, original_name=original_name)
            meta = new_meta(song_id, title=title, artist=artist, duration_s=duration,
                            source_kind="file", source_ref=original_name)
            folder = library.create(meta)
            shutil.move(str(upload), folder / upload.name)
            jobs.enqueue(song_id)
            return JSONResponse(song_out(meta), status_code=201)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    @app.get("/api/songs/{song_id}")
    def get_song(song_id: str) -> dict[str, Any]:
        return song_out(library.get(song_id))

    @app.patch("/api/songs/{song_id}")
    def patch_song(song_id: str, patch: SongPatch) -> dict[str, Any]:
        changes = patch.model_dump(exclude_unset=True)
        if "language" in changes:
            # Una lingua scelta a mano vince sul riconoscimento; vuota torna automatica.
            changes["language"] = (changes["language"] or "").strip().lower() or None
            changes["language_user"] = changes["language"] is not None
            if changes["language"] is None and not library.get(song_id).language_user:
                # Era già automatica: quella rilevata resta dov'è.
                del changes["language"], changes["language_user"]
        for name in ("title", "artist", "lyrics_offset_s", "lyrics_choice"):
            if name in changes and changes[name] is None:
                del changes[name]
        return song_out(library.update(song_id, **changes))

    @app.delete("/api/songs/{song_id}")
    def delete_song(song_id: str) -> Response:
        library.get(song_id)
        if jobs.position(song_id) is not None:
            raise HTTPException(409, BUSY)
        library.delete(song_id)
        return Response(status_code=204)

    @app.post("/api/songs/{song_id}/retry", status_code=202)
    def retry_song(song_id: str, body: RetryBody) -> dict[str, Any]:
        meta = library.get(song_id)
        if body.from_stage is not None and body.from_stage not in STAGES:
            raise HTTPException(400, "Passo sconosciuto")
        if jobs.position(song_id) is None:
            jobs.enqueue(song_id, body.from_stage)
        return song_out(meta)

    # --- dati per il gioco -----------------------------------------------

    @app.get("/api/songs/{song_id}/notes")
    def get_notes(song_id: str) -> FileResponse:
        return json_file(song_id, NOTES)

    @app.get("/api/songs/{song_id}/notes-swiftf0")
    def get_swiftf0_notes(song_id: str) -> FileResponse:
        # Esiste solo per i brani passati dalla prova dei modelli: serve da confronto.
        return json_file(song_id, NOTES_SWIFTF0)

    @app.get("/api/songs/{song_id}/pitch")
    def get_pitch(song_id: str) -> FileResponse:
        return json_file(song_id, PITCH)

    @app.get("/api/songs/{song_id}/lyrics")
    def get_lyrics(song_id: str) -> FileResponse:
        return json_file(song_id, LYRICS)

    @app.put("/api/songs/{song_id}/lyrics")
    def put_lyrics(song_id: str, body: LyricsBody) -> dict[str, Any]:
        """Salva testo e tempi così come li ha sistemati chi gioca."""
        meta = library.get(song_id)
        if not meta.playable:
            raise HTTPException(404, "Non ancora disponibile")
        if jobs.position(song_id) is not None:
            raise HTTPException(409, BUSY)   # la ricerca del testo sta per riscrivere le righe
        try:
            lines = _edited_lines(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        library.write_lyrics(song_id, lines)
        # I tempi arrivano già spostati: lo scostamento globale non serve più.
        changes: dict[str, Any] = {"lyrics_offset_s": 0.0}
        if not lines:
            changes["lyrics_source"] = "none"
        elif meta.lyrics_source in (None, "none"):
            changes["lyrics_source"] = "manual"
        library.update(song_id, **changes)
        if lines and meta.stages["lyrics"].status != "done":
            # Un testo scritto a mano chiude una ricerca fallita: non c'è più niente da riprovare.
            library.set_stage(song_id, "lyrics", "done")
        return lines_to_dict(lines)

    @app.get("/api/songs/{song_id}/waveform")
    def get_waveform(song_id: str) -> FileResponse:
        """Il profilo di volume della voce isolata; si calcola alla prima richiesta."""
        library.get(song_id)
        vocals = library.path(song_id, VOCALS)
        if not vocals.is_file():
            raise HTTPException(404, "Non ancora disponibile")
        cache = library.path(song_id, WAVEFORM)
        if not cache.is_file() or cache.stat().st_mtime < vocals.stat().st_mtime:
            write_json(cache, waveform.peaks(vocals))
        return FileResponse(cache, media_type="application/json", headers=NO_CACHE)

    @app.post("/api/songs/{song_id}/notes/preview")
    def preview_notes(song_id: str, body: NoteParamsBody) -> dict[str, Any]:
        library.get(song_id)
        if not library.path(song_id, PITCH).is_file():
            raise HTTPException(404, "Non ancora disponibile")
        params = NoteParams.from_dict(body.model_dump())
        return notes_to_dict(segment_notes(library.read_pitch(song_id), params))

    @app.post("/api/songs/{song_id}/notes/apply")
    def apply_notes(song_id: str, body: NoteParamsBody) -> dict[str, Any]:
        # Rigenera solo le barre di questo brano: il testo (magari corretto a mano) resta com'è.
        library.get(song_id)
        if not library.path(song_id, PITCH).is_file():
            raise HTTPException(404, "Non ancora disponibile")
        notes = segment_notes(library.read_pitch(song_id), NoteParams.from_dict(body.model_dump()))
        if len(notes) < config.MIN_NOTES:
            raise HTTPException(400, "Con queste soglie non resta quasi nessuna nota.")
        library.write_notes(song_id, notes)
        return notes_to_dict(notes)

    @app.get("/api/songs/{song_id}/audio/{which}")
    def get_audio(song_id: str, which: str) -> FileResponse:
        library.get(song_id)
        name = AUDIO_FILES.get(which)
        if name is None or not library.path(song_id, name).is_file():
            raise HTTPException(404, "Audio non disponibile")
        return FileResponse(library.path(song_id, name), media_type="audio/flac")

    @app.post("/api/songs/{song_id}/scores")
    def post_score(song_id: str, body: ScoreBody) -> dict[str, Any]:
        return library.record_score(song_id, body.difficulty, body.score, body.accuracy, body.stars)

    # --- interfaccia -----------------------------------------------------

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app
