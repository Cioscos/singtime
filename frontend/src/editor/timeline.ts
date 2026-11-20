// La timeline dell'editor: il volume della voce, le note, le righe e le parole
// lungo il tempo. Qui stanno la geometria, il riconoscimento di ciò che sta sotto
// il puntatore e il disegno; il componente ci mette audio e gesti.

import { midiToY, type PitchRange } from "../game/layout";
import { formatDuration } from "../lib/status";
import type { LyricLine, Note } from "../lib/types";
import { wordsOf } from "./lines";

export const TIMELINE_HEIGHT = 196;
/** Le fasce orizzontali, dall'alto: voce, righe, parole, asse del tempo. */
export const WAVE = { top: 6, bottom: 96 };
export const LINES = { top: 104, bottom: 140 };
export const WORDS = { top: 146, bottom: 168 };
const AXIS_Y = 174;

/** Entro quanti pixel da un bordo lo si afferra. */
const EDGE_PX = 6;
/** Un blocco più stretto di così si può solo spostare: i bordi non si distinguerebbero. */
const MIN_RESIZABLE_PX = 18;
const WORD_EDGE_PX = 5;

export const MIN_SPAN_S = 2;

export interface View {
  /** Il primo secondo visibile. */
  start: number;
  /** Quanti secondi stanno nella larghezza. */
  span: number;
  width: number;
}

export const timeToX = (view: View, t: number): number => ((t - view.start) / view.span) * view.width;
export const xToTime = (view: View, x: number): number => view.start + (x / view.width) * view.span;

/** La vista riportata dentro il brano. */
export function clampView(view: View, songDuration: number): View {
  const span = Math.min(Math.max(view.span, MIN_SPAN_S), Math.max(songDuration, MIN_SPAN_S));
  const start = Math.min(Math.max(view.start, 0), Math.max(0, songDuration - span));
  return { ...view, start, span };
}

/** Ingrandisce (factor < 1) o rimpicciolisce tenendo fermo il punto a `anchor` (0…1) della larghezza. */
export function zoomView(view: View, factor: number, anchor: number, songDuration: number): View {
  const pivot = view.start + view.span * anchor;
  const span = Math.min(Math.max(view.span * factor, MIN_SPAN_S), Math.max(songDuration, MIN_SPAN_S));
  return clampView({ ...view, span, start: pivot - span * anchor }, songDuration);
}

/** Durante la riproduzione la vista volta pagina quando il cursore arriva in fondo (o esce a sinistra). */
export function followView(view: View, now: number, songDuration: number): View {
  if (now <= view.start + view.span * 0.88 && now >= view.start) return view;
  return clampView({ ...view, start: now - view.span * 0.12 }, songDuration);
}

export type Hit =
  | { kind: "line"; part: "start" | "end" | "body"; line: number }
  | { kind: "word"; line: number; word: number; edge: "start" | "end" };

function linePart(view: View, line: LyricLine, x: number, slack: number): "start" | "end" | "body" | null {
  const left = timeToX(view, line.start);
  const right = timeToX(view, line.end);
  if (x < left - slack || x > right + slack) return null;
  if (right - left < MIN_RESIZABLE_PX) return "body";
  if (x - left <= EDGE_PX) return "start";
  if (right - x <= EDGE_PX) return "end";
  return "body";
}

/**
 * Che cosa c'è sotto il punto (x, y) della timeline: una riga (un suo bordo o il
 * corpo) oppure un bordo di parola della riga selezionata. Null: spazio libero,
 * dove un clic sposta il cursore dell'audio.
 */
export function hitTest(lines: LyricLine[], selected: number, view: View, x: number, y: number): Hit | null {
  if (y >= LINES.top && y <= LINES.bottom) {
    // La riga selezionata vince anche un filo fuori dal suo bordo: è quella che si sta sistemando.
    if (lines[selected]) {
      const part = linePart(view, lines[selected], x, 3);
      if (part) return { kind: "line", part, line: selected };
    }
    for (let i = 0; i < lines.length; i++) {
      const part = linePart(view, lines[i], x, 0);
      if (part) return { kind: "line", part, line: i };
    }
    return null;
  }
  if (y >= WORDS.top && y <= WORDS.bottom && lines[selected]) {
    const words = wordsOf(lines[selected]);
    if (!words) return null;
    let best: Hit | null = null;
    let distance = WORD_EDGE_PX;
    words.forEach((word, i) => {
      // A parità di distanza vince l'inizio della parola dopo: il confine si trascina da lì.
      for (const edge of ["end", "start"] as const) {
        const d = Math.abs(timeToX(view, word[edge]) - x);
        if (d <= distance) {
          distance = d;
          best = { kind: "word", line: selected, word: i, edge };
        }
      }
    });
    return best;
  }
  return null;
}

export function cursorFor(hit: Hit | null): string {
  if (!hit) return "crosshair";
  if (hit.kind === "word") return "ew-resize";
  return hit.part === "body" ? "grab" : "ew-resize";
}

// --- disegno -----------------------------------------------------------------

export interface TimelineFrame {
  view: View;
  lines: LyricLine[];
  selected: number;
  /** La riga che si sta cantando, o -1. */
  playing: number;
  /** La riga che aspetta il tocco mentre si batte il tempo, o -1. */
  tapping: number;
  notes: Note[];
  range: PitchRange;
  /** Il volume della voce, `rate` valori al secondo da 0 a 255; null finché non arriva. */
  peaks: ArrayLike<number> | null;
  rate: number;
  now: number;
}

const TICKS_S = [0.5, 1, 2, 5, 10, 15, 30, 60, 120];

