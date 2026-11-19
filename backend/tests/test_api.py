import threading

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from karaoke import config
from karaoke.api import create_app
from karaoke.jobs import JobQueue
from karaoke.library import INSTRUMENTAL, META, VOCALS, Library
from karaoke.models import STAGES, LyricLine, PitchCurve, SongMeta, Word
from karaoke.pipeline.acquire import AcquireError, UrlInfo
from karaoke.pipeline.notes import NoteParams
from karaoke.pipeline.runner import Pipeline

NOOP_STAGES = {s: (lambda l, sid: None) for s in STAGES}
LOCAL = "http://127.0.0.1:8765"


def fake_probe(url):
    if "bad" in url:
        raise AcquireError("Video non disponibile")
    return UrlInfo("abc", "Titolo", "Artista", 200.0)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path))
    lib = Library(tmp_path / "library")
    jobs = JobQueue(Pipeline(lib, NOOP_STAGES))
    jobs.start()
    yield TestClient(create_app(lib, jobs, probe=fake_probe), base_url=LOCAL), lib, jobs
    jobs.stop()


def add_song(c, jobs):
    c.post("/api/songs/url", json={"url": "https://youtu.be/abc"})
    jobs.join()


def test_add_url_creates_and_processes(ctx):
    c, lib, jobs = ctx
    r = c.post("/api/songs/url", json={"url": "https://youtu.be/abc"})
    assert r.status_code == 201 and r.json()["id"] == "yt-abc" and r.json()["artist"] == "Artista"
    assert r.json()["separator_model"] == config.SEPARATOR_MODEL
    jobs.join()
    assert c.get("/api/songs/yt-abc").json()["playable"] is True
    assert [s["id"] for s in c.get("/api/songs").json()] == ["yt-abc"]


def test_add_same_url_twice_returns_existing(ctx):
    c, lib, _ = ctx
    c.post("/api/songs/url", json={"url": "https://youtu.be/abc"})
    r = c.post("/api/songs/url", json={"url": "https://www.youtube.com/watch?v=abc&list=PL1"})
    assert r.status_code == 200 and len(lib.list()) == 1


def test_bad_url_leaves_no_song(ctx):
    c, lib, _ = ctx
    r = c.post("/api/songs/url", json={"url": "https://youtu.be/bad"})
    assert r.status_code == 400 and r.json()["detail"] == "Video non disponibile" and lib.list() == []


def test_upload_audio_file_with_awkward_name(ctx, tmp_path):                # Review Focus 4
    c, lib, jobs = ctx
    wav = tmp_path / "t.wav"
    sf.write(wav, np.zeros((4410, 2)), 44100)
    r = c.post("/api/songs/file", files={"file": ("Città è già (live).wav", wav.read_bytes(), "audio/wav")})
    assert r.status_code == 201 and r.json()["id"].startswith("file-") and r.json()["title"] == "Città è già (live)"
    assert len(list(lib.path(r.json()["id"], META).parent.glob("upload.*"))) == 1
    again = c.post("/api/songs/file", files={"file": ("altro nome.wav", wav.read_bytes(), "audio/wav")})
    assert again.status_code == 200 and again.json()["id"] == r.json()["id"]
    assert not list((tmp_path / "tmp").glob("*"))                           # nessun file temporaneo dimenticato


def test_upload_non_audio_is_rejected(ctx, tmp_path):                         # Review Focus 4
    c, lib, _ = ctx
    r = c.post("/api/songs/file", files={"file": ("note.txt", b"ciao", "text/plain")})
    assert r.status_code == 400 and "non contiene audio" in r.json()["detail"] and lib.list() == []
    assert not list((tmp_path / "tmp").glob("*"))


def test_startup_resets_interrupted_stages(tmp_path, monkeypatch):            # Review Focus 2
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path))
    lib = Library(tmp_path / "library")
    lib.create(SongMeta(id="s", title="T", artist="A", duration_s=None, source_kind="file", source_ref="f",
                        separator_model="m", pitch_tracker="swiftf0"))
    lib.set_stage("s", "separate", "running")
    jobs = JobQueue(Pipeline(lib, {}))
    with TestClient(create_app(lib, jobs), base_url=LOCAL) as c:
        assert c.get("/api/songs/s").json()["stages"]["separate"]["status"] == "error"


def test_patch_language_marks_it_user_set(ctx):
    c, lib, jobs = ctx
    add_song(c, jobs)
    r = c.patch("/api/songs/yt-abc", json={"language": "it", "lyrics_offset_s": -0.4})
    assert r.json()["language_user"] is True and r.json()["lyrics_offset_s"] == -0.4
    assert r.json()["title"] == "Titolo"                                      # i campi non inviati restano
    r = c.patch("/api/songs/yt-abc", json={"language": None, "title": "Altro"})
    assert r.json()["language_user"] is False and r.json()["title"] == "Altro"


