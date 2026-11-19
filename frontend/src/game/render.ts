// Disegno della schermata di gioco: le note arrivano da destra verso la linea
// "adesso", acuto in alto e grave in basso; la voce è un pallino con la sua scia.

import type { Note } from "../lib/types";
import { LOOKAHEAD_S, midiToY, NOW_X_FRACTION, timeToX, visibleSlice, type PitchRange } from "./layout";

export interface FrameState {
  width: number;
  height: number;
  /** Il punto del brano che si sta sentendo, in secondi. */
  now: number;
  notes: Note[];
  range: PitchRange;
  /** I tratti già presi della barra i-esima. */
  hits: (index: number) => [number, number][];
  /** La voce degli ultimi secondi, già riportata all'ottava della barra. */
  trail: { t: number; midi: number }[];
  /** La voce in questo momento, oppure null se non si sta cantando. */
  voice: number | null;
  score: number;
  multiplier: number;
  /** Avanzamento del brano, da 0 a 1. */
  progress: number;
  line: { text: string; sung: number } | null;
  nextLine: string | null;
}

const COLORS = {
  background: "#12141c",
  grid: "#1f2331",
  incoming: "#5b8cff",
  hit: "#3ddc97",
  missed: "#3a4157",
  current: "#2b3350",
  voice: "#ffd166",
  nowLine: "#ffffff",
  text: "#ffffff",
  textRest: "#8a93ab",
  textNext: "#55607a",
  track: "#2a2e3d",
};
const FONT = `system-ui, "Segoe UI", sans-serif`;
const TRAIL_SECONDS = 2;
/** Due letture più distanti di così non si collegano: lì la voce mancava. */
const TRAIL_BREAK_S = 0.08;

function bar(g: CanvasRenderingContext2D, x1: number, x2: number, y: number, height: number): void {
  const width = Math.max(2, x2 - x1);
  g.beginPath();
  g.roundRect(x1, y - height / 2, width, height, Math.min(height / 2, width / 2));
}

