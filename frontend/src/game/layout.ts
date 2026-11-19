// Geometria condivisa tra la schermata di gioco e la vista di verifica.

import type { Note } from "../lib/types";

/** La linea "adesso" sta a un terzo scarso dello schermo da sinistra. */
export const NOW_X_FRACTION = 0.3;
/** Secondi di note in arrivo visibili a destra della linea "adesso". */
export const LOOKAHEAD_S = 5;

const RANGE_MARGIN = 3;
const MIN_SPAN = 12;

export interface PitchRange {
  min: number;
  max: number;
}

/** Intervallo verticale adattato all'estensione del brano, in semitoni. */
export function pitchRange(notes: Note[]): PitchRange {
  if (notes.length === 0) return { min: 54, max: 66 };
  let low = Infinity;
  let high = -Infinity;
  for (const note of notes) {
    if (note.pitch < low) low = note.pitch;
    if (note.pitch > high) high = note.pitch;
  }
  let min = low - RANGE_MARGIN;
  let max = high + RANGE_MARGIN;
  if (max - min < MIN_SPAN) {
    const middle = (min + max) / 2;
    min = middle - MIN_SPAN / 2;
    max = middle + MIN_SPAN / 2;
  }
  return { min, max };
}

/** Acuto in alto, grave in basso. */
export function midiToY(midi: number, range: PitchRange, top: number, bottom: number): number {
  return bottom - ((midi - range.min) / (range.max - range.min)) * (bottom - top);
}

/** Posizione orizzontale di un istante quando la linea "adesso" indica `now`. */
export function timeToX(t: number, now: number, width: number): number {
  const nowX = width * NOW_X_FRACTION;
  return nowX + ((t - now) * (width - nowX)) / LOOKAHEAD_S;
}

/** Indici [da, a) delle note che toccano la finestra di tempo; le note sono ordinate. */
export function visibleSlice(notes: Note[], from: number, to: number): [number, number] {
  let first = 0;
  while (first < notes.length && notes[first].start + notes[first].duration < from) first++;
  let last = first;
  while (last < notes.length && notes[last].start <= to) last++;
  return [first, last];
}
