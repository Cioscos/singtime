import numpy as np

from karaoke.models import PitchCurve
from karaoke.pipeline.notes import NoteParams, load_note_params, save_note_params, segment_notes


def curve(segments, hop=0.010):
    """segments: lista di (durata_s, funzione t->midi oppure None per il silenzio)."""
    times, midi, t0 = [], [], 0.0
    for dur, fn in segments:
        n = int(round(dur / hop))
        t = np.arange(n) * hop
        times.append(t0 + t)
        midi.append(np.full(n, np.nan) if fn is None else np.vectorize(fn)(t).astype(float))
        t0 += n * hop
    return PitchCurve(np.concatenate(times), np.concatenate(midi))


def flat(p):
    return lambda t: p


def test_vibrato_is_one_note():
    c = curve([(0.3, None), (1.5, lambda t: 60 + 0.7 * np.sin(2 * np.pi * 6 * t)), (0.3, None)])
    notes = segment_notes(c)
    assert len(notes) == 1 and abs(notes[0].pitch - 60) < 0.15 and abs(notes[0].duration - 1.5) < 0.05


def test_glissando_gives_two_notes_not_a_staircase():
    c = curve([(0.5, flat(60)), (0.15, lambda t: 60 + 4 * t / 0.15), (0.5, flat(64))])
    notes = segment_notes(c)
    assert len(notes) == 2
    assert abs(notes[0].pitch - 60) < 0.2 and abs(notes[1].pitch - 64) < 0.2
    assert abs((notes[0].start + notes[0].duration) - notes[1].start) < 0.03    # contigue


def test_sudden_jump_gives_two_notes():
    notes = segment_notes(curve([(0.5, flat(60)), (0.5, flat(67))]))
    assert len(notes) == 2 and abs(notes[0].pitch - 60) < 0.2 and abs(notes[1].pitch - 67) < 0.2


def test_slow_drift_is_split():
    notes = segment_notes(curve([(3.0, lambda t: 60 + 4 * t / 3.0)]))
    assert 2 <= len(notes) <= 6
    assert notes[0].pitch < notes[-1].pitch


def test_short_blip_is_dropped():
    assert segment_notes(curve([(0.5, None), (0.05, flat(70)), (0.5, None)])) == []


def test_short_gap_is_bridged():
    notes = segment_notes(curve([(0.4, flat(62)), (0.05, None), (0.4, flat(62))]))
    assert len(notes) == 1 and abs(notes[0].duration - 0.85) < 0.03


def test_real_pause_splits():
    assert len(segment_notes(curve([(0.4, flat(62)), (0.3, None), (0.4, flat(62))]))) == 2


def test_long_held_note_stays_one():
    notes = segment_notes(curve([(6.0, lambda t: 58 + 0.1 * np.sin(2 * np.pi * 0.5 * t))]))
    assert len(notes) == 1 and abs(notes[0].duration - 6.0) < 0.05


def test_pitch_is_not_snapped_to_semitones():
    assert abs(segment_notes(curve([(1.0, flat(60.4))]))[0].pitch - 60.4) < 0.05


def test_no_note_shorter_than_minimum_and_no_overlap():
    rng = np.random.default_rng(0)
    segs = [(float(rng.uniform(0.03, 0.4)),
             flat(float(rng.uniform(55, 70))) if rng.random() > 0.3 else None) for _ in range(200)]
    notes = segment_notes(curve(segs))
    assert notes and all(n.duration >= 0.10 - 1e-6 for n in notes)
    assert all(a.start + a.duration <= b.start + 1e-6 for a, b in zip(notes, notes[1:]))


def test_same_result_at_16ms_hop():
    segs = [(0.5, flat(60)), (0.2, None), (0.8, flat(65))]
    a, b = segment_notes(curve(segs, 0.010)), segment_notes(curve(segs, 0.016))
    assert len(a) == len(b) == 2
    assert all(abs(x.start - y.start) < 0.02 and abs(x.pitch - y.pitch) < 0.1 for x, y in zip(a, b))


def test_empty_and_all_silent():
    assert segment_notes(PitchCurve(np.array([]), np.array([]))) == []
    assert segment_notes(curve([(2.0, None)])) == []


def test_params_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path))
    assert load_note_params() == NoteParams()
    save_note_params(NoteParams(min_note_s=0.2))
    assert load_note_params().min_note_s == 0.2


def test_params_change_the_result():
    c = curve([(0.5, None), (0.15, flat(60)), (0.5, None)])
    assert len(segment_notes(c)) == 1
    assert segment_notes(c, NoteParams(min_note_s=0.2)) == []
