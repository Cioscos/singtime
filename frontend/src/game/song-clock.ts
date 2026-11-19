// Il tempo del brano ricavato dall'orologio dell'audio, non dai fotogrammi.

export class SongClock {
  private startedAt: number | null = null;
  private offset = 0;

  /** Il brano parte (o riparte) all'istante `ctxTime` dell'AudioContext, dalla posizione `offset`. */
  start(ctxTime: number, offset = 0): void {
    this.startedAt = ctxTime;
    this.offset = offset;
  }

  pause(ctxTime: number): void {
    this.offset = this.now(ctxTime);
    this.startedAt = null;
  }

  /** Posizione nel brano, in secondi, all'istante `ctxTime` dell'AudioContext. */
  now(ctxTime: number): number {
    return this.startedAt === null ? this.offset : this.offset + (ctxTime - this.startedAt);
  }

  get running(): boolean {
    return this.startedAt !== null;
  }
}
