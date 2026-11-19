import numpy as np
import pytest
import soundfile as sf

from karaoke import config
from karaoke.pipeline.pitch import hz_to_midi, track_pitch


def write_tone(path, hz, seconds=2.0, sr=44100, silence=0.5):
    t = np.arange(int(sr * seconds)) / sr
    y = np.concatenate([np.zeros(int(sr * silence)), 0.3 * np.sin(2 * np.pi * hz * t)])
    sf.write(path, np.stack([y, y], axis=1), sr)


def test_hz_to_midi():
    assert np.allclose(hz_to_midi(np.array([440.0, 220.0])), [69.0, 57.0])


@pytest.mark.slow
@pytest.mark.parametrize("tracker", config.PITCH_CANDIDATES)
def test_tracks_a_pure_tone(tmp_path, tracker):
    write_tone(tmp_path / "v.flac", 220.0)
    curve = track_pitch(tmp_path / "v.flac", tracker)
    voiced = ~np.isnan(curve.midi)
    assert len(curve.times) == len(curve.midi)
    assert abs(np.median(curve.midi[voiced]) - 57.0) < 0.3
    assert np.isnan(curve.midi[curve.times < 0.3]).all()          # il silenzio iniziale non è voce
    assert voiced[curve.times > 0.8].mean() > 0.9


def test_unknown_tracker(tmp_path):
    with pytest.raises(ValueError):
        track_pitch(tmp_path / "v.flac", "boh")
