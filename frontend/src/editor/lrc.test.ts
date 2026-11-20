import { expect, test } from "vitest";
import type { LyricLine, Note } from "../lib/types";
import { formatLrc, linesFromPaste, parseLrc, pasteKind } from "./lrc";

const line = (start: number, end: number, text: string, words: LyricLine["words"] = null): LyricLine => ({ start, end, text, words });
const note = (start: number, duration: number): Note => ({ start, duration, pitch: 60 });

test("LRC lines are read with their times, in order", () => {
  expect(parseLrc("[ar:Qualcuno]\n[00:12.50] Prima riga\r\n[01:02.5]Seconda\n[00:20.00]\nsenza tempo")).toEqual([
    { time: 12.5, text: "Prima riga" }, { time: 20, text: "" }, { time: 62.5, text: "Seconda" }]);
  expect(parseLrc("[00:10.00][00:30.00]Ritornello")).toEqual([
    { time: 10, text: "Ritornello" }, { time: 30, text: "Ritornello" }]);
  expect(parseLrc("[00:07:25]Con i due punti")).toEqual([{ time: 7.25, text: "Con i due punti" }]);
});

test("exported LRC closes a line before a long break and reads back the same", () => {
  const lines = [line(12.5, 15, "Prima  riga"), line(15.2, 18, "Seconda"), line(40, 43.456, "Terza")];
  const text = formatLrc(lines);
  expect(text).toBe("[00:12.50]Prima riga\n[00:15.20]Seconda\n[00:18.00]\n[00:40.00]Terza\n[00:43.46]\n");
  expect(parseLrc(text).filter((entry) => entry.text).map((entry) => entry.time)).toEqual([12.5, 15.2, 40]);
});

test("pasted LRC brings its own times; ends come from the notes", () => {
  const notes = [note(10, 2), note(13, 1)];
  const pasted = linesFromPaste("[00:10.00]Uno\n[00:12.90]Due\n[00:15.00]\n", [line(0, 1, "vecchia")], notes, 100);
  expect(pasted).toEqual([line(10, 12, "Uno"), line(12.9, 14, "Due")]);
  expect(pasteKind("[00:10.00]Uno\n[00:12.90]Due\n[00:15.00]\n", [])).toEqual({ kind: "timed", count: 2 });
});

test("pasted plain text with the same number of lines keeps the times", () => {
  const current = [line(1, 2, "sbajato", [{ start: 1, end: 2, text: "sbajato" }]), line(3, 4, "ok")];
  expect(pasteKind("Sbagliato\n\n  ok  \n", current)).toEqual({ kind: "kept", count: 2 });
  expect(linesFromPaste("Sbagliato\n\n  ok  \n", current, [], 100)).toEqual([
    line(1, 2, "Sbagliato", [{ start: 1, end: 2, text: "sbajato" }]), line(3, 4, "ok")]);
});

test("pasted plain text with a different number of lines is spread along the song", () => {
  const current = [line(1, 2, "una")];
  expect(pasteKind("a\nb", current)).toEqual({ kind: "spread", count: 2 });
  expect(linesFromPaste("a\n  b   c ", current, [note(10, 10)], 100)).toEqual([line(10, 14.5, "a"), line(15, 19.5, "b c")]);
  expect(linesFromPaste("  \n", current, [], 100)).toEqual([]);
  expect(pasteKind("", current).count).toBe(0);
});
