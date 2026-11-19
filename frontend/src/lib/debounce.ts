// Un'azione ritardata: tante chiamate ravvicinate ne fanno partire una sola.

export interface Debounced {
  /** Chiede l'azione: parte quando non arrivano altre richieste per tutto il ritardo. */
  schedule(): void;
  /** Se c'è un'azione in attesa la esegue subito (per esempio lasciando la schermata). */
  flush(): void;
  /** Lascia cadere l'azione in attesa. */
  cancel(): void;
  readonly pending: boolean;
}

export function debounced(run: () => void, delayMs: number): Debounced {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const cancel = () => {
    clearTimeout(timer);
    timer = undefined;
  };
  return {
    schedule() {
      cancel();
      timer = setTimeout(() => {
        timer = undefined;
        run();
      }, delayMs);
    },
    flush() {
      if (timer === undefined) return;
      cancel();
      run();
    },
    cancel,
    get pending() {
      return timer !== undefined;
    },
  };
}