function clipText(g: CanvasRenderingContext2D, text: string, x: number, y: number, left: number, right: number): void {
  if (right - left < 14) return;
  g.save();
  g.beginPath();
  g.rect(left, 0, right - left, TIMELINE_HEIGHT);
  g.clip();
  g.fillText(text, x, y);
  g.restore();
}

export function drawTimeline(g: CanvasRenderingContext2D, frame: TimelineFrame): void {
  const { view, lines, notes, range, peaks, rate } = frame;
  const width = view.width;
  const viewEnd = view.start + view.span;
  const x = (t: number) => timeToX(view, t);

  g.fillStyle = "#12141c";
  g.fillRect(0, 0, width, TIMELINE_HEIGHT);
  g.fillStyle = "#161924";
  g.fillRect(0, LINES.top - 4, width, WORDS.bottom - LINES.top + 8);

  // il volume della voce
  const middle = (WAVE.top + WAVE.bottom) / 2;
  const half = (WAVE.bottom - WAVE.top) / 2;
  if (peaks) {
    g.fillStyle = "#39435f";
    const perPixel = (view.span / width) * rate;
    for (let px = 0; px < width; px++) {
      const from = Math.floor((view.start + (px / width) * view.span) * rate);
      const until = Math.max(from + 1, Math.ceil(from + perPixel));
      let peak = 0;
      for (let i = Math.max(0, from); i < until && i < peaks.length; i++) if (peaks[i] > peak) peak = peaks[i];
      if (peak === 0) continue;
      const h = Math.max(0.5, Math.pow(peak / 255, 0.7) * half);
      g.fillRect(px, middle - h, 1, h * 2);
    }
  }
  g.fillStyle = "#232838";
  g.fillRect(0, middle, width, 1);

  // le note: dove comincia e finisce ogni suono cantato
  g.fillStyle = "rgba(91, 140, 255, 0.95)";
  for (const note of notes) {
    if (note.start > viewEnd) break;
    if (note.start + note.duration < view.start) continue;
    const y = midiToY(note.pitch, range, WAVE.top + 5, WAVE.bottom - 5);
    g.fillRect(x(note.start), y - 1.5, Math.max(1.5, x(note.start + note.duration) - x(note.start) - 1), 3);
  }

  // le righe
  g.textBaseline = "middle";
  const lineMiddle = (LINES.top + LINES.bottom) / 2;
  const wordMiddle = (WORDS.top + WORDS.bottom) / 2;
  lines.forEach((line, i) => {
    if (line.end < view.start || line.start > viewEnd) return;
    const left = x(line.start);
    const right = Math.max(left + 2, x(line.end));
    const selected = i === frame.selected;
    const tapping = i === frame.tapping;
    g.fillStyle = selected ? "rgba(91, 140, 255, 0.5)" : i === frame.playing ? "rgba(91, 140, 255, 0.34)" : "rgba(91, 140, 255, 0.2)";
    g.beginPath();
    g.roundRect(left, LINES.top, right - left, LINES.bottom - LINES.top, 5);
    g.fill();
    g.lineWidth = selected || tapping ? 2 : 1;
    g.strokeStyle = tapping ? "#ffd166" : selected ? "#8fb0ff" : "rgba(91, 140, 255, 0.55)";
    g.stroke();
    g.lineWidth = 1;
    if (selected && right - left >= MIN_RESIZABLE_PX) {
      g.fillStyle = "#c9d8ff";
      g.fillRect(left + 2, LINES.top + 8, 2, LINES.bottom - LINES.top - 16);
      g.fillRect(right - 4, LINES.top + 8, 2, LINES.bottom - LINES.top - 16);
    }
    g.font = "12px system-ui, sans-serif";
    g.fillStyle = line.text.trim() ? "#e8ebf4" : "#8a93ab";
    const label = `${i + 1}  ${line.text.trim() || "(vuota)"}`;
    clipText(g, label, Math.max(left, 0) + 9, lineMiddle + 0.5, left + 6, right - 6);

    // le parole, quando i loro tempi valgono per il testo
    const words = wordsOf(line);
    if (!words) return;
    g.font = "11px system-ui, sans-serif";
    for (const word of words) {
      const wordLeft = x(word.start);
      const wordRight = Math.max(wordLeft + 1, x(word.end));
      if (wordRight < 0 || wordLeft > width) continue;
      g.fillStyle = selected ? "rgba(61, 220, 151, 0.3)" : "rgba(61, 220, 151, 0.13)";
      g.fillRect(wordLeft, WORDS.top, Math.max(1, wordRight - wordLeft - 1), WORDS.bottom - WORDS.top);
      if (selected) {
        g.fillStyle = "#3ddc97";
        g.fillRect(wordLeft, WORDS.top, 1, WORDS.bottom - WORDS.top);
      }
      g.fillStyle = selected ? "#e8ebf4" : "#8a93ab";
      clipText(g, word.text, wordLeft + 4, wordMiddle + 0.5, wordLeft + 2, wordRight - 2);
    }
  });

  // l'asse del tempo
  g.textBaseline = "alphabetic";
  g.font = "10px system-ui, sans-serif";
  g.fillStyle = "#55607a";
  const step = TICKS_S.find((s) => (s / view.span) * width >= 64) ?? TICKS_S[TICKS_S.length - 1];
  for (let t = Math.ceil(view.start / step) * step; t <= viewEnd; t += step) {
    g.fillRect(x(t), AXIS_Y, 1, 5);
    const label = step < 1 ? `${formatDuration(Math.floor(t))}${(t % 1).toFixed(1).slice(1)}` : formatDuration(t);
    g.fillText(label, x(t) + 3, TIMELINE_HEIGHT - 6);
  }

  // il cursore dell'audio
  g.fillStyle = "#ffd166";
  g.fillRect(x(frame.now) - 1, 0, 2, AXIS_Y + 5);
}
