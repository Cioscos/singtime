import { expect, test } from "vitest";
import type { LyricLine } from "../lib/types";
import { clampView, cursorFor, followView, hitTest, LINES, timeToX, WAVE, WORDS, xToTime, zoomView, type View } from "./timeline";

const line = (start: number, end: number, text: string, words: LyricLine["words"] = null): LyricLine => ({ start, end, text, words });

// 10 secondi in 1000 pixel a partire dal secondo 20: 100 pixel al secondo.
const view: View = { start: 20, span: 10, width: 1000 };
const lineY = (LINES.top + LINES.bottom) / 2;
const wordY = (WORDS.top + WORDS.bottom) / 2;

test("time and pixels convert both ways", () => {
  expect(timeToX(view, 25)).toBe(500);
  expect(xToTime(view, 250)).toBe(22.5);
});

test("the view stays inside the song", () => {
  expect(clampView({ start: -5, span: 10, width: 1000 }, 60)).toMatchObject({ start: 0, span: 10 });
  expect(clampView({ start: 55, span: 10, width: 1000 }, 60)).toMatchObject({ start: 50, span: 10 });
  expect(clampView({ start: 0, span: 500, width: 1000 }, 60)).toMatchObject({ start: 0, span: 60 });
  expect(clampView({ start: 0, span: 0.1, width: 1000 }, 60).span).toBe(2);
});

test("zooming keeps the point under the pointer where it is", () => {
  const zoomed = zoomView(view, 0.5, 0.25, 60);
  expect(zoomed).toMatchObject({ start: 21.25, span: 5 });
  expect(xToTime(zoomed, 250)).toBe(xToTime(view, 250));
});

test("the view turns the page when playback reaches the end of it", () => {
  expect(followView(view, 25, 60)).toBe(view);
  expect(followView(view, 29.5, 60).start).toBeCloseTo(28.3);
  expect(followView(view, 5, 60).start).toBeCloseTo(3.8);
});

test("a line is grabbed by its edges or by its body", () => {
  const lines = [line(21, 23, "a"), line(23, 26, "b")];
  expect(hitTest(lines, -1, view, 150, lineY)).toEqual({ kind: "line", part: "body", line: 0 });
  expect(hitTest(lines, -1, view, 103, lineY)).toEqual({ kind: "line", part: "start", line: 0 });
  expect(hitTest(lines, -1, view, 297, lineY)).toEqual({ kind: "line", part: "end", line: 0 });
  expect(hitTest(lines, -1, view, 302, lineY)).toEqual({ kind: "line", part: "start", line: 1 });
  expect(hitTest(lines, -1, view, 700, lineY)).toBeNull();
  expect(hitTest(lines, -1, view, 150, (WAVE.top + WAVE.bottom) / 2)).toBeNull();     // sopra le righe: si sposta l'audio
});

test("on a shared boundary the selected line wins", () => {
  const lines = [line(21, 23, "a"), line(23, 26, "b")];
  expect(hitTest(lines, 1, view, 298, lineY)).toEqual({ kind: "line", part: "start", line: 1 });
  expect(hitTest(lines, 0, view, 302, lineY)).toEqual({ kind: "line", part: "end", line: 0 });
});

test("a line too narrow to tell its edges apart can only be moved", () => {
  expect(hitTest([line(21, 21.1, "a")], -1, view, 101, lineY)).toEqual({ kind: "line", part: "body", line: 0 });
});

test("word edges of the selected line can be grabbed", () => {
  const words = [{ start: 21, end: 22, text: "aa" }, { start: 22, end: 22.6, text: "bb" }];
  const lines = [line(21, 23, "aa bb", words), line(24, 25, "cc", [{ start: 24, end: 25, text: "cc" }])];
  expect(hitTest(lines, 0, view, 201, wordY)).toEqual({ kind: "word", line: 0, word: 1, edge: "start" });   // il confine tra le due
  expect(hitTest(lines, 0, view, 258, wordY)).toEqual({ kind: "word", line: 0, word: 1, edge: "end" });
  expect(hitTest(lines, 0, view, 150, wordY)).toBeNull();
  expect(hitTest(lines, 0, view, 400, wordY)).toBeNull();                 // le parole di un'altra riga no
  expect(hitTest([line(21, 23, "aa bb cc", words)], 0, view, 201, wordY)).toBeNull();   // tempi che non valgono più
});

test("the pointer says what would happen", () => {
  expect(cursorFor(null)).toBe("crosshair");
  expect(cursorFor({ kind: "line", part: "body", line: 0 })).toBe("grab");
  expect(cursorFor({ kind: "line", part: "end", line: 0 })).toBe("ew-resize");
  expect(cursorFor({ kind: "word", line: 0, word: 1, edge: "start" })).toBe("ew-resize");
});