def test_edit_lyrics_text_only(ctx):
    c, lib, jobs = ctx
    add_song(c, jobs)
    lib.write_lyrics("yt-abc", [LyricLine(1, 2, "sbagliato", [Word(1, 2, "sbagliato")]), LyricLine(3, 4, "ok", None)])
    r = c.put("/api/songs/yt-abc/lyrics", json={"texts": ["giusto", "ok"]})
    lines = r.json()["lines"]
    assert lines[0]["text"] == "giusto" and lines[0]["start"] == 1 and lines[0]["words"] is None
    assert c.get("/api/songs/yt-abc/lyrics").json()["lines"][0]["text"] == "giusto"
    assert c.put("/api/songs/yt-abc/lyrics", json={"texts": ["una sola"]}).status_code == 400


def test_notes_preview_does_not_save(ctx):
    c, lib, jobs = ctx
    add_song(c, jobs)
    t = np.arange(0, 2, 0.01)
    lib.write_pitch("yt-abc", PitchCurve(t, np.full(len(t), 60.0)))
    lib.write_notes("yt-abc", [])
    r = c.post("/api/songs/yt-abc/notes/preview", json=NoteParams().to_dict())
    assert len(r.json()["notes"]) == 1 and lib.read_notes("yt-abc") == []
    assert c.get("/api/songs/yt-abc/pitch").json()["midi"][0] == 60.0


def test_retry_and_scores_and_settings(ctx):
    c, lib, jobs = ctx
    add_song(c, jobs)
    assert c.post("/api/songs/yt-abc/retry", json={"from_stage": "notes"}).status_code == 202
    jobs.join()
    assert c.post("/api/songs/yt-abc/retry", json={"from_stage": "boh"}).status_code == 400
    c.post("/api/songs/yt-abc/scores", json={"difficulty": "normal", "score": 10, "accuracy": 0.5, "stars": 2})
    assert c.get("/api/songs/yt-abc").json()["scores"]["normal"]["score"] == 10
    assert c.get("/api/settings").json() == {"mic_device_id": None, "latency_ms": 0, "calibrated": False,
                                             "guide_volume": 0.3, "difficulty": "normal"}
    s = c.get("/api/settings").json()
    s["latency_ms"] = 120
    assert c.put("/api/settings", json=s).json()["latency_ms"] == 120
    assert c.get("/api/settings").json()["latency_ms"] == 120


def test_note_params_roundtrip(ctx):
    c, _, _ = ctx
    assert c.get("/api/note-params").json() == NoteParams().to_dict()
    body = NoteParams(min_note_s=0.2).to_dict()
    assert c.put("/api/note-params", json=body).json()["min_note_s"] == 0.2
    assert c.get("/api/note-params").json()["min_note_s"] == 0.2


def test_audio_files_are_served(ctx):
    c, lib, jobs = ctx
    add_song(c, jobs)
    sf.write(lib.path("yt-abc", VOCALS), np.zeros((4410, 2)), 44100, format="FLAC")
    r = c.get("/api/songs/yt-abc/audio/vocals")
    assert r.status_code == 200 and r.content[:4] == b"fLaC"
    assert c.get("/api/songs/yt-abc/audio/instrumental").status_code == 404
    assert c.get("/api/songs/yt-abc/audio/altro").status_code == 404
    assert not lib.path("yt-abc", INSTRUMENTAL).exists()


def test_delete_and_missing(ctx):
    c, lib, jobs = ctx
    add_song(c, jobs)
    assert c.delete("/api/songs/yt-abc").status_code == 204 and c.get("/api/songs/yt-abc").status_code == 404
    assert c.get("/api/songs/nope/notes").status_code == 404
    assert c.patch("/api/songs/nope", json={"title": "x"}).status_code == 404


def test_cannot_delete_while_processing(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path))
    lib = Library(tmp_path / "library")
    gate = threading.Event()
    jobs = JobQueue(Pipeline(lib, {**NOOP_STAGES, "acquire": lambda l, sid: gate.wait(5)}))
    jobs.start()
    c = TestClient(create_app(lib, jobs, probe=fake_probe), base_url=LOCAL)
    r = c.post("/api/songs/url", json={"url": "https://youtu.be/abc"})
    try:
        assert c.delete("/api/songs/yt-abc").status_code == 409 and lib.exists("yt-abc")
        assert r.json()["queue_position"] in (0, 1)
    finally:
        gate.set()
        jobs.join()
        jobs.stop()


def test_system_reports_gpu(ctx, monkeypatch):
    from karaoke import api

    c, _, _ = ctx
    monkeypatch.setattr(api.separate, "device_info", lambda: (False, None))
    assert c.get("/api/system").json() == {"gpu": False, "gpu_name": None}


def test_swiftf0_comparison_notes(ctx):
    from karaoke.library import NOTES_SWIFTF0
    from karaoke.models import Note

    c, lib, jobs = ctx
    add_song(c, jobs)
    assert c.get("/api/songs/yt-abc/notes-swiftf0").status_code == 404
    lib.write_notes("yt-abc", [Note(1.0, 0.5, 60.0)], NOTES_SWIFTF0)
    assert c.get("/api/songs/yt-abc/notes-swiftf0").json()["notes"] == [{"start": 1.0, "duration": 0.5, "pitch": 60.0}]


