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

/**
 * I caratteri [da, a) della parola che si sta cantando all'istante `t`: ciò che
 * precede è già cantato, ciò che segue deve ancora arrivare. Se in quel momento
 * non si canta nessuna parola i due estremi coincidono. Null se i tempi delle
 * parole non corrispondono al testo: allora vale solo `sungFraction`.
 */
export function wordSpan(line: LyricLine, t: number): [number, number] | null {
  const text = line.text;
  if (line.words && line.words.length > 0) {
    let cursor = 0;
    let sungUntil = 0;
    for (const word of line.words) {
      const from = text.indexOf(word.text, cursor);
      if (from < 0) return null;
      const to = from + word.text.length;
      cursor = to;
      if (t < word.start) return [from, from];
      if (t < word.end) return [from, to];
      sungUntil = to;
    }
    return [sungUntil, sungUntil];
  }
  // Senza i tempi delle parole si stima: la riga scorre in modo uniforme.
  if (t < line.start || line.end <= line.start) return t < line.start ? [0, 0] : [text.length, text.length];
  if (t >= line.end) return [text.length, text.length];
  let at = Math.min(text.length - 1, Math.floor(((t - line.start) / (line.end - line.start)) * text.length));
  while (at < text.length && /\s/.test(text[at])) at++;      // su uno spazio: tocca alla parola dopo
  let from = at;
  while (from > 0 && !/\s/.test(text[from - 1])) from--;
  let to = at;
  while (to < text.length && !/\s/.test(text[to])) to++;
  return [from, to];
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
