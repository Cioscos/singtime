// AudioWorklet: rileva l'altezza della voce dal microfono con il metodo McLeod (pitchy).
// Gira nel thread dell'audio; al thread principale manda solo le letture.

import { PitchDetector } from "pitchy";
import { PitchWindow, WINDOW_SIZE } from "./pitch-window";

// Variabili globali dell'AudioWorkletGlobalScope, assenti dai tipi standard del DOM.
declare const sampleRate: number;
declare const currentFrame: number;
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
}
declare function registerProcessor(name: string, processor: new () => AudioWorkletProcessor): void;

export interface RawReading {
  /** Tempo dell'AudioContext al centro della finestra analizzata. */
  t: number;
  hz: number;
  clarity: number;
  rms: number;
}

class PitchProcessor extends AudioWorkletProcessor {
  private readonly window = new PitchWindow();
  private readonly detector = PitchDetector.forFloat32Array(WINDOW_SIZE);

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0];
    if (channel) {
      this.window.push(channel, currentFrame, (samples, endFrame, rms) => {
        // La frequenza di campionamento è quella reale del contesto, non un valore fisso.
        const [hz, clarity] = this.detector.findPitch(samples, sampleRate);
        const reading: RawReading = { t: (endFrame - WINDOW_SIZE / 2) / sampleRate, hz, clarity, rms };
        this.port.postMessage(reading);
      });
    }
    return true;
  }
}

registerProcessor("pitch-processor", PitchProcessor);
