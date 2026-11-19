import json

import numpy as np
import pytest

from karaoke.library import PITCH, Library, SongExists, SongNotFound
from karaoke.models import STAGES, LyricLine, Note, PitchCurve, SongMeta


def make_meta(song_id="yt-abc"):
    return SongMeta(id=song_id, title="T", artist="A", duration_s=None,
                    source_kind="youtube", source_ref="https://youtu.be/abc",
                    separator_model="m.ckpt", pitch_tracker="swiftf0")


def test_create_get_roundtrip(tmp_path):
    lib = Library(tmp_path)
    lib.create(make_meta())
    assert lib.get("yt-abc").title == "T"
    assert set(lib.get("yt-abc").stages) == set(STAGES)


def test_create_twice_raises(tmp_path):
    lib = Library(tmp_path)
    lib.create(make_meta())
    with pytest.raises(SongExists):
        lib.create(make_meta())


def test_get_missing_raises(tmp_path):
    with pytest.raises(SongNotFound):
        Library(tmp_path).get("nope")


def test_list_newest_first(tmp_path):
    lib = Library(tmp_path)
    old = make_meta("yt-old")
    old.created_at = "2026-01-01T00:00:00+00:00"
    new = make_meta("yt-new")
    new.created_at = "2026-06-01T00:00:00+00:00"
    lib.create(old)
    lib.create(new)
    assert [m.id for m in lib.list()] == ["yt-new", "yt-old"]


def test_delete_removes_folder(tmp_path):
    lib = Library(tmp_path)
    lib.create(make_meta())
    lib.delete("yt-abc")
    assert not lib.exists("yt-abc") and lib.list() == []


def test_playable_needs_first_four_stages(tmp_path):
    lib = Library(tmp_path)
    lib.create(make_meta())
    for s in ("acquire", "separate", "pitch"):
        lib.set_stage("yt-abc", s, "done")
    assert not lib.get("yt-abc").playable
    lib.set_stage("yt-abc", "notes", "done")
    assert lib.get("yt-abc").playable          # il testo non serve per giocare


def test_reset_interrupted(tmp_path):                       # Review Focus 2
    lib = Library(tmp_path)
    lib.create(make_meta())
    lib.set_stage("yt-abc", "separate", "running")
    assert lib.reset_interrupted() == 1
    st = lib.get("yt-abc").stages["separate"]
    assert st.status == "error" and st.error == "Elaborazione interrotta"


def test_pitch_roundtrip_keeps_nan(tmp_path):
    lib = Library(tmp_path)
    lib.create(make_meta())
    lib.write_pitch("yt-abc", PitchCurve(np.array([0.0, 0.016]), np.array([np.nan, 60.5])))
    got = lib.read_pitch("yt-abc")
    assert np.isnan(got.midi[0]) and got.midi[1] == 60.5
    assert json.loads(lib.path("yt-abc", PITCH).read_text())["midi"][0] is None


def test_notes_and_lyrics_roundtrip(tmp_path):
    lib = Library(tmp_path)
    lib.create(make_meta())
    lib.write_notes("yt-abc", [Note(1.0, 0.5, 60.2)])
    lib.write_lyrics("yt-abc", [LyricLine(1.0, 2.0, "ciao", None)])
    assert lib.read_notes("yt-abc") == [Note(1.0, 0.5, 60.2)]
    assert lib.read_lyrics("yt-abc")[0].words is None


def test_record_score_keeps_best(tmp_path):
    lib = Library(tmp_path)
    lib.create(make_meta())
    lib.record_score("yt-abc", "normal", 100, 0.5, 2)
    lib.record_score("yt-abc", "normal", 50, 0.4, 1)
    assert lib.read_scores("yt-abc")["normal"]["score"] == 100
    lib.record_score("yt-abc", "normal", 300, 0.9, 5)
    assert lib.read_scores("yt-abc")["normal"]["stars"] == 5