def test_apply_notes_rewrites_only_the_notes(ctx):
    c, lib, jobs = ctx
    add_song(c, jobs)
    t = np.arange(0, 12, 0.01)
    lib.write_pitch("yt-abc", PitchCurve(t, np.where((t % 2) < 0.3, 60.0 + (t // 2), np.nan)))   # sei note da 0,3 s
    lib.write_notes("yt-abc", [])
    lib.write_lyrics("yt-abc", [LyricLine(1, 2, "corretto a mano", None)])
    r = c.post("/api/songs/yt-abc/notes/apply", json=NoteParams().to_dict())
    assert r.status_code == 200 and len(r.json()["notes"]) == 6 and len(lib.read_notes("yt-abc")) == 6
    assert lib.read_lyrics("yt-abc")[0].text == "corretto a mano"          # il testo non viene toccato
    too_strict = c.post("/api/songs/yt-abc/notes/apply", json=NoteParams(min_note_s=0.5).to_dict())
    assert too_strict.status_code == 400 and len(lib.read_notes("yt-abc")) == 6


def test_song_ids_cannot_escape_the_library(ctx, tmp_path):
    # Su Windows "..%5Cvittima" diventava un percorso fuori dalla libreria.
    import json

    c, lib, _ = ctx
    victim = tmp_path / "vittima"
    victim.mkdir()
    meta = SongMeta(id="vittima", title="T", artist="A", duration_s=None, source_kind="file", source_ref="f",
                    separator_model="m", pitch_tracker="swiftf0")
    (victim / "meta.json").write_text(json.dumps(meta.to_dict()), encoding="utf-8")
    for bad in ("..%5Cvittima", "..%2Fvittima", "a.b", "con%20spazio"):
        assert c.get(f"/api/songs/{bad}").status_code == 404, bad
        assert c.delete(f"/api/songs/{bad}").status_code == 404, bad
        score = {"difficulty": "normal", "score": 1, "accuracy": 0.1, "stars": 0}
        assert c.post(f"/api/songs/{bad}/scores", json=score).status_code == 404, bad
    assert victim.is_dir() and not (victim / "scores.json").exists()


def test_requests_from_other_sites_are_refused(ctx):
    # Il server è solo per questa macchina: una pagina web qualsiasi non deve poterlo usare.
    c, lib, _ = ctx
    assert c.get("/api/songs", headers={"host": "malvagio.example"}).status_code == 403
    r = c.post("/api/songs/url", json={"url": "https://youtu.be/abc"}, headers={"origin": "https://malvagio.example"})
    assert r.status_code == 403 and lib.list() == []
    assert c.get("/api/songs", headers={"origin": "http://127.0.0.1:8765"}).status_code == 200
    assert c.get("/api/songs", headers={"origin": "http://localhost:5173"}).status_code == 200   # vite in sviluppo
    assert c.get("/api/songs", headers={"host": "localhost:8765"}).status_code == 200


def test_upload_longer_than_the_limit_is_rejected(ctx, tmp_path, monkeypatch):
    # Il limite di durata vale per i file come per gli URL.
    c, lib, _ = ctx
    monkeypatch.setattr(config, "MAX_DURATION_S", 1)
    wav = tmp_path / "lungo.wav"
    sf.write(wav, np.zeros((44100 * 2, 2)), 44100)
    r = c.post("/api/songs/file", files={"file": ("lungo.wav", wav.read_bytes(), "audio/wav")})
    assert r.status_code == 400 and "troppo lungo" in r.json()["detail"] and lib.list() == []


def test_note_params_have_sane_limits(ctx):
    c, _, _ = ctx
    body = NoteParams().to_dict()
    assert "glide_window_s" in body
    assert c.put("/api/note-params", json={**body, "vibrato_window_s": 5000}).status_code == 422
    old_client = {k: v for k, v in body.items() if k != "glide_window_s"}       # parametri salvati prima di questa soglia
    assert c.put("/api/note-params", json=old_client).json()["glide_window_s"] == NoteParams().glide_window_s


def test_saving_other_fields_keeps_the_detected_language(ctx):
    c, lib, jobs = ctx
    add_song(c, jobs)
    lib.update("yt-abc", language="en")                      # rilevata da Whisper, non scelta a mano
    r = c.patch("/api/songs/yt-abc", json={"title": "Nuovo", "artist": "Artista", "language": None})
    assert r.json()["title"] == "Nuovo"
    assert r.json()["language"] == "en" and r.json()["language_user"] is False


def test_settings_are_written_atomically(ctx, monkeypatch):
    c, _, _ = ctx
    saved = c.put("/api/settings", json={**c.get("/api/settings").json(), "latency_ms": 80}).json()

    def refuse(src, dst):
        raise OSError("disco pieno")

    monkeypatch.setattr("karaoke.fileio.os.replace", refuse)
    with pytest.raises(OSError):
        c.put("/api/settings", json={**saved, "latency_ms": 999})
    assert c.get("/api/settings").json()["latency_ms"] == 80
