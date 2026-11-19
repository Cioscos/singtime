"""Passo 4: dalla curva di altezza alle barre da cantare.

È il cuore del gioco. Una voce reale fa vibrato, glissati e respiri: l'obiettivo
è un tracciato cantabile, non una copia tremolante della voce originale.
Tutte le soglie stanno in `NoteParams`, perché vanno tarate a orecchio.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

import numpy as np
from scipy.ndimage import median_filter

from .. import config
from ..fileio import read_json, write_json
from ..models import Note, PitchCurve

PARAMS_FILE = "note_params.json"
_EPS = 1e-9


@dataclass
class NoteParams:
    min_note_s: float = 0.10        # nessuna barra più corta di così
    max_gap_s: float = 0.08         # pause più brevi dentro una nota vengono ricucite
    vibrato_window_s: float = 0.20  # larghezza della mediana che appiattisce il vibrato
    split_semitones: float = 0.8    # scarto oltre il quale è un'altra nota
    settle_s: float = 0.06          # quanto deve durare lo scarto per contare
    merge_semitones: float = 0.5    # note consecutive più vicine di così si uniscono
    glide_window_s: float = 0.12    # finestra in cui si riconosce un glissato lento

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NoteParams:
        known = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in data.items() if k in known})


def load_note_params() -> NoteParams:
    path = config.data_dir() / PARAMS_FILE
    if not path.is_file():
        return NoteParams()
    return NoteParams.from_dict(read_json(path))


def save_note_params(params: NoteParams) -> None:
    write_json(config.data_dir() / PARAMS_FILE, params.to_dict())


# Un segmento è un intervallo di fotogrammi [inizio, fine).
Segment = tuple[int, int]


def _runs(mask: np.ndarray) -> list[Segment]:
    """Intervalli consecutivi in cui `mask` è vero."""
    if not mask.any():
        return []
    padded = np.concatenate([[False], mask, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])]


def _bridge_gaps(times: np.ndarray, midi: np.ndarray, hop: float, max_gap_s: float) -> np.ndarray:
    """Riempie per interpolazione i buchi senza voce più corti di `max_gap_s`."""
    filled = midi.copy()
    voiced = _runs(~np.isnan(midi))
    for (_, end_a), (start_b, _) in zip(voiced, voiced[1:]):
        gap = times[start_b] - (times[end_a - 1] + hop)
        if gap <= max_gap_s + _EPS:
            inside = np.arange(end_a, start_b)
            filled[inside] = np.interp(times[inside], [times[end_a - 1], times[start_b]],
                                       [midi[end_a - 1], midi[start_b]])
    return filled


def _split_drift(smooth: np.ndarray, zone: Segment, hop: float, params: NoteParams) -> list[Segment]:
    """Divide una zona stabile quando l'altezza si allontana a lungo dalla mediana."""
    start, end = zone
    segments: list[Segment] = []
    seg_start, depart, j = start, None, start
    while j < end:
        reference_end = depart if depart is not None else j
        reference = np.median(smooth[seg_start:reference_end]) if reference_end > seg_start else smooth[j]
        if abs(smooth[j] - reference) > params.split_semitones:
            if depart is None:
                depart = j
            if (j + 1 - depart) * hop >= params.settle_s - _EPS:
                segments.append((seg_start, depart))
                seg_start, j, depart = depart, depart, None
                continue
        else:
            depart = None
        j += 1
    segments.append((seg_start, end))
    return segments


