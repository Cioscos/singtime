// Il risultato dell'ultima partita passa dalla schermata di gioco a quella del
// risultato tramite sessionStorage. Si toglie solo dopo che il server l'ha
// salvato: così ricaricare la pagina non lo invia di nuovo, e un invio fallito
// non lo fa perdere.

import type { Difficulty, ScoreRecord } from "./types";

export interface LastResult {
  songId: string;
  difficulty: Difficulty;
  score: number;
  accuracy: number;
  stars: number;
}

const KEY = "lastResult";
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function saveLastResult(storage: Store, result: LastResult): void {
  storage.setItem(KEY, JSON.stringify(result));
}

function isValid(value: unknown): value is LastResult {
  const r = value as LastResult;
  return (
    typeof r === "object" && r !== null && typeof r.songId === "string" &&
    ["easy", "normal", "hard"].includes(r.difficulty) &&
    [r.score, r.accuracy, r.stars].every((n) => typeof n === "number" && Number.isFinite(n))
  );
}

/**
 * Il risultato in attesa per questo brano, se c'è. Resta nello storage finché
 * non lo si toglie con `clearLastResult`, cioè dopo che il server l'ha salvato.
 */
export function readLastResult(storage: Store, songId: string): LastResult | null {
  const raw = storage.getItem(KEY);
  if (raw === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = null;
  }
  if (!isValid(parsed)) {
    storage.removeItem(KEY);
    return null;
  }
  return parsed.songId === songId ? parsed : null;
}

export function clearLastResult(storage: Store): void {
  storage.removeItem(KEY);
}

export function isNewRecord(score: number, previous: ScoreRecord | undefined): boolean {
  return score > (previous?.score ?? 0);
}
