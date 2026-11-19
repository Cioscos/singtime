import { STAGES, type LyricsChoice, type Song, type Stage } from "./types";

export type SongStatus =
  | { kind: "ready" }
  | { kind: "processing"; step: number; stage: Stage; detail: string | null }
  | { kind: "queued"; position: number }
  | { kind: "error"; stage: Stage; message: string };

/** Che cosa mostrare in libreria per un brano. */
export function songStatus(song: Song): SongStatus {
  if (song.queue_position !== null && song.queue_position > 0) {
    return { kind: "queued", position: song.queue_position };
  }
  if (song.queue_position === 0) {
    const stage =
      STAGES.find((s) => song.stages[s].status === "running") ??
      STAGES.find((s) => song.stages[s].status !== "done") ??
      "lyrics";
    return { kind: "processing", step: STAGES.indexOf(stage) + 1, stage, detail: song.stages[stage].detail };
  }
  if (song.playable) return { kind: "ready" };
  const failed = STAGES.find((s) => song.stages[s].status === "error");
  if (failed) return { kind: "error", stage: failed, message: song.stages[failed].error ?? "Errore" };
  // Né in coda né finito: l'elaborazione non è mai partita (per esempio dopo una chiusura).
  const first = STAGES.find((s) => song.stages[s].status !== "done") ?? "acquire";
  return { kind: "error", stage: first, message: "Elaborazione non avviata" };
}

/** Perché la ricerca del testo è fallita, se è fallita: il brano si gioca lo stesso, ma senza testo. */
export function lyricsProblem(song: Song): string | null {
  const state = song.stages.lyrics;
  return state.status === "error" ? state.error ?? "Errore" : null;
}

/** Le fonti del testo tra cui si sceglie in Modifica, nell'ordine in cui si mostrano. */
export const LYRICS_CHOICES: { value: LyricsChoice; label: string }[] = [
  { value: "auto", label: "Automatica" },
  { value: "lrclib", label: "LRCLIB" },
  { value: "whisper", label: "Trascrizione dalla voce" },
  { value: "none", label: "Nessun testo" },
];

/** Che cosa succede applicando la fonte scelta. */
export function applyLabel(choice: LyricsChoice): string {
  return choice === "none" ? "Togli il testo" : "Cerca il testo";
}

/** Vero se il brano appena "aggiunto" c'era già: il server restituisce quello esistente. */
export function wasAlreadyThere(library: Song[], added: Song): boolean {
  return library.some((song) => song.id === added.id);
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "";
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
