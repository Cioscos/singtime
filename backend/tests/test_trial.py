import time

from karaoke import config
from karaoke.__main__ import parse_args
from karaoke.library import INSTRUMENTAL, LYRICS, SOURCE, VOCALS, Library
from karaoke.models import STAGES, SongMeta
from karaoke.trial import clean, make_variant, timed_stages


def base_song(tmp_path):
    lib = Library(tmp_path)
    lib.create(SongMeta(id="yt-a", title="T", artist="A", duration_s=10.0, source_kind="youtube",
                        source_ref="u", separator_model=config.SEPARATOR_MODEL, pitch_tracker="swiftf0"))
    for name in (SOURCE, VOCALS, INSTRUMENTAL, LYRICS):
        lib.path("yt-a", name).write_bytes(name.encode())
    for stage in STAGES:
        lib.set_stage("yt-a", stage, "done")
    return lib


def test_variant_for_another_separator_restarts_from_separation(tmp_path):
    lib = base_song(tmp_path)
    vid, from_stage = make_variant(lib, "yt-a", separator_model="vocals_mel_band_roformer.ckpt")
    meta = lib.get(vid)
    assert (vid, from_stage) == ("yt-a--mel-band", "separate")
    assert (meta.title, meta.separator_model, meta.pitch_tracker) == ("T [mel-band]", "vocals_mel_band_roformer.ckpt", "swiftf0")
    assert meta.stages["acquire"].status == "done" and meta.stages["separate"].status == "pending"
    assert lib.path(vid, SOURCE).read_bytes() == SOURCE.encode() and not lib.path(vid, VOCALS).exists()


def test_variant_for_another_tracker_reuses_the_stems(tmp_path):
    lib = base_song(tmp_path)
    vid, from_stage = make_variant(lib, "yt-a", pitch_tracker="fcpe")
    meta = lib.get(vid)
    assert (vid, from_stage, meta.pitch_tracker) == ("yt-a--fcpe", "pitch", "fcpe")
    assert meta.stages["separate"].status == "done" and meta.stages["pitch"].status == "pending"
    assert lib.path(vid, VOCALS).exists() and lib.path(vid, INSTRUMENTAL).exists()


def test_variant_can_be_created_twice(tmp_path):
    lib = base_song(tmp_path)
    first = make_variant(lib, "yt-a", pitch_tracker="fcpe")
    assert make_variant(lib, "yt-a", pitch_tracker="fcpe") == first


def test_clean_removes_only_variants(tmp_path):
    lib = base_song(tmp_path)
    make_variant(lib, "yt-a", pitch_tracker="fcpe")
    make_variant(lib, "yt-a", separator_model="htdemucs_ft.yaml")
    assert clean(lib) == 2 and [m.id for m in lib.list()] == ["yt-a"]


def test_timed_stages_record_how_long_each_took(tmp_path):
    lib, timings = base_song(tmp_path), []
    stages = timed_stages({"pitch": lambda l, sid: time.sleep(0.05)}, timings)
    stages["pitch"](lib, "yt-a")
    (song_id, stage, seconds), = timings
    assert (song_id, stage) == ("yt-a", "pitch") and 0.04 < seconds < 1.0


def test_parse_args():
    assert parse_args([]).no_browser is False and parse_args([]).port == config.PORT
    assert parse_args(["--no-browser", "--port", "9000"]).no_browser is True
    assert parse_args(["--port", "9000"]).port == 9000
