import shutil

import numpy as np
import pytest
import soundfile as sf

from karaoke.library import INSTRUMENTAL, SOURCE, VOCALS, Library
from karaoke.models import SongMeta
from karaoke.pipeline.runner import DEFAULT_STAGES, Pipeline


@pytest.mark.slow
def test_pipeline_end_to_end_on_synthetic_voice(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path / "data"))
    sr = 44100

    def tone(hz, seconds):
        # Otto armoniche e un attacco morbido: SwiftF0 è addestrato su voci reali e
        # non riconosce come "voce" una sinusoide pura (confidenza intorno a 0,5).
        t = np.arange(int(sr * seconds)) / sr
        wave = sum(np.sin(2 * np.pi * hz * k * t) / k for k in range(1, 9))
        return 0.15 * wave * np.minimum(1, np.minimum(t, seconds - t) / 0.02)
    gap = np.zeros(int(sr * 0.3))
    midi = [57, 60, 64, 62, 57, 65]
    y = np.concatenate([np.concatenate([tone(440 * 2 ** ((m - 69) / 12), 0.6), gap]) for m in midi])
    lib = Library(tmp_path / "library")
    meta = SongMeta(id="s", title="T", artist="", duration_s=None, source_kind="file", source_ref="voce.wav",
                    separator_model="finto", pitch_tracker="swiftf0")
    folder = lib.create(meta)
    sf.write(folder / "upload.wav", np.stack([y, y], axis=1), sr)

    def fake_separate(l, sid):
        shutil.copy(l.path(sid, SOURCE), l.path(sid, VOCALS))
        shutil.copy(l.path(sid, SOURCE), l.path(sid, INSTRUMENTAL))

    def no_lyrics(l, sid):
        l.write_lyrics(sid, [])
        l.update(sid, lyrics_source="none")

    assert Pipeline(lib, {**DEFAULT_STAGES, "separate": fake_separate, "lyrics": no_lyrics}).run("s") is True
    notes = lib.read_notes("s")
    got = lib.get("s")
    assert got.playable and abs(got.duration_s - 5.4) < 0.1 and not list(folder.glob("upload.*"))
    assert len(notes) == 6 and all(abs(n.pitch - m) < 0.3 for n, m in zip(notes, midi))
