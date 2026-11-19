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


def test_model_download_is_reported_as_a_percentage(tmp_path):
    """Mentre carica il modello, il separatore scarica i pesi con una barra tqdm: la si ascolta."""
    import types

    class Bar:
        def __init__(self, *a, total=None, **kw):
            self.total, self.n = total, 0

        def update(self, n=1):
            self.n += n

        def close(self):
            pass

    library = types.SimpleNamespace(tqdm=Bar)

    class Downloading(FakeSeparator):
        def load_model(self, model_filename):
            bar = library.tqdm(total=1000, unit="iB", unit_scale=True)
            bar.update(250)
            bar.update(750)
            bar.close()

    FakeSeparator.stems = ["s_(Vocals).flac", "s_(Instrumental).flac"]
    seen = []
    separate(tmp_path / "source.flac", tmp_path, "m.ckpt", tmp_path / "models",
             on_detail=seen.append, separator_factory=Downloading, download_module=library)
    assert seen == ["Scarico il modello (solo la prima volta)…", "Scarico il modello: 25%", "Scarico il modello: 100%"]
    assert library.tqdm is Bar                                   # rimesso a posto alla fine


@pytest.mark.slow
def test_audio_separator_still_downloads_through_tqdm():
    """Guardia: se la libreria cambia modo di scaricare, la percentuale sparirebbe in silenzio."""
    import inspect

    import audio_separator.separator.separator as library

    assert "tqdm(" in inspect.getsource(library.Separator.download_file_if_not_exists)
    assert hasattr(library, "tqdm")
