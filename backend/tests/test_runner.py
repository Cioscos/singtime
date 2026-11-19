import numpy as np
import pytest

from karaoke.library import Library
from karaoke.models import STAGES, PitchCurve, SongMeta
from karaoke.pipeline.runner import DEFAULT_STAGES, NoVoiceError, Pipeline


def lib_with_song(tmp_path):
    lib = Library(tmp_path)
    lib.create(SongMeta(id="s", title="T", artist="A", duration_s=None, source_kind="file", source_ref="f",
                        separator_model="m", pitch_tracker="swiftf0"))
    return lib


def recording_stages(log, fail_at=None, exc=RuntimeError("boom")):
    def make(name):
        def fn(lib, sid):
            log.append(name)
            if name == fail_at:
                raise exc
        return fn
    return {s: make(s) for s in STAGES}


def test_runs_all_in_order(tmp_path):
    lib, log = lib_with_song(tmp_path), []
    assert Pipeline(lib, recording_stages(log)).run("s") is True
    assert log == list(STAGES) and all(st.status == "done" for st in lib.get("s").stages.values())


def test_stops_at_failure_and_records_message(tmp_path):
    lib, log = lib_with_song(tmp_path), []
    assert Pipeline(lib, recording_stages(log, fail_at="pitch")).run("s") is False
    st = lib.get("s").stages
    assert log == ["acquire", "separate", "pitch"]
    assert st["pitch"].status == "error" and st["pitch"].error == "boom" and st["notes"].status == "pending"


def test_retry_resumes_from_failed_stage(tmp_path):
    lib, log = lib_with_song(tmp_path), []
    Pipeline(lib, recording_stages(log, fail_at="pitch")).run("s")
    log.clear()
    Pipeline(lib, recording_stages(log)).run("s")
    assert log == ["pitch", "notes", "lyrics"]


def test_rerun_from_stage_redoes_only_later_ones(tmp_path):
    lib, log = lib_with_song(tmp_path), []
    Pipeline(lib, recording_stages(log)).run("s")
    log.clear()
    Pipeline(lib, recording_stages(log)).run("s", from_stage="notes")
    assert log == ["notes", "lyrics"]


def test_stage_is_marked_running_while_it_works(tmp_path):
    lib, seen = lib_with_song(tmp_path), {}
    stages = {s: (lambda l, sid: None) for s in STAGES}
    stages["pitch"] = lambda l, sid: seen.update(status=l.get(sid).stages["pitch"].status)
    Pipeline(lib, stages).run("s")
    assert seen["status"] == "running"


def test_no_voice_is_a_readable_error(tmp_path):
    lib = lib_with_song(tmp_path)
    Pipeline(lib, recording_stages([], fail_at="notes", exc=NoVoiceError("Nessuna voce trovata"))).run("s")
    assert lib.get("s").stages["notes"].error == "Nessuna voce trovata" and not lib.get("s").playable


def test_real_notes_stage_rejects_instrumental(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path / "data"))
    lib = lib_with_song(tmp_path)
    lib.write_pitch("s", PitchCurve(np.arange(0, 5, 0.01), np.full(500, np.nan)))
    with pytest.raises(NoVoiceError):
        DEFAULT_STAGES["notes"](lib, "s")


def test_real_notes_stage_uses_saved_params(tmp_path, monkeypatch):
    from karaoke.pipeline.notes import NoteParams, save_note_params

    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path / "data"))
    lib = lib_with_song(tmp_path)
    t = np.arange(0, 12, 0.01)
    midi = np.where((t % 2) < 0.3, 60.0 + (t // 2), np.nan)      # sei note da 0,3 s
    lib.write_pitch("s", PitchCurve(t, midi))
    DEFAULT_STAGES["notes"](lib, "s")
    assert len(lib.read_notes("s")) == 6
    save_note_params(NoteParams(min_note_s=0.5))                  # ora sono tutte troppo corte
    with pytest.raises(NoVoiceError):
        DEFAULT_STAGES["notes"](lib, "s")


def test_language_chosen_during_the_transcription_wins(tmp_path, monkeypatch):
    from karaoke.pipeline import lyrics

    lib = lib_with_song(tmp_path)
    lib.write_notes("s", [])

    def slow_find(meta, vocals, notes, transcribe_fn):
        lib.update("s", language="de", language_user=True)       # scelta a mano mentre Whisper lavora
        return [], "none", "en", None

    monkeypatch.setattr(lyrics, "find_lyrics", slow_find)
    DEFAULT_STAGES["lyrics"](lib, "s")
    assert lib.get("s").language == "de" and lib.get("s").language_user is True


def test_failed_transcription_is_a_visible_error_and_the_song_still_plays(tmp_path, monkeypatch):
    from karaoke.pipeline import lyrics

    lib = lib_with_song(tmp_path)
    lib.write_notes("s", [])

    def crash(meta, vocals, notes, transcribe_fn):
        raise lyrics.LyricsError("Trascrizione non riuscita (memoria della scheda grafica esaurita)")

    monkeypatch.setattr(lyrics, "find_lyrics", crash)
    stages = {**{s: (lambda l, sid: None) for s in STAGES}, "lyrics": DEFAULT_STAGES["lyrics"]}
    assert Pipeline(lib, stages).run("s") is False
    meta = lib.get("s")
    assert meta.playable is True
    assert meta.stages["lyrics"].status == "error"
    assert meta.stages["lyrics"].error == "Trascrizione non riuscita (memoria della scheda grafica esaurita)"


def test_transcription_reports_the_model_download(tmp_path, monkeypatch):
    from karaoke.pipeline import lyrics

    lib = lib_with_song(tmp_path)
    lib.write_notes("s", [])
    seen = []

    def fake_transcribe(vocals, language, on_detail=None):
        on_detail("Scarico il modello di trascrizione: 40%")
        seen.append(lib.get("s").stages["lyrics"].detail)
        return [], "en"

    monkeypatch.setattr(lyrics, "transcribe", fake_transcribe)
    monkeypatch.setattr(lyrics, "find_lyrics",
                        lambda meta, vocals, notes, transcribe_fn: ([], "none", transcribe_fn(vocals, None)[1], None))
    DEFAULT_STAGES["lyrics"](lib, "s")
    assert seen == ["Scarico il modello di trascrizione: 40%"]


def test_the_lyrics_note_is_saved_and_cleared(tmp_path, monkeypatch):
    from karaoke.pipeline import lyrics

    lib = lib_with_song(tmp_path)
    lib.write_notes("s", [])
    answers = iter([([], "none", None, "LRCLIB non ha questo brano"), ([], "none", None, None)])
    monkeypatch.setattr(lyrics, "find_lyrics", lambda meta, vocals, notes, transcribe_fn: next(answers))
    DEFAULT_STAGES["lyrics"](lib, "s")
    assert lib.get("s").lyrics_note == "LRCLIB non ha questo brano"
    DEFAULT_STAGES["lyrics"](lib, "s")
    assert lib.get("s").lyrics_note is None