export function drawFrame(g: CanvasRenderingContext2D, s: FrameState): void {
  const { width, height, now, notes, range } = s;
  const top = 78;
  const bottom = height - 128;
  const nowX = width * NOW_X_FRACTION;
  const semitone = (bottom - top) / (range.max - range.min);
  const barHeight = Math.min(20, Math.max(8, semitone * 0.9));
  const x = (t: number) => timeToX(t, now, width);
  const y = (midi: number) => midiToY(Math.min(range.max, Math.max(range.min, midi)), range, top, bottom);

  g.fillStyle = COLORS.background;
  g.fillRect(0, 0, width, height);

  // righe di altezza
  g.strokeStyle = COLORS.grid;
  g.lineWidth = 1;
  for (let midi = Math.ceil(range.min); midi <= Math.floor(range.max); midi += 2) {
    g.beginPath();
    g.moveTo(0, y(midi));
    g.lineTo(width, y(midi));
    g.stroke();
  }
  g.fillStyle = COLORS.textNext;
  g.font = `11px ${FONT}`;
  g.textAlign = "left";
  g.fillText("acuto", 10, top + 4);
  g.fillText("grave", 10, bottom + 4);

  // barre
  const secondsBehind = (nowX / (width - nowX)) * LOOKAHEAD_S;
  const [first, last] = visibleSlice(notes, now - secondsBehind, now + LOOKAHEAD_S);
  for (let i = first; i < last; i++) {
    const note = notes[i];
    const end = note.start + note.duration;
    const yNote = y(note.pitch);
    const isCurrent = note.start <= now && now < end;

    if (note.start >= now) {
      g.fillStyle = COLORS.incoming;                      // in arrivo
      bar(g, x(note.start), x(end), yNote, barHeight);
      g.fill();
      continue;
    }
    // parte già passata: grigia, poi in verde i tratti presi
    g.save();
    bar(g, x(note.start), x(end), yNote, barHeight);
    g.clip();
    g.fillStyle = isCurrent ? COLORS.current : COLORS.missed;
    g.fillRect(x(note.start), yNote - barHeight, x(end) - x(note.start), barHeight * 2);
    g.fillStyle = COLORS.missed;
    g.fillRect(x(note.start), yNote - barHeight, x(Math.min(now, end)) - x(note.start), barHeight * 2);
    g.fillStyle = COLORS.hit;
    for (const [from, to] of s.hits(i)) {
      g.fillRect(x(from), yNote - barHeight, Math.max(1, x(to) - x(from)), barHeight * 2);
    }
    g.restore();
    if (isCurrent) {
      g.strokeStyle = COLORS.incoming;
      g.lineWidth = 2;
      bar(g, x(note.start), x(end), yNote, barHeight);
      g.stroke();
    }
  }

  // linea "adesso"
  g.fillStyle = COLORS.nowLine;
  g.globalAlpha = 0.8;
  g.fillRect(nowX - 1, top - 14, 2, bottom - top + 28);
  g.globalAlpha = 1;

  // scia della voce
  g.strokeStyle = COLORS.voice;
  g.lineWidth = 3;
  g.lineJoin = "round";
  g.lineCap = "round";
  g.beginPath();
  let previousT = -Infinity;
  for (const point of s.trail) {
    if (point.t < now - TRAIL_SECONDS) continue;
    const px = Math.min(nowX, x(point.t));
    if (point.t - previousT > TRAIL_BREAK_S) g.moveTo(px, y(point.midi));
    else g.lineTo(px, y(point.midi));
    previousT = point.t;
  }
  if (s.voice !== null && previousT > -Infinity) g.lineTo(nowX, y(s.voice));
  g.stroke();
  if (s.voice !== null) {
    g.fillStyle = COLORS.voice;
    g.beginPath();
    g.arc(nowX, y(s.voice), 8, 0, Math.PI * 2);
    g.fill();
  }

  // in alto: avanzamento, punteggio, serie
  const trackWidth = Math.min(420, width * 0.4);
  g.fillStyle = COLORS.track;
  g.beginPath();
  g.roundRect(24, 26, trackWidth, 6, 3);
  g.fill();
  g.fillStyle = COLORS.incoming;
  g.beginPath();
  g.roundRect(24, 26, Math.max(6, trackWidth * Math.min(1, Math.max(0, s.progress))), 6, 3);
  g.fill();

  g.textAlign = "right";
  g.fillStyle = COLORS.text;
  g.font = `700 30px ${FONT}`;
  g.fillText(s.score.toLocaleString("it-IT"), width - 24, 40);
  g.fillStyle = s.multiplier > 1 ? COLORS.voice : COLORS.textNext;
  g.font = `600 14px ${FONT}`;
  g.fillText(`serie ×${s.multiplier}`, width - 24, 60);

  // in basso: il testo, con la parte cantata che si accende
  g.textAlign = "left";
  if (s.line) {
    g.font = `600 30px ${FONT}`;
    const textWidth = g.measureText(s.line.text).width;
    const scale = Math.min(1, (width - 48) / textWidth);
    const drawnWidth = textWidth * scale;
    const left = (width - drawnWidth) / 2;
    const baseline = height - 62;
    g.save();
    g.translate(left, baseline);
    g.scale(scale, scale);
    g.fillStyle = COLORS.textRest;
    g.fillText(s.line.text, 0, 0);
    g.beginPath();
    g.rect(0, -40, textWidth * Math.min(1, Math.max(0, s.line.sung)), 60);
    g.clip();
    g.fillStyle = COLORS.hit;
    g.fillText(s.line.text, 0, 0);
    g.restore();
  }
  if (s.nextLine) {
    g.font = `18px ${FONT}`;
    g.fillStyle = COLORS.textNext;
    g.textAlign = "center";
    g.fillText(s.nextLine, width / 2, height - 26, width - 48);
  }
  g.textAlign = "left";
}
