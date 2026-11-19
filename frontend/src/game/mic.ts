// Il microfono del giocatore: apre il dispositivo e consegna le letture di altezza.

import { gate } from "./pitch-math";
import type { RawReading } from "./pitch-processor";
import processorUrl from "./pitch-processor.ts?worker&url";

export interface PitchReading {
  /** Tempo dell'AudioContext al centro della finestra analizzata. */
  t: number;
  /** Altezza in semitoni MIDI, oppure null se non si sta cantando. */
  midi: number | null;
  rms: number;
}

export class MicDeniedError extends Error {
  constructor() {
    super("Permesso del microfono negato.");
    this.name = "MicDeniedError";
  }
}

const loadedContexts = new WeakSet<BaseAudioContext>();

async function openStream(deviceId?: string | null): Promise<MediaStream> {
  // I filtri automatici del browser alterano la voce cantata: vanno spenti.
  const constraints = (id?: string | null): MediaStreamConstraints => ({
    audio: {
      deviceId: id ? { exact: id } : undefined,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    },
  });
  try {
    return await navigator.mediaDevices.getUserMedia(constraints(deviceId));
  } catch (error) {
    const name = (error as DOMException).name;
    if (name === "NotAllowedError" || name === "SecurityError") throw new MicDeniedError();
    if (deviceId && (name === "OverconstrainedError" || name === "NotFoundError")) {
      return openStream(null); // il microfono scelto non c'è più: si usa quello predefinito
    }
    throw new Error("Nessun microfono trovato.");
  }
}

export class Mic {
  onReading: ((reading: PitchReading) => void) | null = null;
  onLost: (() => void) | null = null;

  private readonly stream: MediaStream;
  private readonly nodes: AudioNode[];

  private constructor(stream: MediaStream, nodes: AudioNode[]) {
    this.stream = stream;
    this.nodes = nodes;
  }

  static async open(ctx: AudioContext, deviceId?: string | null): Promise<Mic> {
    const stream = await openStream(deviceId);
    if (!loadedContexts.has(ctx)) {
      await ctx.audioWorklet.addModule(processorUrl);
      loadedContexts.add(ctx);
    }
    const source = ctx.createMediaStreamSource(stream);
    const processor = new AudioWorkletNode(ctx, "pitch-processor");
    // Un'uscita muta verso gli altoparlanti: tiene vivo il nodo senza far sentire il microfono.
    const silent = ctx.createGain();
    silent.gain.value = 0;
    source.connect(processor);
    processor.connect(silent);
    silent.connect(ctx.destination);

    const mic = new Mic(stream, [source, processor, silent]);
    processor.port.onmessage = (event: MessageEvent<RawReading>) => {
      const { t, hz, clarity, rms } = event.data;
      mic.onReading?.({ t, midi: gate(hz, clarity, rms), rms });
    };
    for (const track of stream.getAudioTracks()) {
      track.addEventListener("ended", () => mic.onLost?.());
    }
    return mic;
  }

  /** Il dispositivo effettivamente aperto. */
  get deviceLabel(): string {
    return this.stream.getAudioTracks()[0]?.label ?? "";
  }

  close(): void {
    this.onReading = null;
    this.onLost = null;
    this.nodes.forEach((node) => node.disconnect());
    this.stream.getTracks().forEach((track) => track.stop());
  }
}

/** I microfoni disponibili; le etichette compaiono solo dopo aver dato il permesso. */
export async function listMics(): Promise<{ id: string; label: string }[]> {
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices
    .filter((device) => device.kind === "audioinput" && device.deviceId)
    .map((device, i) => ({ id: device.deviceId, label: device.label || `Microfono ${i + 1}` }));
}
