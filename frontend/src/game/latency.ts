// Taratura del ritardo tra audio e microfono, ad anello chiuso: l'app emette dei
// clic nelle cuffie, una cuffia sta vicino al microfono, e si misura dopo quanto
// tempo il microfono li sente. È il ritardo complessivo uscita + ingresso.

import { HOP_SIZE, WINDOW_SIZE } from "./pitch-window";

/** Silenzio minimo, in secondi, perché un nuovo suono conti come un altro attacco. */
const QUIET_BEFORE_ONSET_S = 0.15;
/** Un attacco "risponde" a un clic solo se arriva entro questo tempo. */
const MATCH_WINDOW_S = 0.5;
const MIN_MATCHES = 3;

/** Istanti in cui il volume supera la soglia dopo un tratto di silenzio. */
export function detectOnsets(readings: { t: number; rms: number }[], threshold: number): number[] {
  const onsets: number[] = [];
  let lastLoud = -Infinity;
  for (const reading of readings) {
    if (reading.rms < threshold) continue;
    if (reading.t - lastLoud >= QUIET_BEFORE_ONSET_S) onsets.push(reading.t);
    lastLoud = reading.t;
  }
  return onsets;
}

/**
 * Ritardo in millisecondi: per ogni clic il primo attacco che lo segue, poi la
 * mediana delle differenze. Null se i clic sentiti sono meno di tre.
 */
export function estimateLatencyMs(clickTimes: number[], onsetTimes: number[]): number | null {
  const delays: number[] = [];
  for (const click of clickTimes) {
    const answer = onsetTimes.find((onset) => onset >= click && onset <= click + MATCH_WINDOW_S);
    if (answer !== undefined) delays.push(answer - click);
  }
  if (delays.length < MIN_MATCHES) return null;
  delays.sort((a, b) => a - b);
  const middle = Math.floor(delays.length / 2);
  const median = delays.length % 2 === 1 ? delays[middle] : (delays[middle - 1] + delays[middle]) / 2;
  return median * 1000;
}

/**
 * Le letture del microfono portano il tempo del centro della finestra analizzata,
 * ma un suono improvviso si nota appena entra in coda alla finestra: l'attacco
 * vero è più avanti di circa mezza finestra, meno mezzo passo di incertezza.
 */
export function onsetCorrection(sampleRate: number): number {
  return (WINDOW_SIZE - HOP_SIZE) / 2 / sampleRate;
}
