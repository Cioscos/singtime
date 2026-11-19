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

/** Quota del tempo cantato che si può ignorare a ciascun estremo per trovare il "grosso" del brano. */
const BULK_TAIL = 0.02;
/** Una barra più lontana di così dal grosso del brano è una svista del rilevatore (di solito un'ottava). */
const OUTLIER_SEMITONES = 7;

/** L'altezza sotto cui sta la quota `fraction` del tempo cantato; `sorted` è ordinato per altezza. */
function pitchAt(sorted: Note[], fraction: number): number {
  const total = sorted.reduce((sum, note) => sum + note.duration, 0);
  let sung = 0;
  for (const note of sorted) {
    sung += note.duration;
    if (sung >= total * fraction - 1e-9) return note.pitch;
  }
  return sorted[sorted.length - 1].pitch;
}

/**
 * Intervallo verticale adattato all'estensione del brano, in semitoni.
 * Le barre isolate molto lontane dal resto non lo allargano: schiaccerebbero
 * tutte le altre, e si disegnano comunque sul bordo.
 */
export function pitchRange(notes: Note[]): PitchRange {
  if (notes.length === 0) return { min: 54, max: 66 };
  const sorted = [...notes].sort((a, b) => a.pitch - b.pitch);
  const lowLimit = pitchAt(sorted, BULK_TAIL) - OUTLIER_SEMITONES;
  const highLimit = pitchAt(sorted, 1 - BULK_TAIL) + OUTLIER_SEMITONES;
  let low = Infinity;
  let high = -Infinity;
  for (const note of notes) {
    if (note.pitch < lowLimit || note.pitch > highLimit) continue;
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

/**
 * La barra a cui riferire la voce all'istante `t`: quella in corso, altrimenti
 * la più vicina nel tempo. Serve a riportare il pallino all'ottava giusta.
 */
export function targetNote(notes: Note[], t: number): Note | null {
  if (notes.length === 0) return null;
  let low = 0;
  let high = notes.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (notes[middle].start + notes[middle].duration <= t) low = middle + 1;
    else high = middle;
  }
  // `low` è la prima barra che non è ancora finita.
  if (low >= notes.length) return notes[notes.length - 1];
  const next = notes[low];
  if (next.start <= t || low === 0) return next;
  const previous = notes[low - 1];
  return t - (previous.start + previous.duration) <= next.start - t ? previous : next;
}
