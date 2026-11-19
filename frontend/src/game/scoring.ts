// Il punteggio: più tempo sulla barra, più punti.
//
// È guidato dalle letture del microfono, mai dai fotogrammi: ogni lettura vale
// per l'intervallo di tempo trascorso dalla lettura precedente.

import type { Difficulty, Note } from "../lib/types";
import { foldToOctave } from "./pitch-math";

/** Quanto si può sbagliare, in semitoni, restando "sulla barra". */
export const TOLERANCE: Record<Difficulty, number> = { easy: 2, normal: 1, hard: 0.5 };
export const POINTS_PER_SECOND = 100;
/** Una barra è riuscita se è stata presa per almeno questa parte della sua durata. */
export const NOTE_SUCCESS_FRACTION = 0.6;
/** Ogni tante barre riuscite di fila il moltiplicatore sale di uno. */
export const STREAK_PER_MULTIPLIER = 5;
export const MAX_MULTIPLIER = 4;
/** Un buco più lungo tra due letture (scheda nascosta, rallentamenti) non viene accreditato. */
export const MAX_FEED_GAP_S = 0.1;

export function starsFor(accuracy: number): number {
  if (accuracy >= 0.9) return 5;
  if (accuracy >= 0.75) return 4;
  if (accuracy >= 0.6) return 3;
  if (accuracy >= 0.45) return 2;
  if (accuracy >= 0.25) return 1;
  return 0;
}

export interface GameResult {
  score: number;
  accuracy: number;
  stars: number;
}

export class ScoreKeeper {
  private readonly notes: Note[];
  private readonly tolerance: number;
  private readonly hitSeconds: number[];
  private readonly segments: [number, number][][];
  private readonly totalSeconds: number;
  private lastT: number | null = null;
  private firstOpen = 0; // prima barra non ancora chiusa
  private hitTotal = 0;
  private points = 0;
  private streakCount = 0;

  constructor(notes: Note[], difficulty: Difficulty) {
    this.notes = notes;
    this.tolerance = TOLERANCE[difficulty];
    this.hitSeconds = notes.map(() => 0);
    this.segments = notes.map(() => []);
    this.totalSeconds = notes.reduce((sum, note) => sum + note.duration, 0);
  }

  /** Registra che dalla lettura precedente fino a `t` la voce era a `voiceMidi` (null = silenzio). */
  feed(t: number, voiceMidi: number | null): void {
    if (this.lastT === null) {
      this.lastT = t;
      this.closeUntil(t);
      return;
    }
    if (t <= this.lastT) return;
    const from = Math.max(this.lastT, t - MAX_FEED_GAP_S);
    if (voiceMidi !== null) {
      for (let i = this.firstOpen; i < this.notes.length && this.notes[i].start < t; i++) {
        const note = this.notes[i];
        const a = Math.max(from, note.start);
        const b = Math.min(t, note.start + note.duration);
        if (b > a && Math.abs(foldToOctave(voiceMidi, note.pitch) - note.pitch) <= this.tolerance) {
          this.credit(i, a, b);
        }
      }
    }
    this.lastT = t;
    this.closeUntil(t);
  }

  /** A fine brano: chiude anche le barre mai raggiunte. */
  finish(): void {
    this.closeUntil(Infinity);
  }

  get score(): number {
    return Math.round(this.points);
  }

  /** Fino a che punto del brano la voce è già stata giudicata. */
  get scoredUntil(): number {
    return this.lastT ?? -Infinity;
  }

  get streak(): number {
    return this.streakCount;
  }

  get multiplier(): number {
    return Math.min(MAX_MULTIPLIER, 1 + Math.floor(this.streakCount / STREAK_PER_MULTIPLIER));
  }

  /** I tratti [da, a] di una barra che sono stati presi, per colorarli. */
  hitSegments(noteIndex: number): [number, number][] {
    return this.segments[noteIndex] ?? [];
  }

  result(): GameResult {
    const accuracy = this.totalSeconds > 0 ? Math.min(1, this.hitTotal / this.totalSeconds) : 0;
    return { score: this.score, accuracy, stars: starsFor(accuracy) };
  }

  private credit(index: number, from: number, to: number): void {
    const seconds = to - from;
    this.hitSeconds[index] += seconds;
    this.hitTotal += seconds;
    this.points += seconds * POINTS_PER_SECOND * this.multiplier;
    const segments = this.segments[index];
    const last = segments[segments.length - 1];
    if (last && from - last[1] < 1e-6) last[1] = to;
    else segments.push([from, to]);
  }

  private closeUntil(t: number): void {
    while (this.firstOpen < this.notes.length) {
      const note = this.notes[this.firstOpen];
      if (note.start + note.duration > t) break;
      const fraction = note.duration > 0 ? this.hitSeconds[this.firstOpen] / note.duration : 0;
      this.streakCount = fraction >= NOTE_SUCCESS_FRACTION ? this.streakCount + 1 : 0;
      this.firstOpen++;
    }
  }
}
