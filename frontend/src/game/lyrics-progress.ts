// Quale riga di testo mostrare e quanta parte ne è già stata cantata.

import type { LyricLine } from "../lib/types";

/** Una riga compare questo tanto prima di cominciare… */
export const LINE_LEAD_S = 1.0;
/** …e resta questo tanto dopo la fine, poi sparisce (stacchi strumentali). */
export const LINE_LINGER_S = 2.0;

/** Indici della riga corrente e della successiva; -1 se non ce n'è. */
export function lineAt(lines: LyricLine[], t: number): { current: number; next: number } {
  let candidate = -1;
  for (let i = 0; i < lines.length && lines[i].start - LINE_LEAD_S <= t; i++) candidate = i;
  if (candidate === -1) return { current: -1, next: lines.length > 0 ? 0 : -1 };
  const current = t <= lines[candidate].end + LINE_LINGER_S ? candidate : -1;
  const next = candidate + 1 < lines.length ? candidate + 1 : -1;
  return { current, next };
}

/** Quota (0…1) dei caratteri della riga già cantati all'istante `t`. */
export function sungFraction(line: LyricLine, t: number): number {
  if (line.words && line.words.length > 0) {
    let total = 0;
    let sung = 0;
    for (const word of line.words) {
      const length = word.text.replace(/\s/g, "").length;
      total += length;
      if (t >= word.end) sung += length;
      else if (t > word.start) sung += length * ((t - word.start) / (word.end - word.start));
    }
    return total > 0 ? Math.min(1, sung / total) : 0;
  }
  // Senza i tempi delle parole la riga si accende in modo uniforme.
  if (line.end <= line.start) return t >= line.start ? 1 : 0;
  return Math.min(1, Math.max(0, (t - line.start) / (line.end - line.start)));
}
