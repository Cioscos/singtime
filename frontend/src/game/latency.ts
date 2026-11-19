// Taratura del ritardo tra audio e microfono, ad anello chiuso: l'app emette dei
// clic nelle cuffie, una cuffia sta vicino al microfono, e si misura dopo quanto
// tempo il microfono li sente. È il ritardo complessivo uscita + ingresso.

import { HOP_SIZE, WINDOW_SIZE } from "./pitch-window";

/** Silenzio minimo, in secondi, perché un nuovo suono conti come un altro attacco. */
const QUIET_BEFORE_ONSET_S = 0.15;
/** Un attacco "risponde" a un clic solo se arriva entro questo tempo. */
const MATCH_WINDOW_S = 0.5;
/** Servono almeno tanti clic sentiti, e d'accordo tra loro, per fidarsi della misura. */
const MIN_MATCHES = 5;
/** Due ritardi "sono d'accordo" se distano dalla mediana meno di così. */
const AGREEMENT_S = 0.02;

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

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
 * mediana delle differenze. Null se i clic sentiti e concordi sono meno di cinque:
 * rumori a caso danno ritardi sparsi, e una misura sbagliata falserebbe tutto il punteggio.
 */
export function estimateLatencyMs(clickTimes: number[], onsetTimes: number[]): number | null {
  const delays: number[] = [];
  for (const click of clickTimes) {
    const answer = onsetTimes.find((onset) => onset >= click && onset <= click + MATCH_WINDOW_S);
    if (answer !== undefined) delays.push(answer - click);
  }
  if (delays.length < MIN_MATCHES) return null;
  const center = median(delays);
  const agreeing = delays.filter((delay) => Math.abs(delay - center) <= AGREEMENT_S);
  if (agreeing.length < MIN_MATCHES) return null;
  return median(agreeing) * 1000;
}

/** Oltre questo valore un ritardo dichiarato non è credibile. */
const MAX_DECLARED_MS = 500;

/**
 * Senza taratura: il ritardo che il browser dichiara per l'uscita e per il
 * microfono. È una stima (con il Bluetooth spesso è troppo bassa), ma è meglio
 * che giudicare la voce come se il ritardo fosse zero.
 */
export function declaredLatencyMs(
  output: { outputLatency?: number; baseLatency?: number },
  inputLatencyS: number | undefined,
): number {
  const usable = (value: number | undefined) => (typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0);
  const out = usable(output.outputLatency) || usable(output.baseLatency);
  return Math.min(MAX_DECLARED_MS, (out + usable(inputLatencyS)) * 1000);
}

/**
 * Le letture del microfono portano il tempo del centro della finestra analizzata,
 * ma un suono improvviso si nota appena entra in coda alla finestra: l'attacco
 * vero è più avanti di circa mezza finestra, meno mezzo passo di incertezza.
 */
export function onsetCorrection(sampleRate: number): number {
  return (WINDOW_SIZE - HOP_SIZE) / 2 / sampleRate;
}