def _gliding(local: np.ndarray, hop: float, params: NoteParams) -> np.ndarray:
    """Fotogrammi in cui l'altezza scivola in modo continuo, anche lentamente.

    Su una finestra più larga di quella dei salti si chiede che il movimento ci
    sia da entrambi i lati del fotogramma: un salto netto ha tutto il movimento
    da un lato solo e non conta, così le melodie veloci restano intatte. Ai bordi
    del tratto, dove un lato manca, si usa l'altro.
    """
    length = len(local)
    half = max(1, int(round(params.glide_window_s / 2 / hop)))
    index = np.arange(length)
    after = np.minimum(index + half, length - 1)
    before = np.maximum(index - half, 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rise_after = np.where(after > index, np.abs(local[after] - local) * half / (after - index), np.nan)
        rise_before = np.where(index > before, np.abs(local - local[before]) * half / (index - before), np.nan)
    rise_after = np.where(np.isnan(rise_after), rise_before, rise_after)
    rise_before = np.where(np.isnan(rise_before), rise_after, rise_before)
    rise_after = np.nan_to_num(rise_after)
    rise_before = np.nan_to_num(rise_before)
    sustained = np.minimum(rise_after, rise_before) > params.split_semitones / 4
    return sustained & (rise_after + rise_before > params.split_semitones)


def _partition_run(smooth: np.ndarray, run: Segment, hop: float, params: NoteParams) -> list[Segment]:
    """Divide un tratto con voce in segmenti contigui che lo coprono tutto."""
    start, end = run
    length = end - start
    local = smooth[start:end]

    # Transizioni: fotogrammi in cui la curva lisciata cambia in fretta (salti e glissati rapidi)…
    half = max(1, int(round(params.settle_s / 2 / hop)))
    index = np.arange(length)
    ahead = local[np.minimum(index + half, length - 1)]
    behind = local[np.maximum(index - half, 0)]
    moving = np.abs(ahead - behind) > params.split_semitones
    # …oppure sta scivolando in modo continuo (glissati lenti, cadute a fine frase).
    moving |= _gliding(local, hop, params)

    segments: list[Segment] = []
    for zone_start, zone_end in _runs(~moving):
        segments.extend(_split_drift(smooth, (start + zone_start, start + zone_end), hop, params))
    if not segments:
        return [run]  # tutto il tratto è una transizione: resta un segmento unico

    # I fotogrammi in movimento vanno per metà a chi precede e per metà a chi segue.
    covered: list[Segment] = []
    cursor = start
    for i, (seg_start, seg_end) in enumerate(segments):
        if seg_start > cursor:  # c'è una transizione prima di questo segmento
            if covered:
                middle = cursor + (seg_start - cursor) // 2
                covered[-1] = (covered[-1][0], middle)
                seg_start = middle
            else:
                seg_start = cursor
        covered.append((seg_start, seg_end))
        cursor = seg_end
        if i == len(segments) - 1 and cursor < end:
            covered[-1] = (covered[-1][0], end)
    return covered


def _dissolve_short(segments: list[Segment], hop: float, min_note_s: float) -> list[Segment]:
    """Scioglie i segmenti troppo corti nei vicini, partendo dal più corto."""
    segments = list(segments)
    while len(segments) > 1:
        lengths = [b - a for a, b in segments]
        k = int(np.argmin(lengths))
        if lengths[k] * hop >= min_note_s - _EPS:
            break
        a, b = segments[k]
        if 0 < k < len(segments) - 1:
            middle = a + (b - a) // 2
            segments[k - 1] = (segments[k - 1][0], middle)
            segments[k + 1] = (middle, segments[k + 1][1])
        elif k == 0:
            segments[1] = (a, segments[1][1])
        else:
            segments[k - 1] = (segments[k - 1][0], b)
        del segments[k]
    if len(segments) == 1 and (segments[0][1] - segments[0][0]) * hop < min_note_s - _EPS:
        return []
    return segments


def _pitch_of(raw: np.ndarray, segment: Segment) -> float:
    """Mediana dei valori non lisciati nell'80% centrale del segmento."""
    start, end = segment
    trim = (end - start) // 10
    return float(np.median(raw[start + trim:end - trim]))


def _merge_close(segments: list[Segment], raw: np.ndarray, merge_semitones: float) -> list[Segment]:
    merged: list[Segment] = []
    for segment in segments:
        if merged and abs(_pitch_of(raw, merged[-1]) - _pitch_of(raw, segment)) < merge_semitones:
            merged[-1] = (merged[-1][0], segment[1])
        else:
            merged.append(segment)
    return merged


def segment_notes(curve: PitchCurve, params: NoteParams | None = None) -> list[Note]:
    """Trasforma la curva di altezza in barre ordinate e mai sovrapposte."""
    params = params or NoteParams()
    times = np.asarray(curve.times, dtype=float)
    midi = np.asarray(curve.midi, dtype=float)
    if len(times) < 2 or np.isnan(midi).all():
        return []
    hop = float(np.median(np.diff(times)))
    if hop <= 0:
        return []

    raw = _bridge_gaps(times, midi, hop, params.max_gap_s)
    window = max(1, int(round(params.vibrato_window_s / hop))) | 1  # dispari

    notes: list[Note] = []
    for run in _runs(~np.isnan(raw)):
        start, end = run
        if (end - start) * hop < params.min_note_s - _EPS:
            continue  # respiri, consonanti, rumori brevi
        smooth = raw.copy()
        smooth[start:end] = median_filter(raw[start:end], size=window, mode="nearest")
        segments = _partition_run(smooth, run, hop, params)
        segments = _dissolve_short(segments, hop, params.min_note_s)
        segments = _merge_close(segments, raw, params.merge_semitones)
        for seg_start, seg_end in segments:
            note_end = times[seg_end - 1] + hop
            if seg_end < len(times):
                note_end = min(note_end, times[seg_end])
            notes.append(Note(start=float(times[seg_start]),
                              duration=float(note_end - times[seg_start]),
                              pitch=_pitch_of(raw, (seg_start, seg_end))))
    return notes
