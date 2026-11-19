// Conversioni di altezza e filtro delle letture del microfono.

/** Sotto questa "chiarezza" la lettura è rumore, non una nota. */
export const MIN_CLARITY = 0.85;
/** Sotto questo volume (RMS) è silenzio. */
export const MIN_RMS = 0.01;
/** Estensione utile per una voce cantata, in Hz. */
export const MIN_HZ = 70;
export const MAX_HZ = 1100;

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

/** L'altezza in semitoni MIDI, oppure null se la lettura non è una voce che canta. */
export function gate(hz: number, clarity: number, rms: number): number | null {
  if (!Number.isFinite(hz) || hz < MIN_HZ || hz > MAX_HZ) return null;
  if (clarity < MIN_CLARITY || rms < MIN_RMS) return null;
  return hzToMidi(hz);
}
