// Testo incollato o esportato: righe semplici oppure in formato LRC ("[mm:ss.cc]testo").

import type { LyricLine, Note } from "../lib/types";
import { autoEnd, distribute, tokens } from "./lines";

const STAMP = /^\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]/;
/** Uno stacco più lungo di così, esportando, si segna con una riga vuota che chiude la precedente. */
const GAP_S = 1;

export interface LrcEntry {
  time: number;
  text: string;
}

/** Le righe con il loro tempo, in ordine; una riga senza testo segna solo la fine di quella prima. */
export function parseLrc(text: string): LrcEntry[] {
  const entries: LrcEntry[] = [];
  for (const raw of text.split(/\r?\n/)) {
    let line = raw.trim();
    const times: number[] = [];
    for (let match = STAMP.exec(line); match; match = STAMP.exec(line)) {
      times.push(Math.round((Number(match[1]) * 60 + Number(match[2].replace(":", "."))) * 1000) / 1000);
      line = line.slice(match[0].length).trimStart();
    }
    for (const time of times) entries.push({ time, text: line });
  }
  return entries.sort((a, b) => a.time - b.time);
}

function stamp(seconds: number): string {
  const hundredths = Math.round(Math.max(0, seconds) * 100);
  const minutes = Math.floor(hundredths / 6000);
  return `[${String(minutes).padStart(2, "0")}:${((hundredths - minutes * 6000) / 100).toFixed(2).padStart(5, "0")}]`;
}

/** Il testo in formato LRC, da usare anche fuori dal gioco. */
export function formatLrc(lines: LyricLine[]): string {
  const rows: string[] = [];
  lines.forEach((line, i) => {
    rows.push(`${stamp(line.start)}${tokens(line.text).join(" ")}`);
    const next = lines[i + 1];
    if (!next || next.start - line.end > GAP_S) rows.push(stamp(line.end));
  });
  return rows.join("\n") + "\n";
}

export type PasteKind =
  /** Il testo aveva i tempi: si usano quelli. */
  | "timed"
  /** Tante righe quante ce n'erano: cambiano le parole, i tempi restano. */
  | "kept"
  /** Righe nuove senza tempi: distribuite lungo il brano, da sincronizzare. */
  | "spread";

/** Come verrebbe letto un testo incollato, senza ancora usarlo. */
export function pasteKind(text: string, current: LyricLine[]): { kind: PasteKind; count: number } {
  const timed = parseLrc(text).filter((entry) => entry.text);
  if (timed.length > 0) return { kind: "timed", count: timed.length };
  const count = text.split(/\r?\n/).filter((row) => row.trim()).length;
  return { kind: count > 0 && count === current.length ? "kept" : "spread", count };
}

/** Le righe che si ottengono incollando `text` al posto del testo attuale. */
export function linesFromPaste(text: string, current: LyricLine[], notes: Note[], songDuration: number): LyricLine[] {
  const entries = parseLrc(text);
  if (entries.some((entry) => entry.text)) {
    const lines: LyricLine[] = [];
    entries.forEach((entry, i) => {
      if (!entry.text) return;
      const limit = i + 1 < entries.length ? entries[i + 1].time : Math.max(songDuration, entry.time);
      lines.push({ start: entry.time, end: autoEnd(entry.time, Math.max(limit, entry.time), notes), text: entry.text, words: null });
    });
    return lines;
  }
  const texts = text.split(/\r?\n/).map((row) => tokens(row).join(" ")).filter(Boolean);
  if (texts.length > 0 && texts.length === current.length) {
    return current.map((line, i) => ({ ...line, text: texts[i] }));
  }
  return distribute(texts, notes, songDuration);
}
