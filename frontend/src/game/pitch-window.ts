// La finestra scorrevole che alimenta il rilevatore di altezza del microfono.
//
// L'audio arriva a blocchi piccoli (128 campioni); il rilevatore vuole finestre
// più lunghe. Qui si accumulano i campioni e ogni `hop` se ne consegna una finestra.

export const WINDOW_SIZE = 2048;
export const HOP_SIZE = 512;

export type WindowHandler = (samples: Float32Array, endFrame: number, rms: number) => void;

export class PitchWindow {
  private readonly size: number;
  private readonly hop: number;
  private readonly ring: Float32Array;
  private readonly out: Float32Array;
  private written = 0;      // campioni ricevuti in totale
  private sinceEmit = 0;    // campioni ricevuti dall'ultima finestra consegnata

  constructor(size = WINDOW_SIZE, hop = HOP_SIZE) {
    this.size = size;
    this.hop = hop;
    this.ring = new Float32Array(size);
    this.out = new Float32Array(size);
  }

  /**
   * Aggiunge un blocco che comincia al campione assoluto `startFrame`.
   * `onWindow` riceve la finestra corrente (il vettore viene riusato: non conservarlo),
   * il campione assoluto subito dopo l'ultimo della finestra, e il volume RMS.
   */
  push(block: Float32Array, startFrame: number, onWindow: WindowHandler): void {
    for (let i = 0; i < block.length; i++) {
      this.ring[this.written % this.size] = block[i];
      this.written++;
      this.sinceEmit++;
      if (this.written >= this.size && this.sinceEmit >= this.hop) {
        this.sinceEmit = 0;
        const head = this.written % this.size; // il campione più vecchio
        let energy = 0;
        for (let j = 0; j < this.size; j++) {
          const value = this.ring[(head + j) % this.size];
          this.out[j] = value;
          energy += value * value;
        }
        onWindow(this.out, startFrame + i + 1, Math.sqrt(energy / this.size));
      }
    }
  }
}
