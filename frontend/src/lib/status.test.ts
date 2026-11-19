import { expect, test } from "vitest";
import { formatDuration, songStatus, wasAlreadyThere } from "./status";
import type { Song, Stage, StageState } from "./types";

const stages = (over: Partial<Record<Stage, Partial<StageState>>>): Record<Stage, StageState> => {
  const out = {} as Record<Stage, StageState>;
  for (const s of ["acquire", "separate", "pitch", "notes", "lyrics"] as Stage[])
    out[s] = { status: "pending", error: null, detail: null, ...over[s] };
  return out;
};
const song = (over: Partial<Song>): Song => ({
  id: "x", title: "T", artist: "A", duration_s: 200, source_kind: "youtube", source_ref: "u",
  separator_model: "m", pitch_tracker: "swiftf0", language: null, language_user: false,
  lyrics_source: null, lyrics_offset_s: 0, created_at: "", stages: stages({}), playable: false,
  queue_position: null, scores: {}, ...over,
});
const done = { status: "done" as const };

test("a song being processed shows the step in progress", () => {
  const s = song({ queue_position: 0, stages: stages({ acquire: done, separate: { status: "running", detail: "Scarico il modello" } }) });
  expect(songStatus(s)).toEqual({ kind: "processing", step: 2, stage: "separate", detail: "Scarico il modello" });
});

test("a song waiting its turn shows the position", () => {
  expect(songStatus(song({ queue_position: 2 }))).toEqual({ kind: "queued", position: 2 });
});

test("a failed song shows the message of the failed step", () => {
  const s = song({ stages: stages({ acquire: done, separate: done, pitch: done, notes: { status: "error", error: "Nessuna voce trovata" } }) });
  expect(songStatus(s)).toEqual({ kind: "error", stage: "notes", message: "Nessuna voce trovata" });
});

test("a playable song is ready even when the lyrics step failed", () => {
  const all = stages({ acquire: done, separate: done, pitch: done, notes: done, lyrics: { status: "error", error: "Elaborazione interrotta" } });
  expect(songStatus(song({ playable: true, stages: all }))).toEqual({ kind: "ready" });
});

test("a song that never started can be retried", () => {
  expect(songStatus(song({}))).toEqual({ kind: "error", stage: "acquire", message: "Elaborazione non avviata" });
});

test("formatDuration", () => {
  expect(formatDuration(249.16)).toBe("4:09");
  expect(formatDuration(59.6)).toBe("1:00");
  expect(formatDuration(null)).toBe("");
});

test("adding a song that is already in the library is noticed", () => {
  const library = [song({ id: "yt-a" }), song({ id: "yt-b" })];
  expect(wasAlreadyThere(library, song({ id: "yt-a" }))).toBe(true);
  expect(wasAlreadyThere(library, song({ id: "yt-c" }))).toBe(false);
  expect(wasAlreadyThere([], song({ id: "yt-a" }))).toBe(false);
});

import { lyricsProblem } from "./status";

test("a playable song whose lyrics search broke says why", () => {
  const playable = { acquire: done, separate: done, pitch: done, notes: done };
  const broken = song({ playable: true, stages: stages({ ...playable, lyrics: { status: "error", error: "Trascrizione non riuscita (memoria esaurita)" } }) });
  expect(songStatus(broken)).toEqual({ kind: "ready" });          // si gioca comunque
  expect(lyricsProblem(broken)).toBe("Trascrizione non riuscita (memoria esaurita)");
  expect(lyricsProblem(song({ playable: true, stages: stages({ ...playable, lyrics: done }) }))).toBeNull();
  expect(lyricsProblem(song({ playable: true, stages: stages({ ...playable, lyrics: { status: "error" } }) }))).toBe("Errore");
});
