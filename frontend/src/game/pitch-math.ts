// Conversioni di altezza e filtro delle letture del microfono.

/** Sotto questa "chiarezza" la lettura è rumore, non una nota. */
export const MIN_CLARITY = 0.85;
/** Sotto questo volume (RMS) è silenzio. */
export const MIN_RMS = 0.01;
/** Estensione utile per una voce cantata, in Hz. */
export const MIN_HZ = 70;
export const MAX_HZ = 1100;

/** Il volume più basso che l'indicatore mostra, in decibel. */
const METER_FLOOR_DB = -60;

/** Il volume (RMS) come posizione da 0 a 1 su una scala in decibel, per l'indicatore del microfono. */
export function meterLevel(rms: number): number {
  if (!(rms > 0)) return 0;
  return Math.min(1, Math.max(0, 1 - (20 * Math.log10(rms)) / METER_FLOOR_DB));
}

export function hzToMidi(hz: number): number {
  return 69 + 12 * Math.log2(hz / 440);
}

/**
 * La voce spostata di ottave intere fino al punto più vicino al bersaglio:
 * cantare la nota giusta un'ottava sopra o sotto vale come giusta.
 */
export function foldToOctave(voiceMidi: number, targetMidi: number): number {
  return voiceMidi - 12 * Math.round((voiceMidi - targetMidi) / 12);
}

const NOTE_NAMES = ["Do", "Do♯", "Re", "Re♯", "Mi", "Fa", "Fa♯", "Sol", "Sol♯", "La", "La♯", "Si"];

/** Il nome della nota più vicina, per esempio "La4". */
export function noteName(midi: number): string {
  const nearest = Math.round(midi);
  return `${NOTE_NAMES[((nearest % 12) + 12) % 12]}${Math.floor(nearest / 12) - 1}`;
}

/** L'altezza in semitoni MIDI, oppure null se la lettura non è una voce che canta. */
export function gate(hz: number, clarity: number, rms: number): number | null {
  if (!Number.isFinite(hz) || hz < MIN_HZ || hz > MAX_HZ) return null;
  if (clarity < MIN_CLARITY || rms < MIN_RMS) return null;
  return hzToMidi(hz);
}
