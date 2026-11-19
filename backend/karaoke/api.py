"""L'API locale: libreria, coda di elaborazione, file per il gioco, impostazioni."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .jobs import JobQueue
from .library import (
    INSTRUMENTAL, LYRICS, META, NOTES, PITCH, VOCALS, Library, SongNotFound,
    lines_to_dict, notes_to_dict,
)
from .models import STAGES, SongMeta
from .pipeline import acquire, separate
from .pipeline.notes import NoteParams, load_note_params, save_note_params, segment_notes

SETTINGS_FILE = "settings.json"
AUDIO_FILES = {"vocals": VOCALS, "instrumental": INSTRUMENTAL}
NO_CACHE = {"Cache-Control": "no-store"}


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


class RetryBody(BaseModel):
    from_stage: str | None = None


class LyricsBody(BaseModel):
    texts: list[str]


class ScoreBody(BaseModel):
    difficulty: Literal["easy", "normal", "hard"]
    score: int
    accuracy: float
    stars: int


class NoteParamsBody(BaseModel):
    min_note_s: float = Field(gt=0)
    max_gap_s: float = Field(ge=0)
    vibrato_window_s: float = Field(gt=0)
    split_semitones: float = Field(gt=0)
    settle_s: float = Field(gt=0)
    merge_semitones: float = Field(ge=0)


def _load_settings() -> Settings:
    path = config.data_dir() / SETTINGS_FILE
    if not path.is_file():
        return Settings()
    return Settings(**json.loads(path.read_text(encoding="utf-8")))


def _save_settings(settings: Settings) -> None:
    path = config.data_dir() / SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.model_dump(), indent=1), encoding="utf-8")


def create_app(library: Library, jobs: JobQueue,
               probe: Callable[[str], acquire.UrlInfo] = acquire.probe_url,
               static_dir: Path | None = None) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Passi rimasti "in corso" da una chiusura precedente: diventano riprovabili.
        library.reset_interrupted()
        yield

    app = FastAPI(title="Karaoke a tracciato", lifespan=lifespan)

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
        for name in ("title", "artist", "lyrics_offset_s"):
            if name in changes and changes[name] is None:
                del changes[name]
        return song_out(library.update(song_id, **changes))

    @app.delete("/api/songs/{song_id}")
    def delete_song(song_id: str) -> Response:
        library.get(song_id)
        if jobs.position(song_id) is not None:
            raise HTTPException(409, "Il brano è in elaborazione: attendi che finisca.")
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

    @app.get("/api/songs/{song_id}/pitch")
    def get_pitch(song_id: str) -> FileResponse:
        return json_file(song_id, PITCH)

    @app.get("/api/songs/{song_id}/lyrics")
    def get_lyrics(song_id: str) -> FileResponse:
        return json_file(song_id, LYRICS)

    @app.put("/api/songs/{song_id}/lyrics")
    def put_lyrics(song_id: str, body: LyricsBody) -> dict[str, Any]:
        library.get(song_id)
        if not library.path(song_id, LYRICS).is_file():
            raise HTTPException(404, "Non ancora disponibile")
        lines = library.read_lyrics(song_id)
        if len(body.texts) != len(lines):
            raise HTTPException(400, "Il numero di righe non coincide")
        for line, text in zip(lines, body.texts):
            text = text.strip()
            if text != line.text:
                line.text = text
                line.words = None  # i tempi delle parole non valgono più per il testo nuovo
        library.write_lyrics(song_id, lines)
        return lines_to_dict(lines)

    @app.post("/api/songs/{song_id}/notes/preview")
    def preview_notes(song_id: str, body: NoteParamsBody) -> dict[str, Any]:
        library.get(song_id)
        if not library.path(song_id, PITCH).is_file():
            raise HTTPException(404, "Non ancora disponibile")
        params = NoteParams.from_dict(body.model_dump())
        return notes_to_dict(segment_notes(library.read_pitch(song_id), params))

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
