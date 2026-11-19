from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from karaoke.pipeline.separate import separate


class FakeSeparator:
    """Scrive file con i nomi tipici di audio-separator, senza separare nulla."""

    stems: list[str] = []

    def __init__(self, **kw):
        self.out = Path(kw["output_dir"])
        self.kw = kw

    def load_model(self, model_filename):
        self.model = model_filename

    def separate(self, path):
        for name in self.stems:
            sf.write(self.out / name, np.full((4410, 2), 0.1), 44100)
        return list(self.stems)


def flacs(folder):
    return sorted(p.name for p in folder.glob("*.flac"))


def test_two_stem_model(tmp_path):
    FakeSeparator.stems = ["source_(Vocals)_x.flac", "source_(Instrumental)_x.flac"]
    separate(tmp_path / "source.flac", tmp_path, "m.ckpt", tmp_path / "models", separator_factory=FakeSeparator)
    assert flacs(tmp_path) == ["instrumental.flac", "vocals.flac"]


def test_vocals_plus_other_model(tmp_path):
    FakeSeparator.stems = ["source_(Vocals)_x.flac", "source_(Other)_x.flac"]
    separate(tmp_path / "source.flac", tmp_path, "m.ckpt", tmp_path / "models", separator_factory=FakeSeparator)
    assert flacs(tmp_path) == ["instrumental.flac", "vocals.flac"]


def test_four_stem_model_sums_non_vocal(tmp_path):
    FakeSeparator.stems = [f"source_({s})_x.flac" for s in ("Vocals", "Drums", "Bass", "Other")]
    separate(tmp_path / "source.flac", tmp_path, "htdemucs_ft.yaml", tmp_path / "models", separator_factory=FakeSeparator)
    data, _ = sf.read(tmp_path / "instrumental.flac")
    assert np.allclose(data, 0.3, atol=1e-3)
    assert flacs(tmp_path) == ["instrumental.flac", "vocals.flac"]


def test_reports_model_download(tmp_path):
    FakeSeparator.stems = ["s_(Vocals).flac", "s_(Instrumental).flac"]
    seen = []
    separate(tmp_path / "source.flac", tmp_path, "m.ckpt", tmp_path / "models",
             on_detail=seen.append, separator_factory=FakeSeparator)
    assert seen == ["Scarico il modello (solo la prima volta)…"]


def test_no_download_notice_when_model_is_present(tmp_path):
    FakeSeparator.stems = ["s_(Vocals).flac", "s_(Instrumental).flac"]
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m.ckpt").write_bytes(b"x")
    seen = []
    separate(tmp_path / "source.flac", tmp_path, "m.ckpt", tmp_path / "models",
             on_detail=seen.append, separator_factory=FakeSeparator)
    assert seen == []


def test_missing_vocals_is_an_error(tmp_path):
    FakeSeparator.stems = ["s_(Drums).flac", "s_(Bass).flac"]
    with pytest.raises(RuntimeError, match="traccia voce"):
        separate(tmp_path / "source.flac", tmp_path, "m.ckpt", tmp_path / "models", separator_factory=FakeSeparator)
