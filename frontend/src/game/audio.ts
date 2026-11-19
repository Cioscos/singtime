// Riproduzione sincronizzata della base strumentale e della voce guida.
//
// Le due tracce partono sempre allo stesso istante dell'AudioContext, e il tempo
// del gioco si ricava da quell'orologio: barre, testo e punteggio restano
// agganciati alla musica anche se la grafica rallenta.

import { audioUrl } from "../lib/api";
import { SongClock } from "./song-clock";

/** Piccolo anticipo con cui si programmano le sorgenti, perché partano insieme. */
export const START_DELAY_S = 0.1;

export class SongPlayer {
  onEnded: (() => void) | null = null;

  private readonly ctx: AudioContext;
  private readonly buffers: [AudioBuffer, AudioBuffer]; // [base, voce guida]
  private readonly gains: [GainNode, GainNode];
  private readonly clock = new SongClock();
  private sources: AudioBufferSourceNode[] = [];
  private generation = 0;
  private finished = false;

  constructor(ctx: AudioContext, instrumental: AudioBuffer, vocals: AudioBuffer) {
    this.ctx = ctx;
    this.buffers = [instrumental, vocals];
    const instrumentalGain = ctx.createGain();
    const guideGain = ctx.createGain();
    instrumentalGain.connect(ctx.destination);
    guideGain.connect(ctx.destination);
    this.gains = [instrumentalGain, guideGain];
  }

  static async load(ctx: AudioContext, songId: string): Promise<SongPlayer> {
    const fetchBuffer = async (which: "instrumental" | "vocals") => {
      const response = await fetch(audioUrl(songId, which));
      if (!response.ok) throw new Error("Audio del brano non disponibile.");
      return ctx.decodeAudioData(await response.arrayBuffer());
    };
    const [instrumental, vocals] = await Promise.all([fetchBuffer("instrumental"), fetchBuffer("vocals")]);
    return new SongPlayer(ctx, instrumental, vocals);
  }

  get duration(): number {
    return this.buffers[0].duration;
  }

  get playing(): boolean {
    return this.clock.running;
  }

  get ended(): boolean {
    return this.finished;
  }

  play(): void {
    if (this.clock.running || this.finished) return;
    const offset = this.clock.now(this.ctx.currentTime);
    const when = this.ctx.currentTime + START_DELAY_S;
    const generation = ++this.generation;
    this.sources = this.buffers.map((buffer, i) => {
      const source = this.ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(this.gains[i]);
      source.onended = () => this.onSourceEnded(generation);
      source.start(when, offset);
      return source;
    });
    this.clock.start(when, offset);
  }

  pause(): void {
    if (!this.clock.running) return;
    this.clock.pause(this.ctx.currentTime);
    this.setPosition(Math.max(0, this.clock.now(this.ctx.currentTime)));
    this.stopSources();
  }

  seek(t: number): void {
    const wasPlaying = this.clock.running;
    this.stopSources();
    this.finished = false;
    this.setPosition(Math.min(Math.max(t, 0), this.duration));
    if (wasPlaying) this.play();
  }

  /** Volume della voce guida, da 0 (muta) a 1. */
  setGuideVolume(volume: number): void {
    this.gains[1].gain.value = Math.min(1, Math.max(0, volume));
  }

  /** Posizione nel brano in questo momento, in secondi (negativa durante l'attacco). */
  songTime(): number {
    return this.clock.now(this.ctx.currentTime);
  }

  /** Posizione nel brano a un dato istante dell'AudioContext (per le letture del microfono). */
  timeAt(ctxTime: number): number {
    return this.clock.now(ctxTime);
  }

  /** Quello che si sta sentendo adesso: l'uscita audio ha il suo ritardo. */
  heardTime(): number {
    return this.songTime() - (this.ctx.outputLatency ?? 0);
  }

  dispose(): void {
    this.stopSources();
    this.setPosition(0);
    this.gains.forEach((gain) => gain.disconnect());
  }

  private setPosition(t: number): void {
    const now = this.ctx.currentTime;
    this.clock.start(now, t);
    this.clock.pause(now);
  }

  private stopSources(): void {
    this.generation++; // le sorgenti fermate a mano non devono segnalare la fine del brano
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // mai partita: niente da fermare
      }
      source.disconnect();
    }
    this.sources = [];
  }

  private onSourceEnded(generation: number): void {
    if (generation !== this.generation || this.finished || !this.clock.running) return;
    this.finished = true;
    this.stopSources();
    this.setPosition(this.duration);
    this.onEnded?.();
  }
}
