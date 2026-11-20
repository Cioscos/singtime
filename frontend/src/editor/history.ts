// Annulla e ripeti: una pila di stati passati e una di stati annullati.

export class History<T> {
  private past: T[] = [];
  private future: T[] = [];
  private lastKey: string | null = null;

  constructor(private readonly limit = 300) {}

  /**
   * Da chiamare prima di una modifica, con lo stato che sta per essere sostituito.
   * Più modifiche di fila con la stessa `key` (per esempio le lettere scritte in
   * una riga) contano come una sola: si annullano insieme.
   */
  record(state: T, key: string | null = null): void {
    if (key !== null && key === this.lastKey && this.past.length > 0) return;
    this.past.push(state);
    if (this.past.length > this.limit) this.past.shift();
    this.future = [];
    this.lastKey = key;
  }

  /** Lo stato a cui tornare, dato quello attuale; undefined se non c'è niente da annullare. */
  undo(current: T): T | undefined {
    if (this.past.length === 0) return undefined;
    this.future.push(current);
    this.lastKey = null;
    return this.past.pop();
  }

  redo(current: T): T | undefined {
    if (this.future.length === 0) return undefined;
    this.past.push(current);
    this.lastKey = null;
    return this.future.pop();
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }

  get canRedo(): boolean {
    return this.future.length > 0;
  }
}
